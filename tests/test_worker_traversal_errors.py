"""A directory failure must not masquerade as a complete inventory."""

from types import SimpleNamespace

import pytest

import worker.main as worker


@pytest.mark.parametrize("failing_path", ["/", "/subdir"])
def test_directory_read_failure_aborts_traversal(monkeypatch, failing_path):
    constants = SimpleNamespace(TSK_FS_META_FLAG_ALLOC=1, TSK_FS_META_TYPE_REG=2, TSK_FS_META_TYPE_DIR=3)
    meta = SimpleNamespace(flags=1, type=3, addr=1, size=0, mtime=0, atime=0, ctime=0, crtime=0)
    entry = SimpleNamespace(info=SimpleNamespace(name=SimpleNamespace(name=b"subdir"), meta=meta))

    def open_dir(*, path):
        if path == failing_path:
            raise OSError("damaged directory")
        return [entry]

    monkeypatch.setattr(worker, "pytsk3", constants)
    monkeypatch.setattr(worker, "_fs_info", SimpleNamespace(open_dir=open_dir))
    with pytest.raises(RuntimeError, match=f"Filesystem traversal failed at {failing_path}: damaged directory"):
        worker.walk_and_extract_artifacts("unused.img")


def test_directory_iteration_failure_aborts_traversal(monkeypatch):
    def broken_entries():
        raise OSError("iteration failed")
        yield

    monkeypatch.setattr(worker, "_fs_info", SimpleNamespace(open_dir=lambda **kwargs: broken_entries()))
    with pytest.raises(RuntimeError, match="Filesystem traversal failed at /: iteration failed"):
        worker.walk_and_extract_artifacts("unused.img")
