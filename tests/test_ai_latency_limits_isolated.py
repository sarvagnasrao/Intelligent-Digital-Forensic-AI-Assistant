import asyncio

from app.ui.pages.ai_analysis_page import _interactive_output_limit
from worker.main import GenerateRequest, generate


def test_interactive_limit_is_configurable(monkeypatch):
    monkeypatch.delenv("IDFA_AI_INTERACTIVE_MAX_TOKENS", raising=False)
    assert _interactive_output_limit(2048) == 2048
    assert _interactive_output_limit(300) == 300
    monkeypatch.setenv("IDFA_AI_INTERACTIVE_MAX_TOKENS", "1024")
    assert _interactive_output_limit(2048) == 1024


def test_oversized_evidence_is_rejected_before_model_call(monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("model must not be called")

    monkeypatch.setattr("worker.main.call_ollama", unexpected)
    result = asyncio.run(generate(GenerateRequest(
        case_id=1, question="synthetic", context_window_tokens=2048,
        max_tokens=512, context_artifacts=[{"content_text": "x" * 10000}],
    )))
    assert not result.success
    assert "context budget" in result.error
