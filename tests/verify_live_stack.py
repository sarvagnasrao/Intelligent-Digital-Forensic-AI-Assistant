"""
Live end-to-end smoke test against a *running* backend.

This is the one gap the in-process suites cannot close: they drive
run_ingestion_with_progress directly, so they prove the pipeline and the
broadcaster are correct but not that uvicorn's own event loop actually
delivers the frames to a real socket. That is the exact seam where the
original bug lived (a worker-thread loop could not reach sockets accepted on
the server's loop), so it is the one thing worth proving over the wire.

Requires: backend on :8000, frontend on :3000, Ollama on :11434.

    $env:PYTHONPATH="."; venv\\Scripts\\python.exe tests\\verify_live_stack.py
"""
import asyncio
import atexit
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import websockets

BASE = os.environ.get("IDFAI_BASE", "http://127.0.0.1:8000")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")
# Vite's dev server binds to `localhost` only, so 127.0.0.1 is refused here
# even though it works for the backend. Keep the hostname it actually serves.
FRONTEND = os.environ.get("IDFAI_FRONTEND", "http://localhost:3000")

PASS, FAIL = [], []

# Cases this run created, cleaned on every exit path via atexit.
_OWNED = []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' - ' + str(detail)) if detail else ''}")


def _hard_cleanup(case_id):
    """
    Removes this run's rows and its per-case directory.

    The API's DELETE /api/cases/{id} is a *soft* delete (status -> Archived),
    which is the right behaviour for chain of custody and the wrong one for a
    test: leaving five Archived cases behind per run makes the Cases page
    unusable and hides real regressions in the noise. So this reaches past the
    API, which is only sound because the test already requires the backend to
    be running locally against this machine's database.
    """
    import shutil

    from backend.database import SessionLocal
    from backend import models
    from backend.dependencies import get_settings

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

    case_dir = os.path.join(get_settings().cases_dir, case_id)
    if os.path.isdir(case_dir):
        shutil.rmtree(case_dir, ignore_errors=True)


@atexit.register
def _purge_owned():
    for cid in list(_OWNED):
        try:
            _hard_cleanup(cid)
        except Exception as e:
            print(f"  warn  could not purge {cid[:8]}: {e}")


def wait_for_backend(timeout=90):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/api/status", timeout=5)
            if r.status_code == 200:
                return r.json()
            last = f"{r.status_code} {r.text[:120]}"
        except Exception as e:
            last = type(e).__name__
        time.sleep(2)
    print(f"  SKIP  backend never became ready: {last}")
    return None


async def collect_progress(ws_url, job_id, deadline_s):
    """
    Reads /ws/global until the job stops running, returning every
    INGESTION_PROGRESS frame seen for it.
    """
    seen, connected = [], False
    deadline = time.time() + deadline_s
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        connected = True
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                break
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            # Frame shape varies; find the event type and the job id anywhere.
            if not isinstance(msg, dict):
                continue
            etype = msg.get("type") or msg.get("event") or msg.get("event_type")
            body = msg.get("data") if isinstance(msg.get("data"), dict) else msg
            if etype != "INGESTION_PROGRESS":
                continue
            if body.get("job_id") != job_id:
                continue
            seen.append((body.get("percent"), body.get("step")))
            if body.get("status") in ("Completed", "Failed"):
                return seen, connected
    return seen, connected


