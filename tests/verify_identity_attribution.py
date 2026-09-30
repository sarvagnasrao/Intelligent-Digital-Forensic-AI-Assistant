"""A record's author must be the server's answer, not the caller's. (B31)

Three routers took the name of the person responsible for an action out of the
**request body** and wrote it into a record:

    POST /api/cases              -> Case.created_by      + AuditLog.performed_by
    POST /api/cases/:id/notes    -> Note.author          + AuditLog.performed_by
    POST /api/cases/:id/queries/ask
                                 -> QueryLog.asked_by    + AuditLog.performed_by
                                 -> and the `asked_by` argument to the RAG prompt

Every one of those routes already resolved the authenticated identity through a
dependency (`current_user: models.User = Depends(require_...)`) and simply did
not consult it for the attribution. So any authenticated user could put any
other user's name — including the Admin's — on a query, a note, a case, and the
matching `CASE_CREATED` / `NOTE_ADDED` / `QUERY_MADE` audit entry.

The two rows agree with each other and disagree with the access log, which is
what makes it durable: this product's entire value proposition is an audit log
that can be trusted, and the cheapest way to make it worthless is to let the
actor name themselves. It is also §18's defect class (a confident,
true-shaped message that is not what happened) applied to authorship rather than
to status, and the same trust mistake already fixed once in `auth_router.py`
(a client-supplied `role`), one layer along.

This suite drives the real endpoints over TestClient and asserts on what landed
in the database. `run_rag_query` is stubbed: the real one needs Ollama and an
open per-case Qdrant lock (§15), takes ~165 s, and is not what is under test —
the claim here is about which name the *router* records.

The forged value is always a real, different account ("admin"), so a guard
cannot pass by comparing a field against itself — the failure mode that let three
of this repo's own tests pass for the wrong reason (§21, §23).
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fastapi.testclient import TestClient

PASS, FAIL = [], []

from _purge import Purge                                     # noqa: E402
_PURGE = Purge("verify_identity_attribution")


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' — ' + str(detail)) if detail else ''}")


# The account the authenticated user will try to impersonate. It exists (the
# seeder makes it) and it is emphatically not the account making the request.
IMPOSTOR = "admin"


def _stub_result(**over):
    """The minimum shape `ask_question` unpacks out of `run_rag_query`."""
    base = {
        "answer": "fixture answer",
        "raw_llm_response": "fixture answer",
        "chunks_used": [],
        "graph_context": "",
        "model_used": "fixture-model",
        "cited_sentence_count": 0,
        "uncited_sentence_count": 0,
        "response_time_ms": 1,
        "ollama_available": True,
    }
    base.update(over)
    return base


def _case_field(SessionLocal, models, case_id, field):
    db = SessionLocal()
    try:
        row = db.query(models.Case).filter(
            models.Case.id == case_id).first()
        return None if row is None else getattr(row, field)
    finally:
        db.close()


def _note_author(SessionLocal, models, note_id):
    db = SessionLocal()
    try:
        row = db.query(models.Note).filter(
            models.Note.id == note_id).first()
        return None if row is None else row.author
    finally:
        db.close()


def _query_asker(SessionLocal, models, query_id):
    db = SessionLocal()
    try:
        row = db.query(models.QueryLog).filter(
            models.QueryLog.id == query_id).first()
        return None if row is None else row.asked_by
    finally:
        db.close()


def _audit_actors(SessionLocal, models, case_id, action_type):
    """performed_by for every audit row of one action type, most recent first.

    A list rather than a single value: the point is that NO row of this action
    carries the forged name, and an assertion on only the newest row would pass
    even if a second, older row disagreed.
    """
    db = SessionLocal()
    try:
        rows = db.query(models.AuditLog).filter(
            models.AuditLog.case_id == case_id,
            models.AuditLog.action_type == action_type).all()
        return [r.performed_by for r in rows]
    finally:
        db.close()


def _cleanup(SessionLocal, models, case_id, note_ids, query_ids):
    db = SessionLocal()
    try:
        for mid in query_ids:
            db.query(models.QueryLog).filter(
                models.QueryLog.id == mid).delete(synchronize_session=False)
        for nid in note_ids:
            db.query(models.Note).filter(
                models.Note.id == nid).delete(synchronize_session=False)
        db.query(models.AuditLog).filter(
            models.AuditLog.case_id == case_id).delete(
                synchronize_session=False)
        db.query(models.CaseAccess).filter(
            models.CaseAccess.case_id == case_id).delete(
                synchronize_session=False)
        db.query(models.Case).filter(
            models.Case.id == case_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def main():
    from backend.main import app
    from backend.database import SessionLocal
    from backend import models
    import backend.routers.queries as qmod

    with TestClient(app) as client:
        # ── Auth ───────────────────────────────────────────────────────────
        print("\n=== 0. the two identities must actually differ ===")
        handle = f"b31_{uuid.uuid4().hex[:8]}"
        email = f"{handle}@idfai.test"
        _reg = client.post("/api/auth/register", json={
            "username": email, "email": email, "password": "Verify@2026",
            "full_name": "Identity Guard", "role": "Investigator",
        })
        # The account was never deleted, so data/forensic.db grew by one
        # `b31_*` user per run -- see tests/_purge.py. Both the id and the
        # username are needed: the audit row registration writes carries the
        # username in `performed_by`, so deleting by id alone orphans it.
        try:
            _PURGE.user((_reg.json() or {}).get("id"), email)
        except Exception:
            _PURGE.user(None, email)
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
            return 0
        H = {"Authorization": f"Bearer {token}"}

        # require_investigator for the case, require_analyst for note/query;
        # Investigator satisfies both.
        db = SessionLocal()
        try:
            me = db.query(models.User).filter(
                models.User.username == email).first()
            if me:
                me.role = "Investigator"
                db.commit()
        finally:
            db.close()

        r = client.get("/api/auth/me", headers=H)
        whoami = (r.json() or {}).get("username")
        check("the caller is authenticated", bool(whoami),
              (r.status_code, whoami))
        check("and the account being impersonated is a DIFFERENT one "
              "(otherwise every assertion below is vacuous)",
              bool(whoami) and whoami != IMPOSTOR,
              f"caller={whoami} forged={IMPOSTOR}")

        # ── A. case creation ───────────────────────────────────────────────
        print("\n=== A. POST /api/cases — Case.created_by ===")
        r = client.post("/api/cases", headers=H, json={
            "case_name": f"b31-guard-{uuid.uuid4().hex[:8]}",
            "case_number": "B31",
            "priority": "Medium",
            "description": "identity attribution guard",
            "created_by": IMPOSTOR,      # the forgery attempt
            "tags": [],
        })
        check("case creation succeeds (the client field is still accepted)",
              r.status_code == 201, (r.status_code, r.text[:200]))
        case_id = (r.json() or {}).get("id")
        # Tracked as soon as it exists, so the atexit hook is a real safety net
        # for a run that dies before `_cleanup` at the end of main().
        _PURGE.ids(case_id)
        if not case_id:
            print("  FAIL  no case id returned; cannot continue")
            FAIL.append("case id")
            print(f"\nPASSED: {len(PASS)}    FAILED: {len(FAIL)}")
            for f in FAIL:
                print(f"  FAIL  {f}")
            return 1

        note_ids, query_ids = [], []
        try:
            stored = _case_field(SessionLocal, models, case_id, "created_by")
            # THE assertion. Pre-fix this is "admin".
            check("Case.created_by is the AUTHENTICATED user, not the "
                  "requested one (pre-fix: 'admin')",
                  stored == whoami, f"stored={stored!r} expected={whoami!r}")

            echoed = (r.json() or {}).get("created_by")
            check("and the API echoes the same value it actually stored",
                  echoed == stored, f"response={echoed!r} db={stored!r}")

            actors = _audit_actors(SessionLocal, models, case_id,
                                   "CASE_CREATED")
            check("the CASE_CREATED audit entry names the authenticated user",
                  bool(actors) and all(a == whoami for a in actors),
                  actors)
            check("no audit entry for this case carries the forged name",
                  IMPOSTOR not in actors, actors)

            # ── B. notes ───────────────────────────────────────────────────
            print("\n=== B. POST /api/cases/:id/notes — Note.author ===")
            r = client.post(f"/api/cases/{case_id}/notes", headers=H, json={
                "content": "b31 guard note",
                "author": IMPOSTOR,       # the forgery attempt
                "linked_to_type": None,
                "linked_to_id": None,
            })
            check("note creation succeeds", r.status_code == 201,
                  (r.status_code, r.text[:200]))
            note_id = (r.json() or {}).get("id")
            if note_id:
                note_ids.append(note_id)
                stored = _note_author(SessionLocal, models, note_id)
                check("Note.author is the AUTHENTICATED user, not the "
                      "requested one (pre-fix: 'admin')",
                      stored == whoami, f"stored={stored!r}")
                actors = _audit_actors(SessionLocal, models, case_id,
                                       "NOTE_ADDED")
                check("the NOTE_ADDED audit entry names the authenticated user",
                      bool(actors) and all(a == whoami for a in actors),
                      actors)

            # ── C. queries ─────────────────────────────────────────────────
            print("\n=== C. POST /queries/ask — QueryLog.asked_by ===")
            real_rag = qmod.run_rag_query
            seen = {}

            def _fake_rag(**kw):
                seen.update(kw)
                return _stub_result()

            qmod.run_rag_query = _fake_rag
            try:
                r = client.post(f"/api/cases/{case_id}/queries/ask",
                                headers=H, json={
                                    "question_text": "b31 guard question",
                                    "asked_by": IMPOSTOR,   # forgery attempt
                                    "evidence_id": None,
                                    "conversation_history": [],
                                })
            finally:
                qmod.run_rag_query = real_rag

            check("the ask endpoint succeeds", r.status_code == 201,
                  (r.status_code, r.text[:200]))
            query_id = (r.json() or {}).get("query_id")
            if query_id:
                query_ids.append(query_id)
                stored = _query_asker(SessionLocal, models, query_id)
                check("QueryLog.asked_by is the AUTHENTICATED user, not the "
                      "requested one (pre-fix: 'admin')",
                      stored == whoami, f"stored={stored!r}")
                actors = _audit_actors(SessionLocal, models, case_id,
                                       "QUERY_MADE")
                check("the QUERY_MADE audit entry names the authenticated user",
                      bool(actors) and all(a == whoami for a in actors),
                      actors)
                check("and no QUERY_MADE entry carries the forged name",
                      IMPOSTOR not in actors, actors)
                # The 4th site: the forged name also reached the prompt.
                check("the name handed to the RAG engine is the authenticated "
                      "user too, so the model was not told a false asker",
                      seen.get("asked_by") == whoami,
                      f"rag asked_by={seen.get('asked_by')!r}")

            # ── D. the fields are optional, so a caller is never FORCED to
            #       assert an identity the server will ignore ───────────────
            print("\n=== D. the identity fields are no longer required ===")
            r = client.post(f"/api/cases/{case_id}/notes", headers=H, json={
                "content": "b31 note with no author field at all",
            })
            check("a note can be created WITHOUT sending an author",
                  r.status_code == 201, (r.status_code, r.text[:200]))
            if (r.json() or {}).get("id"):
                note_ids.append((r.json() or {})["id"])
                stored = _note_author(SessionLocal, models, note_ids[-1])
                check("...and it is still attributed to the authenticated user",
                      stored == whoami, f"stored={stored!r}")

            # ── E. source-level sweep: no router may attribute from the body
            print("\n=== E. no router anywhere attributes an action from the "
                  "request body ===")
            offenders = []
            import glob
            for path in glob.glob(os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "backend", "routers", "*.py")):
                with open(path, encoding="utf-8") as fh:
                    for n, line in enumerate(fh, 1):
                        code = line.split("#", 1)[0]
                        for ident in ("asked_by", "created_by", "author"):
                            if (f"body.{ident}" in code
                                    or f"payload.{ident}" in code):
                                offenders.append(
                                    f"{os.path.basename(path)}:{n} {code.strip()}")
            check("no router reads an identity out of a request body",
                  not offenders, offenders)

        finally:
            _cleanup(SessionLocal, models, case_id, note_ids, query_ids)

        # ── F. residue ─────────────────────────────────────────────────────
        print("\n=== F. the guard left nothing behind ===")
        check("the throwaway case is gone from the database",
              _case_field(SessionLocal, models, case_id, "created_by") is None)

    print(f"\nPASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f in FAIL:
        print(f"  FAIL  {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
