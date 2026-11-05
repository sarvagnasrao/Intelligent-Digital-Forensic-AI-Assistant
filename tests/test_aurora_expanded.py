"""Aurora expanded checks are byte-only/pytsk3: no app, AI, services or database."""

import hashlib
import itertools
import runpy
from pathlib import Path

import pytest

BUILDER = Path(__file__).parent / "demo_case" / "aurora_expanded" / "build_image.py"
FILE_COUNT = 36
HUB_THRESHOLD = max(8, int(FILE_COUNT * 0.5))


def test_aurora_expanded_deterministic_and_no_overwrite(tmp_path):
    demo = runpy.run_path(str(BUILDER))
    path = tmp_path / "demo.img"
    digest = demo["write_image"](path)
    assert path.read_bytes() == demo["build_image"]()
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    before = path.stat().st_mtime_ns
    assert demo["write_image"](path) == digest
    assert path.stat().st_mtime_ns == before
    path.write_bytes(b"preserve this unrelated evidence")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        demo["write_image"](path)
    assert path.read_bytes() == b"preserve this unrelated evidence"


def test_aurora_expanded_content_and_identifier_density():
    demo = runpy.run_path(str(BUILDER))
    files = demo["FILES"]
    contents = dict(files)
    assert len(files) == FILE_COUNT
    assert len(contents) == FILE_COUNT
    assert all(len(name) == 11 for name, _ in files)
    assert all(0 < len(body) <= 512 for _, body in files)
    assert all(b"SYNTHETIC FICTION" in body and b"UTC (+00:00)" in body
               for body in contents.values())

    sample_hash = hashlib.sha256(contents[b"SAMPLE  CSV"]).hexdigest().encode()
    assert sample_hash in contents[b"MANIFESTTXT"]

    # Filenames are weaker evidence, so they get a slightly higher cap.
    groups = (
        (demo["STRONG_IDENTIFIERS"], 5),
        (demo["SHARED_FILENAMES"], 6),
    )
    for identifiers, upper in groups:
        for identifier in identifiers:
            count = sum(identifier in body for body in contents.values())
            assert 2 <= count <= upper, (identifier, count)
            assert count <= HUB_THRESHOLD, (identifier, count)
    assert HUB_THRESHOLD == 18

    # The demo needs more than a handful of genuine shared-value pairs.
    pairs = set()
    for identifier in demo["STRONG_IDENTIFIERS"]:
        holders = [index for index, (_, body) in enumerate(files) if identifier in body]
        pairs.update(itertools.combinations(holders, 2))
    assert len(pairs) >= 60


def test_aurora_expanded_counterevidence_and_decoys():
    demo = runpy.run_path(str(BUILDER))
    contents = dict(demo["FILES"])
    block = contents[b"BLOCK   LOG"]
    assert b"action=DENY" in block
    assert b"bytes_sent=0" in block
    assert b"CANCELLED" in contents[b"CANCEL  TXT"]
    assert b"contradicts" in contents[b"WITNESS TXT"].lower()
    assert b"approved for training" in contents[b"REBUTTALLOG"]
    shared = tuple(demo["STRONG_IDENTIFIERS"]) + tuple(demo["SHARED_FILENAMES"])
    for decoy in (b"GARDEN  TXT", b"LUNCH   TXT"):
        body = contents[decoy]
        assert not any(identifier in body for identifier in shared)


def test_aurora_expanded_image_reads_with_pytsk3(tmp_path):
    pytsk3 = pytest.importorskip("pytsk3")
    demo = runpy.run_path(str(BUILDER))
    path = tmp_path / "aurora_expanded.img"
    demo["write_image"](path)
    image = pytsk3.Img_Info(str(path))
    filesystem = pytsk3.FS_Info(image)
    expected_names = set()
    for short_name, expected in demo["FILES"]:
        stem = short_name[:8].decode().rstrip()
        extension = short_name[8:].decode().rstrip()
        name = f"{stem}.{extension}"
        expected_names.add(name)
        entry = filesystem.open("/" + name)
        assert entry.info.meta.size == len(expected)
        assert entry.read_random(0, len(expected)) == expected
    actual_names = {entry.info.name.name.decode() for entry in filesystem.open_dir("/")}
    assert expected_names <= actual_names
    assert len(expected_names) == FILE_COUNT
    bundled = BUILDER.with_name("aurora_expanded.img")
    assert bundled.read_bytes() == path.read_bytes()
