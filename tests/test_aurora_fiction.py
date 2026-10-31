"""Aurora checks are byte-only/pytsk3: no app, AI, services or live database."""

import hashlib
import runpy
from pathlib import Path

import pytest

BUILDER = Path(__file__).parent / "demo_case" / "aurora_fiction" / "build_image.py"


def test_aurora_importer_is_opt_in_and_loopback_only(capsys):
    script = BUILDER.parents[3] / "scripts" / "prepare_aurora_demo.py"
    importer = runpy.run_path(str(script))
    assert importer["main"]([]) == 0
    assert "--create" in capsys.readouterr().out
    importer["validate_worker"]("http://127.0.0.1:8000")
    for url in ("https://example.test", "http://localhost:8000", "http://127.0.0.1/evil",
                "http://user:pass@127.0.0.1:8000"):
        with pytest.raises(ValueError, match="loopback"):
            importer["validate_worker"](url)


def test_aurora_deterministic_and_no_overwrite(tmp_path):
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


def test_aurora_content_and_identifier_density():
    demo = runpy.run_path(str(BUILDER))
    contents = dict(demo["FILES"])
    assert len(contents) == 11
    assert all(b"SYNTHETIC FICTION" in body and b"UTC (+00:00)" in body
               for body in contents.values())
    sample_hash = hashlib.sha256(contents[b"SAMPLE  CSV"]).hexdigest().encode()
    assert sample_hash in contents[b"MANIFESTTXT"]
    for identifier, count in (
        (b"prism-drop-47@example.test", 3),
        (b"192.0.2.47", 2),
        (b"USB-AURORA-0042", 2),
        (b"DEV-AURORA-07", 2),
        (b"TX-AURORA-19", 2),
    ):
        assert sum(identifier in body for body in contents.values()) == count
        assert count <= int(len(contents) * 0.5)
        assert identifier not in contents[b"GARDEN  TXT"]
    assert b"action=DENY" in contents[b"BLOCK   LOG"]
    assert b"bytes_sent=0" in contents[b"BLOCK   LOG"]
    assert b"CANCELLED" in contents[b"CANCEL  TXT"]


def test_aurora_image_reads_with_pytsk3(tmp_path):
    pytsk3 = pytest.importorskip("pytsk3")
    demo = runpy.run_path(str(BUILDER))
    path = tmp_path / "aurora.img"
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
    bundled = BUILDER.with_name("aurora_fiction.img")
    assert bundled.read_bytes() == path.read_bytes()
