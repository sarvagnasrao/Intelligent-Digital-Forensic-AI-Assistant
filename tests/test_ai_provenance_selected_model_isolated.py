"""Request-scoped model attribution and metadata passage provenance."""
from types import SimpleNamespace

from app.ui.pages.ai_analysis_page import AIAnalysisPage, AskWorker, CitationPanel


def test_selected_model_survives_worker_and_answer(config_home, monkeypatch):
    worker = AskWorker(1, "question", 7, conversation=True, model="chosen:model")
    monkeypatch.setattr(worker, "_generate", lambda *a, **k: ("answer", []))
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert results[0]["model"] == "chosen:model"

    result = {**results[0], "mode": "analysis"}
    page = SimpleNamespace(
        _active_request=7, _remove_pending=lambda: None, _set_busy=lambda busy: None,
        _add_ai_response=lambda *args: None, _save_chat_message=lambda *args, **kwargs: None,
        _conversation_history=[], save_finding_btn=SimpleNamespace(setEnabled=lambda value: None),
    )
    AIAnalysisPage._on_answer(page, result)
    assert page._last_exchange["model"] == "chosen:model"


def test_metadata_is_not_attributed_to_artifact_text(config_home, qt_app):
    worker = AskWorker(1, "image", 1)
    artifact = SimpleNamespace(
        id=1, artifact_id="ART-1-ABC", name="image.jpg", source_path="/image.jpg",
        artifact_type="image", content_text="  ", description="A file", source_size=42,
    )
    item = worker._as_item(None, artifact, score=1.0)
    assert item["citation"]["synthetic_metadata"] is True
    assert item["citation"]["provenance"] == "synthesized artifact metadata"
    assert "not extracted artifact text" in item["context"]["content_warning"]
    assert "visual contents have not been inspected" in item["context"]["content_warning"]
    panel = CitationPanel()
    panel.set_citations([item["citation"]])
    assert "offsets are not artifact text offsets" in panel.citation_list.toPlainText()
