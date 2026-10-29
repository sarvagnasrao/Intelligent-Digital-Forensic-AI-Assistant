"""Run potentially large case deletions without blocking the interface."""
from PySide6.QtCore import QThread, Signal


class DeletionWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, kind: str, record_id: int, user_id: int, reason: str = ""):
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

        session = None
        try:
            session = get_session_factory()()
            user = session.get(User, self.user_id)
            if user is None:
                raise ValueError("Signed-in user could not be found")
            if self.kind == "evidence":
                result = EvidenceService(session).delete_evidence(
                    self.record_id, user, self.reason
                )
            else:
                if not ExaminationService(session).delete_job(self.record_id, user):
                    raise ValueError("This job cannot be deleted while examination or analysis is running")
                result = {}
            session.commit()
            self.succeeded.emit(result)
        except Exception as exc:
            if session is not None:
                session.rollback()
            self.failed.emit(str(exc))
        finally:
            if session is not None:
                session.close()
