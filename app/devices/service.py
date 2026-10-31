"""Explicit device assertions and unconfirmed, source-backed identifier leads."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.auth.models import Case, User, UserRole
from app.devices.models import DeviceEvidenceLink, PhysicalDevice
from app.evidence.models import Evidence
from app.artifacts.models import Artifact, Entity, EntityType


@dataclass(frozen=True)
class DeviceCandidate:
    """An identifier occurrence, not an assertion about a physical device."""

    evidence_id: int
    artifact_id: str
    source_path: str | None
    identifier_type: str
    value: str
    start_offset: int
    end_offset: int
    context: str


class DeviceService:
    def __init__(self, session: Session):
        self.session = session

    def list_devices(self, case_id: int) -> list[PhysicalDevice]:
        return list(
            self.session.scalars(
                select(PhysicalDevice)
                .where(PhysicalDevice.case_id == case_id)
                .order_by(PhysicalDevice.id)
            )
        )

    def identification_candidates(self, case_id: int, evidence_id: int) -> list[DeviceCandidate]:
        """Return exact extracted identifier occurrences for investigator review.

        Identifiers may refer to another device or be copied text. Never group
        occurrences, create devices, or link evidence from these leads.
        """
        rows = self.session.execute(
            select(Entity, Artifact)
            .join(Artifact, Entity.artifact_id == Artifact.id)
            .join(Evidence, Artifact.evidence_id == Evidence.id)
            .where(
                Entity.case_id == case_id,
                Artifact.case_id == case_id,
                Evidence.case_id == case_id,
                Evidence.id == evidence_id,
                Evidence.removed_at.is_(None),
                Entity.entity_type.in_((EntityType.DEVICE_ID, EntityType.MAC_ADDRESS)),
            )
            .order_by(Artifact.id, Entity.id)
        )
        candidates = []
        for entity, artifact in rows:
            text = artifact.content_text or ""
            start, end = entity.start_offset, entity.end_offset
            if (start is None or end is None or start < 0 or end <= start
                    or end > len(text) or text[start:end] != entity.value):
                continue
            candidates.append(DeviceCandidate(
                evidence_id=evidence_id, artifact_id=artifact.artifact_id,
                source_path=artifact.source_path, identifier_type=entity.entity_type.value,
                value=entity.value, start_offset=start, end_offset=end,
                context=text[max(0, start - 80):min(len(text), end + 80)],
            ))
        return candidates

    def create(
        self, case_id: int, user: User, label: str, description: str = "", serial_number: str = ""
    ) -> PhysicalDevice:
        user = self._check_user(user)
        if not self.session.get(Case, case_id):
            raise ValueError("Case not found")
        label = label.strip()
        if not label or len(label) > 256 or len(serial_number.strip()) > 256:
            raise ValueError(
                "A label is required; label and serial number must be at most 256 characters"
            )
        device = PhysicalDevice(
            case_id=case_id,
            label=label,
            description=description.strip() or None,
            serial_number=serial_number.strip() or None,
            created_by_id=user.id,
        )
        self.session.add(device)
        self.session.flush()
        AuditService(self.session).log_event(
            "device",
            "create",
            "success",
            user=user,
            case_id=case_id,
            target_type="physical_device",
            target_id=device.id,
            details={
                "label": label,
                "description": device.description,
                "serial_number": device.serial_number,
            },
        )
        return device

    def link_evidence(
        self, case_id: int, device_id: int, evidence_id: int, user: User
    ) -> DeviceEvidenceLink:
        user = self._check_user(user)
        device = self.session.get(PhysicalDevice, device_id)
        evidence = self.session.get(Evidence, evidence_id)
        if not device or device.case_id != case_id or not evidence or evidence.case_id != case_id:
            raise ValueError("Device and evidence must belong to the active case")
        if evidence.removed_at is not None:
            raise ValueError("Cannot link removed evidence")
        existing = self.session.scalar(
            select(DeviceEvidenceLink).where(
                DeviceEvidenceLink.device_id == device_id,
                DeviceEvidenceLink.evidence_id == evidence_id,
            )
        )
        if existing:
            return existing
        link = DeviceEvidenceLink(
            device_id=device_id, evidence_id=evidence_id, created_by_id=user.id
        )
        self.session.add(link)
        self.session.flush()
        AuditService(self.session).log_event(
            "device",
            "link_evidence",
            "success",
            user=user,
            case_id=case_id,
            target_type="physical_device",
            target_id=device_id,
            details={"evidence_id": evidence_id},
        )
        return link

    def linked_evidence(self, case_id: int, device_id: int) -> list[Evidence]:
        return list(
            self.session.scalars(
                select(Evidence)
                .join(DeviceEvidenceLink, DeviceEvidenceLink.evidence_id == Evidence.id)
                .join(PhysicalDevice, PhysicalDevice.id == DeviceEvidenceLink.device_id)
                .where(
                    PhysicalDevice.id == device_id,
                    PhysicalDevice.case_id == case_id,
                    Evidence.case_id == case_id,
                )
                .order_by(Evidence.id)
            )
        )

    def _check_user(self, user: User) -> User:
        if not user or not user.id:
            raise ValueError("An active investigator is required")
        # Check database values, not attributes on a detached or fabricated caller object.
        row = self.session.execute(
            select(User.is_active, User.role).where(User.id == user.id)
        ).one_or_none()
        if not row or not row.is_active or row.role == UserRole.READ_ONLY:
            raise ValueError("An active investigator is required")
        return self.session.get(User, user.id)
