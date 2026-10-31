"""Relationship graph built from extracted entities and content hashes.

Two artifacts are related when they share a rare entity (an e-mail address, a
phone number, a person's name) or when they hold identical bytes. Nothing is
asserted without support: every edge stores the artifact ids that prove it, so
the UI can show the evidence next to the claim.

The graph is rebuilt from the entities each run rather than incremented, which
is what keeps it correct when an artifact is re-examined or removed. A reviewer's
confirm/reject decision is preserved across rebuilds.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult, Row
from sqlalchemy.orm import Session

from app.analysis.models import (
    EntityRelationship,
    RelationshipKind,
    RelationshipStatus,
)
from app.artifacts.models import Artifact, Entity, EntityType

# Entity kinds that are strong enough to justify an edge on a single shared
# artifact. A path that appears twice is a coincidence; an e-mail address is not.
STRONG_TYPES = {
    EntityType.EMAIL,
    EntityType.PHONE,
    EntityType.CRYPTO_ADDRESS,
    EntityType.HASH,
    EntityType.MAC_ADDRESS,
    EntityType.PERSON,
    EntityType.DEVICE_ID,
}

# Kinds that are recorded as entities but never used to link artifacts. A file
# path is the artifact's own location and a timestamp is its own moment, so
# pairing them with its content says nothing about any other artifact.
PAIRING_EXCLUDED_TYPES = {
    EntityType.FILE_PATH,
    EntityType.TIMESTAMP,
}

# Values that connect almost everything in a case (a system path, a shared
# domain). They are skipped because their co-occurrence says nothing.
GENERIC_VALUES = {
    "c:\\windows", "c:\\windows\\system32", "c:\\program files",
    "c:\\users", "/etc", "/usr", "/var", "/tmp", "/home",
}

# Role mailboxes are often copied into unrelated documents. This deliberately
# small exact-match list avoids guessing from domains or substrings (e.g.
# help.person@example.org). Such an address can still corroborate another link.
GENERIC_EMAIL_LOCAL_PARTS = {"help", "helpdesk", "help-desk", "support"}


def _generic_role_mailbox(key: tuple[str, str]) -> bool:
    if key[0] != EntityType.EMAIL.value:
        return False
    local, separator, domain = key[1].partition("@")
    return bool(separator and domain and local in GENERIC_EMAIL_LOCAL_PARTS)


def _label_key(label: str) -> tuple[str, str]:
    kind, value = label.split("\u0000", 1)
    return kind, value


@dataclass
class RelationshipSettings:
    """Bounds for one rebuild, exposed so the UI can explain the result."""

    # An edge normally needs two artifacts to prove it: one artifact sharing an
    # entity with itself is not a relationship.
    min_shared: int = 2
    max_shared_artifacts_listed: int = 40
    hub_fraction: float = 0.5
    hub_min_artifacts: int = 8
    max_entities_per_artifact: int = 60
    max_relationship_artifacts: int = 40
    # Artifacts sharing one value are paired up to this group size, so a value
    # present in hundreds of files does not produce a quadratic number of edges.
    max_group_for_artifact_links: int = 12
    build_duplicates: bool = True


@dataclass
class RelationshipStats:
    entities: int = 0
    artifact_links: int = 0
    created: int = 0
    updated: int = 0
    removed: int = 0
    kept_reviewed: int = 0
    duplicates: int = 0
    skipped_hubs: int = 0


def _key(entity: Entity) -> tuple[str, str]:
    normalized = _relationship_value(
        entity.entity_type.value, entity.normalized_value or entity.value or ""
    )
    return (entity.entity_type.value, normalized)


def _relationship_value(entity_type: str, value: str) -> str:
    """Preserve case-sensitive crypto identifiers; normalize other graph keys."""
    value = value.strip()
    if entity_type == EntityType.CRYPTO_ADDRESS.value and not value.startswith("0x"):
        return value
    return value.lower()


def _pair_key(
    kind: RelationshipKind, left: tuple[str, str], right: tuple[str, str]
) -> tuple[str, str, str, str, str]:
    """Order the two sides so an edge is the same edge whichever way it is seen."""
    left, right = sorted((left, right))
    return (kind.value, left[0], left[1], right[0], right[1])


class RelationshipBuilder:
    def __init__(
        self,
        session: Session,
        case_id: int,
        settings: RelationshipSettings | None = None,
    ):
        self.session = session
        self.case_id = case_id
        self.settings = settings or RelationshipSettings()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def rebuild(self, job_id: int | None = None) -> RelationshipStats:
        stats = RelationshipStats()

        entity_pairs, artifact_pairs = self._collect_pairs(stats)
        pairs: dict[tuple, dict] = {**entity_pairs, **artifact_pairs}
        if self.settings.build_duplicates:
            duplicates = self._collect_duplicates()
            stats.duplicates = len(duplicates)
            pairs.update(duplicates)

        existing = {
            _pair_key(
                row.kind,
                (row.left_type, _relationship_value(row.left_type, row.left_value)),
                (row.right_type, _relationship_value(row.right_type, row.right_value)),
            ): row
            for row in self.session.execute(
                select(EntityRelationship).where(
                    EntityRelationship.case_id == self.case_id
                )
            ).scalars()
        }

        wanted: set[tuple] = set()
        for key, payload in pairs.items():
            wanted.add(key)
            row = existing.get(key)
            if row is None:
                row = EntityRelationship(
                    case_id=self.case_id,
                    kind=payload["kind"],
                    left_type=payload["left"][0],
                    left_value=payload["left"][1],
                    right_type=payload["right"][0],
                    right_value=payload["right"][1],
                    status=RelationshipStatus.PENDING,
                )
                self.session.add(row)
                stats.created += 1
            else:
                stats.updated += 1
            row.score = payload["score"]
            row.shared_count = payload["shared_count"]
            row.artifact_ids_json = json.dumps(payload["artifact_ids"])
            row.evidence_ids_json = json.dumps(payload["evidence_ids"])
            row.details_json = json.dumps(payload.get("details") or {})
            row.built_by_job_id = job_id

        # Drop edges that no longer have support, but never erase a decision the
        # investigator made: a reviewed row stays so the record of that review
        # survives a re-examination.
        for key, row in existing.items():
            if key in wanted:
                continue
            if row.status != RelationshipStatus.PENDING:
                # Preserve the decision and its original provenance for audit,
                # but do not present an unsupported historical edge as a lead.
                try:
                    details = json.loads(row.details_json or "{}")
                except (TypeError, ValueError):
                    details = {}
                if not isinstance(details, dict):
                    details = {}
                details["unsupported_after_rebuild"] = True
                row.details_json = json.dumps(details)
                stats.kept_reviewed += 1
                continue
            self.session.delete(row)
            stats.removed += 1

        self.session.flush()
        return stats

    # ------------------------------------------------------------------
    # Entity co-occurrence
    # ------------------------------------------------------------------
    def _collect_pairs(
        self, stats: RelationshipStats
    ) -> tuple[dict[tuple, dict], dict[tuple, dict]]:
        rows = list(
            self.session.execute(
                select(Entity)
                .where(Entity.case_id == self.case_id)
                .order_by(Entity.artifact_id, Entity.id)
            ).scalars()
        )
        stats.entities = len(rows)
        if not rows:
            return {}, {}

        # entity key -> set of artifact ids, and artifact -> its entity keys.
        per_entity: dict[tuple[str, str], set[int]] = {}
        per_artifact: dict[int, list[tuple[str, str]]] = {}

        for entity in rows:
            key = _key(entity)
            if not key[1] or key[1] in GENERIC_VALUES:
                continue
            if entity.entity_type in PAIRING_EXCLUDED_TYPES:
                continue
            per_entity.setdefault(key, set()).add(entity.artifact_id)
            bucket = per_artifact.setdefault(entity.artifact_id, [])
            if key not in bucket:
                bucket.append(key)

        stats.artifact_links = sum(len(value) for value in per_artifact.values())
        artifact_total = max(1, len(per_artifact))

        # A value present in most of the case is a hub: it links everything to
        # everything, which hides the specific links that matter.
        hub_limit = max(
            self.settings.hub_min_artifacts,
            int(artifact_total * self.settings.hub_fraction),
        )
        hubs = {key for key, ids in per_entity.items() if len(ids) > hub_limit}
        stats.skipped_hubs = len(hubs)

        pair_artifacts: dict[tuple[str, str, str, str, str], set[int]] = {}
        for artifact_id, keys in per_artifact.items():
            usable = [
                key for key in keys[: self.settings.max_entities_per_artifact]
                if key not in hubs
            ]
            for left, right in combinations(usable, 2):
                pair_artifacts.setdefault(
                    _pair_key(RelationshipKind.SHARED_ENTITY, left, right), set()
                ).add(artifact_id)

        # A sample must be drawn from a supporting artifact's current text,
        # never an arbitrary cached snippet for the same value in another file.
        texts = dict(self.session.execute(
            select(Artifact.id, Artifact.content_text).where(
                Artifact.case_id == self.case_id,
                Artifact.id.in_(per_artifact),
            )
        ).all()) if per_artifact else {}
        samples: dict[tuple[int, tuple[str, str]], str] = {}
        for entity in rows:
            text = texts.get(entity.artifact_id) or ""
            start, end = entity.start_offset, entity.end_offset
            key = (entity.artifact_id, _key(entity))
            if (key not in samples and isinstance(start, int) and isinstance(end, int)
                    and 0 <= start < end <= len(text) and text[start:end] == entity.value):
                samples[key] = text[max(0, start - 100):min(len(text), end + 100)]

        pairs: dict[tuple, dict] = {}
        for pair_key, artifact_ids in pair_artifacts.items():
            _, left_type, left_value, right_type, right_value = pair_key
            left = (left_type, left_value)
            right = (right_type, right_value)
            shared = len(artifact_ids)
            left_count = len(per_entity.get(left, ()))
            right_count = len(per_entity.get(right, ()))
            # One shared artifact is only enough when *both* sides are strong
            # identifiers: "this address and this phone number appeared in the
            # same file" is a finding, "this address and this path" is not.
            left_strong = EntityType(left_type) in STRONG_TYPES
            right_strong = EntityType(right_type) in STRONG_TYPES
            if shared < self.settings.min_shared and not (
                shared == 1 and left_strong and right_strong
            ):
                continue

            # Overlap coefficient: how much of the rarer side is explained by
            # the other. It stays high for a pair mentioned only together.
            denominator = max(1, min(left_count, right_count))
            score = round(shared / denominator, 4)
            if shared == 1:
                # A single co-occurrence must not outrank a pair seen in ten
                # artifacts.
                score = min(score, 0.5)
            if left_count >= 3 and right_count >= 3 and score < 0.34:
                continue

            listed = sorted(artifact_ids)[: self.settings.max_shared_artifacts_listed]
            sample = next((samples[(ident, left)] for ident in sorted(artifact_ids)
                           if (ident, left) in samples), "")
            pairs[pair_key] = {
                "kind": RelationshipKind.SHARED_ENTITY,
                "left": left,
                "right": right,
                "score": score,
                "shared_count": shared,
                "artifact_ids": listed,
                "evidence_ids": self._evidence_ids(listed),
                "details": {
                    "left_artifacts": left_count,
                    "right_artifacts": right_count,
                    "coverage": score,
                    "sample": sample[:200],
                },
            }

        artifact_pairs = self._collect_artifact_links(per_entity, per_artifact, hubs, rows)
        return pairs, artifact_pairs

    def _collect_artifact_links(
        self,
        per_entity: dict[tuple[str, str], set[int]],
        per_artifact: dict[int, list[tuple[str, str]]],
        hubs: set[tuple[str, str]],
        entities: list[Entity],
    ) -> dict[tuple, dict]:
        """Artifact ↔ artifact edges for artifacts that mention the same value.

        Two files can share a single e-mail address and nothing else; that is the
        most common useful finding in a case and it has no entity *pair* to
        describe it. These edges name the artifacts and list the shared values.

        Large groups are paired only up to a cap: a value in fifty files would
        otherwise produce 1,225 edges that say the same thing.
        """
        artifact_sets = {
            artifact_id: {key for key in keys if key not in hubs}
            for artifact_id, keys in per_artifact.items()
        }

        shared: dict[tuple[int, int], set[str]] = {}
        for key, artifact_ids in per_entity.items():
            if key in hubs:
                continue
            labelled = f"{key[0]}\u0000{key[1]}"
            group = sorted(artifact_ids)[: self.settings.max_group_for_artifact_links]
            for left_id, right_id in combinations(group, 2):
                shared.setdefault((left_id, right_id), set()).add(labelled)

        index = self._artifact_index()
        # Excerpts must come from the current artifact text, not a cached model
        # snippet. Invalid or stale offsets are omitted rather than guessed.
        candidate_ids = {ident for pair in shared for ident in pair}
        texts = dict(self.session.execute(
            select(Artifact.id, Artifact.content_text).where(
                Artifact.case_id == self.case_id, Artifact.id.in_(candidate_ids)
            )
        ).all()) if candidate_ids else {}
        excerpts: dict[tuple[int, tuple[str, str]], str] = {}
        for entity in entities:
            text = texts.get(entity.artifact_id) or ""
            start, end = entity.start_offset, entity.end_offset
            key = (entity.artifact_id, _key(entity))
            if (key not in excerpts and isinstance(start, int) and isinstance(end, int)
                    and 0 <= start < end <= len(text) and text[start:end] == entity.value):
                excerpts[key] = text[max(0, start - 100):min(len(text), end + 100)]
        pairs: dict[tuple, dict] = {}
        for (left_id, right_id), labels in shared.items():
            # A shared help desk alone is weak evidence of a meaningful link;
            # keep it in details when an independent identifier also matches.
            if all(_generic_role_mailbox(_label_key(label)) for label in labels):
                continue
            left_row = index.get(left_id)
            right_row = index.get(right_id)
            if left_row is None or right_row is None:
                continue
            union = artifact_sets.get(left_id, set()) | artifact_sets.get(right_id, set())
            score = round(len(labels) / max(1, len(union)), 4)
            # The key sorts the two sides; store them in that same order, or the
            # next rebuild would look for the row under the other arrangement
            # and insert a duplicate that violates the unique constraint.
            sides = sorted([
                ("artifact", str(left_row.artifact_id).lower()),
                ("artifact", str(right_row.artifact_id).lower()),
            ])
            left, right = sides
            row_for = {
                ("artifact", str(left_row.artifact_id).lower()): left_row,
                ("artifact", str(right_row.artifact_id).lower()): right_row,
            }
            pair_key = _pair_key(RelationshipKind.RELATED_ARTIFACTS, left, right)
            pairs[pair_key] = {
                "kind": RelationshipKind.RELATED_ARTIFACTS,
                "left": left,
                "right": right,
                "score": score,
                "shared_count": len(labels),
                "artifact_ids": [row_for[left].id, row_for[right].id],
                "evidence_ids": sorted({
                    int(value) for value in (left_row.evidence_id, right_row.evidence_id)
                    if value is not None
                }),
                "details": {
                    "left_name": row_for[left].name,
                    "right_name": row_for[right].name,
                    "left_path": row_for[left].source_path,
                    "right_path": row_for[right].source_path,
                    "shared": [
                        {
                            "type": label.split("\u0000", 1)[0],
                            "value": label.split("\u0000", 1)[1],
                            "case_artifact_count": len(per_entity[_label_key(label)]),
                            "excerpts": [
                                {"artifact_id": ident, "text": excerpts[(ident, _label_key(label))]}
                                for ident in (row_for[left].id, row_for[right].id)
                                if (ident, _label_key(label)) in excerpts
                            ],
                        }
                        for label in sorted(labels)
                    ][:25],
                },
            }
        return pairs

    def _artifact_index(self) -> dict[int, Row[int, str, str, str | None, int]]:
        rows = self.session.execute(
            select(Artifact.id, Artifact.artifact_id, Artifact.name,
                   Artifact.source_path, Artifact.evidence_id)
            .where(Artifact.case_id == self.case_id)
        ).all()
        return {row.id: row for row in rows}

    def _evidence_ids(self, artifact_ids: list[int]) -> list[int]:
        if not artifact_ids:
            return []
        rows = self.session.execute(
            select(Artifact.evidence_id).where(Artifact.id.in_(artifact_ids))
        ).scalars().all()
        return sorted({int(value) for value in rows if value is not None})

    # ------------------------------------------------------------------
    # Duplicate content
    # ------------------------------------------------------------------
    def _collect_duplicates(self) -> dict[tuple, dict]:
        """One edge per extra copy, all pointing at the group's first artifact."""
        rows = self.session.execute(
            select(
                Artifact.id,
                Artifact.artifact_id,
                Artifact.content_hash,
                Artifact.source_path,
                Artifact.evidence_id,
            )
            .where(
                Artifact.case_id == self.case_id,
                Artifact.content_hash.is_not(None),
                Artifact.content_hash != "",
            )
            .order_by(Artifact.id)
        ).all()

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(str(row.content_hash).lower(), []).append(row)

        pairs: dict[tuple, dict] = {}
        for content_hash, group in groups.items():
            if len(group) < 2:
                continue
            representative = group[0]
            for duplicate in group[1:]:
                left, right = sorted([
                    ("artifact", str(representative.artifact_id).lower()),
                    ("artifact", str(duplicate.artifact_id).lower()),
                ])
                key = _pair_key(RelationshipKind.DUPLICATE_CONTENT, left, right)
                cap = self.settings.max_shared_artifacts_listed
                # Each edge must include both endpoints even when the group is
                # larger than the provenance display limit.
                artifact_ids = [representative.id, duplicate.id]
                artifact_ids.extend(
                    item.id for item in group
                    if item.id not in (representative.id, duplicate.id)
                )
                artifact_ids = artifact_ids[:max(2, cap)]
                pairs[key] = {
                    "kind": RelationshipKind.DUPLICATE_CONTENT,
                    "left": left,
                    "right": right,
                    "score": 1.0,
                    "shared_count": len(group),
                    "artifact_ids": artifact_ids,
                    "evidence_ids": sorted({
                        int(item.evidence_id) for item in group if item.evidence_id
                    }),
                    "details": {
                        "content_hash": content_hash,
                        "paths": [
                            item.source_path for item in group[:20] if item.source_path
                        ],
                    },
                }
        return pairs

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def clear_generated(self) -> int:
        """Delete every still-unreviewed edge for the case."""
        result = self.session.execute(
            delete(EntityRelationship).where(
                EntityRelationship.case_id == self.case_id,
                EntityRelationship.status == RelationshipStatus.PENDING,
            )
        )
        return int(cast(CursorResult[Any], result).rowcount or 0)
