"""Deterministic, unverified briefing data; not an end-to-end AI feature.

Callers supply a case-scoped snapshot. No database, configuration, network or
model is consulted. Exact quotations prove only that text occurs in that snapshot,
not that its contents are true. Free-form claims are deliberately unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LinkKind = Literal["shared_entity", "related_artifacts", "duplicate_content"]
_LINK_KINDS = frozenset({"shared_entity", "related_artifacts", "duplicate_content"})


class UnsupportedClaimError(ValueError):
    """A claim or link cannot be grounded in the supplied case snapshot."""


@dataclass(frozen=True)
class ArtifactExcerpt:
    case_id: int
    artifact_id: int
    text: str


@dataclass(frozen=True)
class Citation:
    artifact_id: int
    quote: str


@dataclass(frozen=True)
class BriefingClaim:
    """A quoted observation, never a paraphrase or investigator conclusion."""

    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class GraphLink:
    """An injected relationship, not a relationship inferred by this helper.

    Citations must cover both artifact endpoints. They ground the endpoints only;
    neither co-occurrence nor matching excerpts establish causation or byte-level
    identity. No arbitrary graph labels are promoted into narrative claims.
    """

    case_id: int
    source_artifact_id: int
    target_artifact_id: int
    kind: LinkKind
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class CaseBriefing:
    case_id: int
    observations: tuple[BriefingClaim, ...]
    graph_links: tuple[GraphLink, ...]
    limitations: tuple[str, ...]
    unverified: bool = True
    status: str = "UNVERIFIED — investigator review required"


def _citation_key(citation: Citation) -> tuple[int, str]:
    return citation.artifact_id, citation.quote


def validate_citation(
    citation: Citation, *, case_id: int, excerpts: tuple[ArtifactExcerpt, ...]
) -> None:
    """Require a nonblank, literal, case-sensitive quote from the named artifact.

    An artifact from another case cannot satisfy a citation, even when its text
    matches. Quotes are never trimmed, normalised, or matched across excerpts.
    """
    if not citation.quote.strip():
        raise UnsupportedClaimError("A citation must contain a nonblank exact quote")
    if not any(
        excerpt.case_id == case_id
        and excerpt.artifact_id == citation.artifact_id
        and citation.quote in excerpt.text
        for excerpt in excerpts
    ):
        raise UnsupportedClaimError(
            f"Citation is outside the supplied case/artifact scope or not exact: "
            f"artifact {citation.artifact_id}"
        )


def assemble_case_briefing(
    case_id: int,
    excerpts: tuple[ArtifactExcerpt, ...],
    graph_links: tuple[GraphLink, ...] = (),
    *,
    claims: tuple[BriefingClaim, ...] | None = None,
) -> CaseBriefing:
    """Build stable, immutable briefing data or refuse unsupported input.

    With no explicit claims, each nonblank excerpt becomes a quoted observation.
    Explicit claims may select shorter exact quotations, but arbitrary narrative
    is rejected even if it has a valid citation: occurrence is not entailment.
    Empty ``claims`` deliberately selects no observations. Excerpts may contain
    multiple chunks of an artifact; no quote can bridge chunk boundaries.
    Cross-case input is rejected rather than silently filtered.
    """
    snapshot = tuple(excerpts)
    if any(excerpt.case_id != case_id for excerpt in snapshot):
        raise UnsupportedClaimError("All excerpts must belong to the requested case")

    def checked(citations: tuple[Citation, ...]) -> tuple[Citation, ...]:
        result = tuple(sorted(set(citations), key=_citation_key))
        if not result:
            raise UnsupportedClaimError("Supporting citations are required")
        for citation in result:
            validate_citation(citation, case_id=case_id, excerpts=snapshot)
        return result

    selected = claims if claims is not None else tuple(
        BriefingClaim(excerpt.text, (Citation(excerpt.artifact_id, excerpt.text),))
        for excerpt in snapshot
        if excerpt.text.strip()
    )
    observations = set()
    for claim in selected:
        citations = checked(claim.citations)
        if any(claim.text != citation.quote for citation in citations):
            raise UnsupportedClaimError("Only verbatim quoted observations are supported")
        observations.add(BriefingClaim(claim.text, citations))

    links = set()
    for link in graph_links:
        if link.case_id != case_id:
            raise UnsupportedClaimError("Graph link belongs to another case")
        if link.kind not in _LINK_KINDS:
            raise UnsupportedClaimError("Unsupported graph relationship kind")
        if link.source_artifact_id == link.target_artifact_id:
            raise UnsupportedClaimError("Graph links must connect distinct artifacts")
        citations = checked(link.citations)
        endpoints = {link.source_artifact_id, link.target_artifact_id}
        if {citation.artifact_id for citation in citations} != endpoints:
            raise UnsupportedClaimError("Graph citations must cover exactly both endpoints")
        links.add(GraphLink(
            link.case_id, link.source_artifact_id, link.target_artifact_id,
            link.kind, citations,
        ))

    limitations = [
        "UNVERIFIED: investigator review is required; quoted source text may be false.",
        "Limited to injected excerpts and graph links, not a complete case examination.",
        "Citations validate exact text and case/artifact scope, not authenticity or truth.",
        "Graph links are supplied, not independently verified; they do not establish "
        "causation, intent, identity, or byte-level duplication.",
        "No model requests, live database access, or end-to-end AI analysis performed.",
    ]
    if not observations:
        limitations.append("No supported quoted observations were supplied.")
    if not links:
        limitations.append("No supported graph links were supplied.")
    return CaseBriefing(
        case_id=case_id,
        observations=tuple(sorted(
            observations,
            key=lambda claim: (claim.text, tuple(map(_citation_key, claim.citations))),
        )),
        graph_links=tuple(sorted(
            links,
            key=lambda link: (
                link.source_artifact_id, link.target_artifact_id, link.kind,
                tuple(map(_citation_key, link.citations)),
            ),
        )),
        limitations=tuple(limitations),
    )
