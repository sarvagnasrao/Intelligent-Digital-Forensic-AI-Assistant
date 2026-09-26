"""End-to-end verification of the three ingestion profiles.

Runs the real pipeline (no mocks) against a generated text document, once per
profile, and asserts:

  * the job reaches 100% and status Completed
  * the profile's knobs actually reach the pipeline (chunk size, batch)
  * progress ticks are monotonically non-decreasing
  * the same file ingested under 'accurate' produces at least as many, and
    normally more, chunks than 'fastest' - which is the whole point of
    offering the choice
"""
import os
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, engine
from backend import models
from backend.modules.ingestion_modes import resolve_mode_for_device, MODES
from backend.modules.resource_governor import ResourceGovernor
from backend.ingestion import run_ingestion_with_progress

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + str(detail)) if detail else ''}")


def _cleanup(case_id, settings):
    """Removes every row and directory this script created.

    Without this the checks would leave cases, evidence, entities and a
    per-case Qdrant store behind on each run, and a re-run would be testing
    against an ever-growing pile of the previous run's data.
    """
    import shutil

    db = SessionLocal()
    try:
        for model in (models.ForensicArtifact, models.Entity,
                      models.IngestionJob, models.Evidence):
            try:
                db.query(model).filter(
                    model.case_id == case_id).delete(
                    synchronize_session=False)
            except Exception:
                pass
        db.query(models.Case).filter(
            models.Case.id == case_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    case_dir = os.path.join(settings.cases_dir, case_id)
    if os.path.isdir(case_dir):
        shutil.rmtree(case_dir, ignore_errors=True)


BODY = (
    "Digital forensic examination report. " * 900 +
    "Suspect device imaged on 2025-11-03. " * 400 +
    "Contact sarvagnasrao@example.com and 192.168.1.44. " * 200
)


def main():
    from backend.dependencies import get_settings
    settings = get_settings()
    os.makedirs(settings.cases_dir, exist_ok=True)

    db = SessionLocal()

    # ── A throwaway case to hang the test evidence off ─────────────────────
    case_id = str(uuid.uuid4())
    case = models.Case(
        id=case_id,
        case_number=f"TEST-{uuid.uuid4().hex[:6].upper()}",
        case_name="Ingestion profile verification",
        description="Automated end-to-end check of fastest/normal/accurate",
        status="Active",
        created_by="verify",
    )
    db.add(case)
    db.commit()

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

        # ── Evidence row ───────────────────────────────────────────────────
        ev_id = str(uuid.uuid4())
        tmp_dir = tempfile.mkdtemp(prefix="idfai_mode_test_")
        src = os.path.join(tmp_dir, "report.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write(BODY)
        size = os.path.getsize(src)

        ev = models.Evidence(
            id=ev_id,
            case_id=case_id,
            filename=os.path.basename(src),
            original_filename=os.path.basename(src),
            file_path=src,
            file_size_bytes=size,
            file_type="text",
            sha256_hash="0" * 64,
            ingested_by="verify",
            status="Queued",
        )
        db.add(ev)

        job_id = str(uuid.uuid4())
        job = models.IngestionJob(
            id=job_id,
            evidence_id=ev_id,
            case_id=case_id,
            status="Running",
            progress_percent=0,
            min_free_ram_mb=256,
            cpu_throttle_percent=100,
            ingestion_mode=mode_key,
            created_by="verify",
        )
        db.add(job)
        db.commit()

        # ── Capture every progress tick ────────────────────────────────────
        ticks = []

        def on_progress(cid, jid, eid, percent, step):
            ticks.append((percent, step))

        t0 = time.time()
        run_ingestion_with_progress(
            evidence_id=ev_id,
            case_id=case_id,
            file_path=src,
            filename=os.path.basename(src),
            job_id=job_id,
            governor=ResourceGovernor(
                min_free_ram_mb=256, cpu_throttle_percent=100),
            progress_callback=on_progress,
            mode=mode,
        )
        elapsed = time.time() - t0

        db.expire_all()
        job = db.query(models.IngestionJob).filter(
            models.IngestionJob.id == job_id).first()
        ev = db.query(models.Evidence).filter(
            models.Evidence.id == ev_id).first()

        chunks = ev.chunk_count or 0
        results[mode_key] = {
            "chunks": chunks,
            "entities": ev.entity_count or 0,
            "status": ev.status,
            "job_status": job.status,
            "percent": job.progress_percent,
            "step": job.current_step,
            "elapsed": elapsed,
            "ticks": len(ticks),
            "text_len": len(BODY),
        }

        print(f"  result: status={ev.status} job={job.status} "
              f"percent={job.progress_percent} chunks={chunks} "
              f"entities={ev.entity_count} in {elapsed:.1f}s")
        print(f"  final step: {job.current_step}")
        print(f"  progress ticks: {len(ticks)}")

        check(f"{mode_key}: evidence Indexed", ev.status == "Indexed", ev.status)
        check(f"{mode_key}: job Completed", job.status == "Completed", job.status)
        check(f"{mode_key}: job at 100%", job.progress_percent == 100,
              job.progress_percent)
        check(f"{mode_key}: job step says Complete",
              (job.current_step or "").startswith("Complete"),
              job.current_step)
        check(f"{mode_key}: chunks were stored", chunks > 0, chunks)
        check(f"{mode_key}: progress ticked", len(ticks) >= 5, len(ticks))

        percents = [p for p, _ in ticks]
        check(f"{mode_key}: progress monotonic",
              all(b >= a for a, b in zip(percents, percents[1:])),
              percents)
        check(f"{mode_key}: progress ends at 100", percents[-1] == 100, percents[-1])

        # The profile must be recorded on the row so a retry reproduces it.
        check(f"{mode_key}: mode persisted on job",
              job.ingestion_mode == mode_key, job.ingestion_mode)

        # ── Cleanup so repeated runs do not pile up Qdrant dirs ────────────
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # ── Cross-profile behaviour ────────────────────────────────────────────
    print("\n=== cross-profile ===")
    print(f"  body length      : {results['fastest']['text_len']} chars")
    print(f"  fastest  chunks  : {results['fastest']['chunks']}")
    print(f"  normal   chunks  : {results['normal']['chunks']}")
    print(f"  accurate chunks  : {results['accurate']['chunks']}")

    check("accurate yields more chunks than fastest",
          results['accurate']['chunks'] > results['fastest']['chunks'],
          f"{results['accurate']['chunks']} vs {results['fastest']['chunks']}")
    check("fastest yields fewer chunks than normal",
          results['fastest']['chunks'] <= results['normal']['chunks'],
          f"{results['fastest']['chunks']} vs {results['normal']['chunks']}")

    # The chunk counts must be consistent with the configured chunk sizes,
    # which is what proves the mode actually reached the pipeline rather than
    # being stored on the row and then ignored.
    for key, mode_key in (("fastest", "fastest"), ("normal", "normal"),
                          ("accurate", "accurate")):
        cs = MODES[mode_key]["chunk_size"]
        expect = -(-len(BODY) // cs)          # ceil
        got = results[key]["chunks"]
        check(f"{mode_key}: chunk count matches chunk_size {cs}",
              got == expect, f"expected {expect}, got {got}")

    # ── Report ─────────────────────────────────────────────────────────────
    _cleanup(case_id, settings)
    print(f"\n{'=' * 62}")
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    code = main()
    db = SessionLocal()
    db.close()
    sys.exit(code)
