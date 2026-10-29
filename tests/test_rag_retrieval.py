"""Regression coverage for passage-level RAG provenance."""
from app.artifacts.service import chunk_text


def test_chunking_covers_long_text_and_preserves_passage_offsets():
    source = "alpha " * 600
    chunks = chunk_text(source)

    assert len(chunks) > 1
    assert chunks[0][0] == 0
    assert chunks[-1][1] == len(source)
    for start, end, passage in chunks:
        assert source[start:end].strip() == passage
        assert end > start


def test_chunk_passages_overlap_for_boundary_context():
    source = "x " * 2000
    chunks = chunk_text(source)
    assert len(chunks) > 1
    assert chunks[1][0] < chunks[0][1]
