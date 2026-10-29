"""Audit service for audit trail and chain of custody."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit.models import AuditEvent
from app.auth.models import User
from app.evidence.models import CustodyEvent, Evidence

if TYPE_CHECKING:
    from app.auth.models import Case


class AuditService:
    """Service for managing audit trail events."""

    def __init__(self, session: Session):
        self.session = session

    def _generate_event_id(self) -> str:
        return f"AUD-{uuid.uuid4().hex[:12].upper()}"

    def log_event(
        self,
        event_type: str,
        action: str,
        result: str,
        user: User | None = None,
        case_id: int | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        details: dict | None = None,
        error_message: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> AuditEvent:
        """Log an audit event."""
        event = AuditEvent(
            event_id=self._generate_event_id(),
            case_id=case_id,
            user_id=user.id if user else None,
            event_type=event_type,
            action=action,
            result=result,
            target_type=target_type,
            target_id=target_id,
            details_json=json.dumps(details) if details else None,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def log_login(self, user: User, success: bool, ip: str | None = None) -> AuditEvent:
        return self.log_event(
            event_type="auth",
            action="login",
            result="success" if success else "failure",
            user=user,
            details={"username": user.username} if user else None,
            error_message=None if success else "Invalid credentials",
            ip_address=ip,
        )

    def log_logout(self, user: User) -> AuditEvent:
        return self.log_event(
            event_type="auth",
            action="logout",
            result="success",
            user=user,
        )

    def log_case_create(self, user: User, case_id: int, case_data: dict) -> AuditEvent:
        return self.log_event(
            event_type="case",
            action="create",
            result="success",
            user=user,
            case_id=case_id,
            target_type="case",
            target_id=case_id,
            details=case_data,
        )

    def log_case_update(self, user: User, case_id: int, changes: dict) -> AuditEvent:
        return self.log_event(
            event_type="case",
            action="update",
            result="success",
            user=user,
            case_id=case_id,
            target_type="case",
            target_id=case_id,
            details=changes,
        )

    def log_case_delete(self, user: User, case_id: int) -> AuditEvent:
        return self.log_event(
            event_type="case",
            action="delete",
            result="success",
            user=user,
            case_id=case_id,
            target_type="case",
            target_id=case_id,
        )

    def log_evidence_register(self, user: User, case_id: int, evidence_id: int, evidence_data: dict) -> AuditEvent:
        return self.log_event(
            event_type="evidence",
            action="register",
            result="success",
            user=user,
            case_id=case_id,
            target_type="evidence",
            target_id=evidence_id,
            details=evidence_data,
        )

    def log_evidence_verify(self, user: User, case_id: int, evidence_id: int, results: dict) -> AuditEvent:
        all_passed = all(results.values())
        return self.log_event(
            event_type="evidence",
            action="verify",
            result="success" if all_passed else "failure",
            user=user,
            case_id=case_id,
            target_type="evidence",
            target_id=evidence_id,
            details=results,
            error_message=None if all_passed else "Hash mismatch detected",
        )

    def log_examination_start(self, user: User, case_id: int, job_id: int) -> AuditEvent:
        return self.log_event(
            event_type="examination",
            action="start",
            result="success",
            user=user,
            case_id=case_id,
            target_type="examination_job",
            target_id=job_id,
        )

    def log_examination_complete(self, user: User, case_id: int, job_id: int, success: bool, error: str | None = None) -> AuditEvent:
        return self.log_event(
            event_type="examination",
            action="complete",
            result="success" if success else "failure",
            user=user,
            case_id=case_id,
            target_type="examination_job",
            target_id=job_id,
            error_message=error,
        )

    def log_search(self, user: User, case_id: int, query: str, mode: str, result_count: int) -> AuditEvent:
        return self.log_event(
            event_type="search",
            action="query",
            result="success",
            user=user,
            case_id=case_id,
            details={"query": query, "mode": mode, "results": result_count},
        )

    def log_ai_query(self, user: User, case_id: int, question: str, model: str, success: bool, citations: list | None = None) -> AuditEvent:
        return self.log_event(
            event_type="ai",
            action="generate",
            result="success" if success else "failure",
            user=user,
            case_id=case_id,
            details={"question": question, "model": model, "citations": len(citations) if citations else 0},
        )

    def log_finding_create(self, user: User, case_id: int, finding_id: int, finding_data: dict) -> AuditEvent:
        return self.log_event(
            event_type="finding",
            action="create",
            result="success",
            user=user,
            case_id=case_id,
            target_type="finding",
            target_id=finding_id,
            details=finding_data,
        )

    def log_finding_verify(self, user: User, case_id: int, finding_id: int, status: str) -> AuditEvent:
        return self.log_event(
            event_type="finding",
            action="verify",
            result="success",
            user=user,
            case_id=case_id,
            target_type="finding",
            target_id=finding_id,
            details={"status": status},
        )

    def log_report_generate(self, user: User, case_id: int, report_id: int, format: str) -> AuditEvent:
        return self.log_event(
            event_type="report",
            action="generate",
            result="success",
            user=user,
            case_id=case_id,
            target_type="report",
            target_id=report_id,
            details={"format": format},
        )

    def record_custody_event(
        self,
        *,
        case_id: int,
        evidence_id: int,
        event_type: str,
        description: str,
        performed_by: User,
        source_location: str | None = None,
        destination_location: str | None = None,
        tool_used: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CustodyEvent:
        """Append a custody record and matching audit entry atomically."""
        evidence = self.session.get(Evidence, evidence_id)
        if evidence is None or evidence.case_id != case_id:
            raise ValueError("Selected evidence does not belong to this case")
        if not description.strip():
            raise ValueError("A custody event description is required")
        event = CustodyEvent(
            evidence_id=evidence.id,
            event_type=event_type,
            description=description.strip(),
            performed_by_id=performed_by.id,
            source_location=(source_location.strip() or None) if source_location else None,
            destination_location=(destination_location.strip() or None) if destination_location else None,
            tool_used=(tool_used.strip() or None) if tool_used else None,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        self.session.add(event)
        self.session.flush()
        self.log_event(
            event_type="custody",
            action=event_type,
            result="success",
            user=performed_by,
            case_id=case_id,
            target_type="evidence",
            target_id=evidence.id,
            details={
                "evidence_ref": evidence.evidence_id,
                "custody_event_id": event.id,
                "description": event.description,
                "source_location": event.source_location,
                "destination_location": event.destination_location,
                "tool_used": event.tool_used,
            },
        )
        return event

    def get_case_audit_events(self, case_id: int, limit: int = 100) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .options(selectinload(AuditEvent.user))
            .where(AuditEvent.case_id == case_id)
            .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
            .limit(max(1, min(limit, 10000)))
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_case_custody_events(self, case_id: int, limit: int = 10000) -> list[CustodyEvent]:
        """Return the custody history for all evidence in a case, newest first."""
        stmt = (
            select(CustodyEvent)
            .join(CustodyEvent.evidence)
            .options(
                selectinload(CustodyEvent.performed_by),
                selectinload(CustodyEvent.evidence),
            )
            .where(Evidence.case_id == case_id)
            .order_by(CustodyEvent.performed_at.desc(), CustodyEvent.id.desc())
            .limit(max(1, min(limit, 10000)))
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_user_audit_events(self, user_id: int, limit: int = 100) -> list[AuditEvent]:
        stmt = select(AuditEvent).where(AuditEvent.user_id == user_id).order_by(AuditEvent.timestamp.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def get_global_audit_events(self, limit: int = 500) -> list[AuditEvent]:
        stmt = select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def export_case_audit(self, case_id: int) -> list[dict]:
        events = self.get_case_audit_events(case_id, limit=10000)
        return [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "event_type": e.event_type,
                "action": e.action,
                "result": e.result,
                "user": e.user.username if e.user else "System",
                "target_type": e.target_type,
                "target_id": e.target_id,
                "details": json.loads(e.details_json) if e.details_json else None,
                "error": e.error_message,
            }
            for e in events
        ]

    def export_case_custody(self, case_id: int) -> list[dict[str, Any]]:
        """Return serializable chain-of-custody entries for export."""
        events = self.get_case_custody_events(case_id, limit=10000)
        exported: list[dict[str, Any]] = []
        for event in events:
            try:
                metadata = json.loads(event.metadata_json) if event.metadata_json else None
            except (TypeError, json.JSONDecodeError):
                metadata = event.metadata_json
            evidence = event.evidence
            exported.append({
                "timestamp": event.performed_at.isoformat() if event.performed_at else None,
                "event_type": event.event_type,
                "evidence_id": evidence.evidence_id if evidence else None,
                "evidence_name": evidence.name if evidence else None,
                "performed_by": event.performed_by.username if event.performed_by else "Unknown",
                "description": event.description,
                "source_location": event.source_location,
                "destination_location": event.destination_location,
                "tool_used": event.tool_used,
                "metadata": metadata,
            })
        return exported
