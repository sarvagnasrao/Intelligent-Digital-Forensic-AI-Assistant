#!/usr/bin/env python3
"""
Stage 5 (workstream P) -- A9 bounded media read + A10 the 500-artifact cap.

A9 -- the document path reads whole files with no ceiling and no stop
---------------------------------------------------------------------
`ingestion.py` read the multimedia branch with a bare `data = f.read()`:
the entire file in one allocation, no `stop_check`, and none of the size
policy (`forensic_ingestion.MAX_FILE_SIZE = 50 MB` /
`VIDEO_MAX_FILE_SIZE = 2 GB`) that the in-image walk already enforces. A
mislabeled 2 GB "video" was read into RAM with no ceiling, and an operator's
Stop could not fire until the read returned -- the same "Stop looks broken"
failure the forensic hash loop was fixed for.

A10 -- indexing stops silently at 500 artifacts
-----------------------------------------------
The forensic store loop `break`s once `stored_files >= 500` and prints one line
to stdout. Nothing in the database records that further artifacts were
extracted but left unsearchable: the queue row says "Complete - N artifacts",
the evidence row says Indexed, and a search that misses one of the un-indexed
files reads as "not on the disk" rather than "not in the index".

What this suite asserts
-----------------------
Part A (A9, unit -- the read helper):
  A1 a small file reads back byte-for-byte
  A2 a file over the size cap is refused, not read
  A3 a stop request aborts the read
  A4 the cap follows the shared 50 MB / 2 GB format policy

Part B (A9, integration -- the real pipeline):
  B1 an over-limit multimedia file fails the evidence loudly, naming the cap
  B2 the failure is NOT the silent "Indexed with 0 chunks"

Part D (A10 -- the cap record):
  D1 `_artifact_cap_report` returns None when nothing was cut
  D2 it reports the counts and a reason when the cap bit
  D3 the forensic run persists a FILE_INGEST_ARTIFACT_CAP audit record
  D3b evidence.notes carries the reason the operator can read
  D4 the cap limits INDEXING only -- every artifact is still recovered
  D5 only the capped number of artifacts reach the embedder

Isolation follows `verify_reindex_idempotency.py`: temp DB / cases / Qdrant dirs
before any backend import, `atexit` cleanup, deterministic embedder stub.

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

TMP = tempfile.mkdtemp(prefix="cfi_perf_ing_")
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
    """Must run before any backend import."""
    db_path = os.path.join(root, "perf_ing.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path
    os.environ["CASES_DIR"] = os.path.join(root, "cases")
    os.environ["QDRANT_DIR"] = os.path.join(root, "qdrant")
    os.environ["DEBUG"] = "False"


def _seed(case_id, ev_id, filename, data):
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
        db.add(models.Case(id=case_id, case_name="PERF ingest",
                           case_number=None, status="Active",
                           created_by="perf"))
        db.commit()
    db.add(models.Evidence(
        id=ev_id, case_id=case_id, filename=filename,
        original_filename=filename,
        file_type=os.path.splitext(filename)[1].lstrip(".") or "txt",
        file_size_bytes=len(data), file_path=stored,
        ingested_by="perf", status="Uploaded"))
    db.commit()
    db.close()
    return stored


def _evidence(ev_id):
    from backend.database import SessionLocal
    from backend import models
    db = SessionLocal()
    try:
        return db.query(models.Evidence).filter(
            models.Evidence.id == ev_id).first()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Part A -- the bounded read helper (A9)
# ---------------------------------------------------------------------------

def part_a():
    print("\nPart A -- bounded, stop-honouring media read (A9)")
    from backend import ingestion as ing
    from backend.modules import forensic_ingestion as fi

    read = getattr(ing, "_read_media_bytes", None)
    if not callable(read):
        for lbl in ("A1 small file read returns the exact bytes",
                    "A2 an over-limit file is refused, not read",
                    "A3 a stop request raises StopIteration",
                    "A4 the cap follows the shared 50 MB / 2 GB policy"):
            check(lbl, False, "no _read_media_bytes in ingestion")
        return

    small = os.path.join(TMP, "small.csv")
    payload = b"date,account,amount\n2025-03-12,ACC-1,10.00\n"
    with open(small, "wb") as f:
        f.write(payload)
    check("A1 small file read returns the exact bytes",
          read(small, "small.csv") == payload)

    big = os.path.join(TMP, "big.csv")
    with open(big, "wb") as f:
        f.write(b"x" * 4096)

    saved = fi.MAX_FILE_SIZE
    fi.MAX_FILE_SIZE = 1024
    try:
        try:
            read(big, "big.csv")
            check("A2 an over-limit file is refused, not read", False,
                  "returned normally for a 4 KB file under a 1 KB cap")
        except RuntimeError as e:
            check("A2 an over-limit file is refused, not read",
                  "limit" in str(e).lower(), str(e)[:120])
        except Exception as e:
            check("A2 an over-limit file is refused, not read", False,
                  f"{type(e).__name__}: {e}")
    finally:
        fi.MAX_FILE_SIZE = saved

    calls = {"n": 0}

    def _stop():
        calls["n"] += 1
        return True

    try:
        read(small, "small.csv", stop_check=_stop)
        check("A3 a stop request raises StopIteration", False,
              "returned normally")
    except StopIteration:
        check("A3 a stop request raises StopIteration", True)
    except Exception as e:
        check("A3 a stop request raises StopIteration", False,
              f"{type(e).__name__}: {e}")

    # The policy is read from forensic_ingestion, not copied: a .csv gets the
    # 50 MB text cap and a .mp4 gets the 2 GB video cap.
    limit_csv = ing._media_size_limit("x.csv")
    limit_mp4 = ing._media_size_limit("x.mp4")
    check("A4 the cap follows the shared 50 MB / 2 GB policy",
          limit_csv == fi.MAX_FILE_SIZE
          and limit_mp4 == fi.VIDEO_MAX_FILE_SIZE
          and limit_mp4 > limit_csv,
          f"csv={limit_csv} mp4={limit_mp4}")


# ---------------------------------------------------------------------------
# Part B -- an oversized file fails loudly, in the real pipeline (A9)
# ---------------------------------------------------------------------------

def part_b():
    print("\nPart B -- the real document pipeline refuses an oversized file")
    from backend import ingestion as ing
    from backend.modules import forensic_ingestion as fi

    if not callable(getattr(ing, "_read_media_bytes", None)):
        check("B1 oversized file marks the evidence Failed", False,
              "no _read_media_bytes in ingestion")
        check("B1b the failure message names the size limit", False,
              "no _read_media_bytes in ingestion")
        return

    case_id, ev_id = str(uuid.uuid4()), str(uuid.uuid4())
    stored = _seed(case_id, ev_id, "huge.csv", b"y" * 8192)

    saved = fi.MAX_FILE_SIZE
    fi.MAX_FILE_SIZE = 2048
    raised = None
    try:
        ing.run_ingestion_with_progress(
            evidence_id=ev_id, case_id=case_id, file_path=stored,
            filename="huge.csv", job_id=None)
    except Exception as e:  # noqa: BLE001 - the pipeline re-raises by design
        raised = e
    finally:
        fi.MAX_FILE_SIZE = saved

    ev = _evidence(ev_id)
    check("B1 oversized file marks the evidence Failed",
          ev is not None and ev.status == "Failed",
          f"status={getattr(ev, 'status', None)}, raised={raised!r}")
    check("B1b the failure message names the size limit",
          ev is not None and "limit" in (ev.error_message or "").lower(),
          f"error_message={getattr(ev, 'error_message', None)!r}")


# ---------------------------------------------------------------------------
# Part C -- the 500-artifact cap is surfaced, not silent (A10)
# ---------------------------------------------------------------------------

class _FakeGovernor:
    def __init__(self):
        self._stop_check = None

    def check_and_throttle(self):
        return None


def _fake_enriched(i):
    name = f"artifact_{i}.txt"
    return {
        "internal_path": f"/dir/{name}",
        "filename": name,
        "size": 128,
        "sha256_hash": f"{i:064d}",
        "modified": "2025-03-14 02:11:07 UTC",
        "accessed": "2025-03-14 02:11:07 UTC",
        "created": "2025-03-14 02:11:07 UTC",
        "born": "2025-03-14 02:11:07 UTC",
        "extracted_text": f"note number {i}: the courier ORION-77 passed here.",
        "extraction_type": "text",
        "shannon_entropy": 3.5,
        "is_deleted": False,
        "gps_latitude": None,
        "gps_longitude": None,
        "stored_file_path": None,
        "stored_file_size": 128,
        "is_viewable": True,
    }


def part_c():
    print("\nPart C -- indexing cap surfaced in the database (A10)")
    from backend import ingestion as ing
    from backend.database import SessionLocal
    from backend import models

    report_fn = getattr(ing, "_artifact_cap_report", None)
    check("C0 _artifact_cap_report exists", callable(report_fn),
          "no _artifact_cap_report in ingestion")
    check("C0b FORENSIC_ARTIFACT_INDEX_CAP is declared",
          getattr(ing, "FORENSIC_ARTIFACT_INDEX_CAP", None) == 500,
          f"cap={getattr(ing, 'FORENSIC_ARTIFACT_INDEX_CAP', None)!r}")

    if callable(report_fn):
        check("C1 no report when the whole corpus was indexed",
              report_fn(3, 3) is None, f"{report_fn(3, 3)!r}")
        rep = report_fn(2, 5)
        check("C2 a truncated index produces a report naming the counts",
              isinstance(rep, dict)
              and rep.get("artifacts_not_indexed") == 3
              and "reason" in rep,
              f"{rep!r}")

    if not callable(report_fn):
        for lbl in ("C3 an AuditLog row records the cap",
                    "C3b evidence.notes carries the reason",
                    "C4 every extracted artifact is still saved",
                    "C5 only the capped number of artifacts is embedded"):
            check(lbl, False, "_artifact_cap_report missing")
        return

    # --- run the forensic pipeline with the cap forced to 2 and 3 artifacts.
    import backend.modules.anomaly_detector as ad
    import backend.modules.credential_scanner as cs

    case_id, ev_id = str(uuid.uuid4()), str(uuid.uuid4())
    image = os.path.join(TMP, "image.raw")
    with open(image, "wb") as f:
        f.write(b"\x00" * 1024)

    saved = {
        "ingest_raw": ing.ingest_raw,
        "extract_file_content": ing.extract_file_content,
        "compute_sha256": ing.compute_sha256,
        "detect_image_format": ing.detect_image_format,
        "inspect_raw_image": ing.inspect_raw_image,
        "image_segment_paths": ing.image_segment_paths,
        "store_chunks": ing.store_chunks,
        "build_graph": ing.build_graph,
        "cap": getattr(ing, "FORENSIC_ARTIFACT_INDEX_CAP", 500),
    }
    ad_saved = ad.run_anomaly_detection
    cs_saved = cs.scan_chunks

    stored_calls = []

    def _fake_store(chunks, source_filename, evidence_id, case_id,
                    qdrant_path, **kw):
        stored_calls.append(source_filename)
        return len(chunks)

    def _fake_generator(file_path, temp_dir, include_deleted=False):
        for i in range(3):
            yield {"internal_path": f"/dir/artifact_{i}.txt",
                   "filename": f"artifact_{i}.txt", "size": 128}

    ing.ingest_raw = _fake_generator
    ing.extract_file_content = lambda fi_, td, eb: _fake_enriched(
        int(fi_["filename"].split("_")[1].split(".")[0]))
    ing.compute_sha256 = lambda p, stop_check=None: "deadbeef"
    ing.detect_image_format = lambda p: "raw"
    ing.inspect_raw_image = lambda p: {"summary": "", "truncated": False}
    ing.image_segment_paths = lambda p: [p]
    ing.store_chunks = _fake_store
    ing.build_graph = lambda **kw: ({}, [])
    ing.FORENSIC_ARTIFACT_INDEX_CAP = 2
    ad.run_anomaly_detection = lambda dicts: []
    cs.scan_chunks = lambda chunks, filename: []

    run_error = None
    stored_path = _seed(case_id, ev_id, "disk.raw", b"\x00" * 1024)
    try:
        db = SessionLocal()
        try:
            ev = db.query(models.Evidence).filter(
                models.Evidence.id == ev_id).first()
            ing._run_forensic_with_progress(
                ev, case_id, stored_path, "disk.raw",
                None, _FakeGovernor(), False,
                ing.case_qdrant_path(case_id), db,
                progress_callback=None,
                mode={"key": "test", "chunk_size": 700,
                      "chunk_overlap": 0, "include_deleted": False})
        except Exception as e:  # noqa: BLE001 - recorded, not swallowed
            run_error = f"{type(e).__name__}: {e}"
        finally:
            db.close()
    finally:
        ing.ingest_raw = saved["ingest_raw"]
        ing.extract_file_content = saved["extract_file_content"]
        ing.compute_sha256 = saved["compute_sha256"]
        ing.detect_image_format = saved["detect_image_format"]
        ing.inspect_raw_image = saved["inspect_raw_image"]
        ing.image_segment_paths = saved["image_segment_paths"]
        ing.store_chunks = saved["store_chunks"]
        ing.build_graph = saved["build_graph"]
        ing.FORENSIC_ARTIFACT_INDEX_CAP = saved["cap"]
        ad.run_anomaly_detection = ad_saved
        cs.scan_chunks = cs_saved

    db = SessionLocal()
    try:
        ev = db.query(models.Evidence).filter(
            models.Evidence.id == ev_id).first()
        audits = db.query(models.AuditLog).filter(
            models.AuditLog.case_id == case_id,
            models.AuditLog.action_type == "FILE_INGEST_ARTIFACT_CAP").all()
        artifacts = db.query(models.ForensicArtifact).filter(
            models.ForensicArtifact.evidence_id == ev_id).all()
    finally:
        db.close()

    check("C2 pipeline ran without error", run_error is None, run_error or "")
    check("C3 an AuditLog row records the cap",
          len(audits) == 1,
          f"{len(audits)} FILE_INGEST_ARTIFACT_CAP row(s)")
    check("C3b the audit details name what was not indexed",
          bool(audits) and "not_indexed"
          in (audits[0].details if audits else ""),
          f"details={audits[0].details if audits else None!r}")
    check("C3c evidence.notes carries the reason",
          ev is not None and "not embedded" in (ev.notes or "").lower(),
          f"notes={getattr(ev, 'notes', None)!r}")
    check("C4 every extracted artifact was still recovered",
          len(artifacts) == 3,
          f"{len(artifacts)} artifact row(s) for 3 extracted files")
    check("C4b the evidence is still marked Indexed (partial by design)",
          ev is not None and ev.status == "Indexed",
          f"status={getattr(ev, 'status', None)}")
    check("C5 only the capped number of files were embedded",
          len(stored_calls) == 2, f"store_chunks called for {stored_calls}")


def main():
    _make_env(TMP)

    from backend.database import init_db
    init_db()

    try:
        part_a()
        part_b()
        part_c()
    finally:
        try:
            from backend.modules import vector_store as vs
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
