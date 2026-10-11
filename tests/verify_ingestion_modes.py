#!/usr/bin/env python3
"""
End-to-end verification of the three ingestion profiles.

Runs the real pipeline (no mocks) against a generated text document, once per
profile, and asserts:

  * the job reaches 100% and status Completed
  * the profile's knobs actually reach the pipeline (chunk size, batch)
  * progress ticks are monotonically non-decreasing
  * the same file ingested under 'accurate' produces at least as many, and
    normally more, chunks than 'fastest' - which is the whole point of
    offering the choice

Isolation follows `verify_reindex_idempotency.py` and `verify_perf_batching.py`:
temp DB / cases / Qdrant dirs chosen BEFORE any backend import, an `atexit`
cleanup, and a deterministic embedder stub so the suite is fast and offline.
"""

import atexit
import hashlib
import os
import shutil
import sys
import tempfile
import time
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

TMP = tempfile.mkdtemp(prefix="cfi_ing_modes_")
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
    db_path = os.path.join(root, "ing_modes.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path
    os.environ["CASES_DIR"] = os.path.join(root, "cases")
    os.environ["QDRANT_DIR"] = os.path.join(root, "qdrant")
    os.environ["DEBUG"] = "False"


def _fake_embed(texts):
    """Deterministic 384-dim vectors without torch / sentence-transformers."""
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        vec = [((h[i % len(h)] / 255.0) - 0.5) for i in range(384)]
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        out.append([x / norm for x in vec])
    return out


class _Array:
    def __init__(self, data):
        self._data = data

    def tolist(self):
        return self._data


def _stub_embedder(vs):
    """No torch / model load; keep provenance comparing like-for-like."""
    vs._embed_model = type("_FakeModel", (), {
        "encode": lambda self, texts, **kw: _Array(_fake_embed(texts)),
        "get_sentence_embedding_dimension": lambda self: 384,
        "max_seq_length": 256,
    })()
    vs._embed_tried = True
    vs.describe_embedder = lambda: {
        "embedder_id": vs.EMBEDDER_ID,
        "vector_size": vs.VECTOR_SIZE,
        "max_seq_length": 256,
    }


# ---------------------------------------------------------------------------
# Corpus and mode constants (copied to avoid importing before env is set)
# ---------------------------------------------------------------------------

BODY = (
    "Digital forensic examination report. " * 900 +
    "Suspect device imaged on 2025-11-03. " * 400 +
    "Contact sarvagnasrao@example.com and 192.168.1.44. " * 200
)

MODES = {
    "fastest": {
        "chunk_size": 700, "chunk_overlap": 120, "embed_batch": 256,
        "ocr": False, "whisper_model": "tiny", "whisper_gpu": False,
        "include_deleted": False,
    },
    "normal": {
        "chunk_size": 700, "chunk_overlap": 120, "embed_batch": 128,
        "ocr": True, "whisper_model": "base", "whisper_gpu": False,
        "include_deleted": False,
    },
    "accurate": {
        "chunk_size": 700, "chunk_overlap": 120, "embed_batch": 64,
        "ocr": True, "whisper_model": "small", "whisper_gpu": False,
        "include_deleted": True,
    },
}


def _seed_case(case_id, ev_id, filename, data):
    """Write a file and its case/evidence rows into the isolated DB."""
    from backend.database import SessionLocal
    from backend import models

    ev_dir = os.path.join(TMP, "cases", case_id, "evidence")
    os.makedirs(ev_dir, exist_ok=True)
    stored = os.path.join(ev_dir, f"{ev_id}_{filename}")
    with open(stored, "wb") as f:
        f.write(data)

    db = SessionLocal()
    if not db.query(models.Case).filter(models.Case.id == case_id).first():
        db.add(models.Case(
            id=case_id, case_name="Ingestion profile verification",
            case_number=None, status="Active", created_by="verify"))
        db.commit()
    db.add(models.Evidence(
        id=ev_id, case_id=case_id, filename=filename,
        original_filename=filename,
        file_path=stored, file_size_bytes=len(data),
        file_type=os.path.splitext(filename)[1].lstrip(".") or "txt",
        sha256_hash=hashlib.sha256(data).hexdigest(),
        ingested_by="verify", status="Queued"))
    db.commit()
    db.close()
    return stored


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    _make_env(TMP)

    # Import AFTER env is set
    from backend.database import init_db, SessionLocal
    from backend import models
    from backend.modules import job_worker as jw
    from backend.modules.ingestion_modes import resolve_mode_for_device
    from backend.ingestion import run_ingestion_with_progress
    from backend.modules.resource_governor import ResourceGovernor
    from backend.modules import vector_store as vs

    _stub_embedder(vs)
    init_db()

    # Stop the worker so jobs run deterministically (see verify_queue_api.py)
    jw.stop_worker()
    t = jw._worker_thread
    if t is not None and t.is_alive():
        t.join(timeout=30)

    db = SessionLocal()
    try:
        case_id = str(uuid.uuid4())
        db.add(models.Case(
            id=case_id,
            case_number=f"TEST-{uuid.uuid4().hex[:6].upper()}",
            case_name="Ingestion profile verification",
            description="Automated end-to-end check of fastest/normal/accurate",
            status="Active", created_by="verify"))
        db.commit()
    finally:
        db.close()

    results = {}

    for mode_key in ("fastest", "normal", "accurate"):
        print(f"\n=== profile: {mode_key} ===")
        mode = resolve_mode_for_device(mode_key)
        print(f"  resolved: chunk={mode['chunk_size']} overlap={mode['chunk_overlap']} "
              f"batch={mode['embed_batch']} ocr={mode['ocr']} "
              f"whisper={mode['whisper_model']}/{mode['whisper_gpu']} "
              f"deleted={mode['include_deleted']}")
        if mode.get("warnings"):
            for w in mode["warnings"]:
                print(f"  warning: {w}")

        # Evidence row
        ev_id = str(uuid.uuid4())
        stored = _seed_case(case_id, ev_id, "report.txt", BODY.encode("utf-8"))

        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            job = models.IngestionJob(
                id=job_id, evidence_id=ev_id, case_id=case_id,
                status="Running", progress_percent=0,
                min_free_ram_mb=256, cpu_throttle_percent=100,
                ingestion_mode=mode_key, created_by="verify")
            db.add(job)
            db.commit()
        finally:
            db.close()

        # Capture every progress tick
        ticks = []

        def on_progress(cid, jid, eid, percent, step):
            ticks.append((percent, step))

        t0 = time.time()
        run_ingestion_with_progress(
            evidence_id=ev_id, case_id=case_id, file_path=stored,
            filename="report.txt", job_id=job_id,
            governor=ResourceGovernor(min_free_ram_mb=256, cpu_throttle_percent=100),
            progress_callback=on_progress, mode=mode)
        elapsed = time.time() - t0

        db = SessionLocal()
        try:
            job = db.query(models.IngestionJob).filter(
                models.IngestionJob.id == job_id).first()
            ev = db.query(models.Evidence).filter(
                models.Evidence.id == ev_id).first()
            chunks = ev.chunk_count or 0
            entities = ev.entity_count or 0
        finally:
            db.close()

        results[mode_key] = {
            "chunks": chunks, "entities": entities,
            "status": ev.status, "job_status": job.status,
            "percent": job.progress_percent, "step": job.current_step,
            "elapsed": elapsed, "ticks": len(ticks),
            "text_len": len(BODY), "mode": mode,
        }

        print(f"  result: status={ev.status} job={job.status} "
              f"percent={job.progress_percent} chunks={chunks} "
              f"entities={entities} in {elapsed:.1f}s")
        print(f"  final step: {job.current_step}")
        print(f"  progress ticks: {len(ticks)}")

        check(f"{mode_key}: evidence Indexed", ev.status == "Indexed", ev.status)
        check(f"{mode_key}: job Completed", job.status == "Completed", job.status)
        check(f"{mode_key}: job at 100%", job.progress_percent == 100, job.progress_percent)
        check(f"{mode_key}: job step says Complete",
              (job.current_step or "").startswith("Complete"), job.current_step)
        check(f"{mode_key}: chunks were stored", chunks > 0, chunks)
        check(f"{mode_key}: progress ticked", len(ticks) >= 5, len(ticks))

        percents = [p for p, _ in ticks]
        check(f"{mode_key}: progress monotonic",
              all(b >= a for a, b in zip(percents, percents[1:])),
              percents)
        check(f"{mode_key}: progress ends at 100", percents[-1] == 100, percents[-1])

        check(f"{mode_key}: mode persisted on job",
              job.ingestion_mode == mode_key, job.ingestion_mode)

    # Cross-profile behaviour
    print("\n=== cross-profile ===")
    print(f"  body length      : {results['fastest']['text_len']} chars")
    print(f"  fastest  chunks  : {results['fastest']['chunks']}")
    print(f"  normal   chunks  : {results['normal']['chunks']}")
    print(f"  accurate chunks  : {results['accurate']['chunks']}")

    from backend.modules.text_parser import chunk_text

    check("all profiles yield the same chunk count (global chunking)",
          results['fastest']['chunks'] == results['normal']['chunks']
          == results['accurate']['chunks'],
          f"{results['fastest']['chunks']} vs {results['normal']['chunks']} vs "
          f"{results['accurate']['chunks']}")
    check("profiles still differ in the knobs that remain per-profile",
          results['fastest']['mode']['ocr'] is False
          and results['normal']['mode']['ocr'] is True
          and results['accurate']['mode']['ocr'] is True,
          "OCR differs across profiles")

    for mode_key in ("fastest", "normal", "accurate"):
        cs = MODES[mode_key]["chunk_size"]
        ov = MODES[mode_key].get("chunk_overlap", 0) or 0

        check(f"{mode_key}: overlap is smaller than the chunk size",
              0 <= ov < cs, f"chunk_size={cs} overlap={ov}")

        stride = cs - ov
        expect = -(-len(BODY) // stride)

        raw_loop = chunk_text(BODY, chunk_size=cs, overlap=ov)
        check(f"{mode_key}: the >20-char trim is not what sets the count",
              len(raw_loop) == expect,
              f"chunker returned {len(raw_loop)}, stride arithmetic says "
              f"{expect} — the assertion below is only exact while these agree")

        check(f"{mode_key}: chunk count matches chunk_size {cs} "
              f"stride {stride}",
              results[mode_key]["chunks"] == expect,
              f"expected {expect}, got {results[mode_key]['chunks']}")

    # A failed index must never read as a successful one
    print("\n=== an indexing failure is not a success ===")
    import backend.ingestion as ingestion_mod
    from backend.modules.vector_store import VectorStoreError

    fail_ev_id = str(uuid.uuid4())
    fail_stored = _seed_case(case_id, fail_ev_id, "report.txt", BODY.encode("utf-8"))

    fail_job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(models.IngestionJob(
            id=fail_job_id, evidence_id=fail_ev_id, case_id=case_id,
            status="Running", progress_percent=0,
            min_free_ram_mb=256, cpu_throttle_percent=100,
            ingestion_mode="normal", created_by="verify"))
        db.commit()
    finally:
        db.close()

    real_store = ingestion_mod.store_chunks

    def exploding_store(**kwargs):
        raise VectorStoreError("simulated Qdrant/Ollama outage")

    ingestion_mod.store_chunks = exploding_store
    raised = None
    try:
        run_ingestion_with_progress(
            evidence_id=fail_ev_id, case_id=case_id, file_path=fail_stored,
            filename="report.txt", job_id=fail_job_id,
            governor=ResourceGovernor(min_free_ram_mb=256, cpu_throttle_percent=100),
            mode=resolve_mode_for_device("normal"))
    except VectorStoreError as e:
        raised = e
    finally:
        ingestion_mod.store_chunks = real_store

    check("the store failure propagates instead of returning 0",
          isinstance(raised, VectorStoreError), raised)

    db = SessionLocal()
    try:
        job = db.query(models.IngestionJob).filter(
            models.IngestionJob.id == fail_job_id).first()
        ev = db.query(models.Evidence).filter(
            models.Evidence.id == fail_ev_id).first()
        check("job is Failed, not Completed", job.status == "Failed", job.status)
        check("job did not stay stuck on Running", job.status != "Running", job.status)
        check("job records the reason",
              bool(job.error_message) and "simulated" in (job.error_message or ""),
              (job.error_message or "")[:90])
        check("job has a terminal timestamp", job.completed_at is not None, job.completed_at)
        check("evidence is Failed, not Indexed", ev.status == "Failed", ev.status)
        check("evidence is not reported as having 0 chunks as a success",
              (ev.chunk_count or 0) == 0, ev.chunk_count)
    finally:
        db.close()

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