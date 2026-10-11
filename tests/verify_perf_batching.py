#!/usr/bin/env python3
"""
Stage 5 (workstream P) -- B4 real batching + B2 payload index.

Two performance findings from AUDIT_BASELINE.md, both measured here against the
real functions that carry them.

B4 -- production encode is not the encode the device resolver benchmarked
------------------------------------------------------------------------
`device_resolver` picks a device by timing `model.encode(chunks,
batch_size=64, normalize_embeddings=True, ...)` and its own note says that
"claims to match production". It does not:

  * `vector_store.get_ollama_embeddings` calls `model.encode(truncated)` with
    **no `batch_size` and no `normalize_embeddings`**;
  * `store_chunks` slices the corpus at `EMBED_SLICE = 16` and hands each slice
    to that call, so the **effective encode batch is 16**, not the 64 that was
    measured.

So the resolver's "best device" decision was fitted on 64-wide batches while
production ran 16-wide ones -- the measurement and the thing measured were
different workloads. Aligning them is the fix; the normalisation is rank-neutral
under Qdrant's COSINE distance, so it changes the cost, not the ranking.

B2 -- the `evidence_id` filter is an unindexed scan
---------------------------------------------------
`search_chunks(evidence_id=...)` and `delete_evidence_points` both build a
Qdrant filter on the `evidence_id` payload field, and no payload index is ever
created for it (`create_payload_index` is absent from the file). The filter is a
full scan of the payload store. The API call is the fix; the honest caveat --
that the pinned embedded Qdrant *ignores* payload indexes -- is asserted and
documented in the source rather than quietly claimed as a speed-up.

What this suite asserts
-----------------------
Part A (B4, unit -- the encode call itself):
  A1 `model.encode` is called with `batch_size=64`
  A2 `model.encode` is called with `normalize_embeddings=True`

Part B (B4, integration -- the batch that actually reaches the model):
  B1 `store_chunks` hands the embedder 64 texts per call, not 16
  B2 the final (short) call carries the remainder
  B3 the embedder is called the minimum number of times for the corpus

Part C (B2 -- payload index):
  C1 `ensure_payload_indexes` requests a KEYWORD index on `evidence_id`
  C2 `ensure_collection` wires it in for a fresh collection
  C3 `store_chunks` reaches the index-ensure path
  C4 repeated ensures do not re-issue the call (embedded mode prints one
     warning per call, so a per-artifact re-issue would be hundreds of lines)
  C5 the `evidence_id` filter still returns only the matching evidence

Isolation follows `verify_reindex_idempotency.py`: temp DB / cases / Qdrant dirs
chosen *before* any backend import, an `atexit` cleanup, and a deterministic
384-dim embedder stub so the suite is fast and offline.

Summary line follows the gate's shape-B convention:
    PASSED: <n>    FAILED: <n>
"""

import atexit
import hashlib
import math
import os
import shutil
import sys
import tempfile
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

TMP = tempfile.mkdtemp(prefix="cfi_perf_batch_")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))

PASS = 0
FAIL = 0
FAILED = []


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        FAILED.append(label)
        print(f"  FAIL {label}" + (f"  -- {detail}" if detail else ""))


