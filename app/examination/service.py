"""Examination service for job management and worker communication."""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.config import get_config
from app.evidence.models import Evidence, EvidenceStatus
from app.examination.models import (
    ExaminationJob,
    ExaminationOperation,
    ExaminationResult,
    JobStatus,
)
from app.examination.profiles import validate_parameters


class ExaminationCancelled(Exception):  # noqa: N818 - retain the existing exception API
    """The worker stopped a scan because the investigator cancelled it."""


def extraction_coverage(rows: list[dict]) -> dict[str, int]:
    """Summarize worker-reported coverage without treating missing text as success."""
    counts = {
        "total": 0,
        "text": 0,
        "deleted": 0,
        "read_errors": 0,
        "partial": 0,
        "unsupported_or_no_text": 0,
        "no_text": 0,
    }
    for row in rows:
        counts["total"] += 1
        if row.get("deleted"):
            counts["deleted"] += 1
        elif row.get("extraction_status") == "partial":
            counts["partial"] += 1
        elif row.get("read_error") or row.get("extraction_status") == "error":
            counts["read_errors"] += 1
        elif row.get("extraction_status") == "unsupported_or_no_text":
            counts["unsupported_or_no_text"] += 1
        elif row.get("content_text"):
            counts["text"] += 1
        else:
            counts["no_text"] += 1
    return counts


