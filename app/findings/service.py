"""Findings service for investigation findings workflow."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.auth.models import User
from app.findings.models import Finding, FindingArtifactLink, FindingOrigin, FindingStatus


class FindingService:
    """Service for managing findings and verification workflow."""

    def __init__(self, session: Session):
        self.session = session

    def _generate_finding_id(self, case_id: int) -> str:
        """Generate next finding ID for case (F001, F002, ...)."""
        stmt = select(Finding).where(Finding.case_id == case_id).order_by(Finding.id.desc())
        last = self.session.execute(stmt).scalars().first()
        if last and last.finding_id.startswith("F"):
            try:
                num = int(last.finding_id[1:])
                return f"F{num + 1:03d}"
            except ValueError:
                pass
        return "F001"

    def create_finding(
        self,
        case_id: int,
        title: str,
        description: str,
        created_by: User,
        conclusion: str | None = None,
        origin: FindingOrigin = FindingOrigin.INVESTIGATOR,
        ai_question: str | None = None,
        ai_answer: str | None = None,
        ai_citations: list[dict] | None = None,
        ai_model: str | None = None,
        ai_confidence: float | None = None,
    ) -> Finding:
        """Create a new finding."""
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(created_by, case_id):
            raise PermissionError("Read-only users cannot create findings")
        finding = Finding(
            finding_id=self._generate_finding_id(case_id),
            case_id=case_id,
            title=title,
            description=description,
            conclusion=conclusion,
            status=FindingStatus.DRAFT,
            origin=origin,
            ai_question=ai_question,
            ai_answer=ai_answer,
            ai_citations_json=ai_citations and __import__("json").dumps(ai_citations),
            ai_model=ai_model,
            ai_confidence=ai_confidence,
            created_by_id=created_by.id,
        )
        self.session.add(finding)
        self.session.flush()
        return finding

    def get_finding(self, finding_id: int) -> Finding | None:
        return self.session.get(Finding, finding_id)

    def get_finding_by_finding_id(self, case_id: int, finding_id: str) -> Finding | None:
        stmt = select(Finding).where(Finding.case_id == case_id, Finding.finding_id == finding_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_findings(
        self,
        case_id: int,
        status: FindingStatus | None = None,
        origin: FindingOrigin | None = None,
    ) -> list[Finding]:
        stmt = select(Finding).where(Finding.case_id == case_id)
        if status:
            stmt = stmt.where(Finding.status == status)
        if origin:
            stmt = stmt.where(Finding.origin == origin)
        return list(self.session.execute(stmt.order_by(Finding.created_at.desc())).scalars().all())

    def update_finding(
        self,
        finding_id: int,
        title: str | None = None,
        description: str | None = None,
        conclusion: str | None = None,
        status: FindingStatus | None = None,
        updated_by: User | None = None,
    ) -> Finding | None:
        finding = self.get_finding(finding_id)
        if not finding:
            return None
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(updated_by, finding.case_id):
            raise PermissionError("Read-only users cannot update findings")
        from app.findings.identity import is_identity_hypothesis, validate_identity_hypothesis

        if is_identity_hypothesis(finding):
            if status in (FindingStatus.VERIFIED, FindingStatus.REJECTED):
                raise ValueError(
                    "Use the review operations to verify or reject an identity hypothesis."
                )
            validate_identity_hypothesis(self.session, finding, description)
        changed = (
            (title is not None and title != finding.title)
            or (description is not None and description != finding.description)
            or (conclusion is not None and conclusion != finding.conclusion)
        )
        if changed and finding.status in (FindingStatus.VERIFIED, FindingStatus.REJECTED):
            finding.status = FindingStatus.DRAFT
            finding.verified_by = None
            finding.verified_at = None
            finding.verification_notes = None
        if changed and status == FindingStatus.VERIFIED:
            raise ValueError("Edit and verification must be separate operations.")
        if title is not None:
            finding.title = title
        if description is not None:
            finding.description = description
        if conclusion is not None:
            finding.conclusion = conclusion
        if status is not None:
            finding.status = status
            if status == FindingStatus.VERIFIED:
                finding.verified_at = datetime.now(UTC)
            elif status in (FindingStatus.DRAFT, FindingStatus.UNDER_REVIEW):
                finding.verified_by = None
                finding.verified_by_id = None
                finding.verified_at = None
                finding.verification_notes = None
        self.session.flush()
        return finding

    def verify_finding(
        self, finding_id: int, verified_by: User, notes: str | None = None
    ) -> Finding | None:
        """Mark finding as verified."""
        finding = self.get_finding(finding_id)
        if not finding:
            return None
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(verified_by, finding.case_id):
            raise PermissionError("Read-only users cannot verify findings")
        from app.findings.identity import is_identity_hypothesis, validate_identity_hypothesis

        if is_identity_hypothesis(finding):
            validate_identity_hypothesis(self.session, finding)
        finding.status = FindingStatus.VERIFIED
        finding.verified_by = verified_by
        finding.verified_at = datetime.now(UTC)
        finding.verification_notes = notes
        self.session.flush()
        return finding

    def reject_finding(
        self, finding_id: int, verified_by: User, notes: str | None = None
    ) -> Finding | None:
        """Reject a finding."""
        finding = self.get_finding(finding_id)
        if not finding:
            return None
        from app.findings.identity import is_identity_hypothesis, validate_identity_hypothesis

        if is_identity_hypothesis(finding):
            validate_identity_hypothesis(self.session, finding)
        finding.status = FindingStatus.REJECTED
        finding.verified_by = verified_by
        finding.verified_at = datetime.now(UTC)
        finding.verification_notes = notes
        self.session.flush()
        return finding

    def link_artifact(
        self,
        finding_id: int,
        artifact_id: int,
        relevance: str = "supports",
        notes: str | None = None,
        cited_in_ai: bool = False,
        *,
        _identity_creation: bool = False,
    ) -> FindingArtifactLink:
        """Link an artifact to a finding."""
        from app.evidence.models import Evidence

        finding = self.get_finding(finding_id)
        from app.findings.identity import is_identity_hypothesis

        if finding is not None and is_identity_hypothesis(finding) and not _identity_creation:
            raise ValueError(
                "Identity sources cannot be changed here; create a new hypothesis "
                "with the revised sources."
            )
        artifact = self.session.execute(
            select(Artifact)
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(
                Artifact.id == artifact_id,
                Evidence.removed_at.is_(None),
            )
        ).scalar_one_or_none()
        if finding is None or artifact is None or artifact.case_id != finding.case_id:
            raise ValueError(
                "Artifact must belong to active evidence in the same case as the finding."
            )
        link = FindingArtifactLink(
            finding_id=finding_id,
            artifact_id=artifact_id,
            relevance=relevance,
            notes=notes,
            cited_in_ai=cited_in_ai,
        )
        self.session.add(link)
        self.session.flush()
        return link

    def unlink_artifact(self, finding_id: int, artifact_id: int) -> bool:
        """Remove artifact link from finding."""
        from app.findings.identity import is_identity_hypothesis

        finding = self.get_finding(finding_id)
        if finding is not None and is_identity_hypothesis(finding):
            raise ValueError(
                "Identity sources cannot be changed here; create a new hypothesis "
                "with the revised sources."
            )
        stmt = select(FindingArtifactLink).where(
            FindingArtifactLink.finding_id == finding_id,
            FindingArtifactLink.artifact_id == artifact_id,
        )
        link = self.session.execute(stmt).scalar_one_or_none()
        if link:
            self.session.delete(link)
            self.session.flush()
            return True
        return False

    def get_finding_artifacts(self, finding_id: int) -> list[Artifact]:
        """Get all artifacts linked to a finding."""
        stmt = (
            select(Artifact)
            .join(FindingArtifactLink)
            .where(FindingArtifactLink.finding_id == finding_id)
        )
        return list(self.session.execute(stmt).scalars().all())

    def delete_finding(self, finding_id: int, deleted_by: User) -> bool:
        finding = self.get_finding(finding_id)
        if not finding:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(deleted_by, finding.case_id):
            raise PermissionError("Read-only users cannot delete findings")
        self.session.delete(finding)
        self.session.flush()
        return True

    def get_finding_stats(self, case_id: int) -> dict:
        """Get finding statistics for a case."""
        findings = self.list_findings(case_id)
        return {
            "total": len(findings),
            "draft": sum(1 for f in findings if f.status == FindingStatus.DRAFT),
            "under_review": sum(1 for f in findings if f.status == FindingStatus.UNDER_REVIEW),
            "verified": sum(1 for f in findings if f.status == FindingStatus.VERIFIED),
            "rejected": sum(1 for f in findings if f.status == FindingStatus.REJECTED),
            "ai_suggested": sum(1 for f in findings if f.origin == FindingOrigin.AI_SUGGESTED),
            "investigator": sum(1 for f in findings if f.origin == FindingOrigin.INVESTIGATOR),
        }
