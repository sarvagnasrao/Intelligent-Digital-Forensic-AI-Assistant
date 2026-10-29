"""Examination service for job management and worker communication."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.config import get_config
from app.evidence.models import Evidence, EvidenceStatus
from app.examination.models import ExaminationJob, ExaminationOperation, ExaminationResult, JobStatus
from app.examination.profiles import parameter_summary, validate_parameters

if TYPE_CHECKING:
    from app.auth.models import Case
    from app.artifacts.models import Artifact, ArtifactType, IndexStatus


class ExaminationCancelled(Exception):
    """The worker stopped a scan because the investigator cancelled it."""


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
        created_by: User = None,
    ) -> ExaminationJob:
        evidence = self.session.get(Evidence, evidence_id)
        if not evidence or evidence.case_id != case_id:
            raise ValueError("Evidence not found or does not belong to case")
        if evidence.status == EvidenceStatus.ARCHIVED:
            raise ValueError("Archived evidence must be restored before creating an examination job")

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
        return list(self.session.execute(stmt.order_by(ExaminationJob.created_at.desc())).scalars().all())

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

        now = datetime.now(timezone.utc)
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
            job.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            return False

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
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

        try:
            # For old records that registered only .002/.003 as a fragment,
            # use the original source set when a complete adjacent sequence is
            # available; newly registered evidence stores the full sequence.
            image_path = evidence.stored_path or evidence.source_path
            try:
                from app.evidence.service import EvidenceService
                from pathlib import Path
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
                "parameters": parameters,
            }

            import asyncio

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
            while not request_task.done():
                await asyncio.sleep(0.75)
                try:
                        progress_response = await self.client.get(progress_url, timeout=3.0)
                        if progress_response.status_code == 200:
                            progress = progress_response.json()
                            if progress.get("status") not in ("failed", "completed"):
                                new_percent = max(
                                    job.progress_percent, min(99, int(progress.get("progress", 0)))
                                )
                                progress_status = progress.get("status")
                                if progress_status == "paused":
                                    new_message = "Paused — waiting to resume"
                                elif progress_status == "pausing":
                                    new_message = "Pausing — finishing current step"
                                else:
                                    new_message = (
                                        progress.get("message") or "Examining evidence"
                                    )
                                # The worker is polled frequently for a live UI,
                                # but unchanged progress should not acquire a
                                # SQLite write lock on every polling tick.
                                if (
                                    new_percent != job.progress_percent
                                    or new_message != job.progress_message
                                ):
                                    job.progress_percent = new_percent
                                    job.progress_message = new_message
                                    self.session.commit()
                except Exception:
                    # Older worker versions do not expose progress polling;
                    # the examination request remains valid without it.
                    pass
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

            created = 0
            updated = 0
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
                    stats = await self._create_artifact_records(
                        job.case_id,
                        job.evidence_id,
                        job.id,
                        res.get("data", {}),
                        parameters,
                    )
                    created += stats["created"]
                    updated += stats["updated"]

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.progress_percent = 100
            if created or updated:
                job.progress_message = (
                    f"Examination completed — {created:,} new, "
                    f"{updated:,} updated artifacts"
                )
            else:
                job.progress_message = "Examination completed — no artifacts found"

            evidence.status = EvidenceStatus.EXAMINED  # type: ignore[assignment]
            AuditService(self.session).log_examination_complete(
                job.created_by, job.case_id, job.id, success=True
            )
            # Queue the background analysis here rather than in the UI, so a
            # job started from the evidence page is analysed too. It only adds
            # a row; the runner does the work.
            try:
                from app.analysis.service import AnalysisService

                AnalysisService(self.session).enqueue_for_examination(
                    job.case_id,
                    job.evidence_id,
                    job.id,
                    parameters={"profile": parameters.get("profile")},
                )
            except Exception:  # noqa: BLE001 - analysis must not fail an examination
                import logging

                logging.getLogger(__name__).warning(
                    "Could not queue analysis for job %s", job.job_id, exc_info=True
                )
            self.session.commit()

            return True

        except ExaminationCancelled:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
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
            message = self._describe_worker_error(e)
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
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
    ) -> dict[str, int]:
        """Ingest worker artifact rows, updating rows a re-run already created.

        Every re-examination used to insert a second copy of every file, so the
        artifact list and every search result doubled. A row is now matched by
        its source path inside the evidence and updated in place; only paths
        that were not there before get a new artifact id.
        """
        from datetime import datetime, timezone

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

        existing_rows = self.session.execute(
            select(Artifact).where(Artifact.evidence_id == evidence_id)
        ).scalars().all()
        by_path = {
            row.source_path: row for row in existing_rows if row.source_path
        }

        for art_data in artifacts_data:
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
                        return datetime.fromtimestamp(ts, tz=timezone.utc)
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
                    content_changed = (previous.content_hash or None) != (
                        art_data.get("content_hash") or None
                    )
                    for field, value in values.items():
                        setattr(previous, field, value)
                    previous.examination_job_id = exam_job_id
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
                        self._persist_text_chunks(previous, values["content_text"], case_id)
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
                    self._persist_text_chunks(artifact, values["content_text"], case_id)
                    by_path[path] = artifact
                    stats["created"] += 1

            except Exception as e:
                # Log but don't fail the examination
                import logging
                logging.getLogger(__name__).error(f"Failed to create artifact record: {e}")

        return stats

    @staticmethod
    def _persist_text_chunks(artifact, text: str | None, case_id: int) -> None:
        """Persist extraction passages immediately, independently of indexing.

        Chunk size is a storage boundary only; concatenating the rows reproduces
        the complete extracted text with exact character offsets.
        """
        if not text:
            return
        from app.artifacts.models import ArtifactChunk

        chunk_size = 20_000
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

        self.session.flush()

    def cancel_job(self, job_id: int) -> bool:
        """Cancel a pending job, or ask the worker to stop a running scan."""
        job = self.get_job(job_id)
        if not job:
            return False

        if job.status == JobStatus.PENDING:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
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

        result_summary = [
            {
                "type": result.result_type,
                "summary": result.summary,
                "artifact_count": result.artifact_count,
            }
            for result in job.results
        ]
        from app.analysis.models import AnalysisJob, AnalysisJobStatus
        from app.artifacts.models import Artifact
        from app.artifacts.service import purge_artifact_rows
        from sqlalchemy import delete

        active_analysis = self.session.execute(
            select(AnalysisJob).where(
                AnalysisJob.examination_job_id == job.id,
                AnalysisJob.status == AnalysisJobStatus.RUNNING,
            )
        ).scalar_one_or_none()
        if active_analysis is not None:
            return False

        artifacts = list(self.session.execute(
            select(Artifact).where(Artifact.examination_job_id == job.id)
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