class ExaminationService:
    """Service for managing examination jobs and communicating with the forensic worker."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_config()
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.worker.timeout_seconds)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _generate_job_id(self) -> str:
        return f"JOB-{uuid.uuid4().hex[:12].upper()}"

    def create_job(
        self,
        case_id: int,
        evidence_id: int,
        operation: ExaminationOperation,
        parameters: dict | None = None,
        created_by: User | None = None,
    ) -> ExaminationJob:
        evidence = self.session.get(Evidence, evidence_id)
        if not evidence or evidence.case_id != case_id:
            raise ValueError("Evidence not found or does not belong to case")
        if evidence.status == EvidenceStatus.ARCHIVED:
            raise ValueError(
                "Archived evidence must be restored before creating an examination job"
            )
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(created_by, case_id):
            raise PermissionError("Read-only users cannot create examination jobs")

        # Qt hands str-based enums back as plain strings, so coerce here rather
        # than storing a string in an enum column.
        if not isinstance(operation, ExaminationOperation):
            try:
                operation = ExaminationOperation(operation)
            except ValueError as exc:
                raise ValueError(f"Unknown examination operation: {operation}") from exc

        # Every job stores the parameters it will actually run with, so the run
        # can be read back and reproduced. Old callers that pass a partial dict
        # get the Balanced defaults for the rest.
        parameters = validate_parameters(parameters)

        job = ExaminationJob(
            job_id=self._generate_job_id(),
            case_id=case_id,
            evidence_id=evidence_id,
            operation=operation,
            parameters_json=json.dumps(parameters),
            status=JobStatus.PENDING,
            created_by_id=created_by.id if created_by else 1,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: int) -> ExaminationJob | None:
        return self.session.get(ExaminationJob, job_id)

    def get_job_by_job_id(self, job_id: str) -> ExaminationJob | None:
        stmt = select(ExaminationJob).where(ExaminationJob.job_id == job_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_jobs(self, case_id: int, evidence_id: int | None = None) -> list[ExaminationJob]:
        stmt = select(ExaminationJob).where(ExaminationJob.case_id == case_id)
        if evidence_id:
            stmt = stmt.where(ExaminationJob.evidence_id == evidence_id)
        return list(
            self.session.execute(stmt.order_by(ExaminationJob.created_at.desc())).scalars().all()
        )

    def mark_interrupted_jobs(self) -> int:
        """Mark jobs left running by a previous session as interrupted.

        Nothing keeps running after the GUI exits, so a job whose status is
        still ``RUNNING`` at startup belongs to a process that is gone. Leaving
        it as running would block retries and keep the progress bar frozen
        forever. The job is not failed: the investigator can start it again.
        """
        stmt = select(ExaminationJob).where(ExaminationJob.status == JobStatus.RUNNING)
        jobs = list(self.session.execute(stmt).scalars().all())
        if not jobs:
            return 0

        now = datetime.now(UTC)
        for job in jobs:
            job.status = JobStatus.INTERRUPTED
            job.progress_message = (
                "IDFA closed while this job was running. Start it again to retry."
            )
            job.completed_at = now
        self.session.flush()
        return len(jobs)

    async def start_job(self, job_id: int) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False

        if job.status not in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.INTERRUPTED):
            return False

        evidence = self.session.get(Evidence, job.evidence_id)
        if not evidence:
            return False
        if evidence.status == EvidenceStatus.ARCHIVED:
            job.status = JobStatus.FAILED
            job.error_message = "Archived evidence must be restored before examination"
            job.progress_message = job.error_message
            job.completed_at = datetime.now(UTC)
            self.session.commit()
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        created_by = self.session.get(User, job.created_by_id)
        if not auth_service.user_can_write_case(created_by, job.case_id):
            raise PermissionError("Read-only users cannot start examinations")

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.completed_at = None
        job.progress_percent = 0
        job.progress_message = "Starting examination..."
        # A retried job must not keep the previous failure's message.
        job.error_message = None

        # A job created by an older build may hold a partial or invalid
        # parameter dictionary. Run it with defaults instead of refusing.
        try:
            parameters = validate_parameters(
                json.loads(job.parameters_json) if job.parameters_json else {}
            )
        except (ValueError, json.JSONDecodeError):
            parameters = validate_parameters({})
        self.session.flush()
        from app.audit.service import AuditService

        AuditService(self.session).log_examination_start(
            job.created_by, job.case_id, job.id
        )
        # Recovery must see RUNNING even if the GUI exits before the worker
        # publishes its first batch or progress update.
        self.session.commit()

        request_task = None
        try:
            # For old records that registered only .002/.003 as a fragment,
            # use the original source set when a complete adjacent sequence is
            # available; newly registered evidence stores the full sequence.
            image_path = evidence.stored_path or evidence.source_path
            try:
                from pathlib import Path

                from app.evidence.service import EvidenceService
                original_parts = EvidenceService._split_image_parts(Path(evidence.source_path))
                if len(original_parts) > 1:
                    try:
                        stored_parts = EvidenceService._split_image_parts(Path(image_path))
                    except (FileNotFoundError, OSError):
                        stored_parts = []
                    if len(stored_parts) != len(original_parts):
                        image_path = str(original_parts[0])
            except (FileNotFoundError, OSError):
                pass
            payload = {
                "case_id": job.case_id,
                "evidence_id": job.evidence_id,
                "job_id": job.job_id,
                "image_path": image_path,
                "operation": job.operation.value,
                "parameters": {**parameters, "progressive_ingestion": True},
            }

            timeout_seconds = float(
                parameters.get("timeout_seconds")
                or self.config.worker.timeout_seconds
            )
            request_task = asyncio.create_task(self.client.post(
                f"{self.config.worker.url}/examine",
                json=payload,
                timeout=timeout_seconds,
            ))
            progress_url = f"{self.config.worker.url}/examine/{job.job_id}/progress"
            batch_url = f"{self.config.worker.url}/examine/{job.job_id}/batch"
            created = 0
            updated = 0
            coverage = extraction_coverage([])
            last_batch = 0
            while not request_task.done():
                await asyncio.sleep(0.75)
                try:
                    batch_response = await self.client.get(batch_url, timeout=3.0)
                    batch = batch_response.json() if batch_response.status_code == 200 else {}
                except Exception:
                    batch = {}
                if batch and batch.get("sequence", 0) > last_batch:
                    try:
                        rows = batch.get("artifacts", [])
                        stats = await self._create_artifact_records(
                            job.case_id, job.evidence_id, job.id,
                            {"artifacts": rows,
                             "partition_offset": batch.get("partition_offset", 0)},
                            parameters,
                            commit_interval=False,
                        )
                        created += stats["created"]
                        updated += stats["updated"]
                        for key, count in extraction_coverage(rows).items():
                            coverage[key] += count
                        self.session.commit()
                        last_batch = batch["sequence"]
                    except Exception:
                        request_task.cancel()
                        with suppress(Exception):
                            await self.client.post(
                                f"{self.config.worker.url}/examine/{job.job_id}/cancel", timeout=3.0
                            )
                        with suppress(asyncio.CancelledError):
                            await request_task
                        raise
                if batch and batch.get("sequence") == last_batch:
                    with suppress(Exception):
                        await self.client.post(f"{batch_url}/{last_batch}/ack", timeout=3.0)
                try:
                    progress_response = await self.client.get(progress_url, timeout=3.0)
                    progress = (
                        progress_response.json() if progress_response.status_code == 200 else {}
                    )
                    new_percent = max(
                        job.progress_percent, min(99, int(progress.get("progress", 0)))
                    )
                except Exception:
                    # Older worker versions do not expose progress polling;
                    # the examination request remains valid without it.
                    progress = {}
                if progress and progress.get("status") not in ("failed", "completed"):
                    progress_status = progress.get("status")
                    if progress_status == "paused":
                        new_message = "Paused — waiting to resume"
                    elif progress_status == "pausing":
                        new_message = "Pausing — finishing current step"
                    else:
                        new_message = progress.get("message") or "Examining evidence"
                    # Persistence errors must abort the scan, not be mistaken
                    # for an unavailable optional progress endpoint.
                    if new_percent != job.progress_percent or new_message != job.progress_message:
                        job.progress_percent = new_percent
                        job.progress_message = new_message
                        self.session.commit()
            response = await request_task

            if response.status_code != 200:
                raise Exception(f"Worker error: {response.status_code} - {response.text}")

            result = response.json()
            if not result.get("success", True):
                error_text = (
                    result.get("error")
                    or result.get("message")
                    or "Worker reported failure"
                )
                if "cancel" in error_text.lower():
                    raise ExaminationCancelled(error_text)
                raise Exception(error_text)

            for res in result.get("results", []):
                exam_result = ExaminationResult(
                    job_id=job.id,
                    result_type=res.get("type", "unknown"),
                    content_json=json.dumps(res.get("data", {})),
                    summary=res.get("summary"),
                    artifact_count=res.get("artifact_count", 0),
                )
                self.session.add(exam_result)

                # Both operations carry artifact rows: ``full_examination``
                # reports "artifacts", ``file_traversal`` reports "file_list".
                # Only the first used to be ingested, so a traversal job left
                # nothing to search.
                if res.get("type") in ("artifacts", "file_list"):
                    data = res.get("data", {})
                    partition_coverage = extraction_coverage(
                        data.get("artifacts") or data.get("files") or []
                    )
                    for key, count in partition_coverage.items():
                        coverage[key] += count
                    def import_progress(processed: int, total: int) -> None:
                        job.progress_percent = max(
                            job.progress_percent,
                            min(99, 90 + (processed * 9 // max(1, total))),
                        )
                        job.progress_message = f"Saving artifacts {processed:,}/{total:,}"
                        self.session.commit()

                    stats = await self._create_artifact_records(
                        job.case_id,
                        job.evidence_id,
                        job.id,
                        data,
                        parameters,
                        progress_callback=import_progress,
                    )
                    created += stats["created"]
                    updated += stats["updated"]

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.progress_percent = 100
            if created or updated:
                job.progress_message = (
                    f"Examination completed — {created:,} new, "
                    f"{updated:,} updated artifacts; "
                    f"{coverage['text']:,} with text, {coverage['no_text']:,} without text, "
                    f"{coverage['unsupported_or_no_text']:,} unsupported or no text, "
                    f"{coverage['deleted']:,} deleted metadata-only, "
                    f"{coverage['read_errors']:,} read errors, "
                    f"{coverage['partial']:,} partial extractions"
                )
            else:
                job.progress_message = "Examination completed — no artifacts found"

            partition_warnings = sum(
                res.get("type") == "partition_warning"
                for res in result.get("results", [])
            )
            if partition_warnings:
                job.progress_message += (
                    f"; incomplete coverage: {partition_warnings} partition(s) not examined"
                )

            evidence.status = EvidenceStatus.EXAMINED  # type: ignore[assignment]
            AuditService(self.session).log_examination_complete(
                job.created_by, job.case_id, job.id, success=True
            )
            # Queue the background analysis here rather than in the UI, so a
            # job started from the evidence page is analysed too. It only adds
            # a row; the runner does the work.
            try:
                from app.analysis.service import AnalysisService

                analysis_service = AnalysisService(self.session)
                analysis_service.enqueue_for_examination(
                    job.case_id,
                    job.evidence_id,
                    job.id,
                    created_by=job.created_by,
                    parameters=analysis_service._parameters_from_examination(job),
                )
            except Exception:  # noqa: BLE001 - analysis must not fail an examination
                import logging

                logging.getLogger(__name__).warning(
                    "Could not queue analysis for job %s", job.job_id, exc_info=True
                )
            self.session.commit()

            return True

        except asyncio.CancelledError:
            # Cancelling the client coroutine does not stop the separate worker
            # process. Ask it to stop before allowing a retry of this job ID.
            if request_task is not None:
                request_task.cancel()
                with suppress(Exception):
                    await self.client.post(
                        f"{self.config.worker.url}/examine/{job.job_id}/cancel", timeout=3.0
                    )
                with suppress(asyncio.CancelledError, Exception):
                    await request_task
            self.session.rollback()
            job.status = JobStatus.INTERRUPTED
            job.completed_at = datetime.now(UTC)
            job.progress_message = "Examination interrupted. Start it again to retry."
            self.session.commit()
            raise

        except ExaminationCancelled:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(UTC)
            job.progress_percent = 0
            job.error_message = None
            job.progress_message = "Cancelled by investigator"
            try:
                AuditService(self.session).log_examination_complete(
                    job.created_by, job.case_id, job.id, success=False,
                    error="Cancelled by investigator",
                )
                self.session.commit()
            except Exception:
                self.session.rollback()
            return False

        except Exception as e:
            # A client timeout or transport failure does not imply the worker
            # stopped scanning (or waiting for an acknowledgement).
            if request_task is not None:
                request_task.cancel()
                with suppress(Exception):
                    await self.client.post(
                        f"{self.config.worker.url}/examine/{job.job_id}/cancel", timeout=3.0
                    )
                with suppress(asyncio.CancelledError, Exception):
                    await request_task
            # A failed flush leaves SQLAlchemy's transaction unusable. Keep
            # previously committed import batches, then persist the failure.
            self.session.rollback()
            message = self._describe_worker_error(e)
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.progress_percent = 0
            job.error_message = message
            job.progress_message = f"Failed: {message}"
            evidence.status = EvidenceStatus.EXAMINATION_FAILED  # type: ignore[assignment]
            try:
                AuditService(self.session).log_examination_complete(
                    job.created_by, job.case_id, job.id, success=False, error=message
                )
                self.session.commit()
            except Exception:
                self.session.rollback()
            return False

    def _describe_worker_error(self, exc: Exception) -> str:
        """Turn transport errors into something an investigator can act on."""
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return (
                f"Cannot reach the forensic worker at {self.config.worker.url}. "
                "Start it with START_IDFA.bat, or from a terminal with "
                "\".venv\\Scripts\\python.exe worker\\main.py\"."
            )
        if isinstance(exc, httpx.TimeoutException):
            return (
                f"The worker did not respond within "
                f"{self.config.worker.timeout_seconds} seconds."
            )
        return str(exc) or exc.__class__.__name__

    async def _create_artifact_records(
        self,
        case_id: int,
        evidence_id: int,
        exam_job_id: int,
        data: dict,
        parameters: dict | None = None,
        progress_callback=None,
        commit_interval: bool = True,
    ) -> dict[str, int]:
        """Ingest worker artifact rows, updating rows a re-run already created.

        Every re-examination used to insert a second copy of every file, so the
        artifact list and every search result doubled. A row is now matched by
        its source path inside the evidence and updated in place; only paths
        that were not there before get a new artifact id.
        """
        from sqlalchemy import delete

        from app.artifacts.models import (
            Artifact,
            ArtifactChunk,
            ArtifactType,
            Entity,
            IndexStatus,
        )

        artifacts_data = data.get("artifacts") or data.get("files") or []
        partition_offset = data.get("partition_offset", 0)
        next_number = self._next_artifact_number(case_id)
        stats = {"created": 0, "updated": 0}

        # Only materialize paths present in this worker batch. SQLite builds
        # may limit bind parameters to 999, including the evidence id.
        # Ignore malformed items here so their errors still occur at their
        # original position in the import loop (and retain committed batches).
        paths = list(dict.fromkeys(
            item.get("path") for item in artifacts_data
            if isinstance(item, dict) and isinstance(item.get("path"), str)
            and item.get("path")
        ))
        by_path = {}
        # With pending ORM changes, the old scan could see an identity-mapped
        # row whose in-memory path differs from its database value (especially
        # when autoflush is disabled). Keep that behavior in this rare case.
        # SQLite may contain non-string values (for example BLOB paths).
        # The original Python dictionary lookup matched those without coercion.
        non_string_path = any(
            isinstance(item, dict) and item.get("path") is not None
            and not isinstance(item.get("path"), str)
            for item in artifacts_data
        )
        # Multiple targeted queries could observe different database snapshots.
        # Large batches retain the original single evidence-wide scan instead.
        if self.session.new or self.session.dirty or non_string_path or len(paths) > 900:
            existing_rows = self.session.execute(
                select(Artifact).where(Artifact.evidence_id == evidence_id)
            ).scalars()
            by_path.update((row.source_path, row) for row in existing_rows if row.source_path)
        else:
            # Execute even for an empty path list, retaining query/autoflush
            # behavior of the original scan.
            existing_rows = self.session.execute(
                select(Artifact).where(
                    Artifact.evidence_id == evidence_id,
                    Artifact.source_path.in_(paths),
                ).order_by(Artifact.id)
            ).scalars()
            # The original evidence scan retained the last row for duplicate
            # paths. Preserve that behavior rather than assuming uniqueness.
            by_path.update((row.source_path, row) for row in existing_rows)

        total_artifacts = len(artifacts_data)
        for item_number, art_data in enumerate(artifacts_data, start=1):
            try:
                # Map artifact type
                artifact_type_str = art_data.get("artifact_type", "file")
                try:
                    artifact_type = ArtifactType(artifact_type_str)
                except ValueError:
                    artifact_type = ArtifactType.FILE

                # Parse timestamps
                def parse_ts(ts):
                    if ts is None:
                        return None
                    try:
                        return datetime.fromtimestamp(ts, tz=UTC)
                    except Exception:
                        return None

                values = {
                    "artifact_type": artifact_type,
                    "name": art_data.get("name") or "unknown",
                    "description": (
                        f"{'Deleted' if art_data.get('deleted') else 'Allocated'} file"
                    ),
                    "source_path": art_data.get("path"),
                    "source_offset": art_data.get("inode"),
                    "source_size": art_data.get("size"),
                    "content_text": art_data.get("content_text"),
                    "content_hash": art_data.get("content_hash"),
                    "mime_type": art_data.get("mime_type"),
                    "extension": art_data.get("extension"),
                    "created_time": parse_ts(art_data.get("crtime")),
                    "modified_time": parse_ts(art_data.get("mtime")),
                    "accessed_time": parse_ts(art_data.get("atime")),
                    "metadata_json": json.dumps({
                        "inode": art_data.get("inode"),
                        "allocated": art_data.get("allocated"),
                        "deleted": art_data.get("deleted"),
                        "fs_type": art_data.get("type"),
                        "partition_offset": partition_offset,
                        "content_truncated": art_data.get("content_truncated"),
                        "read_error": art_data.get("read_error"),
                        "extraction_status": art_data.get("extraction_status", "legacy_unknown"),
                    }),
                }

                path = art_data.get("path")
                previous = by_path.get(path)
                if previous is not None:
                    text_changed = previous.content_text != values["content_text"]
                    content_changed = (previous.content_hash or None) != (
                        art_data.get("content_hash") or None
                    ) or (previous.content_text or None) != (values["content_text"] or None)
                    for field, value in values.items():
                        setattr(previous, field, value)
                    previous.examination_job_id = exam_job_id
                    if text_changed:
                        from app.findings.identity import invalidate_reviewed_sources
                        invalidate_reviewed_sources(self.session, artifact_id=previous.id)
                    if content_changed:
                        # Entities and vectors describe the old bytes; drop
                        # them so the analysis and index rebuild for the new
                        # content instead of mixing the two.
                        self.session.execute(
                            delete(Entity).where(Entity.artifact_id == previous.id)
                        )
                        self.session.execute(
                            delete(ArtifactChunk).where(
                                ArtifactChunk.artifact_id == previous.id
                            )
                        )
                        previous.index_status = IndexStatus.NOT_INDEXED
                        previous.vector_id = None
                        previous.indexed_at = None
                        self.session.flush()
                        self._persist_text_chunks(
                            previous, values["content_text"], case_id,
                            self.config.embeddings.chunk_size,
                        )
                    stats["updated"] += 1
                else:
                    # The counter is advanced here rather than re-queried: the
                    # session does not autoflush, so a query would not see the
                    # rows added earlier in this batch and every artifact would
                    # get the same id.
                    artifact_id = f"ART-{case_id:04d}-{next_number:04d}"
                    next_number += 1
                    artifact = Artifact(
                        artifact_id=artifact_id,
                        case_id=case_id,
                        evidence_id=evidence_id,
                        examination_job_id=exam_job_id,
                        index_status=IndexStatus.NOT_INDEXED,
                        **values,
                    )
                    self.session.add(artifact)
                    self.session.flush()
                    self._persist_text_chunks(
                        artifact, values["content_text"], case_id,
                        self.config.embeddings.chunk_size,
                    )
                    by_path[path] = artifact
                    stats["created"] += 1

            except Exception as e:
                # Never silently claim complete coverage after an import error.
                # Earlier committed batches remain available for review.
                self.session.rollback()
                path = art_data.get("path", "unknown") if isinstance(art_data, dict) else "unknown"
                raise RuntimeError(
                    f"Artifact import failed at item {item_number}/{total_artifacts} "
                    f"({path}); earlier committed batches were retained: {e}"
                ) from e

            if commit_interval and (item_number % 200 == 0 or item_number == total_artifacts):
                self.session.commit()
            if progress_callback and (item_number % 100 == 0 or item_number == total_artifacts):
                progress_callback(item_number, total_artifacts)

        return stats

    @staticmethod
    def _persist_text_chunks(
        artifact, text: str | None, case_id: int, chunk_size: int = 20_000
    ) -> None:
        """Persist extraction passages immediately, independently of indexing.

        Chunk size is a storage boundary only; concatenating the rows reproduces
        the complete extracted text with exact character offsets.
        """
        if not text:
            return
        from app.artifacts.models import ArtifactChunk

        chunk_size = max(1, chunk_size)
        for index, start in enumerate(range(0, len(text), chunk_size)):
            passage = text[start : start + chunk_size]
            artifact.chunks.append(ArtifactChunk(
                case_id=case_id,
                chunk_index=index,
                char_start=start,
                char_end=start + len(passage),
                text=passage,
            ))

    def _next_artifact_number(self, case_id: int) -> int:
        """Return the next free sequence number for a case's artifact ids."""
        from sqlalchemy import select

        from app.artifacts.models import Artifact

        stmt = (
            select(Artifact)
            .where(Artifact.case_id == case_id)
            .order_by(Artifact.id.desc())
        )
        last = self.session.execute(stmt).scalars().first()
        if last is None:
            return 1
        try:
            return int(last.artifact_id.rsplit("-", 1)[-1]) + 1
        except (AttributeError, ValueError):
            return last.id + 1

    def cancel_job(self, job_id: int) -> bool:
        """Cancel a pending job, or ask the worker to stop a running scan."""
        job = self.get_job(job_id)
        if not job:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        created_by = self.session.get(User, job.created_by_id)
        if not auth_service.user_can_write_case(created_by, job.case_id):
            raise PermissionError("Read-only users cannot cancel examinations")

        if job.status == JobStatus.PENDING:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(UTC)
            job.progress_message = "Cancelled by investigator"
            self.session.commit()
            return True

        if job.status == JobStatus.RUNNING:
            try:
                response = httpx.post(
                    f"{self.config.worker.url}/examine/{job.job_id}/cancel",
                    timeout=5.0,
                )
            except httpx.HTTPError as exc:
                job.progress_message = f"Cancel request failed: {exc}"
                self.session.commit()
                return False
            if response.status_code != 200:
                job.progress_message = (
                    "Cancel request was rejected by the worker "
                    f"(HTTP {response.status_code})"
                )
                self.session.commit()
                return False
            # The scan stops at its next entry, and the examine request then
            # returns and marks the job cancelled. Keep RUNNING until that
            # happens so the row never claims the worker stopped when it did not.
            job.progress_message = (
                "Cancelling — the worker stops at the next filesystem entry"
            )
            self.session.commit()
            return True

        return False

    def pause_job(self, job_id: int, *, pause: bool = True) -> bool:
        """Pause or resume a running examination at worker-safe checkpoints."""
        job = self.get_job(job_id)
        if not job or job.status != JobStatus.RUNNING:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        created_by = self.session.get(User, job.created_by_id)
        if not auth_service.user_can_write_case(created_by, job.case_id):
            raise PermissionError("Read-only users cannot pause/resume examinations")
        action = "pause" if pause else "resume"
        try:
            response = httpx.post(
                f"{self.config.worker.url}/examine/{job.job_id}/{action}",
                timeout=5.0,
            )
        except httpx.HTTPError as exc:
            job.progress_message = f"Could not {action} examination: {exc}"
            self.session.commit()
            return False
        if response.status_code != 200:
            job.progress_message = (
                f"Could not {action} examination (worker HTTP {response.status_code})"
            )
            self.session.commit()
            return False
        job.progress_message = (
            "Pausing — finishing current step" if pause else "Resuming examination"
        )
        self.session.commit()
        return True

    def delete_job(self, job_id: int, deleted_by: User) -> bool:
        """Delete a non-running job and all artifacts produced by that run."""
        job = self.get_job(job_id)
        if not job or job.status == JobStatus.RUNNING:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(deleted_by, job.case_id):
            raise PermissionError("Read-only users cannot delete examinations")

        result_summary = [
            {
                "type": result.result_type,
                "summary": result.summary,
                "artifact_count": result.artifact_count,
            }
            for result in job.results
        ]
        from sqlalchemy import delete
        from sqlalchemy.orm import load_only

        from app.analysis.models import AnalysisJob, AnalysisJobStatus
        from app.artifacts.models import Artifact
        from app.artifacts.service import purge_artifact_rows

        active_analysis = self.session.execute(
            select(AnalysisJob).where(
                AnalysisJob.examination_job_id == job.id,
                AnalysisJob.status == AnalysisJobStatus.RUNNING,
            )
        ).scalar_one_or_none()
        if active_analysis is not None:
            return False

        artifacts = list(self.session.execute(
            select(Artifact).options(load_only(
                Artifact.id, Artifact.case_id, Artifact.artifact_id, Artifact.vector_id,
            )).where(Artifact.examination_job_id == job.id)
        ).scalars().all())
        artifact_count = purge_artifact_rows(self.session, artifacts)
        self.session.execute(delete(AnalysisJob).where(
            AnalysisJob.examination_job_id == job.id
        ))

        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="examination", action="delete_job", result="success",
            user=deleted_by, case_id=job.case_id,
            target_type="examination_job", target_id=job.id,
            details={
                "job_id": job.job_id,
                "evidence_id": job.evidence_id,
                "operation": job.operation.value,
                "status": job.status.value,
                "results": result_summary,
                "deleted_artifact_count": artifact_count,
            },
        )
        self.session.delete(job)
        self.session.flush()
        return True

    def get_job_results(self, job_id: int) -> list[ExaminationResult]:
        job = self.get_job(job_id)
        if not job:
            return []
        return list(job.results)

    def get_job_result_summaries(self, job_id: int):
        """Return display fields without loading potentially huge result JSON."""
        stmt = (
            select(ExaminationResult.result_type, ExaminationResult.summary,
                   ExaminationResult.artifact_count)
            .where(ExaminationResult.job_id == job_id)
            .order_by(ExaminationResult.id)
        )
        return self.session.execute(stmt).all()

    def get_supported_operations(self) -> list[dict]:
        return [
            {
                "operation": ExaminationOperation.PARTITION_ANALYSIS.value,
                "name": "Partition Analysis",
                "description": "Analyze partition table (MBR/GPT)",
                "supported": True,
            },
            {
                "operation": ExaminationOperation.FILESYSTEM_DETECTION.value,
                "name": "Filesystem Detection",
                "description": "Detect filesystem type (NTFS, FAT32, ext4, etc.)",
                "supported": True,
            },
            {
                "operation": ExaminationOperation.FILE_TRAVERSAL.value,
                "name": "File System Traversal",
                "description": "List files and directories",
                "supported": True,
            },
            {
                "operation": ExaminationOperation.FILE_EXTRACTION.value,
                "name": "File Extraction",
                "description": "Extract file contents and metadata",
                "supported": True,
            },
            {
                "operation": ExaminationOperation.DELETED_RECOVERY.value,
                "name": "Deleted File Recovery",
                "description": "Recover deleted/unallocated files",
                "supported": True,
            },
            {
                "operation": ExaminationOperation.FULL_EXAMINATION.value,
                "name": "Full Examination",
                "description": "Complete pipeline: partitions -> FS -> files -> extraction",
                "supported": True,
            },
        ]
