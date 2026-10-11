"""Stage 4.2 (finding C3): an answer must be traceable to the excerpts it used.

`QueryLog.chunks_used` is a JSON array of the excerpt references an answer was
built from. It is written on every ask (`backend/routers/queries.py`, via
`json.dumps(result["chunks_used"])`) but was **never returned by the API**:

* `POST /queries/ask` dropped it from its response body (it has no
  `response_model`, so adding the key is purely additive); and
* `GET /queries/{id}` / `PATCH /queries/{id}/flag` serialise through
  `schemas.QueryResponse`, which had **no `chunks_used` field at all**.

So the stored record carried the claim-to-excerpt link and the API silently
withheld it. This suite pins both halves, and pins the shape rule that matters
most for a forensic record: an absent, empty or malformed `chunks_used` must
come back as `None` ("not returnable"), never as `[]` ("the answer used no
excerpts"), because those are different facts and the second one is false.

Run:  PYTHONPATH=. python tests/verify_query_traceability.py
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fastapi.testclient import TestClient                       # noqa: E402
from sqlalchemy import text                                     # noqa: E402

PASS, FAIL = [], []

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _purge import Purge                                        # noqa: E402

_PURGE = Purge("verify_query_traceability")
_purge, _track, _track_user = _PURGE.run, _PURGE.ids, _PURGE.user


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' — ' + str(detail)) if detail else ''}")


def _base_query_response(**over):
    """The minimum valid QueryResponse payload, with room to override."""
    d = {
        "id": "q1", "case_id": "c1", "evidence_id": None,
        "asked_by": "u", "asked_at": "2026-01-01T00:00:00",
        "question_text": "q", "processed_response": "a",
        "model_used": "m", "cited_sentence_count": 1,
        "uncited_sentence_count": 0, "response_time_ms": 12,
        "is_flagged": False,
    }
    d.update(over)
    return d


# ---------------------------------------------------------------------------
# A. The schema validator, in isolation and without a database.
# ---------------------------------------------------------------------------
def part_a_schema():
    from backend.schemas import QueryResponse

    print("\n=== A. QueryResponse.chunks_used ===")
    fields = set(getattr(QueryResponse, "model_fields", {}))
    check("A1 QueryResponse declares a chunks_used field",
          "chunks_used" in fields, sorted(fields))
    if "chunks_used" not in fields:
        # Every later assertion would be vacuous; record them as failures so
        # the pre-fix run is honest rather than silently short.
        for label in ("A2", "A3", "A4", "A5", "A6", "A7", "A8"):
            check(f"{label} (chunks_used absent - the whole point of C3)",
                  False, "field not declared")
        return

    def parsed(**over):
        return QueryResponse.model_validate(_base_query_response(**over)).chunks_used

    refs = [{"source": "a.txt", "chunk_index": 0, "point_id": "p1"},
            {"source": "b.txt", "chunk_index": 3, "point_id": "p2"}]

    check("A2 a stored JSON string is parsed into the list it encodes",
          parsed(chunks_used=json.dumps(refs)) == refs,
          parsed(chunks_used=json.dumps(refs)))
    check("A3 an already-decoded list round-trips untouched",
          parsed(chunks_used=refs) == refs)
    check("A4 an absent column is None, NOT []",
          parsed() is None, repr(parsed()))
    check("A5 SQL NULL is None, NOT []",
          parsed(chunks_used=None) is None, repr(parsed(chunks_used=None)))
    check("A6 malformed JSON is None, NOT []",
          parsed(chunks_used="{not json") is None)
    check("A7 a JSON non-list is None, NOT []",
          parsed(chunks_used='{"a": 1}') is None)
    check("A8 an empty string is None, NOT []",
          parsed(chunks_used="") is None)
    # An explicit stored "[]" IS a measurement: the answer used no excerpts.
    check("A9 a stored empty array is a real [], not None",
          parsed(chunks_used="[]") == [])


# ---------------------------------------------------------------------------
# B. The API surface, through TestClient against the real app.
# ---------------------------------------------------------------------------
def part_b_api():
    from backend.main import app
    from backend.database import SessionLocal
    from backend import models
    from backend.modules import job_worker as jw
    import backend.routers.queries as qmod

    with TestClient(app) as client:
        # The lifespan starts the ingestion worker; stop it so no fixture is
        # picked up and no query races this run (see verify_queue_api.py).
        jw.stop_worker()
        t = jw._worker_thread
        if t is not None and t.is_alive():
            t.join(timeout=30)

        # ── auth ───────────────────────────────────────────────────────────
        email = f"trace_{uuid.uuid4().hex[:8]}@idfai.test"
        r = client.post("/api/auth/register", json={
            "username": email, "email": email, "password": "Verify@2026",
            "full_name": "Trace Verifier", "role": "Investigator",
        })
        try:
            _track_user((r.json() or {}).get("id"), email)
        except Exception:
            pass
        token = None
        if r.status_code < 400:
            r = client.post("/api/auth/login", data={
                "username": email, "password": "Verify@2026"})
            token = (r.json() or {}).get("access_token")
        if not token:
            r = client.post("/api/auth/login", data={
                "username": "admin", "password": "Admin@IDF2025"})
            token = (r.json() or {}).get("access_token")
        if not token:
            print(f"  SKIP  could not authenticate: {r.status_code} "
                  f"{r.text[:200]}")
            return
        H = {"Authorization": f"Bearer {token}"}

        # ── fixtures: a case and three query rows covering the shapes ──────
        case_id = str(uuid.uuid4())
        q_with = str(uuid.uuid4())
        q_null = str(uuid.uuid4())
        q_bad = str(uuid.uuid4())
        refs = [{"source": "fw.log", "chunk_index": 0, "point_id": "p1"},
                {"source": "mail.txt", "chunk_index": 2, "point_id": "p2"}]
        db = SessionLocal()
        try:
            db.add(models.Case(id=case_id, case_name="traceability",
                               created_by="verify"))
            db.add(models.QueryLog(
                id=q_bad, case_id=case_id, asked_by="verify",
                question_text="bad", processed_response="a",
                chunks_used="{not json"))
            db.add(models.QueryLog(
                id=q_with, case_id=case_id, asked_by="verify",
                question_text="with refs", processed_response="a",
                chunks_used=json.dumps(refs)))
            db.add(models.QueryLog(
                id=q_null, case_id=case_id, asked_by="verify",
                question_text="null", processed_response="a",
                chunks_used=None))
            db.commit()
            # `QueryLog.chunks_used` carries a column-level default of "[]".
            # SQLAlchemy substitutes that default even when None is passed
            # explicitly, so the row above is "[]", not NULL. Force a genuine
            # SQL NULL -- the "not returnable" state B4 is about -- directly.
            db.execute(text("UPDATE query_logs SET chunks_used = NULL "
                            "WHERE id = :i"), {"i": q_null})
            db.commit()
            _track(case_id)
        finally:
            db.close()

        # ── GET /queries/{id} ──────────────────────────────────────────────
        print("\n=== B. GET /api/cases/:id/queries/:query_id ===")
        r = client.get(f"/api/cases/{case_id}/queries/{q_with}", headers=H)
        check("B1 GET returns 200", r.status_code == 200, r.status_code)
        body = r.json() if r.status_code == 200 else {}
        check("B2 GET returns chunks_used at all",
              "chunks_used" in body, sorted(body.keys()))
        check("B3 GET returns the stored excerpt references",
              body.get("chunks_used") == refs, body.get("chunks_used"))

        r = client.get(f"/api/cases/{case_id}/queries/{q_null}", headers=H)
        check("B4 a NULL chunks_used comes back as None, not []",
              r.status_code == 200 and r.json().get("chunks_used") is None,
              r.json().get("chunks_used"))

        r = client.get(f"/api/cases/{case_id}/queries/{q_bad}", headers=H)
        check("B5 malformed chunks_used comes back as None, not []",
              r.status_code == 200 and r.json().get("chunks_used") is None,
              r.json().get("chunks_used"))

        # ── PATCH /queries/{id}/flag uses the same response_model ──────────
        print("\n=== B. PATCH /queries/:id/flag ===")
        r = client.patch(f"/api/cases/{case_id}/queries/{q_with}/flag",
                         headers=H)
        check("B6 PATCH returns 200", r.status_code == 200, r.status_code)
        check("B7 PATCH keeps the excerpt references in its response",
              r.json().get("chunks_used") == refs,
              r.json().get("chunks_used"))

        # ── POST /ask (result dict -> response body, additive) ─────────────
        print("\n=== B. POST /api/cases/:id/queries/ask ===")
        real_rag = qmod.run_rag_query
        ask_refs = [{"source": "asked.txt", "chunk_index": 1, "point_id": "p9"}]

        def _fake_rag(**kw):
            return {
                "answer": "grounded fixture answer",
                "raw_llm_response": "grounded fixture answer",
                "chunks_used": ask_refs,
                "graph_context": "",
                "prompt_stats": {},
                "refused": False,
                "grounding": {"checked": 1, "grounded": 1, "ungrounded": [],
                              "grounded_ratio": 1.0},
                "model_used": "fixture-model",
                "cited_sentence_count": 1,
                "uncited_sentence_count": 0,
                "response_time_ms": 1,
                "ollama_available": True,
            }

        qmod.run_rag_query = _fake_rag
        try:
            r = client.post(f"/api/cases/{case_id}/queries/ask", headers=H,
                            json={"question_text": "trace me",
                                  "conversation_history": []})
        finally:
            qmod.run_rag_query = real_rag

        check("B8 ask returns 201", r.status_code == 201, r.text[:200])
        abody = r.json() if r.status_code == 201 else {}
        check("B9 the ask response now carries chunks_used",
              "chunks_used" in abody, sorted(abody.keys()))
        check("B10 the ask response's chunks_used is the result's list",
              abody.get("chunks_used") == ask_refs, abody.get("chunks_used"))
        check("B11 the ask response carries the grounding verdict",
              "grounding" in abody, sorted(abody.keys()))

        # The stored row must still hold the same JSON (no silent loss).
        qid = abody.get("query_id")
        if qid:
            _track(qid)
            db = SessionLocal()
            try:
                row = db.query(models.QueryLog).filter(
                    models.QueryLog.id == qid).first()
                stored = json.loads(row.chunks_used) if row and row.chunks_used \
                    else None
            finally:
                db.close()
            check("B12 the reference list was persisted, not just echoed",
                  stored == ask_refs, stored)

        _purge()


def main():
    part_a_schema()
    part_b_api()

    print(f"\n{'=' * 62}")
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f in FAIL:
        print(f"  FAIL  {f}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
