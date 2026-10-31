"""Partition coverage without accessing real images or services."""
import pytest

import worker.main as worker


@pytest.mark.parametrize("operation", ["filesystem_detection", "file_traversal", "full_examination", "file_extraction", "artifact_extraction"])
@pytest.mark.parametrize("selected", [False, True])
def test_examine_all_supported_partitions(monkeypatch, tmp_path, operation, selected):
    image = tmp_path / "evidence.img"
    image.touch()
    monkeypatch.setattr(worker, "get_partitions", lambda _: [{"offset": 100}, {"offset": 200}, {"offset": 300}])
    def mount(_, offset):
        if offset == 200:
            return {"error": "unsupported"}
        monkeypatch.setattr(worker, "_fs_info", object())
        return {"fs_type": "test"}

    monkeypatch.setattr(worker, "get_filesystem_info", mount)
    visited = []

    def walk(_image, offset, **kwargs):
        visited.append(offset)
        return [{"name": str(offset)}]

    monkeypatch.setattr(worker, "walk_and_extract_artifacts", walk)
    request = worker.ExamineRequest(case_id=1, evidence_id=1, image_path=str(image), operation=operation, parameters={"partition_offset": 300} if selected else {})
    response = worker._examine_sync(request)
    assert response.success, response.error
    warnings = [r for r in response.results if r["type"] == "partition_warning"]
    assert [r["data"]["partition_offset"] for r in warnings] == ([] if selected else [200])
    if warnings:
        assert "incomplete coverage" in warnings[0]["summary"].lower()
        assert warnings[0]["data"]["error"] == "unsupported"
    expected = [300] if selected else [100, 300]
    if operation == "filesystem_detection":
        assert [r["data"]["partition_offset"] for r in response.results if r["type"] == "filesystem"] == expected
    else:
        assert visited == expected
        results = [r for r in response.results if r["type"] in ("artifacts", "file_list")]
        assert [r["data"]["partition_offset"] for r in results] == expected
        assert [r["artifact_count"] for r in results] == [1] * len(expected)
