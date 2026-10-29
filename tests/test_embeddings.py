"""Ollama embedding client: batching, ordering and failure handling."""
from __future__ import annotations

import pytest

from app.ai import embeddings


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def embedding_config(config_home, data_dir, monkeypatch):
    """A saved config with a small batch size so batching is observable."""
    from app.config import Config, save_config, set_data_dir

    config = set_data_dir(Config(), data_dir)
    config.embeddings.batch_size = 2
    save_config(config)
    monkeypatch.setattr(embeddings, "host", lambda: "http://ollama.test")
    return config


def test_embeds_in_batches_and_keeps_order(embedding_config, monkeypatch):
    calls: list[list[str]] = []

    def fake_post(url, json, timeout):  # noqa: A002 - mirrors httpx signature
        calls.append(list(json["input"]))
        return FakeResponse(
            200,
            {"embeddings": [[float(len(text))] * 384 for text in json["input"]]},
        )

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    vectors = embeddings.embed_texts(["a", "bb", "ccc", "dddd", "eeeee"])

    assert len(vectors) == 5
    # batch_size is 2, so five texts become three requests.
    assert [len(call) for call in calls] == [2, 2, 1]
    assert [len(vector) for vector in vectors] == [384] * 5
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0
    assert vectors[4][0] == 5.0


def test_blank_texts_are_replaced_not_dropped(embedding_config, monkeypatch):
    sent: list[str] = []

    def fake_post(url, json, timeout):  # noqa: A002
        sent.extend(json["input"])
        return FakeResponse(200, {"embeddings": [[0.0] * 384 for _ in json["input"]]})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    vectors = embeddings.embed_texts(["text", "", "   "])

    assert len(vectors) == 3
    assert sent == ["text", " ", " "]


def test_wrong_dimension_is_reported(embedding_config, monkeypatch):
    monkeypatch.setattr(
        embeddings.httpx,
        "post",
        lambda url, json, timeout: FakeResponse(200, {"embeddings": [[0.0] * 128]}),
    )

    with pytest.raises(embeddings.EmbeddingError) as excinfo:
        embeddings.embed_texts(["text"])

    assert "128" in str(excinfo.value)
    assert "384" in str(excinfo.value)


def test_count_mismatch_is_reported(embedding_config, monkeypatch):
    monkeypatch.setattr(
        embeddings.httpx,
        "post",
        lambda url, json, timeout: FakeResponse(200, {"embeddings": []}),
    )

    with pytest.raises(embeddings.EmbeddingError):
        embeddings.embed_texts(["one", "two"])


def test_http_error_mentions_the_model(embedding_config, monkeypatch):
    monkeypatch.setattr(
        embeddings.httpx,
        "post",
        lambda url, json, timeout: FakeResponse(500, {"error": "boom"}),
    )

    with pytest.raises(embeddings.EmbeddingError) as excinfo:
        embeddings.embed_texts(["text"])

    assert "all-minilm" in str(excinfo.value)


def test_connection_error_becomes_embedding_error(embedding_config, monkeypatch):
    def explode(url, json, timeout):  # noqa: A002
        raise OSError("no route to host")

    monkeypatch.setattr(embeddings.httpx, "post", explode)

    with pytest.raises(embeddings.EmbeddingError) as excinfo:
        embeddings.embed_texts(["text"])

    assert "Could not reach Ollama" in str(excinfo.value)


def test_no_texts_makes_no_request(embedding_config, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("should not have been called")

    monkeypatch.setattr(embeddings.httpx, "post", fail)
    assert embeddings.embed_texts([]) == []


def test_empty_single_text_returns_empty(embedding_config):
    assert embeddings.embed_text("") == []
    assert embeddings.embed_text("   ") == []


def test_model_available_checks_the_tag_list(embedding_config, monkeypatch):
    monkeypatch.setattr(
        embeddings.httpx,
        "get",
        lambda url, timeout: FakeResponse(
            200, {"models": [{"name": "phi3:mini"}, {"name": "all-minilm:latest"}]}
        ),
    )
    assert embeddings.model_available() is True


def test_model_available_is_false_when_missing(embedding_config, monkeypatch):
    monkeypatch.setattr(
        embeddings.httpx,
        "get",
        lambda url, timeout: FakeResponse(200, {"models": [{"name": "phi3:mini"}]}),
    )
    assert embeddings.model_available() is False


def test_model_available_survives_an_offline_runtime(embedding_config, monkeypatch):
    def offline(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(embeddings.httpx, "get", offline)
    assert embeddings.model_available() is False


def test_invalid_batch_size_never_breaks_the_loop(embedding_config, monkeypatch):
    calls: list[int] = []

    def fake_post(url, json, timeout):  # noqa: A002
        calls.append(len(json["input"]))
        return FakeResponse(200, {"embeddings": [[0.0] * 384 for _ in json["input"]]})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    # Zero means "unset", so the configured default (64) applies.
    embedding_config.embeddings.batch_size = 0
    embeddings.embed_texts(["a", "b"])
    assert calls == [2]

    # A negative batch size clamps to one instead of raising from range().
    embedding_config.embeddings.batch_size = -5
    embeddings.embed_texts(["a", "b"])
    assert calls == [2, 1, 1]
