"""Background analysis: entities, timeline events and the relationship graph.

One job covers one evidence item (one examination). The queue is small on
purpose:

* a job is created when an examination completes, and any completed
  examination without one is picked up by :meth:`enqueue_missing`, which is how
  evidence added to an existing case gets analysed without a second click;
* only the regex pass is unconditional, because it is fast and exact;
* model calls are limited to a handful of the largest texts, and can be
  deferred while a scan is running so analysis never competes with the worker.

Everything is written in small committed batches with progress, so the UI can
show what is happening and a cancel stops between artifacts rather than after
the whole case.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.analysis.extractors import (
    content_entities_for_artifact,
    normalize_value,
)
from app.analysis.models import (
    AnalysisJob,
    AnalysisJobStatus,
    EntityRelationship,
    RelationshipStatus,
)
from app.analysis.relationships import RelationshipBuilder, RelationshipSettings
from app.artifacts.models import Artifact, Entity, EntityType, TimelineEvent
from app.auth.models import User
from app.auth.service import AuthService
from app.config import get_config
from app.examination.models import ExaminationJob, JobStatus

logger = logging.getLogger(__name__)

# Jobs cancelled from the UI. The runner is in-process, so a module-level set is
# enough and avoids re-reading the database inside the extraction loop.
_CANCELLED: set[int] = set()

# Commit progress this often, so the queue pane is live without flooding SQLite.
COMMIT_EVERY = 200


class AnalysisCancelled(Exception):
    """Raised inside a run after the investigator cancels the job."""


def _now() -> datetime:
    return datetime.now(UTC)


def _short_id(prefix: str, case_id: int) -> str:
    """A unique, readable identifier.

    A per-case counter cannot be used: re-analysing an artifact deletes and
    recreates its entities, so a counter would either collide with surviving
    rows or require a full table scan to seed. A random suffix is stable across
    that churn and still sorts by case.
    """
    return f"{prefix}-{case_id:04d}-{uuid.uuid4().hex[:10]}"


class AnalysisService:
    def __init__(self, session: Session):
        self.session = session
        self.config = get_config()

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------
    def enqueue_for_examination(
        self,
        case_id: int,
        evidence_id: int,
        examination_job_id: int | None,
        created_by: User,
        *,
        parameters: dict | None = None,
        manual: bool = False,
    ) -> AnalysisJob | None:
        """Create the analysis job for one completed examination."""
        if not self.config.analysis.enabled or (not self.config.analysis.auto_queue and not manual):
            return None

        auth_service = AuthService(self.session)
        if (created_by is None or not created_by.is_active
                or not auth_service.user_can_write_case(created_by, case_id)):
            raise PermissionError("Read-only users cannot perform analysis")

        if examination_job_id is not None:
            existing = self.session.execute(
                select(AnalysisJob).where(
                    AnalysisJob.examination_job_id == examination_job_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing

        job = AnalysisJob(
            job_id=_short_id("ANL", case_id),
            case_id=case_id,
            evidence_id=evidence_id,
            examination_job_id=examination_job_id,
            status=AnalysisJobStatus.PENDING,
            parameters_json=json.dumps(parameters or self._default_parameters()),
        )
        self.session.add(job)
        self.session.flush()
        return job

    def enqueue_missing(
        self, case_id: int, created_by: User | None = None, *, manual: bool = False
    ) -> list[AnalysisJob]:
        """Queue analysis for completed examinations that have none.

        This is what keeps a growing case current: a new evidence item gets a
        new examination job, and the next poll picks it up here.
        """
        if not self.config.analysis.enabled or (not self.config.analysis.auto_queue and not manual):
            return []

        auth_service = AuthService(self.session)
        if (created_by is None or not created_by.is_active
                or not auth_service.user_can_write_case(created_by, case_id)):
            raise PermissionError("Read-only users cannot perform analysis")

        from app.evidence.models import Evidence

        analysed = select(AnalysisJob.examination_job_id).where(
            AnalysisJob.examination_job_id.is_not(None)
        )
        rows = self.session.execute(
            select(ExaminationJob)
            .join(Evidence, ExaminationJob.evidence_id == Evidence.id)
            .where(
                ExaminationJob.case_id == case_id,
                ExaminationJob.status == JobStatus.COMPLETED,
                Evidence.removed_at.is_(None),
                ExaminationJob.id.not_in(analysed),
            )
            .order_by(ExaminationJob.id)
        ).scalars().all()

        created: list[AnalysisJob] = []
        for exam in rows:
            job = self.enqueue_for_examination(
                exam.case_id, exam.evidence_id, exam.id,
                created_by=created_by,
                parameters=self._parameters_from_examination(exam),
                manual=manual,
            )
            if job is not None:
                created.append(job)
        return created

    def _default_parameters(self) -> dict:
        analysis = self.config.analysis
        return {
            "llm_enabled": analysis.llm_enabled,
            "llm_max_artifacts": analysis.llm_max_artifacts,
            "llm_max_chars": analysis.llm_max_chars,
            "build_timeline": analysis.build_timeline,
            "build_relationships": analysis.build_relationships,
            "max_entities_per_artifact": analysis.max_entities_per_artifact,
        }

    def _parameters_from_examination(self, exam: ExaminationJob) -> dict:
        """Analysis inherits the examination's depth, so presets carry over."""
        parameters = self._default_parameters()
        try:
            stored = json.loads(exam.parameters_json or "{}")
        except (TypeError, json.JSONDecodeError):
            stored = {}
        profile = str(stored.get("profile") or "").strip().lower()
        if profile == "fast":
            # A triage run should not spend minutes on model calls.
            parameters["llm_enabled"] = False
        if profile == "deep":
            parameters["max_entities_per_artifact"] = 120
        parameters["profile"] = profile or "balanced"
        return parameters

    def next_pending(self, case_id: int | None = None) -> AnalysisJob | None:
        stmt = select(AnalysisJob).where(AnalysisJob.status == AnalysisJobStatus.PENDING)
        if case_id is not None:
            stmt = stmt.where(AnalysisJob.case_id == case_id)
        return self.session.execute(stmt.order_by(AnalysisJob.id).limit(1)).scalar_one_or_none()

    def list_jobs(self, case_id: int | None = None, limit: int = 50) -> list[AnalysisJob]:
        stmt = select(AnalysisJob)
        if case_id is not None:
            stmt = stmt.where(AnalysisJob.case_id == case_id)
        return list(
            self.session.execute(
                stmt.order_by(AnalysisJob.id.desc()).limit(max(1, limit))
            ).scalars()
        )

    def get_job(self, job_pk: int) -> AnalysisJob | None:
        return self.session.get(AnalysisJob, job_pk)

    def counts(self, case_id: int | None = None) -> dict[str, int]:
        stmt = select(AnalysisJob.status, func.count()).group_by(AnalysisJob.status)
        if case_id is not None:
            stmt = stmt.where(AnalysisJob.case_id == case_id)
        totals = dict.fromkeys(AnalysisJobStatus, 0)
        for status, count in self.session.execute(stmt).all():
            totals[status] = count
        return {status.value: value for status, value in totals.items()}

    def _authorize_job_action(self, job_pk: int, case_id: int, user: User) -> AnalysisJob | None:
        actor = self.session.get(User, user.id) if user is not None and user.id is not None else None
        if actor is not None:
            self.session.refresh(actor)
        if (case_id is None or actor is None or not actor.is_active
                or not AuthService(self.session).user_can_write_case(actor, case_id)):
            raise PermissionError("Case write access required")
        job = self.get_job(job_pk)
        if job is not None and job.case_id != case_id:
            raise PermissionError("Analysis job does not belong to the selected case")
        return job

    def cancel(self, job_pk: int, case_id: int, user: User) -> bool:
        job = self._authorize_job_action(job_pk, case_id, user)
        if job is None:
            return False
        result = self.session.execute(update(AnalysisJob).where(
            AnalysisJob.id == job_pk, AnalysisJob.case_id == case_id,
            AnalysisJob.status == AnalysisJobStatus.PENDING,
        ).values(status=AnalysisJobStatus.CANCELLED, completed_at=_now(),
                 progress_message="Cancelled by investigator"))
        if not result.rowcount:
            result = self.session.execute(update(AnalysisJob).where(
                AnalysisJob.id == job_pk, AnalysisJob.case_id == case_id,
                AnalysisJob.status == AnalysisJobStatus.RUNNING,
            ).values(progress_message="Cancelling…"))
        self.session.commit()
        return bool(result.rowcount)

    def retry(self, job_pk: int, case_id: int, user: User) -> bool:
        job = self._authorize_job_action(job_pk, case_id, user)
        if job is None:
            return False
        if job.status in (AnalysisJobStatus.PENDING, AnalysisJobStatus.RUNNING):
            return False
        _CANCELLED.discard(job_pk)
        job.status = AnalysisJobStatus.PENDING
        job.stage = None
        job.progress_percent = 0
        job.progress_message = "Queued again"
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        self.session.commit()
        return True

    def is_examination_running(self, case_id: int | None = None) -> bool:
        stmt = select(func.count()).select_from(ExaminationJob).where(
            ExaminationJob.status == JobStatus.RUNNING
        )
        if case_id is not None:
            stmt = stmt.where(ExaminationJob.case_id == case_id)
        return bool(self.session.execute(stmt).scalar_one())

    # ------------------------------------------------------------------
    # Running one job
    # ------------------------------------------------------------------
    def _check_cancelled(self, job: AnalysisJob) -> None:
        state = self.session.execute(
            select(AnalysisJob.status, AnalysisJob.progress_message).where(AnalysisJob.id == job.id)
        ).one_or_none()
        if (job.id in _CANCELLED or state is None or state[0] != AnalysisJobStatus.RUNNING
                or state[1] == "Cancelling…"):
            raise AnalysisCancelled("Cancelled by investigator")

    def _progress(self, job: AnalysisJob, percent: int, stage: str, message: str) -> None:
        result = self.session.execute(update(AnalysisJob).where(
            AnalysisJob.id == job.id, AnalysisJob.status == AnalysisJobStatus.RUNNING,
            AnalysisJob.progress_message != "Cancelling…",
        ).values(progress_percent=max(0, min(99, percent)), stage=stage, progress_message=message))
        if not result.rowcount:
            raise AnalysisCancelled("Cancelled by investigator")
        self.session.commit()

    async def run(self, job_pk: int, user: User) -> dict:
        """Analyse one evidence item. Returns a small summary dictionary."""
        job = self.get_job(job_pk)
        if job is None:
            return {"ok": False, "error": "The analysis job no longer exists."}
        if job.status != AnalysisJobStatus.PENDING:
            return {"ok": False, "error": f"Job is {job.status.value}"}

        auth_service = AuthService(self.session)
        if (user is None or not user.is_active
                or not auth_service.user_can_write_case(user, job.case_id)):
            raise PermissionError("Read-only users cannot perform analysis")

        if job_pk in _CANCELLED:
            return {"ok": False, "cancelled": True, "error": "Cancelled by investigator"}
        claimed = self.session.execute(update(AnalysisJob).where(
            AnalysisJob.id == job_pk, AnalysisJob.status == AnalysisJobStatus.PENDING,
        ).values(status=AnalysisJobStatus.RUNNING, started_at=_now(), error_message=None,
                 progress_percent=1, stage="loading", progress_message="Loading artifacts"))
        self.session.commit()
        if not claimed.rowcount:
            return {"ok": False, "cancelled": True, "error": "Job is no longer pending"}
        self.session.refresh(job)

        try:
            parameters = self._job_parameters(job)
            artifacts = list(self.session.execute(
                select(Artifact)
                .where(
                    Artifact.case_id == job.case_id,
                    Artifact.evidence_id == job.evidence_id,
                )
                .order_by(Artifact.id)
            ).scalars().all())
            job.artifact_count = len(artifacts)
            self.session.commit()

            if not artifacts:
                return self._finish(job, entity_count=0, message="No artifacts to analyse")

            entity_count = self._extract_entities(job, artifacts, parameters)
            timeline_count = 0
            if parameters.get("build_timeline", True):
                timeline_count = self._build_timeline(job, artifacts)

            llm_count = 0
            llm_skipped_note = ""
            if parameters.get("llm_enabled", True):
                defer = (
                    self.config.analysis.defer_llm_while_examining
                    and self.is_examination_running(job.case_id)
                )
                if defer:
                    llm_skipped_note = "model extraction skipped while examination runs"
                elif self._cloud_llm_needs_consent(job.case_id):
                    llm_skipped_note = "cloud model NER skipped (case consent required)"
                else:
                    llm_count = await self._extract_with_llm(job, artifacts, parameters)
            job.llm_count = llm_count

            if parameters.get("build_relationships", True):
                self._build_relationships(job)

            summary = (
                f"{entity_count:,} entities, {timeline_count:,} timeline events"
                + (f", {llm_count:,} model entities" if llm_count else "")
                + (f"; {llm_skipped_note}" if llm_skipped_note else "")
            )
            return self._finish(job, entity_count=entity_count, message=summary)

        except AnalysisCancelled:
            self.session.rollback()
            job = self.get_job(job_pk)
            job.status = AnalysisJobStatus.CANCELLED
            job.stage = "cancelled"
            job.completed_at = _now()
            job.progress_message = "Cancelled by investigator"
            self.session.commit()
            return {"ok": False, "cancelled": True, "error": "Cancelled by investigator"}
        except Exception as exc:  # noqa: BLE001 - the queue must survive anything
            logger.exception("Analysis job %s failed", job.job_id)
            self.session.rollback()
            job = self.get_job(job_pk)
            if job is not None:
                if job.progress_message == "Cancelling…" or job_pk in _CANCELLED:
                    job.status = AnalysisJobStatus.CANCELLED
                    job.stage = "cancelled"
                    job.progress_message = "Cancelled by investigator"
                    job.completed_at = _now()
                    self.session.commit()
                    return {"ok": False, "cancelled": True, "error": "Cancelled by investigator"}
                job.status = AnalysisJobStatus.FAILED
                job.stage = "failed"
                job.error_message = str(exc) or exc.__class__.__name__
                job.progress_message = "Analysis failed"
                job.completed_at = _now()
                self.session.commit()
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}
        finally:
            _CANCELLED.discard(job_pk)

    def _cloud_llm_needs_consent(self, case_id: int) -> bool:
        """Whether configured cloud NER is blocked for this case."""
        from app.config import cloud_api_key

        if self.config.ollama.provider != "openai" or not cloud_api_key(self.config):
            return False
        from app.auth.models import Case

        case = self.session.get(Case, case_id)
        return not bool(case and case.cloud_ai_consent_at)

    def _job_parameters(self, job: AnalysisJob) -> dict:
        parameters = self._default_parameters()
        try:
            stored = json.loads(job.parameters_json or "{}")
        except (TypeError, json.JSONDecodeError):
            stored = {}
        if isinstance(stored, dict):
            parameters.update(stored)
        return parameters

    def _finish(self, job: AnalysisJob, *, entity_count: int, message: str) -> dict:
        self._check_cancelled(job)
        result = self.session.execute(update(AnalysisJob).where(
            AnalysisJob.id == job.id, AnalysisJob.status == AnalysisJobStatus.RUNNING,
            AnalysisJob.progress_message != "Cancelling…",
        ).values(status=AnalysisJobStatus.COMPLETED, stage="done", progress_percent=100,
                 entity_count=entity_count, progress_message=message, completed_at=_now()))
        if not result.rowcount:
            raise AnalysisCancelled("Cancelled by investigator")
        self.session.commit()
        return {"ok": True, "entities": entity_count, "message": message}

    # ------------------------------------------------------------------
    # Step 1: deterministic entities
    # ------------------------------------------------------------------
    def _extract_entities(
        self, job: AnalysisJob, artifacts: list[Artifact], parameters: dict
    ) -> int:
        limit = int(parameters.get("max_entities_per_artifact") or 60)
        total = len(artifacts)
        written = 0

        # Re-analysis replaces the previous result for these artifacts, so a
        # re-examination cannot leave stale entities behind.
        self._check_cancelled(job)
        artifact_ids = [artifact.id for artifact in artifacts]
        for start in range(0, len(artifact_ids), 500):
            batch = artifact_ids[start:start + 500]
            self.session.execute(delete(Entity).where(Entity.artifact_id.in_(batch)))
        self.session.commit()

        for index, artifact in enumerate(artifacts, start=1):
            self._check_cancelled(job)
            for entity in content_entities_for_artifact(artifact)[:limit]:
                written += self._add_entity(job, artifact, entity)
            if index % COMMIT_EVERY == 0 or index == total:
                self.session.commit()
                percent = 5 + int(45 * index / max(1, total))
                self._progress(
                    job, percent, "entities",
                    f"Entities: {written:,} from {index:,}/{total:,} artifacts",
                )
        self.session.commit()
        return written

    def _add_entity(self, job: AnalysisJob, artifact: Artifact, entity) -> int:
        """Insert one entity, ignoring one already recorded for this artifact."""
        offsets_from_content = entity.metadata.get("field") in (None, "content_text")
        snippet = (
            entity.metadata.get("snippet") or entity.metadata.get("quote") or ""
        )[:1000]
        row = Entity(
            entity_id=_short_id("ENT", job.case_id),
            case_id=job.case_id,
            artifact_id=artifact.id,
            entity_type=entity.entity_type,
            value=entity.value,
            normalized_value=entity.normalized or normalize_value(
                entity.entity_type, entity.value
            ),
            start_offset=entity.start if offsets_from_content and entity.start >= 0 else None,
            end_offset=entity.end if offsets_from_content and entity.end >= 0 else None,
            context_snippet=snippet or None,
            confidence=float(entity.confidence),
            extractor=entity.extractor,
        )
        self.session.add(row)
        return 1

    # ------------------------------------------------------------------
    # Step 2: timeline
    # ------------------------------------------------------------------
    def _build_timeline(self, job: AnalysisJob, artifacts: list[Artifact]) -> int:
        self.session.execute(
            delete(TimelineEvent).where(
                TimelineEvent.artifact_id.in_([artifact.id for artifact in artifacts]),
                TimelineEvent.source == "artifact",
            )
        )
        self.session.commit()

        written = 0
        total = len(artifacts)
        for index, artifact in enumerate(artifacts, start=1):
            self._check_cancelled(job)
            for event_type, label, timestamp in (
                ("file_created", "Created", artifact.created_time),
                ("file_modified", "Modified", artifact.modified_time),
                ("file_accessed", "Accessed", artifact.accessed_time),
            ):
                if timestamp is None:
                    continue
                self.session.add(
                    TimelineEvent(
                        event_id=_short_id("EVT", job.case_id),
                        case_id=job.case_id,
                        artifact_id=artifact.id,
                        timestamp=timestamp,
                        timestamp_utc=timestamp,
                        timezone="UTC" if timestamp.tzinfo else None,
                        certainty="high",
                        event_type=event_type,
                        title=f"{label}: {artifact.name}"[:256],
                        description=artifact.source_path,
                        source="artifact",
                        metadata_json=json.dumps({
                            "artifact_id": getattr(artifact, "artifact_id", None),
                            "evidence_id": artifact.evidence_id,
                        }),
                    )
                )
                written += 1
            if index % COMMIT_EVERY == 0 or index == total:
                self.session.commit()
                percent = 50 + int(20 * index / max(1, total))
                self._progress(
                    job, percent, "timeline",
                    f"Timeline: {written:,} events",
                )
        self.session.commit()
        return written

    # ------------------------------------------------------------------
    # Step 3: model-assisted names
    # ------------------------------------------------------------------
    async def _extract_with_llm(
        self, job: AnalysisJob, artifacts: list[Artifact], parameters: dict
    ) -> int:
        from app.analysis.llm import AnalysisLLM

        llm = AnalysisLLM(self.config)
        if not llm.available():
            return 0

        max_chars = max(500, int(parameters.get("llm_max_chars") or 6000))

        candidates = [
            artifact for artifact in artifacts
            if (artifact.content_text or "").strip()
        ]
        # Every retained text is material; do not silently prioritize large
        # files or truncate the case to a configured artifact count.
        candidates.sort(key=lambda item: item.id)

        written = 0
        failures = 0
        for index, artifact in enumerate(candidates, start=1):
            self._check_cancelled(job)
            result = await llm.extract_named_entities(
                artifact.content_text or "", max_chars=max_chars
            )
            self._check_cancelled(job)
            if result.error:
                failures += 1
                if failures == 1:
                    self._progress(
                        job, 72, "names",
                        f"Model extraction unavailable: {result.error}"[:500],
                    )
                # Earlier windows may already contain source-verified leads.
                # Persist those even when a later request fails.

            existing = {
                (entity.entity_type.value, (entity.normalized_value or "").lower())
                for entity in self.session.execute(
                    select(Entity).where(Entity.artifact_id == artifact.id)
                ).scalars()
            }
            for entity in result.entities:
                if (entity.entity_type.value, entity.normalized) in existing:
                    continue
                self._add_entity(job, artifact, entity)
                written += 1
            self.session.commit()
            if result.error and failures >= 3:
                break
            percent = 70 + int(20 * index / max(1, len(candidates)))
            self._progress(
                job, percent, "names",
                f"Names: {written} model entities from {index}/{len(candidates)} documents",
            )

        self.session.commit()
        return written

    # ------------------------------------------------------------------
    # Step 4: relationship graph
    # ------------------------------------------------------------------
    def _build_relationships(self, job: AnalysisJob) -> None:
        self._check_cancelled(job)
        self._progress(job, 92, "relationships", "Linking shared entities")
        analysis = self.config.analysis
        stats = RelationshipBuilder(
            self.session,
            job.case_id,
            RelationshipSettings(
                hub_fraction=analysis.hub_fraction,
                hub_min_artifacts=analysis.hub_min_artifacts,
                max_entities_per_artifact=analysis.max_entities_per_artifact,
                max_shared_artifacts_listed=analysis.max_relationship_artifacts,
            ),
        ).rebuild(job_id=job.id)
        self._check_cancelled(job)
        job.relationship_count = stats.created + stats.updated
        self.session.commit()

    # ------------------------------------------------------------------
    # Reviewer decisions
    # ------------------------------------------------------------------
    def review_relationship(
        self,
        relationship_id: int,
        status: RelationshipStatus,
        user_id: int | None,
    ) -> bool:
        row = self.session.get(EntityRelationship, relationship_id)
        if row is None:
            return False
        if not isinstance(status, RelationshipStatus):
            status = RelationshipStatus(status)
        row.status = status
        row.reviewed_by_id = user_id
        row.reviewed_at = _now()
        self.session.commit()
        return True

    def list_relationships(
        self,
        case_id: int,
        *,
        status: RelationshipStatus | None = None,
        kind: str | None = None,
        min_score: float = 0.0,
        limit: int = 500,
    ) -> list[EntityRelationship]:
        stmt = select(EntityRelationship).where(
            EntityRelationship.case_id == case_id,
            self._active_relationship_condition(case_id),
        )
        if status is not None:
            stmt = stmt.where(EntityRelationship.status == status)
        if kind:
            stmt = stmt.where(EntityRelationship.kind == kind)
        if min_score:
            stmt = stmt.where(EntityRelationship.score >= min_score)
        return list(
            self.session.execute(
                stmt.order_by(EntityRelationship.score.desc(), EntityRelationship.id)
                .limit(max(1, limit))
            ).scalars()
        )

    def relationship_counts(self, case_id: int) -> dict[str, int]:
        rows = self.session.execute(
            select(EntityRelationship.status, func.count())
            .where(
                EntityRelationship.case_id == case_id,
                self._active_relationship_condition(case_id),
            )
            .group_by(EntityRelationship.status)
        ).all()
        totals = {status.value: 0 for status in RelationshipStatus}
        for status, count in rows:
            totals[status] = count
        return totals

    @staticmethod
    def _active_relationship_condition(case_id: int):
        """Hide links supported by evidence removed from the active case."""
        from sqlalchemy import case, exists

        from app.evidence.models import Evidence

        ids = func.json_each(case(
            (func.json_valid(EntityRelationship.evidence_ids_json) == 1,
             EntityRelationship.evidence_ids_json),
            else_="[]",
        )).table_valued("value")
        removed = select(Evidence.id).where(
            Evidence.case_id == case_id, Evidence.removed_at.is_not(None)
        )
        details = case(
            (func.json_valid(EntityRelationship.details_json) == 1,
             EntityRelationship.details_json),
            else_="{}",
        )
        return (
            ~exists(select(1).select_from(ids).where(ids.c.value.in_(removed)).correlate(EntityRelationship))
            & (func.coalesce(func.json_extract(details, "$.unsupported_after_rebuild"), 0) != 1)
        )

    def list_entities(
        self,
        case_id: int,
        *,
        entity_type: EntityType | None = None,
        query: str | None = None,
        limit: int = 500,
    ) -> list[Entity]:
        from app.evidence.models import Evidence

        stmt = (
            select(Entity)
            .join(Artifact, Entity.artifact_id == Artifact.id)
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(Entity.case_id == case_id, Evidence.removed_at.is_(None))
        )
        if entity_type is not None:
            stmt = stmt.where(Entity.entity_type == entity_type)
        if query:
            like = f"%{query.strip()}%"
            stmt = stmt.where(Entity.value.ilike(like))
        return list(
            self.session.execute(
                stmt.order_by(Entity.entity_type, Entity.value).limit(max(1, limit))
            ).scalars()
        )

    def entity_type_counts(self, case_id: int) -> dict[str, int]:
        from app.evidence.models import Evidence

        rows = self.session.execute(
            select(Entity.entity_type, func.count())
            .join(Artifact, Entity.artifact_id == Artifact.id)
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(Entity.case_id == case_id, Evidence.removed_at.is_(None))
            .group_by(Entity.entity_type)
        ).all()
        totals: dict[str, int] = {}
        for entity_type, count in rows:
            key = getattr(entity_type, "value", str(entity_type))
            totals[key] = count
        return totals

    def list_timeline(
        self,
        case_id: int,
        *,
        event_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[TimelineEvent]:
        from sqlalchemy import or_

        from app.evidence.models import Evidence

        stmt = (
            select(TimelineEvent)
            .options(selectinload(TimelineEvent.artifact))
            .outerjoin(Artifact, TimelineEvent.artifact_id == Artifact.id)
            .outerjoin(Evidence, Artifact.evidence_id == Evidence.id)
            .where(
                TimelineEvent.case_id == case_id,
                or_(TimelineEvent.artifact_id.is_(None), Evidence.removed_at.is_(None)),
            )
        )
        if event_type:
            stmt = stmt.where(TimelineEvent.event_type == event_type)
        if since:
            stmt = stmt.where(TimelineEvent.timestamp >= since)
        if until:
            stmt = stmt.where(TimelineEvent.timestamp <= until)
        return list(
            self.session.execute(
                stmt.order_by(TimelineEvent.timestamp.desc()).limit(max(1, limit))
            ).scalars()
        )
