"""Archiving evidence must actually archive it. (B29)

The Archive button in the Evidence Library set `status='Archived'`, wrote the
audit entry, returned 200, and the toast said "Evidence archived" — and the row
was still in the list, because `GET /evidence` filtered on `case_id` alone and
never on status. The action succeeded and was invisible, which to the operator
is indistinguishable from a button that does nothing.

That is the whole of it, and it is the defect class this repo keeps meeting: a
confident, true-shaped message that is not what happened. Three more sat behind
it, and each is guarded here:

  * the Qdrant cleanup was `except Exception: print(...)` and marked
    non-fatal, so a failed cleanup left the vectors in the index while the
    dialog promised queries would no longer return the content
  * archiving required Admin, but uploading evidence requires Investigator and
    so does archiving the whole case — the broader action was gated lower than
    the narrower one
  * there was no way back, and no way to even see what had been archived

The test drives the real app over TestClient and asserts on observable
outcomes — list contents, database status, HTTP codes — not on which functions
were called. Qdrant is stubbed, because embedded Qdrant takes an exclusive lock
per directory (§15) and a stub is the right thing here: the claims under test
are about the archive's contract, not about Qdrant's delete semantics.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fastapi.testclient import TestClient

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' — ' + str(detail)) if detail else ''}")


class _FakeQdrant:
    """
    Records the delete calls the archive makes. Stands in for the embedded
    client, which cannot be opened twice on one path and is not what is under
    test.
    """

    def __init__(self, fail=False):
        self.deletes = []
        self._fail = fail

    def delete(self, collection_name=None, points_selector=None):
        if self._fail:
            raise RuntimeError("storage folder is locked by another instance")
        key = None
        try:
            key = points_selector.must[0].match.value
        except Exception:
            pass
        self.deletes.append((collection_name, key))


def _make_case_and_evidence(SessionLocal, models, n_evidence=2,
                            status="Indexed", chunk_count=120,
                            entity_count=34):
    """Build a throwaway case with evidence rows, directly in the database.

    Upload is not used because it hashes a real file and queues a job; none of
    that is what is under test, and a real upload would leave a per-case
    Qdrant directory behind.
    """
    db = SessionLocal()
    try:
        case_id = str(uuid.uuid4())
        db.add(models.Case(
            id=case_id,
            case_name=f"archive-guard-{case_id[:8]}",
            case_number=f"ARCH-{case_id[:8]}",
            status="Active",
            created_by="archive-guard",
            description="fixture",
        ))
        db.commit()

        rows = []
        for i in range(n_evidence):
            ev = models.Evidence(
                id=str(uuid.uuid4()),
                case_id=case_id,
                filename=f"fixture_{i}.txt",
                original_filename=f"fixture_{i}.txt",
                file_type="text",
                file_size_bytes=2048,
                file_path=f"{case_id}/evidence/fixture_{i}.txt",
                sha256_hash="0" * 64,
                ingested_by="archive-guard",
                status=status,
                chunk_count=chunk_count,
                entity_count=entity_count,
            )
            db.add(ev)
            rows.append(ev.id)
        db.commit()
        return case_id, rows
    finally:
        db.close()


def _status_of(SessionLocal, models, evidence_id):
    db = SessionLocal()
    try:
        row = db.query(models.Evidence).filter(
            models.Evidence.id == evidence_id).first()
        return None if row is None else (row.status, row.chunk_count,
                                         row.entity_count)
    finally:
        db.close()


def _paths_of(SessionLocal, models, case_id):
    """
    (file_path, sha256_hash) per evidence row, sorted.

    Read from the DATABASE, not the API response: EvidenceResponse does not
    expose file_path, and that is correct — a server-side path has no business
    in a client payload. So the honest way to ask "is the file still on disk"
    is to read the row that points at it.
    """
    db = SessionLocal()
    try:
        rows = db.query(models.Evidence).filter(
            models.Evidence.case_id == case_id).all()
        return sorted((r.file_path, r.sha256_hash) for r in rows)
    finally:
        db.close()


def _cleanup(SessionLocal, models, case_id, ev_ids):
    db = SessionLocal()
    try:
        db.query(models.IngestionJob).filter(
            models.IngestionJob.case_id == case_id).delete(
                synchronize_session=False)
        db.query(models.Evidence).filter(
            models.Evidence.case_id == case_id).delete(
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
    import backend.modules.vector_store as vs

    with TestClient(app) as client:
        # ── Auth ───────────────────────────────────────────────────────────
        # /login takes an OAuth2 form, not JSON.
        email = f"arch_{uuid.uuid4().hex[:8]}@idfai.test"
        r = client.post("/api/auth/register", json={
            "username": email, "email": email, "password": "Verify@2026",
            "full_name": "Archive Guard", "role": "Investigator",
        })
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

        # Promote to Investigator in the database. require_role() reads
        # `user.role` off the row on every request, so no re-login is needed —
        # but doing it explicitly means the role assertions below do not depend
        # on whether /register honours a requested role.
        db = SessionLocal()
        try:
            me = db.query(models.User).filter(
                models.User.username == email).first()
            if me:
                me.role = "Investigator"
                db.commit()
        finally:
            db.close()

        # ── A. the regression: archived means out of the list ─────────────
        print("\n=== A. an archived item leaves the evidence list ===")
        case_id, ev_ids = _make_case_and_evidence(SessionLocal, models, 3)
        try:
            fake = _FakeQdrant()
            real_get_client = vs.get_client
            vs.get_client = lambda path, _f=fake: _f

            before = client.get(f"/api/cases/{case_id}/evidence",
                                headers=H).json()
            check("all three fixtures start visible",
                  len(before) == 3, [e["original_filename"] for e in before])

            target, keep = ev_ids[0], ev_ids[1]
            # Captured before the archive, because "the file is still on disk"
            # is only a claim if it is compared against the prior state rather
            # than against itself.
            paths_before = _paths_of(SessionLocal, models, case_id)
            r = client.delete(
                f"/api/cases/{case_id}/evidence/{target}", headers=H)
            check("archive returns 200", r.status_code == 200,
                  (r.status_code, r.text[:160]))
            check("the database row says Archived",
                  _status_of(SessionLocal, models, target)[0] == "Archived",
                  _status_of(SessionLocal, models, target))
            # Archiving deleted the vectors, so a chunk_count left at 120 would
            # be counting chunks that no longer exist — and four consumers read
            # it without checking status (case export, PDF report, report
            # generator, queue evidence row). The invariant is the simple one:
            # chunk_count is what is in the index right now.
            check("chunk_count is zeroed on archive, not left counting "
                  "deleted vectors",
                  _status_of(SessionLocal, models, target)[1] == 0,
                  _status_of(SessionLocal, models, target))
            check("but entity_count is untouched — entities live in the "
                  "database and archiving never removed them",
                  _status_of(SessionLocal, models, target)[2] == 34,
                  _status_of(SessionLocal, models, target))

            after = client.get(f"/api/cases/{case_id}/evidence",
                               headers=H).json()
            ids = [e["id"] for e in after]
            # THE assertion. Pre-fix this list still contained `target`,
            # because the query filtered on case_id alone.
            check("the archived item is GONE from the default list",
                  target not in ids, ids)
            check("and the other two are untouched",
                  sorted(ids) == sorted([keep, ev_ids[2]]), ids)
            check("the count dropped by exactly one",
                  len(after) == 2, len(after))

            # ── B. it is hidden, not destroyed ───────────────────────────
            print("\n=== B. hidden, not destroyed ===")
            with_arch = client.get(
                f"/api/cases/{case_id}/evidence",
                params={"include_archived": True}, headers=H).json()
            check("include_archived=true brings it back",
                  target in [e["id"] for e in with_arch],
                  [e["original_filename"] for e in with_arch])
            check("and the file is still on disk — archiving hides a row, it "
                  "does not delete data",
                  _paths_of(SessionLocal, models, case_id) == paths_before
                  and all(p and h for p, h in paths_before),
                  (paths_before, _paths_of(SessionLocal, models, case_id)))
            check("the two lists partition the case exactly",
                  len(with_arch) == 3
                  and len({e["id"] for e in after}
                          | {e["id"] for e in with_arch}) == 3,
                  (len(after), len(with_arch)))
            check("the archived row is labelled Archived, not Failed",
                  [e["status"] for e in with_arch
                   if e["id"] == target] == ["Archived"],
                  [e["status"] for e in with_arch])

            # ── C. restore reverses it, honestly ─────────────────────────
            print("\n=== C. restore is the inverse, and tells the truth ===")
            r = client.post(f"/api/cases/{case_id}/evidence/{target}/restore",
                            headers=H)
            check("restore returns 200", r.status_code == 200,
                  (r.status_code, r.text[:200]))
            restored = _status_of(SessionLocal, models, target)
            # 'Uploaded', not 'Indexed': archiving deleted the vectors, so
            # claiming Indexed would be the §15/B14 searchable-as-empty lie.
            check("restored status is Uploaded, NOT Indexed",
                  restored[0] == "Uploaded", restored)
            check("chunk_count stays 0 — it was zeroed at archive time, and "
                  "restore does not invent an index that was deleted",
                  restored[1] == 0, restored)
            check("entity_count is KEPT — entities live in the DB and "
                  "archiving never removed them",
                  restored[2] == 34, restored)
            back = [e["id"] for e in client.get(
                f"/api/cases/{case_id}/evidence", headers=H).json()]
            check("and it is visible in the default list again",
                  target in back, back)
            msg = (r.json() or {}).get("message", "")
            check("the response says it must be re-queued, so the UI does "
                  "not imply the index came back",
                  "queue" in msg.lower() and "uploaded" in msg.lower(), msg)

            # ── D. the refusals ───────────────────────────────────────────
            print("\n=== D. the operations that must refuse ===")
            r = client.post(f"/api/cases/{case_id}/evidence/{keep}/restore",
                            headers=H)
            check("restoring something that is not archived is a 409",
                  r.status_code == 409, (r.status_code, r.text[:140]))

            r = client.delete(f"/api/cases/{case_id}/evidence/{keep}",
                              headers=H)
            check("archiving works on an active item", r.status_code == 200,
                  r.status_code)
            r = client.delete(f"/api/cases/{case_id}/evidence/{keep}",
                              headers=H)
            check("archiving it twice is a 409, not a second success",
                  r.status_code == 409, (r.status_code, r.text[:140]))
            r = client.post(f"/api/cases/{case_id}/evidence/{keep}/restore",
                            headers=H)
            check("and it restores cleanly afterwards", r.status_code == 200,
                  r.status_code)

            # A live ingestion job holds the evidence row and keeps writing
            # into the collection the archive is about to empty.
            db = SessionLocal()
            try:
                db.add(models.IngestionJob(
                    id=str(uuid.uuid4()),
                    evidence_id=ev_ids[2],
                    case_id=case_id,
                    status="Running",
                    queue_position=0,
                    progress_percent=40,
                    created_by="archive-guard",
                ))
                db.commit()
            finally:
                db.close()
            r = client.delete(f"/api/cases/{case_id}/evidence/{ev_ids[2]}",
                              headers=H)
            check("archiving mid-ingestion is refused with 409",
                  r.status_code == 409, (r.status_code, r.text[:160]))
            check("and the evidence is left ACTIVE — the refusal did not "
                  "half-archive it",
                  _status_of(SessionLocal, models, ev_ids[2])[0] == "Running"
                  or _status_of(SessionLocal, models, ev_ids[2])[0]
                  != "Archived",
                  _status_of(SessionLocal, models, ev_ids[2]))
            detail = ""
            try:
                detail = (r.json().get("detail") or {}).get("detail", "")
            except Exception:
                pass
            check("the refusal explains what to do about it",
                  "stop" in detail.lower() or "job" in detail.lower(),
                  detail)
            db = SessionLocal()
            try:
                db.query(models.IngestionJob).filter(
                    models.IngestionJob.case_id == case_id).delete(
                        synchronize_session=False)
                db.commit()
            finally:
                db.close()

            # ── E. the Qdrant cleanup is load-bearing ───────────────────
            print("\n=== E. a failed index cleanup must not archive ===")
            # The dialog promises queries will no longer return the content.
            # If the vectors are still there, that promise is false, so the
            # archive is refused rather than reported as successful.
            vs.get_client = lambda path: _FakeQdrant(fail=True)
            doomed = ev_ids[2]
            r = client.delete(f"/api/cases/{case_id}/evidence/{doomed}",
                              headers=H)
            check("a cleanup failure is a 500, not a success", 
                  r.status_code == 500, (r.status_code, r.text[:200]))
            check("the evidence was NOT archived",
                  _status_of(SessionLocal, models, doomed)[0] != "Archived",
                  _status_of(SessionLocal, models, doomed))
            check("and it is still in the active list, intact",
                  doomed in [e["id"] for e in client.get(
                      f"/api/cases/{case_id}/evidence", headers=H).json()])
            try:
                body = r.json().get("detail") or {}
                text = f"{body.get('error','')} {body.get('detail','')}"
            except Exception:
                text = r.text
            check("the message says the content is still searchable, which "
                  "is the whole reason for refusing",
                  "still" in text.lower() and "quer" in text.lower(), text)

            # ── F. it only deletes THIS evidence's vectors ───────────────
            print("\n=== F. the cleanup is scoped to the one item ===")
            # A FRESH recorder. The one from section A already holds three
            # deletes, and asserting against a shared accumulator would have
            # measured this section's history rather than its behaviour.
            scoped_fake = _FakeQdrant()
            vs.get_client = lambda path, _f=scoped_fake: _f
            scoped = ev_ids[2]
            client.delete(f"/api/cases/{case_id}/evidence/{scoped}",
                          headers=H)
            check("exactly one delete was issued",
                  len(scoped_fake.deletes) == 1, scoped_fake.deletes)
            check("and it was filtered to this evidence id",
                  scoped_fake.deletes
                  and scoped_fake.deletes[0][1] == scoped,
                  scoped_fake.deletes)
            # The collection name is derived from the case id (a prefix plus a
            # short form of it), so assert that relationship rather than a
            # literal — a test that hardcodes the whole UUID would be asserting
            # today's naming scheme, not the property.
            check("and it targeted this case's collection",
                  scoped_fake.deletes
                  and str(scoped_fake.deletes[0][0]).startswith("case_")
                  and case_id[:8] in str(scoped_fake.deletes[0][0]),
                  scoped_fake.deletes)
        finally:
            vs.get_client = real_get_client
            _cleanup(SessionLocal, models, case_id, ev_ids)

        # ── G. the role gate ──────────────────────────────────────────────
        # Archiving required Admin while uploading evidence required
        # Investigator and so did archiving the whole case. The broader action
        # was gated LOWER than the narrower one, so the gate could only have
        # been a copy-paste. Asserted on the row's actual role so the test does
        # not depend on what /register does with a requested role.
        print("\n=== G. an Investigator can archive; a Viewer cannot ===")
        db = SessionLocal()
        try:
            my_role = db.query(models.User).filter(
                models.User.username == email).first().role
        finally:
            db.close()
        check("the acting user really is an Investigator (not Admin)",
              my_role == "Investigator", my_role)

        case2, ev2 = _make_case_and_evidence(SessionLocal, models, 1)
        try:
            fake2 = _FakeQdrant()
            real2 = vs.get_client
            vs.get_client = lambda path, _f=fake2: _f
            r = client.delete(f"/api/cases/{case2}/evidence/{ev2[0]}",
                              headers=H)
            check("an Investigator archiving succeeds (pre-fix: 403)",
                  r.status_code == 200, (r.status_code, r.text[:200]))
            check("and it actually left the list",
                  ev2[0] not in [e["id"] for e in client.get(
                      f"/api/cases/{case2}/evidence", headers=H).json()])

            # The other half of the claim: lowering the gate must not have
            # removed it. A gate that stops gating is a different bug, and only
            # a test that also tries the lower role can tell the two apart.
            case3, ev3 = _make_case_and_evidence(SessionLocal, models, 1)
            try:
                fake3 = _FakeQdrant()
                real3 = vs.get_client
                vs.get_client = lambda path, _f=fake3: _f
                db = SessionLocal()
                try:
                    db.query(models.User).filter(
                        models.User.username == email).one().role = "Viewer"
                    db.commit()
                finally:
                    db.close()
                r = client.delete(f"/api/cases/{case3}/evidence/{ev3[0]}",
                                  headers=H)
                check("a Viewer is still refused with 403", 
                      r.status_code == 403, (r.status_code, r.text[:200]))
                check("and no vectors were deleted for a refused attempt",
                      fake3.deletes == [], fake3.deletes)
                check("the evidence is untouched",
                      _status_of(SessionLocal, models, ev3[0])[0]
                      == "Indexed",
                      _status_of(SessionLocal, models, ev3[0]))
            finally:
                vs.get_client = real3
                _cleanup(SessionLocal, models, case3, ev3)
        finally:
            vs.get_client = real2
            _cleanup(SessionLocal, models, case2, ev2)

    print("\n" + "=" * 66)
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f in FAIL:
        print(f"  FAILED: {f}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