def _make_env(root):
    """Point the backend at an isolated temp environment. MUST run before any
    backend import (get_settings is lru_cached; backend.database builds its
    engine at import time)."""
    db_path = os.path.join(root, "perf_batch.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path
    os.environ["CASES_DIR"] = os.path.join(root, "cases")
    os.environ["QDRANT_DIR"] = os.path.join(root, "qdrant")
    os.environ["DEBUG"] = "False"


def _fake_embed(texts):
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        vec = [((h[i % len(h)] / 255.0) - 0.5) for i in range(384)]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        out.append([x / norm for x in vec])
    return out


def _stub_embedder(vs):
    """No torch / model load; keep provenance comparing like-for-like."""
    vs.get_ollama_embeddings = _fake_embed
    vs.describe_embedder = lambda: {
        "embedder_id": vs.EMBEDDER_ID,
        "vector_size": vs.VECTOR_SIZE,
        "max_seq_length": 256,
    }


# ---------------------------------------------------------------------------
# Part A -- the encode kwargs (B4)
# ---------------------------------------------------------------------------

class _RecordingModel:
    """Stands in for the loaded SentenceTransformer and records how it is
    called. Only `encode` is reached by get_ollama_embeddings."""

    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append({"n": len(texts), "kwargs": dict(kwargs)})
        return _Array(_fake_embed(list(texts)))


class _Array:
    def __init__(self, data):
        self._data = data

    def tolist(self):
        return self._data


def part_a():
    print("\nPart A -- model.encode is called with real batch kwargs (B4)")
    from backend.modules import vector_store as vs

    model = _RecordingModel()
    saved_model, saved_tried = vs._embed_model, vs._embed_tried
    vs._embed_model = model
    vs._embed_tried = True
    try:
        vs.get_ollama_embeddings(["alpha", "beta"])
    finally:
        vs._embed_model = saved_model
        vs._embed_tried = saved_tried

    if not model.calls:
        check("A1 model.encode is called with batch_size=64", False,
              "model.encode was never reached")
        check("A2 model.encode is called with normalize_embeddings=True", False,
              "model.encode was never reached")
        return

    kwargs = model.calls[0]["kwargs"]
    check("A1 model.encode is called with batch_size=64",
          kwargs.get("batch_size") == 64,
          f"batch_size={kwargs.get('batch_size')!r}")
    check("A2 model.encode is called with normalize_embeddings=True",
          kwargs.get("normalize_embeddings") is True,
          f"normalize_embeddings={kwargs.get('normalize_embeddings')!r}")


# ---------------------------------------------------------------------------
# Part B -- the batch that actually reaches the embedder (B4)
# ---------------------------------------------------------------------------

def part_b():
    print("\nPart B -- store_chunks hands the embedder 64 texts per call (B4)")
    from backend.modules import vector_store as vs

    sizes = []

    def _recorder(texts):
        sizes.append(len(texts))
        return _fake_embed(list(texts))

    qpath = os.path.join(TMP, "partb_qdrant")
    case_id, ev_id = str(uuid.uuid4()), str(uuid.uuid4())
    chunks = [f"chunk number {i} with a little text to embed" for i in range(150)]

    saved = vs.get_ollama_embeddings
    vs.get_ollama_embeddings = _recorder
    try:
        n = vs.store_chunks(chunks, "batch.txt", ev_id, case_id, qpath,
                            chunking={"chunk_size": 700, "chunk_overlap": 0})
    finally:
        vs.get_ollama_embeddings = saved

    check("B1 the embedder receives 64 texts per call, not 16",
          len(sizes) > 0 and sizes[0] == 64,
          f"call sizes: {sizes}")
    check("B1b every full call carries exactly 64 texts",
          all(s == 64 for s in sizes[:-1]) if sizes else False,
          f"call sizes: {sizes}")
    check("B2 the final call carries the remainder (150 -> 64,64,22)",
          sizes == [64, 64, 22],
          f"call sizes: {sizes}")
    check("B3 the embedder is called the minimum number of times",
          len(sizes) == math.ceil(len(chunks) / 64),
          f"{len(sizes)} call(s) for {len(chunks)} chunks")
    check("B4 every chunk was stored exactly once",
          n == len(chunks), f"store_chunks returned {n}")


# ---------------------------------------------------------------------------
# Part C -- payload index (B2)
# ---------------------------------------------------------------------------

class _SpyClient:
    """Records create_payload_index calls without opening any storage."""

    def __init__(self):
        self.calls = []

    def create_payload_index(self, **kwargs):
        self.calls.append(kwargs)
        return None


def part_c():
    print("\nPart C -- the evidence_id payload index is requested (B2)")
    from backend.modules import vector_store as vs

    try:
        from qdrant_client.models import PayloadSchemaType
    except Exception as e:  # pragma: no cover - import guard
        check("C1 ensure_payload_indexes requests a KEYWORD index on evidence_id",
              False, f"PayloadSchemaType unavailable: {e}")
        return

    ensure = getattr(vs, "ensure_payload_indexes", None)
    check("C1 ensure_payload_indexes exists", callable(ensure),
          "no ensure_payload_indexes in vector_store")
    if not callable(ensure):
        for lbl in ("C1b the request names evidence_id",
                    "C1c the schema is KEYWORD",
                    "C2 ensure_collection wires the index in",
                    "C3 store_chunks reaches the index-ensure path",
                    "C4 repeated ensures do not re-issue the call"):
            check(lbl, False, "ensure_payload_indexes missing")
        return

    spy = _SpyClient()
    ensure(spy, "case_deadbeef", os.path.join(TMP, "c1_qdrant"))
    check("C1b the request names evidence_id",
          bool(spy.calls) and spy.calls[0].get("field_name") == "evidence_id",
          f"calls={spy.calls}")
    check("C1c the schema is KEYWORD",
          bool(spy.calls)
          and spy.calls[0].get("field_schema") == PayloadSchemaType.KEYWORD,
          f"calls={spy.calls}")

    # C4 -- dedup, so embedded mode's per-call warning is emitted once, not once
    # per stored artifact.
    ensure(spy, "case_deadbeef", os.path.join(TMP, "c1_qdrant"))
    check("C4 repeated ensures do not re-issue the call",
          len(spy.calls) == 1,
          f"create_payload_index called {len(spy.calls)} times")

    # C2 -- ensure_collection must reach the ensure path for a fresh collection.
    recorded = []
    real_ensure = vs.ensure_payload_indexes

    def _spy_ensure(client, collection_name, qdrant_path=None):
        recorded.append((collection_name, qdrant_path))

    vs.ensure_payload_indexes = _spy_ensure
    try:
        client = vs.get_client(os.path.join(TMP, "c2_qdrant"))
        vs.ensure_collection(client, "case_c2c2c2c2",
                             os.path.join(TMP, "c2_qdrant"))
    finally:
        vs.ensure_payload_indexes = real_ensure
    check("C2 ensure_collection wires the index in",
          any(name == "case_c2c2c2c2" for name, _ in recorded),
          f"ensure_payload_indexes calls: {recorded}")

    # C3 -- store_chunks reaches the same path.
    recorded.clear()
    vs.ensure_payload_indexes = (
        lambda client, name, path=None, _r=recorded: _r.append((name, path)))
    qpath3 = os.path.join(TMP, "c3_qdrant")
    case3 = str(uuid.uuid4())
    try:
        vs.store_chunks(["one chunk"], "c3.txt", "ev-c3", case3, qpath3)
    finally:
        vs.ensure_payload_indexes = real_ensure
    check("C3 store_chunks reaches the index-ensure path",
          len(recorded) >= 1, f"ensure_payload_indexes calls: {recorded}")

    # C4b -- the dedup key is per storage path, so a second case still gets one.
    spy2 = _SpyClient()
    ensure(spy2, "case_deadbeef", os.path.join(TMP, "c4_other_qdrant"))
    check("C4b a different storage path still issues the call",
          len(spy2.calls) == 1, f"calls={spy2.calls}")

    # C5 -- the filter still returns only the matching evidence (the property
    # the index exists to accelerate, unchanged by its absence).
    case5 = str(uuid.uuid4())
    qpath5 = os.path.join(TMP, "c5_qdrant")
    vs.store_chunks(["alpha evidence about ORION-77"],
                    "a.txt", "ev-a", case5, qpath5)
    vs.store_chunks(["beta evidence about ORION-77"],
                    "b.txt", "ev-b", case5, qpath5)
    hits = vs.search_chunks(query="ORION-77 evidence",
                            case_id=case5, qdrant_path=qpath5,
                            top_k=10, evidence_id="ev-a")
    check("C5 the evidence_id filter returns only the matching evidence",
          len(hits) > 0 and all(h["evidence_id"] == "ev-a" for h in hits),
          f"returned evidence_ids: {[h['evidence_id'] for h in hits]}")


def main():
    _make_env(TMP)

    from backend.modules import vector_store as vs
    from backend.database import init_db

    # Part A must run BEFORE we stub get_ollama_embeddings, because it tests
    # the real function's encode kwargs.
    part_a()

    _stub_embedder(vs)
    init_db()

    try:
        part_b()
        part_c()
    finally:
        try:
            vs.close_all_clients()
        except Exception:
            pass

    print("\n" + "=" * 66)
    for label in FAILED:
        print(f"  FAILED: {label}")
    print(f"PASSED: {PASS}    FAILED: {FAIL}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
