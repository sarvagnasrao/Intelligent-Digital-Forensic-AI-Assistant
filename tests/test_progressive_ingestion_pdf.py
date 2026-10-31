import asyncio
import hashlib

import worker.document_extraction as documents
import worker.main as worker


def test_pdf_extraction_is_not_gated_by_deep(monkeypatch, tmp_path):
    monkeypatch.setattr(documents, "extract_pdf_text", lambda content, **kwargs: content.decode())
    path = tmp_path / "evidence.pdf"
    path.write_bytes(b"embedded text")
    for deep in (False, True):
        assert worker.extract_text_content(b"embedded text", "application/pdf", ".pdf", deep) == "embedded text"
        artifact = worker.describe_file_evidence(str(path), deep=deep)
        assert artifact["content_text"] == "embedded text"
        assert artifact["content_hash"] == hashlib.sha256(b"embedded text").hexdigest()


def test_batch_ack_requires_matching_sequence():
    worker._artifact_batches["test-job"] = {"sequence": 3, "artifacts": []}
    try:
        assert not asyncio.run(worker.acknowledge_examination_batch("test-job", 2))["acknowledged"]
        assert asyncio.run(worker.examination_batch("test-job"))["sequence"] == 3
        assert asyncio.run(worker.acknowledge_examination_batch("test-job", 3))["acknowledged"]
        assert asyncio.run(worker.examination_batch("test-job")) == {}
    finally:
        worker._artifact_batches.pop("test-job", None)
