from qdrant_client import QdrantClient
from qdrant_client.models import (Distance,
    VectorParams, PointStruct)
import uuid
import os

import torch
torch.set_num_threads(4)
from sentence_transformers import SentenceTransformer

VECTOR_SIZE = 384
import requests
from backend.dependencies import get_settings

# Initialize model once globally so it doesn't reload on every batch
# all-MiniLM-L6-v2 is extremely fast on CPU
_embed_model = None

def get_ollama_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Replaced with SentenceTransformers for much faster CPU embedding.
    Keeps the same function name to avoid breaking imports.
    """
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer('all-MiniLM-L6-v2')
    
    truncated = [t[:1000] for t in texts]
    embeddings = _embed_model.encode(truncated)
    return embeddings.tolist()


def get_collection_name(case_id: str) -> str:
    """
    Each case gets its own Qdrant collection.
    Format: case_{case_id_first_8_chars}
    """
    return f"case_{case_id[:8]}"


_qdrant_client = None

def get_client(qdrant_path: str) -> QdrantClient:
    """Returns Qdrant client for given path, cached globally."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(path=qdrant_path)
    return _qdrant_client


def ensure_collection(client: QdrantClient,
                       collection_name: str):
    """Creates collection if it does not exist."""
    existing = [c.name for c in
                client.get_collections().collections]
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE
            )
        )


class VectorStoreError(RuntimeError):
    """
    Raised when chunks could not be embedded or stored.

    This used to be a bare `print(...)` plus `return 0`, which made a broken
    index indistinguishable from a document that legitimately had no text:
    the caller saw 0 either way and went on to report "Completed - 0 chunks"
    with the evidence marked Indexed. That is the same silent-success defect
    that made a truncated disk image look processed, and it is worse here
    because the investigator then searches a case that has nothing in it and
    concludes the evidence was clean.
    """


def store_chunks(chunks: list[str],
                 source_filename: str,
                 evidence_id: str,
                 case_id: str,
                 qdrant_path: str) -> int:
    """
    Embeds and stores chunks in the case collection.
    Returns number of chunks stored.

    Returns 0 only when there was nothing to store. Any real failure -
    Ollama unreachable, Qdrant refusing the upsert, an un-parseable
    embedding response - raises VectorStoreError so the job can be marked
    Failed instead of silently reporting success.
    """
    if not chunks:
        return 0
    try:
        client = get_client(qdrant_path)
        collection = get_collection_name(case_id)
        ensure_collection(client, collection)

        # Batch encode all chunks via local Ollama API
        embeddings = []
        if chunks:
            embeddings = get_ollama_embeddings(chunks)

        points = []
        for i, chunk in enumerate(chunks):
            embedding = embeddings[i]
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "text": chunk,
                    "source": source_filename,
                    "evidence_id": evidence_id,
                    "case_id": case_id,
                    "chunk_index": i
                }
            ))

        client.upsert(
            collection_name=collection,
            points=points
        )
        return len(points)

    except Exception as e:
        # Loudly, and with the underlying reason attached. A caller that
        # swallows this has to work much harder to be wrong in the same way.
        raise VectorStoreError(
            f"Could not index {len(chunks)} chunk(s) from "
            f"'{source_filename}' (evidence {evidence_id}): {type(e).__name__}: "
            f"{e}"
        ) from e


def search_chunks(query: str,
                  case_id: str,
                  qdrant_path: str,
                  top_k: int = 7,
                  evidence_id: str = None
                  ) -> list[dict]:
    """
    Searches for semantically similar chunks.
    Optionally filters by evidence_id.
    """
    try:
        client = get_client(qdrant_path)
        collection = get_collection_name(case_id)
        query_vector = get_ollama_embeddings([query])[0]

        query_filter = None
        if evidence_id:
            from qdrant_client.models import (
                Filter, FieldCondition, MatchValue)
            query_filter = Filter(
                must=[FieldCondition(
                    key="evidence_id",
                    match=MatchValue(value=evidence_id)
                )]
            )

        results = client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=query_filter
        )

        return [{
            "text": r.payload.get("text", ""),
            "source": r.payload.get("source", ""),
            "evidence_id": r.payload.get(
                "evidence_id", ""),
            "chunk_index": r.payload.get(
                "chunk_index", 0),
            "score": round(r.score, 3)
        } for r in results]

    except Exception as e:
        print(f"QDRANT SEARCH ERROR: {e}")
        return []


def delete_case_collection(case_id: str,
                            qdrant_path: str):
    """Deletes entire Qdrant collection for a case."""
    try:
        client = get_client(qdrant_path)
        collection = get_collection_name(case_id)
        client.delete_collection(collection)
    except Exception as e:
        print(f"QDRANT DELETE ERROR: {e}")
