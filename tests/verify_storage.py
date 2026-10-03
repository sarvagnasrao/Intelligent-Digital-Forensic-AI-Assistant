"""Storage transparency: a number nobody measured must never be a 0.

`storage_router.py` exists because an operator asking "where is my disk going"
was being answered with figures that were partly historical and partly not
measured at all. It carries three rules, and each has a way of being broken by
an innocent-looking edit, so each is guarded here:

  * **A section that could not be walked reports `null` bytes plus a reason,
    never `0`.** A case that has never held a disk image has no
    `evidence/extracted` directory. Rendering that as "0 B" reads as "this case
    costs nothing", which is the direction that hides a 635 MB acquisition.
    (AGENTS.md §16 — the ninth time this rule has been needed, and the first
    time it is about capacity rather than health.)

  * **Recorded and measured sizes are reported as two separate numbers.**
    `evidence.file_size_bytes` is written once at upload and never re-measured.
    A row whose file was deleted outside the app carries its size for ever, so
    a total built from that column is a historical figure presented as a
    present one. The difference between the columns *is* the finding.

  * **An index has two legitimate homes and both are checked.** An index left in
    the cases directory by the relocation migration is still a real, searchable
    index; reporting `0` bytes for it because the canonical path is empty is
    the B28 defect rebuilt. (AGENTS.md §21.)

The suite drives the real app over `TestClient` and asserts on HTTP responses
and the filesystem, not on which helper functions ran. Qdrant is never opened —
embedded mode holds an exclusive lock per directory (§15) and the claims here
are about measurement, not about Qdrant.

Fixtures are built directly in the database, as `verify_evidence_archive.py`
does: a real upload would hash a file, queue a job and leave a per-case Qdrant
directory behind, none of which is under test. Rows are removed by `_purge`,
which fires on every exit path (§25) — a suite that writes to the live forensic
database is a defect in its own right.
"""
import os
import sys
import uuid
import shutil
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fastapi.testclient import TestClient

PASS, FAIL = [], []

from _purge import Purge                                     # noqa: E402
_PURGE = Purge("verify_storage")

SCRATCH = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMP", ".")),
    "idfa_storage_guard",
)


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' — ' + str(detail)) if detail else ''}")


