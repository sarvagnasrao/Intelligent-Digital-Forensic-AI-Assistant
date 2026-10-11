#!/usr/bin/env python3
"""
Stage 3 -- re-index idempotency.

The defect this suite is written against (A5/B1)
------------------------------------------------
Re-ingesting the same evidence must be a no-op for the index. It is not:

  * `store_chunks` mints `id=str(uuid.uuid4())` for every point, so a second
    ingest of the same file writes a *second* copy of every chunk under fresh
    ids. The collection doubles, triples, ... with each re-index.
  * There is no delete-before-reindex keyed on evidence_id. Nothing removes the
    previous points first.
  * Consequently `(source, chunk_index)` is no longer unique, and a query
    returns the same passage several times, each scoring the same.

Why the consequence matters (this repo's defining defect)
---------------------------------------------------------
A forensic index that silently accumulates duplicate copies of the same
evidence is not merely wasteful. Ranked retrieval returns the duplicates as
separate "sources" and `chunks_used` counts them, so an investigator reading
"5 matching passages" from one document sees corroboration that does not exist.
The honest state of a doubly-ingested case is indistinguishable from a rich
one.

What this suite asserts
-----------------------
Part A (unit, `store_chunks` directly -- the exact function that writes):
  A1 the second identical store does not grow the point count
  A2 it writes the same point ids (deterministic ids, not uuid4)
  A3 (source, chunk_index) stays unique across both stores
  A4 the stored text for each (source, chunk_index) is unchanged
  A5 a positive control: the first store really did write >1 point, so A1-A3
     are not passing vacuously

Part B (integration, the real `run_ingestion_with_progress` end to end):
  B1 a second full ingest does not grow the case's point count
  B2 it does not grow `evidence.chunk_count` beyond the real chunk count
  B3 (source, chunk_index) is unique in the collection after the second run
  B4 the point count equals the number of chunks the file actually has

Part C:
  C1 `search_chunks` returns no duplicate (source, chunk_index) after a
     re-ingest -- the query-visible statement of the same defect

Isolation
---------
Exactly like `bench_pipeline.py`: a temp SQLite DB, temp cases dir and temp
Qdrant dir, chosen *before* any backend import (get_settings is lru_cached and
backend.database builds its engine at import time). The running server's
database and the real data/cases are never touched. The embedding model is
stubbed with a deterministic 384-dim vector so the suite is fast, offline and
does not contend with a live ingest for the real model.

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

TMP = tempfile.mkdtemp(prefix="cfi_reindex_")
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
    backend import."""
    db_path = os.path.join(root, "reindex.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path
    os.environ["CASES_DIR"] = os.path.join(root, "cases")
    os.environ["QDRANT_DIR"] = os.path.join(root, "qdrant")
    os.environ["DEBUG"] = "False"


# ---------------------------------------------------------------------------
# Deterministic embedding stub (384-dim, distinct per text, stable per text)
# ---------------------------------------------------------------------------

def _fake_embed(texts):
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        vec = [((h[i % len(h)] / 255.0) - 0.5) for i in range(384)]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        out.append([x / norm for x in vec])
    return out


def _stub_embedder(vs):
    """Replace the embedder and the measured signature, so no torch / model load
    happens and the provenance guard compares like-for-like within the stub."""
    vs.get_ollama_embeddings = _fake_embed
    vs.describe_embedder = lambda: {
        "embedder_id": vs.EMBEDDER_ID,
        "vector_size": vs.VECTOR_SIZE,
        "max_seq_length": 256,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _scroll_points(vs, case_id, qdrant_path):
    """Every point in the case collection as (id, source, chunk_index, text)."""
    client = vs.get_client(qdrant_path)
    coll = vs.get_collection_name(case_id)
    recs, _ = client.scroll(
        collection_name=coll, limit=100000,
        with_payload=True, with_vectors=False)
    rows = []
    for r in recs:
        p = r.payload or {}
        rows.append((str(r.id), p.get("source"), p.get("chunk_index"),
                     p.get("text")))
    return rows


def _seed_case_and_evidence(root, filename, text):
    from backend.database import init_db, SessionLocal
    from backend import models

    init_db()
    db = SessionLocal()
    case_id = str(uuid.uuid4())
    db.add(models.Case(id=case_id, case_name="REINDEX idempotency",
                       case_number=None, status="Active", created_by="test"))
    db.commit()

    ev_id = str(uuid.uuid4())
    ev_dir = os.path.join(root, "cases", case_id, "evidence")
    os.makedirs(ev_dir, exist_ok=True)
    stored = os.path.join(ev_dir, f"{ev_id}_{filename}")
    data = text.encode("utf-8")
    with open(stored, "wb") as f:
        f.write(data)
    db.add(models.Evidence(
        id=ev_id, case_id=case_id, filename=filename,
        original_filename=filename, file_type="txt",
        file_size_bytes=len(data), file_path=stored,
        ingested_by="test", status="Uploaded"))
    db.commit()
    db.close()
    return case_id, ev_id, stored


def _chunk_count(ev_id):
    from backend.database import SessionLocal
    from backend import models
    db = SessionLocal()
    try:
        row = db.query(models.Evidence).filter(
            models.Evidence.id == ev_id).first()
        return row.chunk_count if row else None
    finally:
        db.close()


def _ingest(case_id, ev_id, stored, filename):
    from backend.ingestion import run_ingestion_with_progress
    return run_ingestion_with_progress(
        evidence_id=ev_id, case_id=case_id, file_path=stored,
        filename=filename, job_id=None)


# ---------------------------------------------------------------------------
# Part A -- store_chunks is idempotent for identical input
# ---------------------------------------------------------------------------

def part_a():
    print("\nPart A -- store_chunks idempotency (unit)")
    from backend.modules import vector_store as vs
    from backend.database import init_db
    init_db()

    case_id = str(uuid.uuid4())
    ev_id = str(uuid.uuid4())
    qpath = vs.case_qdrant_path(case_id)
    chunks = ["Alpha passage about ORION-77 movement %d." % i
              for i in range(6)]

    n1 = vs.store_chunks(chunks, "unit.txt", ev_id, case_id, qpath,
                         chunking={"chunk_size": 700, "chunk_overlap": 100})
    rows1 = _scroll_points(vs, case_id, qpath)
    ids1 = sorted(r[0] for r in rows1)

    n2 = vs.store_chunks(chunks, "unit.txt", ev_id, case_id, qpath,
                         chunking={"chunk_size": 700, "chunk_overlap": 100})
    rows2 = _scroll_points(vs, case_id, qpath)
    ids2 = sorted(r[0] for r in rows2)

    check("A5 first store wrote every chunk (>1 point)",
          n1 == len(chunks) and len(rows1) == len(chunks),
          f"store_chunks returned {n1}, collection holds {len(rows1)}, "
          f"expected {len(chunks)}")
    check("A1 second identical store does not grow the point count",
          len(rows2) == len(rows1),
          f"{len(rows1)} -> {len(rows2)} points")
    check("A2 second store writes the same point ids (deterministic ids)",
          ids1 == ids2,
          "ids differ between two identical stores "
          f"({len(set(ids1) ^ set(ids2))} of {len(ids1)} changed)")
    keys = [(r[1], r[2]) for r in rows2]
    check("A3 (source, chunk_index) is unique after re-store",
          len(keys) == len(set(keys)),
          f"{len(keys) - len(set(keys))} duplicate (source, chunk_index)")
    by_key1 = {(r[1], r[2]): r[3] for r in rows1}
    by_key2 = {(r[1], r[2]): r[3] for r in rows2}
    check("A4 stored text per (source, chunk_index) is unchanged",
          by_key1 == by_key2,
          "text changed for at least one chunk")


# ---------------------------------------------------------------------------
# Part B -- the real ingestion path is idempotent end to end
# ---------------------------------------------------------------------------

def part_b(root):
    print("\nPart B -- run_ingestion_with_progress idempotency (integration)")
    from backend.modules import vector_store as vs

    # Enough distinct paragraphs to force several chunks under any profile.
    body = "".join(
        "Case note %04d: the courier ORION-77 moved a crate to Havenport "
        "docks at 0%d:%02d. Witness Zephyrine Kalt logged the same plate "
        "number in the ledger, reference ZK-%04d.\n" % (i, i % 24, i % 60, i)
        for i in range(60))

    filename = "notes_orion.txt"
    case_id, ev_id, stored = _seed_case_and_evidence(root, filename, body)
    qpath = vs.case_qdrant_path(case_id)

    _ingest(case_id, ev_id, stored, filename)
    rows1 = _scroll_points(vs, case_id, qpath)
    cc1 = _chunk_count(ev_id)
    ids1 = sorted(r[0] for r in rows1)

    _ingest(case_id, ev_id, stored, filename)
    rows2 = _scroll_points(vs, case_id, qpath)
    cc2 = _chunk_count(ev_id)
    ids2 = sorted(r[0] for r in rows2)

    check("B4 the first ingest really produced a multi-chunk index",
          len(rows1) > 1,
          f"only {len(rows1)} point(s) -- cannot test idempotency")
    check("B1 second full ingest does not grow the point count",
          len(rows2) == len(rows1),
          f"{len(rows1)} -> {len(rows2)} points")
    check("B2 evidence.chunk_count is stable across re-ingest",
          cc1 == cc2 == len(rows1),
          f"chunk_count {cc1} -> {cc2}, collection holds {len(rows1)}")
    keys = [(r[1], r[2]) for r in rows2]
    check("B3 (source, chunk_index) is unique after re-ingest",
          len(keys) == len(set(keys)),
          f"{len(keys) - len(set(keys))} duplicate (source, chunk_index)")
    check("B2b point ids are deterministic across re-ingest",
          ids1 == ids2,
          f"{len(set(ids1) ^ set(ids2))} of {len(ids1)} ids changed")

    # Part C -- the same defect as a query sees it.
    hits = vs.search_chunks(query="ORION-77 courier movement",
                            case_id=case_id, qdrant_path=qpath, top_k=50)
    seen = [(h["source"], h["chunk_index"]) for h in hits]
    check("C1 search returns no duplicate (source, chunk_index)",
          len(seen) == len(set(seen)),
          f"{len(seen) - len(set(seen))} duplicate hit(s) across "
          f"{len(seen)} results")

    return case_id, ev_id, stored, filename


# ---------------------------------------------------------------------------
# Part D -- a re-ingest after the extracted text changed must REPLACE
# ---------------------------------------------------------------------------

def part_d(case_id, ev_id, stored, filename):
    print("\nPart D -- changed-content re-ingest replaces, not appends")
    from backend.modules import vector_store as vs
    qpath = vs.case_qdrant_path(case_id)

    # A shorter body produces fewer chunks than the Part B body. If the previous
    # points were not cleared first, the collection would hold old + new and D1
    # would see more points than the new chunk count.
    shorter = "".join(
        "Revised note %04d: crate ORION-77 logged at Havenport.\n" % i
        for i in range(6))
    with open(stored, "wb") as f:
        f.write(shorter.encode("utf-8"))

    _ingest(case_id, ev_id, stored, filename)
    rows = _scroll_points(vs, case_id, qpath)
    cc = _chunk_count(ev_id)
    keys = [(r[1], r[2]) for r in rows]

    check("D1 changed re-ingest leaves no stale points",
          len(rows) == cc,
          f"collection holds {len(rows)} point(s) but chunk_count={cc} "
          f"(stale points survived the replace)")
    check("D2 changed re-ingest keeps (source, chunk_index) unique",
          len(keys) == len(set(keys)),
          f"{len(keys) - len(set(keys))} duplicate (source, chunk_index)")


def main():
    print("=" * 66)
    print("Stage 3 -- re-index idempotency")
    print("=" * 66)
    _make_env(TMP)

    # Backend now imports against the isolated env.
    from backend.modules import vector_store as vs
    _stub_embedder(vs)

    try:
        part_a()
        case_id, ev_id, stored, filename = part_b(TMP)
        part_d(case_id, ev_id, stored, filename)
    finally:
        # Release the per-case Qdrant directory locks (Windows) before the
        # atexit rmtree runs.
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
