"""AI passage citations retain offsets into the original artifact text."""
from types import SimpleNamespace

from app.ui.pages.ai_analysis_page import AskWorker


def test_keyword_passage_offsets_include_leading_whitespace(config_home):
    worker = AskWorker(1, "needle", 1)
    text = " \n\t" + "x" * 1500 + "needle" + "y" * 1500
    artifact = SimpleNamespace(
        id=1, artifact_id="ART-1-ABC", name="note.txt", source_path="/note.txt",
        artifact_type="file", content_text=text,
    )
    item = worker._as_item(None, artifact, score=1.0)
    context, citation = item["context"], item["citation"]
    assert text[context["passage_start"]:context["passage_end"]] == context["content_text"]
    assert citation["char_start"] == context["passage_start"]
    assert citation["char_end"] == context["passage_end"]
    assert "needle" in context["content_text"]
