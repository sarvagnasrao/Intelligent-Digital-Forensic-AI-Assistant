import json

from app.analysis.llm import parse_model_answer


def test_long_quote_excerpt_contains_grounded_value_and_is_literal():
    quote = "Context " * 80 + "Alice Example arrived."
    source = "Alice Example elsewhere. " + quote
    answer = json.dumps([{"type": "person", "value": "Alice Example", "quote": quote}])

    entity = parse_model_answer(answer, source)[0]
    excerpt = entity.metadata["quote"]
    assert len(excerpt) <= 300
    assert entity.value in excerpt
    assert excerpt in quote
    assert source[entity.start:entity.end] == entity.value
