"""Row cleanup that runs on every exit path.

Why this exists
---------------
Four suites drive the app through `TestClient`, which means they register a
throwaway user. Three of them deleted their cases and evidence at the end of
the happy path but never deleted the **user**, so `data/forensic.db`
accumulated one `modes_*` / `stop_*` / `arch_*` / `b31_*` account per run --
measured at 92 users and 249 orphaned audit rows.

Worse, that cleanup sat *after* every assertion with no `finally` and no
`atexit`, so a failure or an early return left the case and evidence rows
behind too. A test suite that writes to the live forensic database is a defect
in its own right: in this product the database *is* the evidence record, and
`verify_service_health.py` already established the rule for itself ("Nothing
here touches `data/forensic.db`"). See AGENTS.md sections 10 and 14.

Usage
-----
    from _purge import Purge

    purge = Purge()
    purge.user(user_id, username)     # as soon as the account exists
    purge.ids(case_id, evidence_id)   # as each fixture row is committed

and nothing else -- the `atexit` hook is registered in `__init__`, so it fires
on a failed assertion, an exception, or `sys.exit(1)`.

Two details that are easy to get wrong and fail silently
--------------------------------------------------------
* Children are deleted before parents. `Query.delete()` bypasses ORM cascades,
  so the ordering is the only thing standing between a partial run and a
  foreign-key error.
* Audit rows carry the **username** in `performed_by`, not the user id --
  `_log_auth_event` passes `details["username"]`. Deleting users by id and
  leaving `audit_logs` untouched orphans the trail behind a name that no
  longer resolves to an account; filtering `performed_by` by *id* deletes
  nothing at all while looking like it worked.

Deliberately *not* handled here: the pre-existing ~92 accounts. They are the
operator's to remove, and a test script silently deleting rows it did not
create is exactly the behaviour these suites were corrected for.
"""
import atexit

# Table order for `ids()`: children first.
_ID_MODELS = ("IngestionJob", "Evidence", "ForensicArtifact", "Note",
              "QueryLog", "Entity", "Report", "Case")


class Purge:
    """Records what a run created and deletes it however the run ends."""

    def __init__(self, label="suite"):
        self.label = label
        self._ids = []
        self._user_ids = []
        self._usernames = []
        self.done = False
        atexit.register(self.run)

    # ── recording ────────────────────────────────────────────────────────
    def ids(self, *values):
        for v in values:
            if v and v not in self._ids:
                self._ids.append(v)

    def user(self, user_id=None, username=None):
        if user_id and user_id not in self._user_ids:
            self._user_ids.append(user_id)
        if username and username not in self._usernames:
            self._usernames.append(username)

    @property
    def empty(self):
        return not (self._ids or self._user_ids or self._usernames)

    # ── deletion ─────────────────────────────────────────────────────────
    def run(self):
        """Idempotent: calling it explicitly and again at exit is harmless."""
        if self.done or self.empty:
            return
        self.done = True
        try:
            from backend.database import SessionLocal
            from backend import models
        except Exception as e:                # interpreter already tearing down
            print(f"  WARN  {self.label}: cleanup could not import "
                  f"({type(e).__name__}) - rows may remain")
            return
        try:
            db = SessionLocal()
        except Exception as e:
            print(f"  WARN  {self.label}: cleanup could not connect "
                  f"({type(e).__name__}) - rows may remain")
            return
        try:
            if self._ids:
                for name in _ID_MODELS:
                    model = getattr(models, name, None)
                    if model is None or not hasattr(model, "case_id"):
                        continue
                    db.query(model).filter(model.case_id.in_(self._ids)).delete(
                        synchronize_session=False)
                for name in _ID_MODELS:
                    model = getattr(models, name, None)
                    if model is None or not hasattr(model, "id"):
                        continue
                    db.query(model).filter(model.id.in_(self._ids)).delete(
                        synchronize_session=False)
            if self._usernames:
                db.query(models.AuditLog).filter(
                    models.AuditLog.performed_by.in_(self._usernames)
                ).delete(synchronize_session=False)
            if self._user_ids:
                db.query(models.User).filter(
                    models.User.id.in_(self._user_ids)
                ).delete(synchronize_session=False)
            db.commit()
        except Exception as e:
            print(f"  WARN  {self.label}: cleanup skipped "
                  f"({type(e).__name__}: {e})")
        finally:
            db.close()
