"""Case management service."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.auth.models import Case, User, UserRole
from app.auth.service import AuthService

if TYPE_CHECKING:
    from app.evidence.models import Evidence


class CaseService:
    """Service for case management operations."""

    def __init__(self, session: Session):
        self.session = session
        self.auth_service = AuthService(session)

    def create_case(
        self,
        case_id: str,
        title: str,
        description: str | None,
        objective: str | None,
        priority: str,
        created_by: User,
        assignee_id: int | None = None,
    ) -> Case:
        """Create a new case."""
        # Validate assignee
        assignee = None
        if assignee_id:
            assignee = self.auth_service.get_user_by_id(assignee_id)
            if not assignee or not assignee.is_active:
                raise ValueError("Invalid assignee")

        case = Case(
            case_id=case_id,
            title=title,
            description=description,
            objective=objective,
            priority=priority,
            created_by_id=created_by.id,
            assignee_id=assignee.id if assignee else None,
            status="open",
        )
        self.session.add(case)
        self.session.flush()
        return case

    def get_case_by_id(self, case_id: int) -> Case | None:
        """Get case by database ID."""
        return self.session.get(Case, case_id)

    def get_case_by_case_id(self, case_id: str) -> Case | None:
        """Get case by human-readable case_id."""
        return self.session.execute(select(Case).where(Case.case_id == case_id)).scalar_one_or_none()

    def update_case(
        self,
        case_id: int,
        title: str | None = None,
        description: str | None = None,
        objective: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        assignee_id: int | None = None,
    ) -> Case | None:
        """Update case fields."""
        case = self.get_case_by_id(case_id)
        if not case:
            return None
        if case.archived_at is not None:
            raise PermissionError("Archived cases are read-only; restore the case before editing")

        if title is not None:
            case.title = title
        if description is not None:
            case.description = description
        if objective is not None:
            case.objective = objective
        if priority is not None:
            case.priority = priority
        if status is not None:
            old_status = case.status
            case.status = status
            if status == "closed" and old_status != "closed":
                case.closed_at = datetime.now(timezone.utc)
        if assignee_id is not None:
            if assignee_id == 0:
                case.assignee_id = None
            else:
                assignee = self.auth_service.get_user_by_id(assignee_id)
                if not assignee or not assignee.is_active:
                    raise ValueError("Invalid assignee")
                case.assignee_id = assignee.id

        self.session.flush()
        return case

    def _require_active_admin(self, actor: User) -> User:
        """Validate permissions against persisted identity, not a stale UI model."""
        stored = self.session.get(User, actor.id) if actor is not None else None
        if stored is None or not stored.is_active or stored.role != UserRole.ADMIN:
            raise PermissionError("Only an active administrator can archive or restore cases")
        return stored

    def archive_case(self, case_id: int, actor: User, reason: str = "") -> bool:
        """Archive without deleting any evidence, audit event, or custody record."""
        from app.audit.service import AuditService

        admin = self._require_active_admin(actor)
        case = self.get_case_by_id(case_id)
        if case is None or case.archived_at is not None:
            return False

        reason = (reason or "").strip()
        if len(reason) > 512:
            raise ValueError("Archive reason must be 512 characters or fewer")
        case.archived_at = datetime.now(timezone.utc)
        case.archived_by_id = admin.id
        case.archive_reason = reason or None
        AuditService(self.session).log_event(
            event_type="case",
            action="archive",
            result="success",
            user=admin,
            case_id=case.id,
            target_type="case",
            target_id=case.id,
            details={"case_reference": case.case_id, "reason": reason},
        )
        self.session.flush()
        return True

    def restore_case(self, case_id: int, actor: User) -> bool:
        """Restore a case without changing its forensic evidence history."""
        from app.audit.service import AuditService

        admin = self._require_active_admin(actor)
        case = self.get_case_by_id(case_id)
        if case is None or case.archived_at is None:
            return False
        previous_reason = case.archive_reason
        case.archived_at = None
        case.archived_by_id = None
        case.archive_reason = None
        AuditService(self.session).log_event(
            event_type="case",
            action="restore",
            result="success",
            user=admin,
            case_id=case.id,
            target_type="case",
            target_id=case.id,
            details={"case_reference": case.case_id, "previous_archive_reason": previous_reason},
        )
        self.session.flush()
        return True

    def delete_case(self, case_id: int) -> bool:
        """Retired destructive operation: case removal is deliberately disabled."""
        raise PermissionError("Permanent case deletion is disabled; use archive_case")

    def list_archived_cases(self, user: User) -> list[Case]:
        """List archived cases for the administrator's restoration interface."""
        self._require_active_admin(user)
        return list(self.session.execute(
            select(Case).where(Case.archived_at.is_not(None))
            .order_by(Case.archived_at.desc())
        ).scalars().all())

    def list_cases(
        self,
        user: User,
        status: str | None = None,
        priority: str | None = None,
        assignee_id: int | None = None,
        search: str | None = None,
        *,
        include_archived: bool = False,
    ) -> list[Case]:
        """List cases accessible to user; archived cases require admin access."""
        if not user.is_active:
            return []
        if include_archived:
            self._require_active_admin(user)
        if user.role == UserRole.ADMIN:
            stmt = select(Case)
        else:
            stmt = select(Case).where(
                (Case.assignee_id == user.id) | (Case.created_by_id == user.id)
            )

        if not include_archived:
            stmt = stmt.where(Case.archived_at.is_(None))
        if status:
            stmt = stmt.where(Case.status == status)
        if priority:
            stmt = stmt.where(Case.priority == priority)
        if assignee_id:
            stmt = stmt.where(Case.assignee_id == assignee_id)
        if search:
            search_term = f"%{search}%"
            stmt = stmt.where(
                (Case.case_id.ilike(search_term)) |
                (Case.title.ilike(search_term)) |
                (Case.description.ilike(search_term))
            )

        return list(self.session.execute(stmt.order_by(Case.updated_at.desc())).scalars().all())

    def get_case_stats(self, user: User) -> dict[str, int]:
        """Get case statistics for dashboard."""
        cases = self.list_cases(user)
        total = len(cases)
        active = sum(1 for c in cases if c.status in ("open", "active"))
        on_hold = sum(1 for c in cases if c.status == "on_hold")
        closed = sum(1 for c in cases if c.status == "closed")
        needs_attention = sum(1 for c in cases if c.status == "open" and c.priority in ("high", "critical"))
        return {
            "total": total,
            "active": active,
            "on_hold": on_hold,
            "closed": closed,
            "needs_attention": needs_attention,
        }

    def get_case_overview(self, case_id: int) -> dict:
        """Return active-evidence metrics and actionable case workflow state."""
        from app.artifacts.models import Artifact, IndexStatus
        from app.audit.models import AuditEvent
        from app.analysis.models import AnalysisJob, AnalysisJobStatus
        from app.evidence.models import Evidence, EvidenceHash, EvidenceStatus
        from app.examination.models import ExaminationJob, JobStatus
        from app.findings.models import Finding, FindingStatus
        from app.reports.models import Report, ReportStatus

        def count(model, *criteria) -> int:
            stmt = select(func.count()).select_from(model).where(model.case_id == case_id)
            if criteria:
                stmt = stmt.where(*criteria)
            return int(self.session.execute(stmt).scalar_one())

        active_evidence = Evidence.removed_at.is_(None)
        active_evidence_ids = select(Evidence.id).where(
            Evidence.case_id == case_id, active_evidence
        )
        evidence_count = count(Evidence, active_evidence)
        verified_ids = select(EvidenceHash.evidence_id).where(
            EvidenceHash.evidence_id.in_(active_evidence_ids),
            EvidenceHash.match_result.is_(True),
        ).distinct()
        verified_count = int(self.session.execute(
            select(func.count()).select_from(Evidence).where(
                Evidence.id.in_(verified_ids),
                Evidence.status != EvidenceStatus.INTEGRITY_FAILED,
            )
        ).scalar_one())
        failed_integrity_count = count(
            Evidence, active_evidence, Evidence.status == EvidenceStatus.INTEGRITY_FAILED
        )

        active_exams = ExaminationJob.evidence_id.in_(active_evidence_ids)
        running_job_count = count(
            ExaminationJob, active_exams, ExaminationJob.status == JobStatus.RUNNING
        )
        failed_job_count = count(
            ExaminationJob, active_exams,
            ExaminationJob.status.in_((JobStatus.FAILED, JobStatus.INTERRUPTED)),
        )
        examined_ids = select(ExaminationJob.evidence_id).where(
            active_exams, ExaminationJob.status == JobStatus.COMPLETED
        ).distinct()
        examined_evidence_count = int(self.session.execute(
            select(func.count()).select_from(Evidence).where(
                Evidence.id.in_(examined_ids)
            )
        ).scalar_one())

        active_artifacts = Artifact.evidence_id.in_(active_evidence_ids)
        artifact_count = count(Artifact, active_artifacts)
        searchable_count = count(
            Artifact, active_artifacts, Artifact.content_text.is_not(None),
            Artifact.content_text != "",
        )
        indexed_count = count(
            Artifact, active_artifacts,
            Artifact.index_status == IndexStatus.INDEXED,
            Artifact.content_text.is_not(None), Artifact.content_text != "",
        )
        analysis_active = AnalysisJob.evidence_id.in_(active_evidence_ids)
        analysis_running_count = count(
            AnalysisJob, analysis_active,
            AnalysisJob.status == AnalysisJobStatus.RUNNING,
        )
        analysis_failed_count = count(
            AnalysisJob, analysis_active,
            AnalysisJob.status.in_((AnalysisJobStatus.FAILED, AnalysisJobStatus.INTERRUPTED)),
        )
        analysis_done_ids = select(AnalysisJob.evidence_id).where(
            analysis_active, AnalysisJob.status == AnalysisJobStatus.COMPLETED
        ).distinct()
        analyzed_evidence_count = int(self.session.execute(
            select(func.count()).select_from(Evidence).where(
                Evidence.id.in_(analysis_done_ids)
            )
        ).scalar_one())
        analysis_eligible_count = examined_evidence_count

        review_count = count(
            Finding, Finding.status.in_((FindingStatus.DRAFT, FindingStatus.UNDER_REVIEW))
        )
        verified_findings = count(Finding, Finding.status == FindingStatus.VERIFIED)
        reports_count = count(Report, Report.status == ReportStatus.COMPLETED)
        removed_artifact_count = int(self.session.execute(
            select(func.count()).select_from(Artifact).join(
                Evidence, Artifact.evidence_id == Evidence.id
            ).where(Artifact.case_id == case_id, Evidence.removed_at.is_not(None))
        ).scalar_one())

        def stage(status: str, detail: str, value: str) -> dict[str, str]:
            return {"status": status, "detail": detail, "value": value}

        workflow = {
            "evidence": stage(
                "not_started" if not evidence_count else (
                    "needs_attention" if failed_integrity_count else
                    "complete" if verified_count == evidence_count else "in_progress"
                ),
                ("Register evidence to begin." if not evidence_count else
                 f"{verified_count} of {evidence_count} active evidence items integrity-verified."),
                f"{verified_count}/{evidence_count}",
            ),
            "examination": stage(
                "not_started" if not evidence_count else (
                    "needs_attention" if failed_job_count else
                    "complete" if examined_evidence_count == evidence_count else
                    "in_progress" if running_job_count else "not_started"
                ),
                ("No active evidence to examine." if not evidence_count else
                 f"{examined_evidence_count} of {evidence_count} active evidence items examined; "
                 f"{running_job_count} running, {failed_job_count} failed/interrupted."),
                f"{examined_evidence_count}/{evidence_count}",
            ),
            "artifacts": stage(
                "not_started" if not examined_evidence_count else (
                    "needs_attention" if not artifact_count else
                    "complete" if indexed_count == searchable_count else "in_progress"
                ),
                ("Examine evidence to create artifact records." if not examined_evidence_count else
                 f"{artifact_count} active artifacts; {indexed_count} of {searchable_count} "
                 "text-bearing artifacts indexed."),
                f"{indexed_count}/{searchable_count}",
            ),
            "analysis": stage(
                "not_started" if not analysis_eligible_count else (
                    "needs_attention" if analysis_failed_count else
                    "complete" if analyzed_evidence_count == analysis_eligible_count else
                    "in_progress" if analysis_running_count else "not_started"
                ),
                ("Analysis becomes available after examination." if not analysis_eligible_count else
                 f"{analyzed_evidence_count} of {analysis_eligible_count} examined evidence items analyzed; "
                 f"{analysis_running_count} running, {analysis_failed_count} failed/interrupted."),
                f"{analyzed_evidence_count}/{analysis_eligible_count}",
            ),
        }

        if not evidence_count:
            next_action = {"key": "evidence", "title": "Register evidence", "detail":
                           "Add active evidence to start the case workflow."}
        elif failed_integrity_count:
            next_action = {"key": "evidence", "title": "Resolve integrity issues", "detail":
                           f"{failed_integrity_count} active evidence item(s) have a failed integrity check."}
        elif verified_count < evidence_count:
            next_action = {"key": "evidence", "title": "Verify evidence integrity", "detail":
                           f"Verify {evidence_count - verified_count} active evidence item(s) before examination."}
        elif failed_job_count:
            next_action = {"key": "examination", "title": "Review failed examinations", "detail":
                           f"{failed_job_count} examination job(s) failed or were interrupted."}
        elif examined_evidence_count < evidence_count:
            next_action = {"key": "examination", "title": "Examine remaining evidence", "detail":
                           f"{evidence_count - examined_evidence_count} active evidence item(s) still need examination."}
        elif not artifact_count:
            next_action = {"key": "examination", "title": "Review extraction results", "detail":
                           "Examination has completed but no active artifact records were found."}
        elif indexed_count < searchable_count:
            next_action = {"key": "artifacts", "title": "Index extracted text", "detail":
                           f"{searchable_count - indexed_count} text-bearing artifact(s) remain unindexed."}
        elif analysis_failed_count or analyzed_evidence_count < analysis_eligible_count:
            next_action = {"key": "entities", "title": "Review entity analysis", "detail":
                           "Check the analysis queue for pending or failed case analysis."}
        elif review_count:
            next_action = {"key": "findings", "title": "Review case findings", "detail":
                           f"{review_count} finding(s) need investigator review."}
        else:
            next_action = {"key": "reports", "title": "Generate a case report", "detail":
                           "Core processing is up to date. Reporting is optional."}

        activity = self.session.execute(
            select(AuditEvent)
            .where(AuditEvent.case_id == case_id)
            .order_by(AuditEvent.timestamp.desc())
            .limit(8)
        ).scalars().all()
        activity_labels = {
            ("evidence", "remove"): "Evidence removed from active case",
            ("evidence", "return"): "Evidence returned to active case",
            ("evidence", "delete"): "Evidence permanently deleted",
            ("examination", "delete_job"): "Examination and derived artifacts deleted",
            ("artifact", "delete"): "Extracted artifact deleted",
        }
        return {
            "stats": {
                "evidence": evidence_count,
                "examinations": examined_evidence_count,
                "artifacts": artifact_count,
                "indexed": indexed_count,
                "searchable": searchable_count,
                "findings_review": review_count,
                "findings_verified": verified_findings,
                "reports": reports_count,
                "removed_artifacts": removed_artifact_count,
            },
            "workflow": workflow,
            "next_action": next_action,
            "activity": [
                {
                    "action": activity_labels.get(
                        (event.event_type, event.action),
                        f"{event.event_type.replace('_', ' ').title()} — "
                        f"{event.action.replace('_', ' ').title()}",
                    ),
                    "result": event.result,
                    "timestamp": event.timestamp,
                }
                for event in activity
            ],
        }

    def get_recent_activity(self, user: User, limit: int = 10) -> list[dict]:
        """Get recent case activity for dashboard."""
        # This would query audit_events in a real implementation
        # For now, return recent case updates
        cases = self.list_cases(user)
        cases.sort(key=lambda c: c.updated_at, reverse=True)
        return [
            {
                "case_id": c.case_id,
                "title": c.title,
                "action": "updated",
                "timestamp": c.updated_at.isoformat() if c.updated_at else c.created_at.isoformat(),
            }
            for c in cases[:limit]
        ]

    def get_dashboard_alerts(self, user: User) -> list[dict]:
        """Get alerts for dashboard (overdue, failed exams, etc.)."""
        alerts = []
        cases = self.list_cases(user)
        for case in cases:
            if case.status == "open" and case.priority in ("high", "critical"):
                alerts.append({
                    "level": "warning",
                    "message": f"High priority case '{case.title}' needs attention",
                    "case_id": case.id,
                })
        return alerts
