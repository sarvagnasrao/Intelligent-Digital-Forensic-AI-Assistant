"""Disk-image reads must not present incomplete evidence as complete text."""

from types import SimpleNamespace

import pytest

import worker.main as worker


@pytest.mark.parametrize("source, expected_status", [(b"partial", "error"), (b"complete", "extracted")])
def test_disk_image_short_read_is_not_extracted(monkeypatch, source, expected_status):
    constants = SimpleNamespace(TSK_FS_META_FLAG_ALLOC=1, TSK_FS_META_TYPE_REG=2, TSK_FS_META_TYPE_DIR=3)
    meta = SimpleNamespace(flags=1, type=2, addr=42, size=8, mtime=0, atime=0, ctime=0, crtime=0)
    entry = SimpleNamespace(info=SimpleNamespace(name=SimpleNamespace(name=b"note.txt"), meta=meta))

    class File:
        def read_random(self, offset, size):
            return source[offset:offset + size]

    fs = SimpleNamespace(open_dir=lambda **kwargs: [entry], open_meta=lambda **kwargs: File())
    monkeypatch.setattr(worker, "pytsk3", constants)
    monkeypatch.setattr(worker, "_fs_info", fs)
    artifact = worker.walk_and_extract_artifacts("unused.img")[0]

    assert artifact["extraction_status"] == expected_status
    if expected_status == "error":
        assert artifact["content_text"] is None
        assert artifact["content_hash"] is None
        assert artifact["content_truncated"] is True
        assert artifact["read_error"] == "Short read: 7 of 8 bytes"
    else:
        assert artifact["content_text"] == "complete"
        assert artifact["content_hash"] is not None
        assert artifact["content_truncated"] is False
        assert artifact["read_error"] is None
