"""Semantic embeddings through the local Ollama runtime.

Ollama serves ``all-minilm``, which is the same ``all-MiniLM-L6-v2`` model that
earlier builds loaded through sentence-transformers. It produces identical
384-dimension unit vectors, so vectors already stored in Qdrant stay valid and
no re-indexing is needed.

Keeping embeddings in Ollama removes torch, transformers and the duplicated
~900 MB model folder from the installation, at the cost of an HTTP round trip
that is amortised by batching whole ranges of artifacts per request.
"""
from __future__ import annotations

import logging

import httpx

from app.config import cloud_api_key, get_config

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "all-minilm"
DEFAULT_BATCH_SIZE = 64


class EmbeddingError(RuntimeError):
    """Raised when the embedding service cannot produce vectors."""


def model_id() -> str:
    """Configured embedding model name, as Ollama knows it."""
    return (get_config().embeddings.model_id or "").strip() or DEFAULT_MODEL


def host() -> str:
    """Ollama endpoint without a trailing slash."""
    return get_config().ollama.host.rstrip("/")


def batch_size() -> int:
    return max(1, int(get_config().embeddings.batch_size or DEFAULT_BATCH_SIZE))


def _timeout() -> float:
    # Embedding a batch is fast, but the first call loads the model, and a
    # busy Ollama can queue behind a chat request. Use the AI timeout rather
    # than failing a large index run on a slow first batch.
    return float(get_config().ollama.timeout_seconds)


def model_available() -> bool:
    """True when Ollama is reachable and has the embedding model pulled.

    Deliberately cheap and side-effect free: it must be safe to call from the
    status strip on every refresh, and it must never trigger a download.
    """
    wanted = model_id()
    config = get_config()
    if config.embeddings.provider == "openai":
        return bool(cloud_api_key(config).strip())
    try:
        response = httpx.get(f"{host()}/api/tags", timeout=5.0)
        if response.status_code != 200:
            return False
        names = [item.get("name", "") for item in response.json().get("models", [])]
    except Exception:
        return False
    return any(name == wanted or name.startswith(f"{wanted}:") for name in names)


def pull_model() -> str:
    """Ask Ollama to fetch the embedding model; returns the model name.

    This is the only path that touches the network, and it is only called when
    a user explicitly asks for it. On the offline bundle the model is already
    present, so this returns immediately.
    """
    wanted = model_id()
    try:
        response = httpx.post(
            f"{host()}/api/pull",
            json={"model": wanted, "stream": False},
            timeout=float(get_config().ollama.timeout_seconds),
        )
    except Exception as exc:
        raise EmbeddingError(f"Could not reach Ollama at {host()}: {exc}") from exc
    if response.status_code != 200:
        raise EmbeddingError(
            f"Ollama returned HTTP {response.status_code} while pulling {wanted}"
        )
    return wanted


def embed_texts(texts: list[str], *, batch: int | None = None) -> list[list[float]]:
    """Embed ``texts`` and return one vector per input, in order.

    Requests are split into batches so a large index run does not build one
    enormous JSON body, while still paying HTTP overhead per batch instead of
    per artifact.
    """
    if not texts:
        return []

    size = batch or batch_size()
    expected_dimensions = int(get_config().qdrant.vector_size)
    vectors: list[list[float]] = []

    # Ollama rejects an empty string, so blank artifacts are embedded as a
    # single space: the position count must match the artifact count, because
    # callers pair vectors with records by index.
    prepared = [text if text and text.strip() else " " for text in texts]

    for start in range(0, len(prepared), size):
        chunk = prepared[start:start + size]
        try:
            config = get_config()
            if config.embeddings.provider == "openai":
                key = cloud_api_key(config)
                if not key.strip():
                    raise EmbeddingError(
                        "Cloud embeddings are selected, but the API key is missing in Settings."
                    )
                body = {"model": model_id(), "input": chunk}
                if model_id().startswith("text-embedding-3"):
                    body["dimensions"] = expected_dimensions
                response = httpx.post(
                    f"{config.ollama.cloud_base_url.rstrip('/')}/embeddings",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                    timeout=_timeout(),
                )
            else:
                response = httpx.post(
                    f"{host()}/api/embed",
                    json={"model": model_id(), "input": chunk, "options": {"num_gpu": 0}},
                    timeout=_timeout(),
                )
        except Exception as exc:
            if isinstance(exc, EmbeddingError):
                raise
            provider_name = (
                "cloud embedding provider"
                if get_config().embeddings.provider == "openai"
                else f"Ollama at {host()}"
            )
            raise EmbeddingError(
                f"Could not reach {provider_name}: {exc}"
            ) from exc

        if response.status_code != 200:
            detail = response.text[:300]
            provider = "cloud provider" if get_config().embeddings.provider == "openai" else "Ollama"
            raise EmbeddingError(
                f"{provider} embedding request failed (HTTP {response.status_code}). "
                f"Check that {model_id()} is pulled. {detail}"
            )

        if get_config().embeddings.provider == "openai":
            data = response.json().get("data") or []
            data.sort(key=lambda row: row.get("index", 0))
            batch_vectors = [row.get("embedding", []) for row in data]
        else:
            batch_vectors = response.json().get("embeddings") or []
        if len(batch_vectors) != len(chunk):
            raise EmbeddingError(
                f"Ollama returned {len(batch_vectors)} vectors for {len(chunk)} texts"
            )
        for vector in batch_vectors:
            if len(vector) != expected_dimensions:
                raise EmbeddingError(
                    f"{model_id()} produced {len(vector)}-dimension vectors but Qdrant "
                    f"is configured for {expected_dimensions}. Reconcile the model and "
                    "vector size before indexing."
                )
            vectors.append(list(vector))

    return vectors


def embed_text(text: str) -> list[float]:
    """Embed one string, for interactive search."""
    if not text or not text.strip():
        return []
    return embed_texts([text])[0]
