import asyncio
import json

from app.analysis.llm import AnalysisLLM, LLMResult, parse_model_answer


def answer(value, quote):
    return json.dumps([{"type": "person", "value": value, "quote": quote}])


def test_model_quote_must_contain_value_and_match_source_literally():
    source = "Alice met Bob. Carol called later."
    assert not parse_model_answer(answer("Alice", "Carol called later"), source)
    assert not parse_model_answer(answer("Alice", "alice met Bob"), source)
    assert not parse_model_answer(answer("Alice", "Alice  met Bob"), source)
    assert not parse_model_answer(answer("alice", "Alice met Bob"), source)
    assert len(parse_model_answer(answer("Alice", "Alice met Bob"), source)) == 1


def test_model_offset_points_to_quoted_occurrence_in_original_text():
    source = "  Alice appears earlier. " + "x" * 30 + " Bob met Alice."
    client = AnalysisLLM.__new__(AnalysisLLM)
    client.available = lambda: True

    async def ask(_prompt):
        return LLMResult([], answer=answer("Alice", "Bob met Alice"))

    client._ask = ask
    result = asyncio.run(client.extract_named_entities(source))
    entity = result.entities[0]
    assert entity.start == source.rfind("Alice")
    assert source[entity.start:entity.end] == entity.value
