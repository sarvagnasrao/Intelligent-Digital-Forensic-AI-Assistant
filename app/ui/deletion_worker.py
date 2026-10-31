"""Run potentially large case deletions without blocking the interface."""
from PySide6.QtCore import QThread, Signal


class EvidenceDeletionPreviewWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, evidence_id: int):
        super().__init__()
        self.evidence_id = evidence_id

    def run(self):
        from app.db.session import get_session_factory
        from app.evidence.service import EvidenceService

        session = None
        try:
            session = get_session_factory()()
            service = EvidenceService(session)
            evidence = service.get_evidence_by_id(self.evidence_id)
            if evidence is None:
                raise ValueError("That evidence no longer exists.")
            self.succeeded.emit({
                "files": [str(path) for path in service.case_store_files(evidence)],
                "blockers": service.deletion_blockers(evidence),
                "impact": service.deletion_impact(evidence),
            })
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if session is not None:
                session.close()


class DeletionWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, kind: str, record_id: int | list[int], user_id: int, reason: str = ""):
        super().__init__()
        self.kind = kind
        self.record_id = record_id
        self.user_id = user_id
        self.reason = reason

    def run(self):
        from app.auth.models import User
        from app.db.session import get_session_factory
        from app.evidence.service import EvidenceService
        from app.examination.service import ExaminationService
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError

        session = None
        try:
            session = get_session_factory()()
            # Reserve SQLite's single writer before reading the evidence and
            # contacting Qdrant. Otherwise a concurrent writer can invalidate
            # our read snapshot and SQLite rejects the later DELETE immediately.
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            user = session.get(User, self.user_id)
            if user is None:
                raise ValueError("Signed-in user could not be found")
            if self.kind == "evidence":
                result = EvidenceService(session).delete_evidence(
                    self.record_id, user, self.reason
                )
            elif self.kind == "examination_batch":
                deleted = 0
                errors = []
                for job_id in self.record_id:
                    try:
                        if session.get_bind().dialect.name == "sqlite" and not session.in_transaction():
                            session.execute(text("BEGIN IMMEDIATE"))
                        if not ExaminationService(session).delete_job(job_id, user):
                            raise ValueError("Job is running, has active analysis, or no longer exists")
                        session.commit()
                        deleted += 1
                    except Exception as exc:
                        session.rollback()
                        errors.append(f"Job {job_id}: {exc}")
                result = {"deleted": deleted, "errors": errors}
            else:
                if not ExaminationService(session).delete_job(self.record_id, user):
                    raise ValueError("This job cannot be deleted while examination or analysis is running")
                result = {}
            session.commit()
            self.succeeded.emit(result)
        except Exception as exc:
            if session is not None:
                session.rollback()
            if isinstance(exc, OperationalError) and "locked" in str(exc).lower():
                self.failed.emit(
                    "The case database is busy with another operation. "
                    "Wait for examination, analysis or indexing to finish, then try again."
                )
            else:
                self.failed.emit(str(exc))
        finally:
            if session is not None:
                session.close()
