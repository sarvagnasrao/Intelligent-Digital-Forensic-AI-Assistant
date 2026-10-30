"""Evidence service for registration, hashing, and integrity verification."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.config import get_config
from app.evidence.models import CustodyEvent, Evidence, EvidenceHash, EvidenceStatus, EvidenceType, HashAlgorithm

if TYPE_CHECKING:
    from app.auth.models import Case


class EvidenceService:
    """Service for evidence management and integrity."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_config()

    @staticmethod
    def detect_file_type(path: str | Path) -> tuple[EvidenceType, str]:
        """Identify the evidence category and file format without user input.

        Disk-image containers are classified as IMAGE. Other files remain
        ORIGINAL evidence; their concrete format is recorded as a MIME type.
        A few common signatures supplement the filename-based MIME guess.
        """
        file_path = Path(path)
        extension = file_path.suffix.lower()
        disk_image_extensions = {
            ".001", ".002", ".003", ".004", ".005", ".006", ".007", ".008",
            ".dd", ".img", ".raw", ".e01", ".e02", ".e03", ".iso",
            ".aff", ".vmdk", ".vhd", ".vhdx", ".vdi",
        }
        if extension in disk_image_extensions:
            mime_type = "application/x-ewf" if extension.startswith(".e") else "application/x-raw-disk-image"
            return EvidenceType.IMAGE, mime_type

        guessed_mime, _ = mimetypes.guess_type(file_path.name)
        mime_type = guessed_mime or "application/octet-stream"
        try:
            with file_path.open("rb") as handle:
                signature = handle.read(16)
            if signature.startswith(b"%PDF-"):
                mime_type = "application/pdf"
            elif signature.startswith(b"\x89PNG\r\n\x1a\n"):
                mime_type = "image/png"
            elif signature.startswith(b"\xff\xd8\xff"):
                mime_type = "image/jpeg"
            elif signature.startswith((b"GIF87a", b"GIF89a")):
                mime_type = "image/gif"
            elif signature.startswith(b"SQLite format 3\x00"):
                mime_type = "application/vnd.sqlite3"
            elif signature.startswith(b"PK\x03\x04"):
                # Keep the more specific OOXML type where the extension tells
                # us which package was detected.
                mime_type = guessed_mime if guessed_mime and guessed_mime.startswith("application/vnd.") else "application/zip"
            elif signature.startswith(b"MZ"):
                mime_type = "application/vnd.microsoft.portable-executable"
            elif signature.startswith(b"\x7fELF"):
                mime_type = "application/x-elf"
        except OSError:
            # The registration path reports missing/unreadable files with its
            # normal validation error; detection itself remains non-fatal.
            pass
        return EvidenceType.ORIGINAL, mime_type

    def _generate_evidence_id(self, case_id: int) -> str:
        """Generate next evidence ID for case (E001, E002, ...)."""
        stmt = select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id.desc())
        last = self.session.execute(stmt).scalars().first()
        if last and last.evidence_id.startswith("E"):
            try:
                num = int(last.evidence_id[1:])
                return f"E{num + 1:03d}"
            except ValueError:
                pass
        return "E001"

    @staticmethod
    def _split_image_parts(path: Path) -> list[Path]:
        """Return every consecutive numbered raw-image segment as one image.

        The user may browse to any segment, so normalize .002/.003/etc. back
        to .001 rather than silently registering only the selected fragment.
        """
        match = re.search(r"\.(\d{3})$", path.name)
        if not match:
            return [path]
        selected_part = int(match.group(1))
        if selected_part < 1:
            return [path]
        first = path.with_suffix(".001")
        if not first.is_file():
            raise FileNotFoundError(
                f"Segmented raw image part {path.name} was selected, but its first segment "
                f"{first.name} is missing. Select the complete image set."
            )
        parts = []
        index = 1
        while True:
            part = first.with_suffix(f".{index:03d}")
            if not part.is_file():
                break
            parts.append(part)
            index += 1
        later_parts = [
            candidate for candidate in first.parent.glob(f"{first.stem}.*")
            if (match := re.search(r"\.(\d{3})$", candidate.name))
            and int(match.group(1)) > len(parts)
        ]
        if later_parts:
            missing = first.with_suffix(f".{len(parts) + 1:03d}").name
            raise FileNotFoundError(
                f"Segmented raw image has a gap: expected {missing} before "
                f"{min(later_parts, key=lambda item: item.name).name}."
            )
        if selected_part > len(parts):
            raise FileNotFoundError(
                f"Segmented raw image is incomplete: expected {first.name} through "
                f".{selected_part:03d}, but a segment is missing."
            )
        return parts

    def _remove_unregistered_copy(self, stored_path: str) -> None:
        """Remove only the copy created for a registration that failed to save."""
        root = Path(self.config.worker.evidence_root_windows).resolve()
        path = Path(stored_path)
        try:
            parts = self._split_image_parts(path)
        except (FileNotFoundError, OSError):
            parts = [path]
        for part in parts:
            try:
                if part.resolve().is_relative_to(root):
                    part.unlink(missing_ok=True)
            except OSError:
                # The database error is the actionable failure; leave any copy
                # we cannot safely remove in place rather than touch a source.
                continue

    def _copy_to_case_store(self, source_path: str, case_id: int, evidence_id: str,
                            progress_callback=None) -> str:
        """Copy evidence file to case storage directory.

        The copy is written to a sibling ``.part`` file and moved into place
        only once complete, so an interrupted copy can never leave a truncated
        file at the evidence path. Copying a file onto itself is a no-op:
        opening the destination with ``"wb"`` would otherwise truncate the
        source before it is read.
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        sources = self._split_image_parts(source)
        source = sources[0]

        dest_dir = Path(self.config.worker.evidence_root_windows) / str(case_id)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Preserve numbered raw-image segments together as one evidence item.
        ext = source.suffix
        dest_path = dest_dir / f"{evidence_id}{ext}"
        if source.resolve() == dest_path.resolve():
            return str(dest_path)

        # Copy in chunks
        chunk_size = self.config.forensics.chunk_size_bytes
        total = sum(item.stat().st_size for item in sources)
        copied = 0
        for index, item in enumerate(sources, 1):
            target = dest_path if index == 1 else dest_dir / f"{evidence_id}.{index:03d}"
            part_path = target.with_name(target.name + ".part")
            try:
                with open(item, "rb") as src, open(part_path, "wb") as dst:
                    while chunk := src.read(chunk_size):
                        dst.write(chunk)
                        copied += len(chunk)
                        if progress_callback:
                            progress_callback(f"Copying image segment {index}/{len(sources)}", copied, total)
                os.replace(part_path, target)
            finally:
                part_path.unlink(missing_ok=True)

        return str(dest_path)

    def _calculate_hashes(self, file_path: str, algorithms: list[HashAlgorithm],
                          progress_callback=None) -> dict[HashAlgorithm, str]:
        """Calculate hashes for a file using streaming."""
        hashes = {algo: hashlib.new(algo.value) for algo in algorithms}
        chunk_size = self.config.forensics.chunk_size_bytes
        parts = self._split_image_parts(Path(file_path))
        total = sum(item.stat().st_size for item in parts)
        processed = 0
        for index, part in enumerate(parts, 1):
            with open(part, "rb") as f:
                while chunk := f.read(chunk_size):
                    for h in hashes.values():
                        h.update(chunk)
                    processed += len(chunk)
                    if progress_callback:
                        progress_callback(f"Hashing image segment {index}/{len(parts)}", processed, total)

        return {algo: h.hexdigest() for algo, h in hashes.items()}

    def register_evidence(
        self,
        case_id: int,
        name: str,
        source_path: str,
        evidence_type: EvidenceType | None = None,
        description: str | None = None,
        registered_by: User = None,
        copy_to_store: bool = True,
        reference_hashes: dict[HashAlgorithm, str] | None = None,
        progress_callback=None,
    ) -> Evidence:
        """Register new evidence item."""
        # Verify case exists
        from app.auth.models import Case
        from app.auth.service import AuthService
        case = self.session.get(Case, case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Check write permission
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(registered_by, case_id):
            raise PermissionError("Read-only users cannot register evidence")

        # Verify source file exists
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        source_parts = self._split_image_parts(source)
        source = source_parts[0]
        source_path = str(source)
        detected_type, detected_mime = self.detect_file_type(source)

        # Generate evidence ID
        evidence_id = self._generate_evidence_id(case_id)

        # Copy to case store if requested
        stored_path = None
        if copy_to_store:
            stored_path = self._copy_to_case_store(
                source_path, case_id, evidence_id, progress_callback
            )
            hash_path = stored_path
        else:
            hash_path = source_path

        # Get file info
        stored_parts = self._split_image_parts(Path(hash_path))
        size_bytes = sum(item.stat().st_size for item in stored_parts)
        mime_type = detected_mime
        ext = source.suffix.lower()

        # Calculate hashes
        algorithms = [HashAlgorithm(a) for a in self.config.forensics.hash_algorithms]
        calculated_hashes = self._calculate_hashes(hash_path, algorithms, progress_callback)

        # Create evidence record
        evidence = Evidence(
            evidence_id=evidence_id,
            case_id=case_id,
            name=name,
            description=description,
            evidence_type=detected_type,
            source_path=source_path,
            stored_path=stored_path,
            size_bytes=size_bytes,
            mime_type=mime_type,
            extension=ext,
            status=EvidenceStatus.REGISTERED,
            registered_by_id=registered_by.id if registered_by else 1,
        )
        self.session.add(evidence)
        try:
            self.session.flush()
        except Exception:
            self.session.rollback()
            if stored_path:
                self._remove_unregistered_copy(stored_path)
            raise

        # Store hash records
        now = datetime.now(timezone.utc)
        author_id = registered_by.id if registered_by else 1
        intake_mismatch = False
        for algo, hash_value in calculated_hashes.items():
            supplied = (reference_hashes or {}).get(algo)
            if supplied:
                # A hash from the evidence bag was supplied. It must stay the
                # reference, because that is what later verifications - and the
                # laboratory - compare against. Storing the value IDFA computed
                # instead would make the next check compare the file with
                # itself and quietly report a pass.
                matched = hash_value.lower() == supplied.strip().lower()
                intake_mismatch = intake_mismatch or not matched
                self.session.add(EvidenceHash(
                    evidence_id=evidence.id,
                    algorithm=algo,
                    hash_value=supplied.strip(),
                    is_reference=True,
                    calculated_by_id=author_id,
                    verified_at=now,
                    verified_by_id=author_id,
                    match_result=matched,
                ))
                self.session.add(EvidenceHash(
                    evidence_id=evidence.id,
                    algorithm=algo,
                    hash_value=hash_value,
                    is_reference=False,
                    calculated_by_id=author_id,
                ))
            else:
                # No manifest: the hashes computed at registration are the
                # baseline that later integrity checks are compared against.
                # Without this, registered evidence had no reference hashes and
                # ``verify_integrity`` could never verify anything.
                self.session.add(EvidenceHash(
                    evidence_id=evidence.id,
                    algorithm=algo,
                    hash_value=hash_value,
                    is_reference=True,
                    calculated_by_id=author_id,
                ))

        if reference_hashes:
            # The record should say at once that the copy does not match the
            # bag, rather than waiting for someone to run a verification.
            evidence.status = (
                EvidenceStatus.INTEGRITY_FAILED if intake_mismatch
                else EvidenceStatus.INTEGRITY_VERIFIED
            )

        # Custody event
        custody = CustodyEvent(
            evidence_id=evidence.id,
            event_type="registered",
            description=f"Evidence registered: {name}",
            performed_by_id=registered_by.id if registered_by else 1,
            source_location=source_path,
            destination_location=stored_path,
            tool_used="idfa_evidence_service",
        )
        self.session.add(custody)

        # Keep the general audit trail alongside the evidence-specific custody
        # record, in the same transaction as registration.
        from app.audit.service import AuditService

        AuditService(self.session).log_evidence_register(
            registered_by,
            case_id,
            evidence.id,
            {"evidence_ref": evidence.evidence_id, "name": evidence.name,
             "type": evidence.evidence_type.value, "status": evidence.status.value},
        )

        self.session.flush()
        return evidence

    def verify_integrity(self, evidence_id: int, verified_by: User,
                         progress_callback=None) -> dict[HashAlgorithm, bool]:
        """Verify evidence integrity against reference hashes."""
        evidence = self.session.get(Evidence, evidence_id)
        if not evidence:
            raise ValueError(f"Evidence {evidence_id} not found")

        hash_path = evidence.stored_path or evidence.source_path
        if not hash_path or not Path(hash_path).exists():
            raise FileNotFoundError(f"Evidence file not found: {hash_path}")

        # Get reference hashes
        ref_hashes = {}
        for h in evidence.hashes:
            if h.is_reference:
                ref_hashes[h.algorithm] = h.hash_value

        if not ref_hashes:
            raise ValueError("No reference hashes found for verification")

        # Calculate current hashes
        algorithms = list(ref_hashes.keys())
        if progress_callback:
            progress_callback("Preparing integrity verification", 0, 1)
        current_hashes = self._calculate_hashes(hash_path, algorithms, progress_callback)

        # Compare and record verification
        results = {}
        for algo, current_hash in current_hashes.items():
            ref_hash = ref_hashes[algo]
            match = current_hash.lower() == ref_hash.lower()
            results[algo] = match

            # Update or create verification record
            ref_record = next((h for h in evidence.hashes if h.algorithm == algo and h.is_reference), None)
            if ref_record:
                ref_record.verified_at = datetime.now(timezone.utc)
                ref_record.verified_by_id = verified_by.id
                ref_record.match_result = match
            else:
                # Create new verification record
                verify_record = EvidenceHash(
                    evidence_id=evidence.id,
                    algorithm=algo,
                    hash_value=current_hash,
                    is_reference=False,
                    calculated_by_id=verified_by.id,
                    verified_against_id=next(h.id for h in evidence.hashes if h.algorithm == algo and h.is_reference),
                    verified_at=datetime.now(timezone.utc),
                    verified_by_id=verified_by.id,
                    match_result=match,
                )
                self.session.add(verify_record)

        # Update evidence status
        all_match = all(results.values())
        evidence.status = EvidenceStatus.INTEGRITY_VERIFIED if all_match else EvidenceStatus.INTEGRITY_FAILED

        # Custody event
        custody = CustodyEvent(
            evidence_id=evidence.id,
            event_type="verified",
            description=f"Integrity verification: {'PASSED' if all_match else 'FAILED'}",
            performed_by_id=verified_by.id,
            tool_used="idfa_hash_verification",
            metadata_json=str({"results": {a.value: m for a, m in results.items()}}),
        )
        self.session.add(custody)

        from app.audit.service import AuditService

        AuditService(self.session).log_evidence_verify(
            verified_by,
            evidence.case_id,
            evidence.id,
            {algorithm.value: matched for algorithm, matched in results.items()},
        )

        self.session.flush()
        return results

    def archive_evidence(self, evidence_id: int, performed_by: User) -> bool:
        """Remove evidence from active workflows while preserving its record."""
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence or evidence.status == EvidenceStatus.ARCHIVED:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(performed_by, evidence.case_id):
            raise PermissionError("Read-only users cannot archive evidence")
        previous_status = evidence.status.value
        evidence.status = EvidenceStatus.ARCHIVED
        self.session.add(CustodyEvent(
            evidence_id=evidence.id,
            event_type="archived",
            description=f"Evidence archived from active case workflows (previous status: {previous_status})",
            performed_by_id=performed_by.id,
            source_location=evidence.stored_path or evidence.source_path,
            tool_used="idfa_evidence_service",
            metadata_json=json.dumps({"previous_status": previous_status}),
        ))
        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="evidence", action="archive", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={"evidence_ref": evidence.evidence_id, "name": evidence.name},
        )
        self.session.flush()
        return True

    def restore_evidence(self, evidence_id: int, performed_by: User) -> bool:
        """Restore an archived evidence record to its prior workflow status."""
        import json
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence or evidence.status != EvidenceStatus.ARCHIVED:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(performed_by, evidence.case_id):
            raise PermissionError("Read-only users cannot restore evidence")
        archive_event = next(
            (event for event in reversed(evidence.custody_events)
             if event.event_type == "archived"), None
        )
        prior = EvidenceStatus.REGISTERED
        if archive_event and archive_event.metadata_json:
            try:
                prior = EvidenceStatus(json.loads(archive_event.metadata_json).get("previous_status", "registered"))
            except (ValueError, TypeError):
                pass
        evidence.status = prior
        self.session.add(CustodyEvent(
            evidence_id=evidence.id,
            event_type="restored",
            description=f"Evidence restored to active case workflows (status: {prior.value})",
            performed_by_id=performed_by.id,
            source_location=evidence.stored_path or evidence.source_path,
            tool_used="idfa_evidence_service",
        ))
        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="evidence", action="restore", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={"evidence_ref": evidence.evidence_id, "name": evidence.name},
        )
        self.session.flush()
        return True

    def get_evidence_by_id(self, evidence_id: int) -> Evidence | None:
        return self.session.get(Evidence, evidence_id)

    def get_evidence_by_case(
        self, case_id: int, *, include_removed: bool = False
    ) -> list[Evidence]:
        """Evidence registered to a case, newest last.

        Removed items are tombstones: they stay queryable for the case record
        but are hidden from normal lists, the examination picker and reports.
        """
        stmt = select(Evidence).where(Evidence.case_id == case_id)
        if not include_removed:
            stmt = stmt.where(Evidence.removed_at.is_(None))
        return list(self.session.execute(stmt.order_by(Evidence.id)).scalars().all())


    def update_evidence_status(self, evidence_id: int, status: EvidenceStatus) -> Evidence | None:
        evidence = self.get_evidence_by_id(evidence_id)
        if evidence:
            evidence.status = status
            self.session.flush()
        return evidence

    # ------------------------------------------------------- files on disk
    # What the record actually points at, as opposed to what it claims: a case
    # store can be moved or cleaned by hand, and the investigator needs to see
    # that in the list rather than discover it during verification.
    STORED_PRESENT = "present"
    STORED_REFERENCE = "reference"
    STORED_MISSING = "missing"

    def stored_parts(self, evidence: Evidence) -> list[Path]:
        """Every file that belongs to this evidence, segments included."""
        target = evidence.stored_path or evidence.source_path
        if not target:
            return []
        path = Path(target)
        try:
            return self._split_image_parts(path)
        except FileNotFoundError:
            # A missing or incomplete segment set is reported by ``file_state``;
            # listing what the record names is still more useful than nothing.
            return [path]

    def file_state(self, evidence: Evidence) -> str:
        target = evidence.stored_path or evidence.source_path
        if not target or not Path(target).is_file():
            return self.STORED_MISSING
        return self.STORED_PRESENT if evidence.stored_path else self.STORED_REFERENCE

    def disk_size(self, evidence: Evidence) -> int:
        """Bytes actually present on disk for this item."""
        return sum(
            part.stat().st_size for part in self.stored_parts(evidence) if part.is_file()
        )

    def check_files(self, case_id: int) -> dict[int, str]:
        """File state for every item in the case, removed ones included."""
        return {
            evidence.id: self.file_state(evidence)
            for evidence in self.get_evidence_by_case(case_id, include_removed=True)
        }

    def case_storage(self, case_id: int) -> dict[str, int]:
        """Counts and bytes for the storage summary in the page header."""
        items = self.get_evidence_by_case(case_id, include_removed=True)
        active = [item for item in items if not item.is_removed]
        return {
            "items": len(active),
            "bytes": sum(item.size_bytes for item in active),
            "missing": sum(
                1 for item in active if self.file_state(item) == self.STORED_MISSING
            ),
            "archived": sum(
                1 for item in active if item.status == EvidenceStatus.ARCHIVED
            ),
            "removed": sum(1 for item in items if item.is_removed),
        }

    # ------------------------------------------------------------- removal
    def remove_evidence(
        self, evidence_id: int, performed_by: User, reason: str = ""
    ) -> bool:
        """Take an item out of the case without deleting the record or files."""
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence or evidence.is_removed:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(performed_by, evidence.case_id):
            raise PermissionError("Read-only users cannot remove evidence")

        evidence.removed_at = datetime.now(timezone.utc)
        evidence.removed_by_id = performed_by.id
        evidence.removal_reason = reason.strip() or None
        from app.findings.identity import invalidate_reviewed_sources
        invalidate_reviewed_sources(self.session, evidence_id=evidence.id, user=performed_by)
        self.session.add(CustodyEvent(
            evidence_id=evidence.id,
            event_type="removed",
            description=(
                "Evidence removed from the case record"
                + (f": {reason.strip()}" if reason.strip() else "")
            ),
            performed_by_id=performed_by.id,
            source_location=evidence.stored_path or evidence.source_path,
            tool_used="idfa_evidence_service",
        ))
        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="evidence", action="remove", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={"evidence_ref": evidence.evidence_id, "name": evidence.name,
                     "reason": reason.strip()},
        )
        self.session.flush()
        return True

    def return_evidence(self, evidence_id: int, performed_by: User) -> bool:
        """Undo a removal; the record and its files were never altered."""
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence or not evidence.is_removed:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(performed_by, evidence.case_id):
            raise PermissionError("Read-only users cannot return evidence")

        evidence.removed_at = None
        evidence.removed_by_id = None
        evidence.removal_reason = None
        self.session.add(CustodyEvent(
            evidence_id=evidence.id,
            event_type="returned",
            description="Evidence returned to the case record",
            performed_by_id=performed_by.id,
            source_location=evidence.stored_path or evidence.source_path,
            tool_used="idfa_evidence_service",
        ))
        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="evidence", action="return", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={"evidence_ref": evidence.evidence_id, "name": evidence.name},
        )
        self.session.flush()
        return True

    def deletion_blockers(self, evidence: Evidence) -> list[str]:
        """Reasons a permanent deletion must wait, such as a running job."""
        from app.analysis.models import AnalysisJob, AnalysisJobStatus
        from app.examination.models import ExaminationJob, JobStatus

        running_exams = self.session.execute(
            select(ExaminationJob).where(
                ExaminationJob.evidence_id == evidence.id,
                ExaminationJob.status == JobStatus.RUNNING,
            )
        ).scalars().all()
        running_analysis = self.session.execute(
            select(AnalysisJob).where(
                AnalysisJob.evidence_id == evidence.id,
                AnalysisJob.status == AnalysisJobStatus.RUNNING,
            )
        ).scalars().all()
        blockers = []
        if running_exams:
            blockers.append(
                f"{len(running_exams)} examination job(s) are still running."
            )
        if running_analysis:
            blockers.append(
                f"{len(running_analysis)} background analysis job(s) are still running."
            )
        return blockers

    def deletion_impact(self, evidence: Evidence) -> dict[str, int]:
        """Counts of derived records that permanent evidence deletion removes."""
        from sqlalchemy import func

        from app.artifacts.models import Artifact
        from app.examination.models import ExaminationJob

        return {
            "jobs": int(self.session.execute(
                select(func.count()).select_from(ExaminationJob).where(
                    ExaminationJob.evidence_id == evidence.id
                )
            ).scalar_one()),
            "artifacts": int(self.session.execute(
                select(func.count()).select_from(Artifact).where(
                    Artifact.evidence_id == evidence.id
                )
            ).scalar_one()),
        }

    def case_store_files(self, evidence: Evidence) -> list[Path]:
        """Files this item owns inside the case store; never the source."""
        if not evidence.stored_path:
            return []
        configured = self.config.worker.evidence_root_windows or ""
        if not configured.strip():
            # Without a known case store there is no way to prove a file is
            # ours to delete, so nothing is deleted.
            return []
        root = Path(configured).resolve()
        owned: list[Path] = []
        for part in self.stored_parts(evidence):
            try:
                if part.is_file() and root in part.resolve().parents:
                    owned.append(part)
            except OSError:
                continue
        return owned

    def delete_evidence(
        self,
        evidence_id: int,
        performed_by: User,
        reason: str = "",
        *,
        delete_files: bool = True,
    ) -> dict[str, int]:
        """Delete evidence and all examination artifacts/results derived from it.

        Only files inside the case evidence folder are removed: the original
        acquisition path is never touched, and a tampered ``stored_path`` cannot
        be used to delete something outside the case.
        """
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence:
            raise ValueError("That evidence no longer exists.")
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(performed_by, evidence.case_id):
            raise PermissionError("Read-only users cannot delete evidence")

        blockers = self.deletion_blockers(evidence)
        if blockers:
            raise ValueError(" ".join(blockers))

        impact = self.deletion_impact(evidence)

        files = self.case_store_files(evidence) if delete_files else []
        freed = sum(part.stat().st_size for part in files)

        # Files first: if a file cannot be removed, the record stays so the
        # investigator can retry rather than lose track of a leftover copy. A
        # file that vanished since the dialog opened is already gone.
        for part in files:
            part.unlink(missing_ok=True)

        from sqlalchemy import delete
        from sqlalchemy.orm import load_only

        from app.analysis.models import AnalysisJob
        from app.artifacts.models import Artifact
        from app.artifacts.service import purge_artifact_rows
        from app.examination.models import ExaminationJob
        from app.audit.service import AuditService

        artifacts = self.session.execute(
            select(Artifact).options(load_only(
                Artifact.id, Artifact.case_id, Artifact.artifact_id, Artifact.vector_id,
            )).where(Artifact.evidence_id == evidence.id)
        ).scalars().all()
        purge_artifact_rows(self.session, artifacts)
        self.session.execute(delete(AnalysisJob).where(
            AnalysisJob.evidence_id == evidence.id
        ))
        self.session.execute(delete(ExaminationJob).where(
            ExaminationJob.evidence_id == evidence.id
        ))
        self.session.expire(evidence, ["examinations"])

        AuditService(self.session).log_event(
            event_type="evidence", action="delete", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={
                "evidence_ref": evidence.evidence_id,
                "name": evidence.name,
                "reason": reason.strip(),
                "files_deleted": len(files),
                "bytes_freed": freed,
                "source_kept": evidence.source_path,
                "examination_jobs_deleted": impact["jobs"],
                "artifacts_deleted": impact["artifacts"],
            },
        )

        self.session.delete(evidence)
        self.session.flush()
        return {
            "files": len(files),
            "bytes": freed,
            "jobs": impact["jobs"],
            "artifacts": impact["artifacts"],
        }

    # ------------------------------------------------------------- metadata
    def update_details(
        self, evidence_id: int, name: str, description: str, performed_by: User
    ) -> bool:
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence:
            return False
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(performed_by, evidence.case_id):
            raise PermissionError("Read-only users cannot update evidence details")
        name = name.strip()
        if not name:
            raise ValueError("The evidence name cannot be empty.")

        evidence.name = name
        evidence.description = description.strip() or None
        self.session.add(CustodyEvent(
            evidence_id=evidence.id,
            event_type="details_edited",
            description=f"Evidence details edited (name: {name})",
            performed_by_id=performed_by.id,
            tool_used="idfa_evidence_service",
        ))
        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="evidence", action="edit", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={"evidence_ref": evidence.evidence_id, "name": name},
        )
        self.session.flush()
        return True

    # ---------------------------------------------------------- reference hash
    _HEX_LENGTH = {
        HashAlgorithm.SHA256: 64,
        HashAlgorithm.MD5: 32,
        HashAlgorithm.SHA1: 40,
    }

    def set_reference_hash(
        self,
        evidence_id: int,
        algorithm: HashAlgorithm,
        hash_value: str,
        performed_by: User,
        note: str = "",
        progress_callback=None,
    ) -> dict[HashAlgorithm, bool]:
        """Adopt a hash from the evidence bag, then verify the file against it.

        The supplied value becomes the reference and the stored copy is hashed
        immediately, so a mismatch is visible at once rather than at the next
        verification run.
        """
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence:
            raise ValueError("That evidence no longer exists.")
        from app.auth.service import AuthService
        auth_service = AuthService(self.session)
        if not auth_service.user_can_write_case(performed_by, evidence.case_id):
            raise PermissionError("Read-only users cannot set reference hash")

        value = hash_value.strip().lower()
        expected = self._HEX_LENGTH[algorithm]
        if not re.fullmatch(rf"[0-9a-f]{{{expected}}}", value):
            raise ValueError(
                f"A {algorithm.value.upper()} hash is {expected} hexadecimal characters."
            )

        record = next(
            (
                item
                for item in evidence.hashes
                if item.algorithm == algorithm and item.is_reference
            ),
            None,
        )
        if record is None:
            record = EvidenceHash(
                evidence_id=evidence.id,
                algorithm=algorithm,
                hash_value=value,
                is_reference=True,
                calculated_by_id=performed_by.id,
            )
            self.session.add(record)
        else:
            record.hash_value = value

        self.session.add(CustodyEvent(
            evidence_id=evidence.id,
            event_type="hash_reference_set",
            description=(
                f"{algorithm.value.upper()} reference hash recorded from an external source"
                + (f" ({note.strip()})" if note.strip() else "")
            ),
            performed_by_id=performed_by.id,
            tool_used="idfa_evidence_service",
            metadata_json=json.dumps({"algorithm": algorithm.value, "value": value}),
        ))
        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="evidence", action="set_reference_hash", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={"evidence_ref": evidence.evidence_id,
                     "algorithm": algorithm.value, "hash": value},
        )
        self.session.flush()

        return self.verify_integrity(evidence_id, performed_by, progress_callback)

    # -------------------------------------------------------------- export
    def export_copy(
        self,
        evidence_id: int,
        destination: str | Path,
        performed_by: User,
        progress_callback=None,
    ) -> dict[str, object]:
        """Copy the evidence out, then hash the copy to prove it arrived intact."""
        evidence = self.get_evidence_by_id(evidence_id)
        if not evidence:
            raise ValueError("That evidence no longer exists.")

        parts = [part for part in self.stored_parts(evidence) if part.is_file()]
        if not parts:
            raise FileNotFoundError(
                "None of this item's files are present on disk, so there is "
                "nothing to export."
            )

        target_dir = Path(destination)
        target_dir.mkdir(parents=True, exist_ok=True)

        total = sum(part.stat().st_size for part in parts)
        copied_bytes = 0
        copied: list[Path] = []
        chunk_size = self.config.forensics.chunk_size_bytes
        for part in parts:
            target = target_dir / part.name
            with open(part, "rb") as source_file, open(target, "wb") as target_file:
                while chunk := source_file.read(chunk_size):
                    target_file.write(chunk)
                    copied_bytes += len(chunk)
                    if progress_callback:
                        progress_callback(
                            f"Copying {part.name}", copied_bytes, total
                        )
            shutil.copystat(part, target)
            copied.append(target)

        references = {
            item.algorithm: item.hash_value
            for item in evidence.hashes
            if item.is_reference
        }
        verified: bool | None = None
        if references:
            if progress_callback:
                progress_callback("Hashing the exported copy", 0, 1)
            current = self._calculate_hashes(str(copied[0]), list(references))
            verified = all(
                current[algo].lower() == value.lower()
                for algo, value in references.items()
            )

        self.session.add(CustodyEvent(
            evidence_id=evidence.id,
            event_type="exported",
            description=(
                f"Exported {len(copied)} file(s) to {target_dir}"
                + ("; hash verified" if verified else
                   "; hash mismatch" if verified is False else "")
            ),
            performed_by_id=performed_by.id,
            source_location=evidence.stored_path or evidence.source_path,
            destination_location=str(target_dir),
            tool_used="idfa_evidence_service",
        ))
        from app.audit.service import AuditService
        AuditService(self.session).log_event(
            event_type="evidence", action="export", result="success",
            user=performed_by, case_id=evidence.case_id,
            target_type="evidence", target_id=evidence.id,
            details={"evidence_ref": evidence.evidence_id,
                     "destination": str(target_dir), "verified": verified},
        )
        self.session.flush()
        return {
            "files": [str(path) for path in copied],
            "destination": str(target_dir),
            "verified": verified,
        }

    def case_manifest(self, case_id: int) -> list[dict[str, object]]:
        """One row per evidence item, for a CSV/JSON case manifest."""
        from app.auth.models import Case

        case = self.session.get(Case, case_id)
        rows: list[dict[str, object]] = []
        for evidence in self.get_evidence_by_case(case_id, include_removed=True):
            references = {
                item.algorithm.value: item.hash_value
                for item in evidence.hashes
                if item.is_reference
            }
            verified = [item for item in evidence.hashes if item.verified_at]
            rows.append({
                "case": case.case_id if case else case_id,
                "evidence_id": evidence.evidence_id,
                "name": evidence.name,
                "type": evidence.evidence_type.value,
                "status": evidence.status.value,
                "removed": evidence.is_removed,
                "removal_reason": evidence.removal_reason or "",
                "source_path": evidence.source_path,
                "stored_path": evidence.stored_path or "",
                "file_state": self.file_state(evidence),
                "size_bytes": evidence.size_bytes,
                "hashes": references,
                "last_verified": (
                    max(item.verified_at for item in verified).isoformat()
                    if verified else ""
                ),
                "registered_at": (
                    evidence.registered_at.isoformat()
                    if evidence.registered_at else ""
                ),
                "custody_events": len(evidence.custody_events),
            })
        return rows