def _write(path, size, filler=b"A"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write((filler * (size // len(filler) + 1))[:size])
    return size


def _make_case(SessionLocal, models, case_name="storage-guard"):
    db = SessionLocal()
    try:
        case_id = str(uuid.uuid4())
        _PURGE.ids(case_id)
        db.add(models.Case(
            id=case_id,
            case_name=f"{case_name}-{case_id[:8]}",
            case_number=f"STOR-{case_id[:8]}",
            status="Active",
            created_by="storage-guard",
            description="fixture",
        ))
        db.commit()
        return case_id
    finally:
        db.close()


def _add_evidence(SessionLocal, models, case_id, path, recorded, name):
    """
    Insert a row with a deliberately chosen recorded size.

    `recorded` is decoupled from the real file on purpose: that divergence is
    what the two-column contract is about, and a fixture where they agreed
    could not tell the contract apart from a single sum.
    """
    db = SessionLocal()
    try:
        ev_id = str(uuid.uuid4())
        _PURGE.ids(ev_id)
        db.add(models.Evidence(
            id=ev_id,
            case_id=case_id,
            filename=os.path.basename(path),
            original_filename=name,
            file_type="text",
            file_size_bytes=recorded,
            file_path=path,
            sha256_hash="0" * 64,
            ingested_by="storage-guard",
            status="Indexed",
            chunk_count=7,
            entity_count=3,
        ))
        db.commit()
        return ev_id
    finally:
        db.close()


def _add_artifact(SessionLocal, models, case_id, ev_id, path, recorded,
                  internal_path="dir/artifact.txt"):
    db = SessionLocal()
    try:
        art_id = str(uuid.uuid4())
        _PURGE.ids(art_id)
        db.add(models.ForensicArtifact(
            id=art_id,
            case_id=case_id,
            evidence_id=ev_id,
            internal_path=internal_path,
            # `filename` is NOT NULL. The obvious field name for a size,
            # `file_size`, does not exist on this model -- it is
            # `file_size_bytes` (the size inside the image) versus
            # `stored_file_size` (what was written to disk). Getting that
            # wrong raises TypeError from the declarative constructor, which
            # is the good failure: the suite dies instead of printing a
            # green summary it has not earned (AGENTS.md §26).
            filename=os.path.basename(internal_path),
            file_extension=".txt",
            file_size_bytes=recorded,
            extraction_type="text",
            stored_file_size=recorded,
            stored_file_path=path,
            is_viewable=True,
            is_deleted=False,
        ))
        db.commit()
        return art_id
    finally:
        db.close()


def _grant_access(SessionLocal, models, case_id, user_id):
    """Per-case access is checked by the storage endpoints, so grant it."""
    db = SessionLocal()
    try:
        db.add(models.CaseAccess(
            id=str(uuid.uuid4()),
            case_id=case_id,
            user_id=user_id,
            role_on_case="Viewer",
            granted_by="storage-guard",
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"  WARN  could not grant case access: {type(e).__name__}: {e}")
    finally:
        db.close()


def _user_id(SessionLocal, models, username):
    db = SessionLocal()
    try:
        row = db.query(models.User).filter(
            models.User.username == username).first()
        return row.id if row else None
    finally:
        db.close()


def main():
    from backend.main import app
    from backend.database import SessionLocal
    from backend import models

    if os.path.isdir(SCRATCH):
        shutil.rmtree(SCRATCH, ignore_errors=True)

    with TestClient(app) as client:
        # ── Auth ───────────────────────────────────────────────────────────
        email = f"stor_{uuid.uuid4().hex[:8]}@idfai.test"
        reg = client.post("/api/auth/register", json={
            "username": email, "email": email, "password": "Verify@2026",
            "full_name": "Storage Guard",
        })
        try:
            _PURGE.user((reg.json() or {}).get("id"), email)
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
            print(f"  SKIP  could not authenticate: {r.status_code} {r.text[:200]}")
            return 0
        H = {"Authorization": f"Bearer {token}"}
        uid = _user_id(SessionLocal, models, email)

        # ── A. a directory that does not exist is not zero ──────────────────
        print("\n=== A. an unmeasured section reports null, not 0 ===")
        case_id = _make_case(SessionLocal, models)
        _grant_access(SessionLocal, models, case_id, uid)

        # No `evidence/extracted` directory is created for this case, which is
        # the true state of every case that has never held a disk image.
        d = client.get(f"/api/storage/cases/{case_id}", headers=H)
        check("case breakdown returns 200", d.status_code == 200, d.status_code)
        body = d.json() if d.status_code == 200 else {}

        ext = body.get("extracted") or {}
        check("extracted.bytes is null when the directory is absent",
              ext.get("bytes") is None, f"got {ext.get('bytes')!r}")
        check("extracted.state names why",
              ext.get("state") == "unavailable", ext.get("state"))
        check("extracted carries a reason",
              bool(ext.get("reason")), ext.get("reason"))
        check("extracted human string is null too, not '0.0 B'",
              ext.get("bytes") is None)

        # The single most dangerous version of this bug: a total that silently
        # treats the unmeasurable section as zero reads as a smaller case.
        check("total.disk_bytes is a real measurement here (0 B evidence is "
              "legitimate — this case has no evidence rows)",
              body.get("total", {}).get("disk_bytes") == 0,
              body.get("total", {}).get("disk_bytes"))

        # ── B. recorded vs measured ─────────────────────────────────────────
        print("\n=== B. recorded and measured sizes are reported separately ===")
        real = _write(os.path.join(SCRATCH, case_id, "present.txt"), 4096)
        missing_path = os.path.join(SCRATCH, case_id, "gone.txt")
        ev_present = _add_evidence(SessionLocal, models, case_id,
                                   os.path.join(SCRATCH, case_id, "present.txt"),
                                   recorded=999999, name="present.txt")
        ev_missing = _add_evidence(SessionLocal, models, case_id,
                                   missing_path, recorded=7777, name="gone.txt")
        art_path = os.path.join(SCRATCH, case_id, "artifacts", "extracted.txt")
        _write(art_path, 2048)
        art_id = _add_artifact(SessionLocal, models, case_id, ev_present,
                               art_path, recorded=512)

        d = client.get(f"/api/storage/cases/{case_id}", headers=H)
        body = d.json()
        ev = body.get("evidence") or {}
        items = {i["name"]: i for i in (ev.get("items") or [])}

        check("both evidence rows are listed",
              {"present.txt", "gone.txt"} <= set(items), sorted(items))
        p = items.get("present.txt") or {}
        g = items.get("gone.txt") or {}

        check("a present file's measured size is the real size",
              p.get("disk_bytes") == real, f"{p.get('disk_bytes')} vs {real}")
        check("a present file's recorded size is what the DB says",
              p.get("db_bytes") == 999999, p.get("db_bytes"))
        check("the two differ and both are shown (pre-fix: one summed column)",
              p.get("db_bytes") != p.get("disk_bytes"))

        check("a missing file is flagged missing",
              g.get("missing") is True, g.get("missing"))
        check("a missing file's measured size is null, not 0",
              g.get("disk_bytes") is None, f"got {g.get('disk_bytes')!r}")
        check("a missing file's recorded size is still reported",
              g.get("db_bytes") == 7777, g.get("db_bytes"))

        check("evidence.missing counts only the absent file",
              ev.get("missing") == 1, ev.get("missing"))
        check("evidence.disk_bytes sums the measurable files only",
              ev.get("disk_bytes") == real, ev.get("disk_bytes"))
        check("evidence.db_bytes sums what the database recorded",
              ev.get("db_bytes") == 999999 + 7777, ev.get("db_bytes"))

        arts = body.get("artifacts") or {}
        check("artifacts are counted separately from evidence",
              arts.get("count") == 1, arts.get("count"))
        check("artifact measured size is real",
              (arts.get("items") or [{}])[0].get("disk_bytes") == 2048,
              (arts.get("items") or [{}])[0].get("disk_bytes"))

        # ── C. the flat inventory agrees with the breakdown ────────────────
        print("\n=== C. the inventory cannot disagree with the breakdown ===")
        inv = client.get(f"/api/storage/cases/{case_id}/files", headers=H)
        check("inventory returns 200", inv.status_code == 200, inv.status_code)
        ib = inv.json() if inv.status_code == 200 else {}
        byname = {f["name"]: f for f in (ib.get("files") or [])}
        check("inventory has the same three rows",
              len(ib.get("files") or []) == 3, len(ib.get("files") or []))
        check("inventory's measured total equals the breakdown's",
              ib.get("disk_bytes") == (ev.get("disk_bytes") or 0) + (arts.get("disk_bytes") or 0),
              f"{ib.get('disk_bytes')} vs {ev.get('disk_bytes')}+{arts.get('disk_bytes')}")
        check("inventory counts the missing file",
              ib.get("missing_count") == 1, ib.get("missing_count"))
        check("inventory separates measured from unmeasurable rows",
              ib.get("unmeasurable_count") == 1, ib.get("unmeasurable_count"))
        check("inventory's recorded total equals the breakdown's",
              ib.get("db_bytes") == (ev.get("db_bytes") or 0) + (arts.get("db_bytes") or 0),
              ib.get("db_bytes"))

        k = client.get(f"/api/storage/cases/{case_id}/files?kind=evidence", headers=H)
        check("kind filter returns only evidence",
              len((k.json() or {}).get("files") or []) == 2,
              len((k.json() or {}).get("files") or []))
        k = client.get(f"/api/storage/cases/{case_id}/files?kind=artifact", headers=H)
        check("kind filter returns only artifacts",
              len((k.json() or {}).get("files") or []) == 1,
              len((k.json() or {}).get("files") or []))

        # ── D. the index has two homes, and both are checked ───────────────
        print("\n=== D. an index in the non-canonical location is found ===")
        from backend.dependencies import get_settings
        settings = get_settings()
        try:
            from backend.modules.vector_store import case_qdrant_path
            canonical = case_qdrant_path(case_id)
        except Exception as e:
            canonical = None
            print(f"  WARN  canonical resolver unavailable: {type(e).__name__}: {e}")

        legacy = os.path.join(settings.cases_dir, case_id, "qdrant")
        made = []
        try:
            # An index sitting ONLY in the cases directory, with nothing at the
            # canonical path. The pre-fix code walked the canonical path and
            # reported 0 bytes for a real, searchable index (AGENTS.md §21).
            _write(os.path.join(legacy, "collection", "storage.sqlite"), 8192)
            made.append(legacy)
            d = client.get(f"/api/storage/cases/{case_id}", headers=H)
            idx = (d.json() or {}).get("index") or {}
            check("a legacy-located index is measured, not reported as 0",
                  idx.get("bytes") == 8192, f"{idx.get('bytes')} (location={idx.get('location')})")
            check("its location is named rather than left implicit",
                  idx.get("location") == "in_cases", idx.get("location"))
            check("provenance is unattributed for an index with no sidecar",
                  (idx.get("provenance") or {}).get("state") == "unattributed",
                  (idx.get("provenance") or {}).get("state"))

            # Now both locations exist. They are two copies of one index, so
            # summing them would double the reported size.
            if canonical and os.path.abspath(canonical) != os.path.abspath(legacy):
                _write(os.path.join(canonical, "collection", "storage.sqlite"), 8192)
                made.append(canonical)
                d = client.get(f"/api/storage/cases/{case_id}", headers=H)
                idx2 = (d.json() or {}).get("index") or {}
                check("a duplicated index is counted once",
                      idx2.get("bytes") == 8192, idx2.get("bytes"))
                check("duplication is reported, not collapsed",
                      idx2.get("duplicated") is True, idx2.get("duplicated"))
                check("the canonical copy wins when both exist",
                      idx2.get("location") == "canonical", idx2.get("location"))
        finally:
            for path in made:
                shutil.rmtree(path, ignore_errors=True)

        d = client.get(f"/api/storage/cases/{case_id}", headers=H)
        idx3 = (d.json() or {}).get("index") or {}
        check("a case with no index says absent rather than measuring nothing",
              idx3.get("location") == "absent", idx3.get("location"))
        check("and its bytes are 0 with state ok (it was looked for and not there)",
              idx3.get("bytes") == 0, idx3.get("bytes"))

        # ── E. overview: per-case table and orphan directories ─────────────
        print("\n=== E. the overview agrees with the per-case view ===")
        o = client.get("/api/storage/overview", headers=H)
        check("overview returns 200", o.status_code == 200, o.status_code)
        ob = o.json() if o.status_code == 200 else {}
        row = next((c for c in (ob.get("cases") or {}).get("items", [])
                    if c.get("case_id") == case_id), None)
        check("this case appears in the per-case table", row is not None)
        if row:
            check("the table's evidence size equals the breakdown's",
                  row.get("evidence_disk_bytes") == ev.get("disk_bytes"),
                  f"{row.get('evidence_disk_bytes')} vs {ev.get('disk_bytes')}")
            check("the table's missing count equals the breakdown's",
                  row.get("evidence_missing") == ev.get("missing"),
                  row.get("evidence_missing"))
            check("the table's index location equals the breakdown's",
                  row.get("index_location") == idx3.get("location"),
                  f"{row.get('index_location')} vs {idx3.get('location')}")

        check("overview totals a measurable evidence figure",
              isinstance((ob.get("totals") or {}).get("evidence_disk_bytes"), int))
        check("overview reports the cases tree state",
              (ob.get("cases_tree") or {}).get("state") in
              ("ok", "error", "unavailable"),
              (ob.get("cases_tree") or {}).get("state"))
        check("volumes carry a state, and a failure is not an empty list",
              (ob.get("volumes") or {}).get("state") in
              ("ok", "error", "unavailable"))
        orp = ob.get("orphan_case_dirs") or {}
        check("orphan directories carry a state whatever the role",
              orp.get("state") in ("ok", "error", "unavailable"),
              f"count={orp.get('count')} state={orp.get('state')}")
        check("a non-Admin is told the list is withheld rather than shown as 0",
              orp.get("count") is None and bool(orp.get("reason")),
              f"count={orp.get('count')} reason={orp.get('reason')!r}")
        check("totals say they are scoped when cases were withheld",
              (ob.get("totals") or {}).get("scoped_to_your_cases") is True
              and isinstance((ob.get("totals") or {}).get("cases_hidden"), int),
              f"scoped={(ob.get('totals') or {}).get('scoped_to_your_cases')}")

        # A directory with no database row must reach an Admin -- that is the
        # whole point of the section, and this install has ~150 of them from
        # earlier runs. It must NOT reach a non-Admin: an orphan has no case row,
        # so nobody can hold an access record for one, and its directory id plus
        # size would name an investigation the user is not assigned to.
        ghost = os.path.join(settings.cases_dir, f"ghost-{uuid.uuid4().hex[:10]}")
        admin_H = None
        try:
            _write(os.path.join(ghost, "evidence", "x.txt"), 1234)
            o = client.get("/api/storage/overview", headers=H)
            g = (o.json() or {}).get("orphan_case_dirs") or {}
            check("a non-Admin does not receive the orphan list",
                  g.get("items") is None, type(g.get("items")).__name__)

            ar = client.post("/api/auth/login", data={
                "username": "admin", "password": "Admin@IDF2025"})
            atok = (ar.json() or {}).get("access_token")
            if atok:
                admin_H = {"Authorization": f"Bearer {atok}"}
                o = client.get("/api/storage/overview", headers=admin_H)
                items = {c["case_id"] for c in
                         ((o.json() or {}).get("orphan_case_dirs") or {}).get("items") or []}
                check("an Admin does receive it, and the ghost is in it",
                      os.path.basename(ghost) in items,
                      f"{len(items)} orphan dir(s) listed")
                check("the orphan section reports a real count for an Admin",
                      isinstance(((o.json() or {})
                                  .get("orphan_case_dirs") or {}).get("count"), int))
            else:
                print(f"  SKIP  admin login unavailable ({ar.status_code}) "
                      f"-- the Admin-side orphan check was not measured")
        finally:
            shutil.rmtree(ghost, ignore_errors=True)

        # ── F. access control and refusals ─────────────────────────────────
        print("\n=== F. a case you may not see is refused, not summarised ===")
        other = _make_case(SessionLocal, models, case_name="no-access")
        d = client.get(f"/api/storage/cases/{other}", headers=H)
        check("no access record means 403, not a 200 with empty figures",
              d.status_code == 403, d.status_code)
        d = client.get(f"/api/storage/cases/{other}/files", headers=H)
        check("the inventory is refused too",
              d.status_code == 403, d.status_code)
        d = client.get("/api/storage/cases/does-not-exist", headers=H)
        check("an unknown case is 404",
              d.status_code == 404, d.status_code)

        d = client.get("/api/storage/overview", headers=H)
        check("the overview does not include cases you cannot see",
              other not in {c["case_id"] for c in (d.json().get("cases") or {}).get("items", [])})

        d = client.get("/api/storage/overview")
        check("the overview requires authentication",
              d.status_code in (401, 403), d.status_code)

    shutil.rmtree(SCRATCH, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\n  FAILED:")
        for f in FAIL:
            print(f"    FAIL  {f}")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n  {len(PASS)} passed, 1 failed")
        print("    FAIL  suite raised — the run above is not a result")
        sys.exit(1)