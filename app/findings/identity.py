"""Investigator-authored identity hypotheses, stored as ordinary findings.

Literal excerpts demonstrate provenance, not that an interpretation is true.
This module never infers identity from a relationship or an identifier.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.models import EntityRelationship
from app.artifacts.models import Artifact
from app.auth.models import User
from app.evidence.models import Evidence
from app.findings.models import Finding, FindingArtifactLink, FindingStatus
from app.findings.service import FindingService


def _has_line_break(value: str) -> bool:
    """Reject all Unicode line boundaries in evidence-controlled headers."""
    return any(char in value for char in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


def _has_source_header(value: str) -> bool:
    """An excerpt must not visually impersonate another linked source."""
    return any(
        line.startswith(("[supports] ", "[contradicts] ", "[contextual] "))
        for line in value.splitlines()[1:]
    )


def _has_interpretation_header(value: str) -> bool:
    """Evidence must not visually impersonate an investigator interpretation."""
    return any(line.startswith("Interpretation: ") for line in value.splitlines()[1:])


@dataclass(frozen=True)
class IdentitySource:
    artifact_id: int
    quote: str
    relevance: str  # supports, contradicts, or contextual
    explanation: str


def is_identity_hypothesis(finding: Finding) -> bool:
    return (finding.description or "").startswith(
        "Identity hypothesis (unverified):\n"
    ) or finding.title == "Identity hypothesis (unverified)"


def invalidate_reviewed_sources(
    session: Session,
    *,
    evidence_id: int | None = None,
    artifact_id: int | None = None,
    user: User | None = None,
) -> None:
    """Invalidate reviews in the same transaction as a source change."""
    if (evidence_id is None) == (artifact_id is None):
        raise ValueError("Specify exactly one evidence or artifact source.")
    query = (
        select(Finding)
        .join(FindingArtifactLink)
        .join(Artifact)
        .where(Finding.status.in_((FindingStatus.VERIFIED, FindingStatus.REJECTED)))
    )
    query = (
        query.where(Artifact.evidence_id == evidence_id)
        if evidence_id is not None
        else query.where(Artifact.id == artifact_id)
    )
    from app.audit.service import AuditService

    for finding in session.scalars(query.distinct()).all():
        if not is_identity_hypothesis(finding):
            continue
        reason = (
            "linked evidence was removed"
            if evidence_id is not None
            else "linked extracted text changed"
        )
        details = {
            "reason": reason,
            "evidence_id": evidence_id,
            "artifact_id": artifact_id,
            "previous_status": finding.status.value,
            "previous_reviewer_id": finding.verified_by_id,
            "previous_reviewed_at": finding.verified_at.isoformat()
            if finding.verified_at
            else None,
            "previous_review_notes": finding.verification_notes,
        }
        finding.status = FindingStatus.DRAFT
        finding.verified_by = None
        finding.verified_by_id = None
        finding.verified_at = None
        finding.verification_notes = (
            f"Review needed: {reason}. Previous review is recorded in the audit trail."
        )
        AuditService(session).log_event(
            event_type="finding",
            action="invalidate_review",
            result="success",
            user=user,
            case_id=finding.case_id,
            target_type="finding",
            target_id=finding.id,
            details=details,
        )


def validate_identity_hypothesis(
    session: Session, finding: Finding, description: str | None = None
) -> None:
    """Validate the existing human-authored record without interpreting its claims."""
    text = finding.description if description is None else description
    try:
        heading, rest = text.split("\n\nAlternative explanations:\n", 1)
        alternatives, sources_text = rest.split(
            "\n\nSource excerpts and investigator interpretations:\n", 1
        )
    except ValueError as exc:
        raise ValueError(
            "Identity hypothesis must retain its hypothesis, alternatives and source sections."
        ) from exc
    if (
        not heading.startswith("Identity hypothesis (unverified):\n")
        or not heading.split("\n", 1)[1].strip()
    ):
        raise ValueError("An identity hypothesis is required.")
    # Optional graph context follows the alternatives, separated by a blank line.
    alternatives = alternatives.split("\n\nRelated graph entry:", 1)[0]
    if not any(line.startswith("- ") and line[2:].strip() for line in alternatives.splitlines()):
        raise ValueError("At least one alternative explanation is required.")
    from app.findings.models import FindingArtifactLink

    links = session.scalars(
        select(FindingArtifactLink)
        .where(FindingArtifactLink.finding_id == finding.id)
        .order_by(FindingArtifactLink.id)
    ).all()
    if not links or not any(link.relevance == "supports" for link in links):
        raise ValueError("At least one supporting source is required.")
    blocks = []
    for link in links:
        artifact = session.scalar(
            select(Artifact)
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(
                Artifact.id == link.artifact_id,
                Artifact.case_id == finding.case_id,
                Evidence.case_id == finding.case_id,
                Evidence.removed_at.is_(None),
            )
        )
        notes = link.notes or ""
        if (
            link.relevance not in {"supports", "contradicts", "contextual"}
            or not notes.startswith("Excerpt: ")
            or "\nInterpretation: " not in notes
        ):
            raise ValueError("Each identity source needs a relevance, excerpt and interpretation.")
        quote, explanation = notes[len("Excerpt: ") :].split("\nInterpretation: ", 1)
        if _has_interpretation_header(quote):
            raise ValueError("Source excerpt contains a reserved interpretation separator.")
        if _has_source_header(quote):
            raise ValueError("Source excerpt contains a reserved source header.")
        if (
            artifact is None
            or not quote.strip()
            or not explanation.strip()
            or quote not in (artifact.content_text or "")
        ):
            raise ValueError("Source must be active, in this case, and contain the exact excerpt.")
        if any(_has_line_break(value) for value in (artifact.artifact_id, artifact.name)):
            raise ValueError("Source artifact identifier and name must not contain line breaks.")
        blocks.append(f"[{link.relevance}] {artifact.artifact_id}: {artifact.name}\n{notes}")
    if sources_text != "\n".join(blocks):
        raise ValueError(
            "Identity source claims must match the linked artifacts and their excerpts."
        )


def create_identity_hypothesis(
    session: Session,
    case_id: int,
    created_by: User,
    hypothesis: str,
    alternatives: list[str],
    sources: list[IdentitySource],
    relationship_id: int | None = None,
) -> Finding:
    """Create a draft for human review; caller controls transaction boundaries.

    Sources must be active same-case artifacts and quotes must occur literally in
    extracted text. Alternatives and relevance are investigator interpretations.
    A relationship is optional context, not evidence of a person's identity.
    """
    hypothesis = hypothesis.strip()
    alternatives = [value.strip() for value in alternatives if value.strip()]
    if not hypothesis or not alternatives:
        raise ValueError("A hypothesis and at least one alternative explanation are required.")
    # These delimiters are used to parse the persisted description during review.
    # Accepting them in free text would create a draft that can never be reviewed.
    if "\n\nAlternative explanations:\n" in hypothesis or any(
        "\n\nSource excerpts and investigator interpretations:\n" in value
        for value in [hypothesis, *alternatives]
    ) or any("\n\nRelated graph entry:" in value for value in alternatives):
        raise ValueError("Hypothesis or alternatives contain a reserved section heading.")
    if not sources or not any(source.relevance == "supports" for source in sources):
        raise ValueError("At least one supporting source is required.")
    if len({source.artifact_id for source in sources}) != len(sources):
        raise ValueError("Use one source entry per artifact.")
    relationship = None
    if relationship_id is not None:
        relationship = session.get(EntityRelationship, relationship_id)
        if relationship is None or relationship.case_id != case_id:
            raise ValueError("Relationship must belong to the same case.")

    artifacts = {}
    for source in sources:
        if source.relevance not in {"supports", "contradicts", "contextual"}:
            raise ValueError("Invalid source relevance.")
        if not source.quote.strip() or not source.explanation.strip():
            raise ValueError("Each source needs a literal excerpt and explanation.")
        if _has_interpretation_header(source.quote):
            raise ValueError(
                "Source excerpt contains a reserved interpretation separator; "
                "select a shorter excerpt."
            )
        if _has_source_header(source.quote):
            raise ValueError(
                "Source excerpt contains a reserved source header; select a shorter excerpt."
            )
        artifact = session.execute(
            select(Artifact)
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(
                Artifact.id == source.artifact_id,
                Artifact.case_id == case_id,
                Evidence.case_id == case_id,
                Evidence.removed_at.is_(None),
            )
        ).scalar_one_or_none()
        if artifact is None or source.quote not in (artifact.content_text or ""):
            raise ValueError("Source must be active, in this case, and contain the exact excerpt.")
        # These fields are interpolated into the human-readable source header.
        # Evidence-controlled newlines could impersonate an excerpt or an
        # investigator's interpretation in that record.
        if any(_has_line_break(value) for value in (artifact.artifact_id, artifact.name)):
            raise ValueError("Source artifact identifier and name must not contain line breaks.")
        artifacts[source.artifact_id] = artifact

    lines = ["Identity hypothesis (unverified):", hypothesis, "", "Alternative explanations:"]
    lines.extend(f"- {value}" for value in alternatives)
    if relationship is not None:
        lines.extend(
            [
                "",
                f"Related graph entry: #{relationship.id} ({relationship.kind.value}); "
                "co-occurrence is not proof of identity.",
            ]
        )
    lines.extend(["", "Source excerpts and investigator interpretations:"])
    for source in sources:
        artifact = artifacts[source.artifact_id]
        lines.extend(
            [
                f"[{source.relevance}] {artifact.artifact_id}: {artifact.name}",
                f"Excerpt: {source.quote}",
                f"Interpretation: {source.explanation}",
            ]
        )
    service = FindingService(session)
    finding = service.create_finding(
        case_id, "Identity hypothesis (unverified)", "\n".join(lines), created_by
    )
    for source in sources:
        service.link_artifact(
            finding.id,
            source.artifact_id,
            source.relevance,
            notes=f"Excerpt: {source.quote}\nInterpretation: {source.explanation}",
            actor=created_by,
            _identity_creation=True,
        )
    return finding