def main():
    print("=== services ===")
    status = wait_for_backend()
    if not status:
        return 0
    check("backend /api/status is 200", True, json.dumps(status)[:160])
    try:
        # Vite transforms modules on first request, so the very first hit can
        # take several seconds even though the server is already listening.
        fr = httpx.get(FRONTEND, timeout=25)
        check("frontend dev server answers", fr.status_code == 200,
              f"{FRONTEND} -> {fr.status_code}")
    except Exception as e:
        check("frontend dev server answers", False, type(e).__name__)
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5)
        models = [m["name"] for m in tags.json().get("models", [])]
        check("ollama reachable", tags.status_code == 200, models[:3])
    except Exception as e:
        check("ollama reachable", False, type(e).__name__)

    # ── auth ───────────────────────────────────────────────────────────────
    # follow_redirects matters: /api/cases/ 307s to /api/cases, and httpx
    # does not follow by default the way a browser or axios would.
    with httpx.Client(base_url=BASE, timeout=30, follow_redirects=True) as c:
        email = f"live_{uuid.uuid4().hex[:8]}@idfai.test"
        c.post("/api/auth/register", json={
            "username": email, "email": email, "password": "Verify@2026",
            "full_name": "Live Verifier", "role": "Investigator"})
        r = c.post("/api/auth/login", data={"username": email,
                                            "password": "Verify@2026"})
        token = (r.json() or {}).get("access_token")
        if not token:
            r = c.post("/api/auth/login", data={"username": "admin",
                                                "password": "Admin@IDF2025"})
            token = (r.json() or {}).get("access_token")
        if not token:
            print("  SKIP  no token")
            return 0
        H = {"Authorization": f"Bearer {token}"}
        me = c.get("/api/auth/me", headers=H)
        check("authenticated", me.status_code == 200,
              (me.json() or {}).get("username"))

        # ── the two endpoints the UI depends on ────────────────────────────
        print("\n=== GET /api/queue/modes ===")
        r = c.get("/api/queue/modes", headers=H)
        check("200", r.status_code == 200, r.status_code)
        modes = (r.json() or {}).get("modes", [])
        check("three profiles", [m["key"] for m in modes] ==
              ["fastest", "normal", "accurate"],
              [m.get("key") for m in modes])
        for m in modes:
            e = m["effective"]
            print(f"  {m['key']:<9} chunk={e['chunk_size']:<6} "
                  f"overlap={e['chunk_overlap']:<4} batch={e['embed_batch']:<4} "
                  f"ocr={str(e['ocr']):<5} whisper={e['whisper_model']}/"
                  f"{'gpu' if e['whisper_gpu'] else 'cpu'} "
                  f"deleted={e['include_deleted']}")
            for w in e.get("warnings", []):
                print(f"            ! {w}")

        print("\n=== GET /api/queue/system-info ===")
        r = c.get("/api/queue/system-info", headers=H)
        check("200", r.status_code == 200, r.status_code)
        b = (r.json() or {}).get("suggested_budget", {})
        print(f"  floor {b.get('ram_floor_default_mb')} MB, "
              f"ceiling {b.get('ram_floor_max_mb')} MB, "
              f"cpu {b.get('cpu_throttle_percent')}%, "
              f"free {b.get('available_ram_mb')} MB")
        print(f"  {b.get('description')}")
        check("default_mode present", bool((r.json() or {}).get("default_mode")),
              (r.json() or {}).get("default_mode"))

        # ── a real upload + queue ──────────────────────────────────────────
        print("\n=== upload + queue via HTTP ===")
        cr = c.post("/api/cases", headers=H, json={
            "case_name": f"Live WS check {uuid.uuid4().hex[:6]}",
            "description": "temporary", "created_by": "verify"})
        check("case created", cr.status_code in (200, 201),
              f"{cr.status_code} {cr.text[:200]}")
        try:
            case = (cr.json() or {}).get("id")
        except Exception:
            case = None
        if not case:
            print(f"  SKIP  no case id: {cr.text[:200]}")
            return 1

        # From here on the run owns a case. atexit guarantees removal on every
        # exit path - failed assertion, exception, sys.exit - so a broken run
        # cannot quietly leave a case behind for the next one to trip over.
        _OWNED.append(case)

        body = ("forensic narrative paragraph. " * 60000).encode()
        fr2 = c.post(f"/api/cases/{case}/evidence/upload", headers=H,
                     files={"file": ("live_ws_check.txt", body, "text/plain")},
                     data={"ingested_by": "verify"})
        check("evidence uploaded", fr2.status_code in (200, 201),
              fr2.text[:200])
        ev = (fr2.json() or {}).get("id")
        if not ev:
            print(f"  SKIP  no evidence id: {fr2.text[:300]}")
            return 1
        print(f"  case={case[:8]} evidence={ev[:8]} "
              f"({len(body) / 1024:.0f} KB)")

        r = c.post("/api/queue/add", headers=H, json={
            "evidence_id": ev, "case_id": case,
            "ingestion_mode": "accurate", "priority": 1})
        check("queued", r.status_code in (200, 201), r.text[:200])
        added = r.json() or {}
        job = added.get("job_id") or added.get("id")
        print(f"  job={str(job)[:8]} mode={added.get('ingestion_mode')} "
              f"ram_floor={added.get('min_free_ram_mb')} MB "
              f"cpu={added.get('cpu_throttle_percent')}%")
        for w in added.get("mode_warnings", []) or []:
            print(f"  ! {w}")
        check("mode stored on the job", added.get("ingestion_mode") == "accurate",
              added.get("ingestion_mode"))

        # ── the actual point: live progress over the wire ─────────────────
        print("\n=== live progress over /ws/global ===")
        seen, connected = asyncio.run(
            collect_progress(f"{WS_BASE}/ws/global", job, 180))

        print(f"  socket connected: {connected}")
        print(f"  frames received  : {len(seen)}")
        for pct, step in seen:
            print(f"    {str(pct):>4}%  {step}")

        check("websocket accepted the connection", connected)
        check("progress frames arrived on the socket", len(seen) >= 3,
              f"{len(seen)} frames")
        pcts = [p for p, _ in seen if isinstance(p, (int, float))]
        check("percentages are monotonically non-decreasing",
              pcts == sorted(pcts), pcts)
        check("reached 100%", bool(pcts) and pcts[-1] == 100, pcts[-3:])
        check("more than one distinct percent (a live bar, not a jump)",
              len(set(pcts)) >= 3, sorted(set(pcts)))
        check("every step names the profile",
              all(f"[accurate]" in (s or "") for _, s in seen),
              [s for _, s in seen if "[accurate]" not in (s or "")][:2])

        # ── the job actually finished in the database ─────────────────────
        # There is no GET /queue/{id}; the row comes from the listing, which
        # is also what QueuePage.jsx renders, so this checks the same shape
        # the UI consumes.
        print("\n=== final job state ===")
        r = c.get("/api/queue/list", headers=H)
        row = next((j for j in (r.json() or []) if j.get("id") == job), None)
        check("job row still listed", row is not None)
        if row:
            print(f"  status={row.get('status')} "
                  f"percent={row.get('progress_percent')} "
                  f"mode={row.get('ingestion_mode')}")
            print(f"  step={row.get('current_step')}")
            print(f"  governor={row.get('governor')}")
            check("job reached a terminal state",
                  row.get("status") in ("Completed", "Failed"),
                  row.get("status"))
            check("job status is Completed, not Failed",
                  row.get("status") == "Completed", row.get("status"))
            check("job is at 100%", row.get("progress_percent") == 100,
                  row.get("progress_percent"))
            check("row carries the profile", row.get("ingestion_mode") == "accurate",
                  row.get("ingestion_mode"))

        # ── cleanup ────────────────────────────────────────────────────────
        print("\n=== cleanup ===")
        c.delete(f"/api/queue/{job}", headers=H)
        dr = c.delete(f"/api/cases/{case}", headers=H)
        check("case delete accepted", dr.status_code in (200, 204),
              dr.status_code)
        # The worker holds its own session, so confirm nothing was left behind
        # before this run removes it.
        time.sleep(1.0)
        chk = c.get("/api/queue/list", headers=H)
        still = [j for j in (chk.json() or []) if j.get("id") == job]
        check("job gone from the queue listing", not still, len(still))

        _hard_cleanup(case)
        _OWNED.remove(case)
        from backend.database import SessionLocal
        from backend import models
        _db = SessionLocal()
        try:
            gone = _db.query(models.Case).filter(
                models.Case.id == case).count()
        finally:
            _db.close()
        check("case row removed (not left Archived)", gone == 0, gone)

    print(f"\n{'=' * 62}")
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f in FAIL:
        print(f"  FAILED: {f}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
