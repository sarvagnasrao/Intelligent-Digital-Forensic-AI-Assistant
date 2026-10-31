from types import SimpleNamespace
from unittest.mock import MagicMock
from pathlib import Path

import pytest

from app.evidence.service import EvidenceService


def make_service(parts):
    service = EvidenceService.__new__(EvidenceService)
    service.session = MagicMock()
    service.config = SimpleNamespace(
        forensics=SimpleNamespace(chunk_size_bytes=16)
    )
    evidence = SimpleNamespace(
        id=1, case_id=1, evidence_id="EV-1", hashes=[],
        stored_path=str(parts[0]), source_path=str(parts[0]),
    )
    service.get_evidence_by_id = lambda _id: evidence
    service.stored_parts = lambda _evidence: parts
    return service


def test_export_to_source_directory_does_not_change_source(tmp_path):
    source = tmp_path / "image.E01"
    source.write_bytes(b"original evidence")
    service = make_service([source])

    with pytest.raises(FileExistsError):
        service.export_copy(1, tmp_path, MagicMock())

    assert source.read_bytes() == b"original evidence"
    service.session.add.assert_not_called()


def test_existing_later_segment_prevents_any_copy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    parts = [source / "image.E01", source / "image.E02"]
    for index, part in enumerate(parts):
        part.write_bytes(f"segment {index}".encode())
    destination = tmp_path / "destination"
    destination.mkdir()
    existing = destination / "image.E02"
    existing.write_bytes(b"do not replace")

    service = make_service(parts)
    with pytest.raises(FileExistsError):
        service.export_copy(1, destination, MagicMock())

    assert not (destination / "image.E01").exists()
    assert existing.read_bytes() == b"do not replace"
    assert [part.read_bytes() for part in parts] == [b"segment 0", b"segment 1"]
    service.session.add.assert_not_called()


def test_export_creates_new_segmented_copy(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    parts = [source / "image.E01", source / "image.E02"]
    for index, part in enumerate(parts):
        part.write_bytes(f"segment {index}".encode())
    monkeypatch.setattr("app.audit.service.AuditService", MagicMock())
    monkeypatch.setattr("app.evidence.service.CustodyEvent", MagicMock())
    service = make_service(parts)

    result = service.export_copy(1, tmp_path / "export", MagicMock())

    assert [open_path.read_bytes() for open_path in map(Path, result["files"])] == [
        b"segment 0", b"segment 1"
    ]
    assert result["verified"] is None
