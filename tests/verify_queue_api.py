"""Smoke-test the queue API surface the new UI depends on.

Drives the real app through TestClient so the response shapes are exactly
what the frontend receives, and asserts the device-derived limits actually
appear (i.e. the '8 GB' hardcode is gone from the contract, not just the UI).
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Windows console defaults to cp1252 and chokes on the em-dash used in
# the assertion labels. Force UTF-8 rather than silently dropping output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fastapi.testclient import TestClient

PASS, FAIL = [], []

# Cleanup that runs on every exit path -- see tests/_purge.py for why the
# three original statements at the end of the happy path were not enough.
# Measured: they left 92 test accounts and 249 orphaned audit rows in
# data/forensic.db, because they never removed the registered user and never
# ran at all on a failing one.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _purge import Purge                                     # noqa: E402

_PURGE = Purge("verify_queue_api")
_purge, _track = _PURGE.run, _PURGE.ids
_track_user = _PURGE.user


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + str(detail)) if detail else ''}")


def main():
    from backend.main import app
    from backend.database import SessionLocal
    from backend.modules import job_worker as jw
    from backend import models

    with TestClient(app) as client:
        # ── Stop the ingestion worker before anything else ──────────────────
        # Entering this block ran the FastAPI lifespan, and that lifespan
        # calls `job_worker.start_worker()`. So this suite was racing a live
        # worker thread for its whole run.
        #
        # It showed up as a gate failure that looked like a product
        # regression:
        #
        #   FAIL  patch returns 200 - {"detail":"The ingestion profile is
        #         fixed once a job starts ..."}
        #
        # `/api/queue/add` creates a `Queued` job, the worker's loop polls
        # every 2 s, and it can start that job before the next request
        # arrives. Once the row said `Running`, refusing a profile change is
        # the *correct* product behaviour (B16) and the assertion failed
        # against it. A day before a review that is the worst possible
        # failure: a red suite that invites somebody to "fix" the product,
        # when the product is right.
        #
        # The fix is to remove the race, not to weaken the assertion. Every
        # status this suite asserts on is now one the suite itself chose.
        #
        # It has to happen *inside* the `with`, because the lifespan runs on
        # entry and would start the worker again otherwise.
        jw.stop_worker()
        _t = jw._worker_thread
        if _t is not None and _t.is_alive():
            # The loop sleeps up to 2 s between polls and a job already in
            # flight runs to completion, so this is not instant.
            _t.join(timeout=30)
        check("the ingestion worker is stopped, so job status is "
              "deterministic rather than a race",
              _t is None or not _t.is_alive(),
              "STILL ALIVE - every status assertion below is a race"
              if (_t is not None and _t.is_alive()) else "exited")
        # ── Auth ───────────────────────────────────────────────────────────
        email = f"modes_{uuid.uuid4().hex[:8]}@idfai.test"
        r = client.post("/api/auth/register", json={
            "username": email, "email": email, "password": "Verify@2026",
            "full_name": "Mode Verifier", "role": "Investigator",
        })
        # Tracked the moment it exists, by id *and* by username, so the hook can
        # remove both the account and the audit row registration wrote for it.
        try:
            _track_user((r.json() or {}).get("id"), email)
        except Exception:
            pass
        token = None
        if r.status_code < 400:
            # Register returns 201 without a token; sign in to get one.
            # /login takes an OAuth2 form, not JSON.
            r = client.post("/api/auth/login", data={
                "username": email, "password": "Verify@2026"})
            token = (r.json() or {}).get("access_token")
        if not token:
            # Fall back to the seeded admin so the run is still meaningful.
            r = client.post("/api/auth/login", data={
                "username": "admin", "password": "Admin@IDF2025"})
            token = (r.json() or {}).get("access_token")
        if not token:
            print(f"  SKIP  could not authenticate: {r.status_code} {r.text[:200]}")
            return 0
        H = {"Authorization": f"Bearer {token}"}

        # ── Promote to Investigator, in the database ────────────────────────
        # This used to ask for the role at registration:
        #     "role": "Investigator"
        # and it worked, because /register honoured whatever the client
        # asked for. That was a privilege-escalation hole — any anonymous
        # caller could register as Admin — and it has since been closed:
        # the server now assigns Analyst to every user after the first and
        # ignores any requested role.
        #
        # So this suite was passing *because of* the vulnerability, and
        # closing it turned 12 assertions red. The honest repair is here
        # rather than in the router: a test that needs a privileged account
        # must say so out loud, and must obtain the role the way an
        # administrator would, instead of relying on a hole.
        #
        # require_role() re-reads `user.role` off the row on every request,
        # so no re-login is needed after the UPDATE.
        db = SessionLocal()
        try:
            me = db.query(models.User).filter(
                models.User.username == email).first()
            if me:
                me.role = "Investigator"
                db.commit()
        finally:
            db.close()

        # ── GET /queue/modes ───────────────────────────────────────────────
        print("\n=== GET /api/queue/modes ===")
        r = client.get("/api/queue/modes", headers=H)
        check("modes endpoint returns 200", r.status_code == 200, r.status_code)
        modes = r.json().get("modes", [])
        check("exactly three profiles",
              [m["key"] for m in modes] == ["fastest", "normal", "accurate"],
              [m.get("key") for m in modes])
        for m in modes:
            eff = m.get("effective", {})
            print(f"  {m['key']:<9} chunk={eff.get('chunk_size')} "
                  f"overlap={eff.get('chunk_overlap')} "
                  f"batch={eff.get('embed_batch')} "
                  f"ocr={eff.get('ocr')} "
                  f"whisper={eff.get('whisper_model')}/"
                  f"{'gpu' if eff.get('whisper_gpu') else 'cpu'} "
                  f"deleted={eff.get('include_deleted')}")
        check("every profile carries a device-resolved 'effective' block",
              all(m.get("effective", {}).get("chunk_size")
                  for m in modes),
              [sorted(m.get("effective", {}).keys()) for m in modes])
        check("effective exposes every knob the pipeline reads",
              all(all(k in m.get("effective", {}) for k in
                      ("chunk_size", "chunk_overlap", "embed_batch", "ocr",
                       "whisper_model", "whisper_gpu", "include_deleted",
                       "max_parallel", "warnings"))
                  for m in modes),
              sorted(modes[0].get("effective", {}).keys()))
        check("default_mode is a valid key",
              r.json().get("default_mode") in
              ("fastest", "normal", "accurate"), r.json().get("default_mode"))
        # Chunking is now global (700/120) — profiles differ in OCR, Whisper,
        # deleted-file recovery, and embed_batch. The "least/most work" test
        # must reflect the knobs that actually differ, not the old chunk-size proxy.
        check("fastest does the least work, accurate the most",
              modes[0]["effective"]["ocr"] is False
              and modes[0]["effective"]["include_deleted"] is False
              and modes[2]["effective"]["ocr"] is True
              and modes[2]["effective"]["include_deleted"] is True
              and modes[0]["effective"]["embed_batch"] > modes[2]["effective"]["embed_batch"],
              "fastest: no OCR, no deleted-recovery, larger batch; accurate: OCR, deleted-recovery, smaller batch")

        # ── GET /queue/system-info ─────────────────────────────────────────
        print("\n=== GET /api/queue/system-info ===")
        r = client.get("/api/queue/system-info", headers=H)
        check("system-info returns 200", r.status_code == 200, r.status_code)
        body = r.json()
        for k in ("system", "hardware", "suggested_budget", "modes", "default_mode"):
            check(f"payload has '{k}'", k in body, list(body.keys()))
        b = body.get("suggested_budget", {})
        print(f"  budget: ram_floor_default={b.get('ram_floor_default_mb')} MB "
              f"ram_floor_max={b.get('ram_floor_max_mb')} MB "
              f"cpu={b.get('cpu_throttle_percent')}%")
        print(f"  device: {b.get('description')}")
        check("budget sends slider bounds", "ram_floor_max_mb" in b, list(b.keys()))
        check("slider ceiling never exceeds free RAM",
              0 < b.get("ram_floor_max_mb", 0) <= b.get("available_ram_mb", 0),
              f"max={b.get('ram_floor_max_mb')} avail={b.get('available_ram_mb')}")
        # The invariant is that the ceiling *tracks* available memory, not
        # that it sits below some constant. Asserting "below 8 GB" would pass
        # on a hardcoded 8192 MB and fail on a 32 GB box, which is backwards.
        #
        # The ceiling is available RAM rounded DOWN to a whole GB
        # (ingestion_modes.suggest_budget, `avail // 1024 * 1024`), with a
        # 1 GB floor and a 64 GB cap. Pin the formula itself rather than a
        # ratio band: the band is not a property of the design, it is a
        # side-effect of where free memory happened to sit when this ran. An
        # earlier version asserted "70-100% of free" and failed at 50% purely
        # because the machine had 2047 MB free instead of 2538 - the 1 GB
        # rounding discarded 1023 MB, which is correct behaviour, not a bug.
        # A ratio assertion cannot distinguish that from a real regression.
        avail = b.get("available_ram_mb", 0)
        total = b.get("total_ram_mb", 0)
        expected_max = max(1024, min(avail, total) // 1024 * 1024)
        expected_max = max(1024, min(expected_max, 64 * 1024))
        check("slider ceiling is free RAM floored to a whole GB",
              b.get("ram_floor_max_mb") == expected_max,
              f"max={b.get('ram_floor_max_mb')} expected={expected_max} "
              f"avail={avail} total={total}")
        check("slider ceiling is never above what is free",
              b.get("ram_floor_max_mb", 0) <= avail,
              f"max={b.get('ram_floor_max_mb')} avail={avail}")
        check("slider ceiling has a 1 GB floor even on a starved machine",
              b.get("ram_floor_max_mb", 0) >= 1024,
              f"max={b.get('ram_floor_max_mb')}")
        check("default floor sits inside the slider range",
              b.get("ram_floor_min_mb", 0) <= b.get("ram_floor_default_mb", 0)
              <= b.get("ram_floor_max_mb", 0),
              f"{b.get('ram_floor_min_mb')} <= "
              f"{b.get('ram_floor_default_mb')} <= "
              f"{b.get('ram_floor_max_mb')}")
        check("budget is within the machine's RAM",
              0 < b.get("ram_floor_default_mb", 0) <= b.get("total_ram_mb", 0),
              f"{b.get('ram_floor_default_mb')} of {b.get('total_ram_mb')}")

        # ── POST /queue/estimate (mode-aware) ──────────────────────────────
        print("\n=== POST /api/queue/estimate ===")
        db = SessionLocal()
        try:
            case_id = str(uuid.uuid4())
            db.add(models.Case(id=case_id, case_name="API modes",
                               created_by="verify"))
            db.commit()
            _track(case_id)
            ev_id = str(uuid.uuid4())
            path = os.path.join(os.environ.get("TEMP", "."),
                                f"apimode_{ev_id[:8]}.txt")
            # Large enough that the 10 s floor does not mask the difference
            # between the three profiles. At ~0.4 MB all three estimate to
            # "10 seconds" and the comparison proves nothing.
            with open(path, "w", encoding="utf-8") as f:
                f.write("evidence body text for a forensic narrative. " * 400000)
            db.add(models.Evidence(
                id=ev_id, case_id=case_id,
                filename=os.path.basename(path),
                original_filename=os.path.basename(path),
                file_type="text",
                file_size_bytes=os.path.getsize(path),
                file_path=path, sha256_hash="2" * 64,
                ingested_by="verify", status="Uploaded"))
            db.commit()
            _track(ev_id)
        finally:
            db.close()

        secs = {}
        for mode in ("fastest", "normal", "accurate"):
            r = client.post("/api/queue/estimate", headers=H, json={
                "evidence_ids": [ev_id], "ingestion_mode": mode})
            check(f"estimate({mode}) returns 200", r.status_code == 200,
                  r.status_code)
            tot = r.json()["total_seconds"]
            secs[mode] = tot
            f0 = r.json()["files"][0]
            print(f"  {mode:<9} total={tot}s  {r.json()['total_human_readable']}"
                  f"  factor={f0.get('mode_factor')}  chunk={f0.get('chunk_size')}")
        check("estimate honours the profile",
              secs["fastest"] < secs["normal"] < secs["accurate"], secs)

        # Omitted limits must be filled from the device, not defaulted.
        r = client.post("/api/queue/estimate", headers=H,
                        json={"evidence_ids": [ev_id]})
        check("estimate with no overrides uses the device throttle",
              r.status_code == 200 and
              r.json()["files"][0]["throttle_applied"] in (True, False),
              r.json()["files"][0].get("throttle_applied"))

        # ── POST /queue/add ────────────────────────────────────────────────
        print("\n=== POST /api/queue/add ===")
        r = client.post("/api/queue/add", headers=H, json={
            "evidence_id": ev_id, "case_id": case_id,
            "ingestion_mode": "accurate", "priority": 1})
        check("add returns 200", r.status_code == 200, r.text[:300])
        added = r.json()
        print(f"  stored: mode={added.get('ingestion_mode')} "
              f"cpu={added.get('cpu_throttle_percent')}% "
              f"ram_floor={added.get('min_free_ram_mb')} MB")
        print(f"  warnings: {added.get('mode_warnings')}")
        check("mode echoed back", added.get("ingestion_mode") == "accurate",
              added.get("ingestion_mode"))
        check("omitted RAM floor filled from the device",
              added.get("min_free_ram_mb") == b.get("ram_floor_default_mb"),
              f"{added.get('min_free_ram_mb')} vs {b.get('ram_floor_default_mb')}")
        check("omitted CPU filled from the device",
              added.get("cpu_throttle_percent") == b.get("cpu_throttle_percent"),
              f"{added.get('cpu_throttle_percent')} vs "
              f"{b.get('cpu_throttle_percent')}")
        job_id = added.get("job_id") or added.get("id")

        # Bad mode / bad limits must be rejected, not silently coerced.
        r = client.post("/api/queue/add", headers=H, json={
            "evidence_id": ev_id, "case_id": case_id,
            "ingestion_mode": "turbo"})
        check("unknown profile rejected", r.status_code == 400, r.status_code)
        r = client.post("/api/queue/add", headers=H, json={
            "evidence_id": ev_id, "case_id": case_id,
            "cpu_throttle_percent": 400})
        check("out-of-range CPU rejected", r.status_code == 400, r.status_code)
        r = client.post("/api/queue/add", headers=H, json={
            "evidence_id": ev_id, "case_id": case_id,
            "min_free_ram_mb": 999999999})
        check("absurd RAM floor rejected", r.status_code == 400, r.status_code)

        # ── Job listing shape ──────────────────────────────────────────────
        print("\n=== GET /api/queue/list ===")
        r = client.get("/api/queue/list", headers=H)
        check("list returns 200", r.status_code == 200, r.status_code)
        row = next((j for j in r.json() if j.get("id") == job_id), None)
        check("job row present in list", row is not None)
        if row:
            print(f"  row: mode={row.get('ingestion_mode')} "
                  f"status={row.get('status')} "
                  f"governor={row.get('governor')}")
            check("row exposes ingestion_mode", row.get("ingestion_mode")
                  == "accurate", row.get("ingestion_mode"))
            check("row exposes a governor snapshot",
                  isinstance(row.get("governor"), dict), row.get("governor"))

        # ── PATCH settings ─────────────────────────────────────────────────
        print("\n=== PATCH /api/queue/{id}/settings ===")
        r = client.patch(f"/api/queue/{job_id}/settings", headers=H, json={
            "cpu_throttle_percent": 55, "min_free_ram_mb": 3000,
            "ingestion_mode": "fastest"})
        check("patch returns 200", r.status_code == 200, r.text[:300])
        if r.status_code == 200:
            print(f"  applied_live={r.json().get('applied_live')}")
        r = client.patch(f"/api/queue/{job_id}/settings", headers=H,
                         json={"cpu_throttle_percent": 2})
        check("patch validates the CPU range", r.status_code == 400,
              r.status_code)

        # ── PATCH must not lie ──────────────────────────────────────────────
        # Every assertion here is about a response that reports success for
        # something that did not happen. The worker resolves the profile once,
        # at job_worker.py:353, and never re-reads it, so accepting a profile
        # change on a running job would write the column and change nothing.
        print("\n=== PATCH refuses what it cannot do ===")

        # A body with no recognised key used to answer ok:true having done
        # nothing at all.
        r = client.patch(f"/api/queue/{job_id}/settings", headers=H, json={})
        check("empty PATCH is rejected, not reported as applied",
              r.status_code == 400, r.status_code)
        r = client.patch(f"/api/queue/{job_id}/settings", headers=H,
                         json={"nonsense": 1})
        check("unrecognised-only PATCH is rejected",
              r.status_code == 400, r.status_code)

        # Flip the fixture to Running to exercise the profile refusal. Inserted
        # as Running rather than Queued on purpose: the worker only ever selects
        # Queued jobs, so a Queued fixture can be picked up and executed by a
        # second process (see AGENTS.md section 10).
        db = SessionLocal()
        try:
            j = db.query(models.IngestionJob).filter(
                models.IngestionJob.id == job_id).first()
            j.status = "Running"
            db.commit()
        finally:
            db.close()

        r = client.patch(f"/api/queue/{job_id}/settings", headers=H,
                         json={"ingestion_mode": "accurate"})
        check("profile change on a Running job is refused",
              r.status_code == 400, r.status_code)
        check("the refusal explains itself",
              "fixed" in (r.json().get("detail") or "").lower(),
              (r.json().get("detail") or "")[:90])

        # ...and the column must not have moved, which is the whole point.
        db = SessionLocal()
        try:
            j = db.query(models.IngestionJob).filter(
                models.IngestionJob.id == job_id).first()
            check("refused profile left the stored mode untouched",
                  j.ingestion_mode == "fastest", j.ingestion_mode)
            j.status = "Queued"
            db.commit()
        finally:
            db.close()

        # CPU/RAM must still be accepted on a running job — the governor is
        # live for those two, unlike the profile.
        db = SessionLocal()
        try:
            j = db.query(models.IngestionJob).filter(
                models.IngestionJob.id == job_id).first()
            j.status = "Running"
            db.commit()
        finally:
            db.close()
        r = client.patch(f"/api/queue/{job_id}/settings", headers=H,
                         json={"cpu_throttle_percent": 60})
        check("CPU ceiling is still editable while running",
              r.status_code == 200, r.status_code)
        db = SessionLocal()
        try:
            j = db.query(models.IngestionJob).filter(
                models.IngestionJob.id == job_id).first()
            check("live CPU change was stored",
                  j.cpu_throttle_percent == 60, j.cpu_throttle_percent)
            j.status = "Queued"
            db.commit()
        finally:
            db.close()

        # ── A stopped job must remain visible ──────────────────────────────
        # Stop sets status="Stopped" (job_worker.py:459). It is terminal, but
        # it was in neither the active bucket nor the history bucket of any
        # read endpoint, so a stopped job silently disappeared from the queue:
        # the operator stopped it, watched the row leave the screen, and kept
        # no record of how far it had got.
        print("\n=== Stopped jobs stay in the queue ===")
        # Pre-bound so the cleanup below cannot raise NameError and mask the
        # real failure with a traceback from somewhere else entirely.
        ev2 = stopped_job = None
        db = SessionLocal()
        try:
            ev2 = str(uuid.uuid4())
            db.add(models.Evidence(
                id=ev2, case_id=case_id, filename="stopped.bin",
                original_filename="stopped.bin", file_type="binary",
                file_size_bytes=10, file_path=os.path.join(
                    os.environ.get("TEMP", "."), "stopped.bin"),
                sha256_hash="3" * 64, ingested_by="verify", status="Uploaded"))
            stopped_job = str(uuid.uuid4())
            db.add(models.IngestionJob(
                id=stopped_job, evidence_id=ev2, case_id=case_id,
                status="Stopped", progress_percent=42,
                current_step="Stopped by user", created_by="verify",
                ingestion_mode="accurate"))
            db.commit()
            _track(ev2, stopped_job)
        finally:
            db.close()

        r = client.get("/api/queue/list", headers=H)
        row = next((j for j in r.json() if j.get("id") == stopped_job), None)
        check("stopped job appears in /queue/list", row is not None)
        if row:
            check("stopped job keeps the percent it reached",
                  row.get("progress_percent") == 42,
                  row.get("progress_percent"))
        r = client.get("/api/queue/history", headers=H)
        check("stopped job appears in /queue/history",
              any(j.get("id") == stopped_job for j in r.json()),
              [j.get("status") for j in r.json()][:8])

        # And it must be re-queueable, since a stop reverts the evidence to
        # Uploaded. A row the operator cannot act on is half a fix.
        r = client.post("/api/queue/add", headers=H, json={
            "evidence_id": ev2, "case_id": case_id,
            "ingestion_mode": "accurate"})
        check("stopped evidence can be re-queued", r.status_code == 200,
              r.text[:160])
        requeued = (r.json() or {}).get("job_id") or (r.json() or {}).get("id")
        check("re-queue carried the profile forward",
              (r.json() or {}).get("ingestion_mode") == "accurate",
              (r.json() or {}).get("ingestion_mode"))
        if requeued:
            client.delete(f"/api/queue/{requeued}", headers=H)

        # ── POST /system-info/rescan ───────────────────────────────────────
        print("\n=== POST /api/queue/system-info/rescan ===")
        r = client.post("/api/queue/system-info/rescan", headers=H)
        check("rescan returns 200", r.status_code == 200, r.status_code)
        check("rescan reports rescanned=true",
              r.json().get("rescanned") is True, r.json().get("rescanned"))

        # ── Cleanup ────────────────────────────────────────────────────────
        # The atexit hook does the row deletion on every path, including the
        # failing and the interrupted ones. This explicit call keeps the happy
        # path's behaviour visible and lets the temp file go now rather than at
        # interpreter shutdown; it is idempotent.
        client.delete(f"/api/queue/{job_id}", headers=H)
        _track(job_id, ev_id)
        _purge()
        try:
            os.remove(path)
        except OSError:
            pass

    print(f"\n{'=' * 62}")
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f in FAIL:
        print(f"  FAILED: {f}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
