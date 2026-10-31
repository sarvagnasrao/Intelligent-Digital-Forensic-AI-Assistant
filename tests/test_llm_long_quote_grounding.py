import asyncio
import json

from app.analysis.llm import AnalysisLLM, LLMResult, parse_model_answer


def test_long_quote_offsets_point_inside_verified_quote():
    quote = "Context " * 40 + "Alice Example arrived."
    source = "Alice Example elsewhere. " + quote
    answer = json.dumps([{"type": "person", "value": "Alice Example", "quote": quote}])

    entity = parse_model_answer(answer, source)[0]
    expected = source.index(quote) + quote.index("Alice Example")
    assert (entity.start, entity.end) == (expected, expected + len(entity.value))
    assert len(entity.metadata["quote"]) == 300


def test_windowed_extraction_preserves_grounded_offset():
    quote = "Context " * 40 + "Alice Example arrived."
    source = "Alice Example elsewhere. " + quote
    answer = json.dumps([{"type": "person", "value": "Alice Example", "quote": quote}])
    client = AnalysisLLM(config=object())
    client.available = lambda: True

    async def ask(_prompt):
        return LLMResult([], answer=answer)

    client._ask = ask
    result = asyncio.run(client.extract_named_entities(source))
    entity = result.entities[0]
    expected = source.index(quote) + quote.index("Alice Example")
    assert (entity.start, entity.end) == (expected, expected + len(entity.value))
