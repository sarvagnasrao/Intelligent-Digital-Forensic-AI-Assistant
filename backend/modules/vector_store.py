from qdrant_client import QdrantClient
from qdrant_client.models import (Distance,
    VectorParams, PointStruct)
import uuid
import os
import threading
import requests

from backend.dependencies import get_settings

VECTOR_SIZE = 384

# Chunks per embed call inside store_chunks. Purely a responsiveness knob:
# smaller slices mean a shorter worst-case wait for a Stop, and more places
# for the governor to throttle. The resulting vectors are identical.
EMBED_SLICE = 16

# Local embedding model, loaded on first use.
#
# These two imports used to sit at module scope. requirements.txt no longer
# pins torch or sentence-transformers (they were removed to stop OOM crashes
# during ingestion), so on any install that follows requirements.txt they
# raised ImportError at "import backend.main" - which does not degrade the
# embedding path, it takes down the entire backend: no status endpoint, no
# queue, no cases. An optional, lazily-needed dependency must never be able to
# do that, so they are imported here instead.
#
# Note the backend is still local SentenceTransformers, despite this function's
# name. Switching to Ollama's embedder is NOT a drop-in change: MiniLM-L6-v2
# is 384-dim and matches VECTOR_SIZE, while Ollama's embedder is 768-dim, so
# every existing per-case collection would have to be rebuilt and re-indexed.
# That is a migration with its own decision, not a bug fix.
_embed_model = None
_embed_tried = False


def get_ollama_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Embeds texts locally with all-MiniLM-L6-v2 and returns 384-dim vectors.

    Keeps the historical function name so existing imports do not break.
    """
    global _embed_model, _embed_tried

    if not _embed_model:
        if _embed_tried:
            raise RuntimeError(
                "Local embedding model is unavailable. Install "
                "sentence-transformers and torch, or migrate the vector store "
                "to an Ollama embedder (which requires re-indexing, because it "
                "is 768-dim rather than 384)."
            )
        _embed_tried = True
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "Embedding requires torch and sentence-transformers, which "
                f"are not installed ({e}). They are intentionally absent from "
                "requirements.txt; see the note above this function."
            ) from e

        # This used to be torch.set_num_threads(4), hardcoded at import time
        # and applied process-wide. It was wrong twice over: it ignored how
        # many cores the machine actually has, and a global thread-pool
        # override fights the resource governor, whose entire job is to cap
        # CPU use at the ceiling the operator set. Sizing off the real core
        # count leaves the governor in charge.
        try:
            torch.set_num_threads(max(1, (os.cpu_count() or 2)))
        except Exception:
            pass
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

# Per-path client cache. Qdrant's embedded mode takes an *exclusive* lock on
# a storage directory, so this map is not just an optimisation - it is the
# thing that stops the process from opening the same folder twice.
_clients = {}
_clients_lock = threading.RLock()


def _client_key(qdrant_path: str) -> str:
    """
    Normalised absolute path, used as the client cache key.

    Normalising is mandatory, not cosmetic. Callers spell the same directory
    two different ways: cases.py builds it with os.path.join (backslashes on
    Windows) while ingestion.py, queries.py, entities.py and evidence.py
    build it with f"{cases_dir}/{case_id}/qdrant" (forward slashes). Keyed on
    the raw string those are two different keys pointing at one directory,
    the cache opens it twice, and the second open fails with
    "Storage folder ... is already accessed by another instance of Qdrant
    client". os.path.abspath also collapses the "./data/cases/..." form the
    settings default produces.
    """
    return os.path.abspath(os.path.normpath(qdrant_path))


def get_client(qdrant_path: str) -> QdrantClient:
    """
    Returns the Qdrant client for a case's storage path, one per path.

    This used to cache a single global client and ignore qdrant_path
    completely, so only the *first* case opened in a process was ever
    reachable: every later case was silently served that same client. Case B's
    chunks were therefore written into case A's storage folder, and case B's
    collection never existed - so a search over case B found nothing and the
    investigator concluded the evidence was clean. Per-case isolation is the
    whole point of a per-case collection name, and it cannot hold while the
    client is shared.

    Callers are unchanged: the public signature is the same.
    """
    global _qdrant_client
    key = _client_key(qdrant_path)
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            os.makedirs(key, exist_ok=True)
            client = QdrantClient(path=key)
            _clients[key] = client
            # Kept for anything that still introspects the old global.
            _qdrant_client = client
        return client


def close_client(qdrant_path: str) -> bool:
    """
    Closes and forgets the client for a path, releasing its directory lock.

    Without this the case directory cannot be removed on Windows: the open
    client holds the files, shutil.rmtree raises, and the case is deleted from
    the database while its vector store is left on disk. Returns True if a
    client was open.
    """
    key = _client_key(qdrant_path)
    with _clients_lock:
        client = _clients.pop(key, None)
    if client is None:
        return False
    try:
        client.close()
    except Exception as e:
        print(f"QDRANT CLOSE ERROR for {key}: {e}")
        return False
    return True


def close_all_clients() -> int:
    """Closes every cached client. Used by tests and by shutdown."""
    with _clients_lock:
        keys = list(_clients.keys())
    return sum(1 for k in keys if close_client(k))


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
                 qdrant_path: str,
                 stop_check=None) -> int:
    """
    Embeds and stores chunks in the case collection.
    Returns number of chunks stored.

    Returns 0 only when there was nothing to store. Any real failure -
    embedding backend unreachable, Qdrant refusing the upsert, an
    un-parseable embedding response - raises VectorStoreError so the job can
    be marked Failed instead of silently reporting success.

    stop_check is consulted between embed slices, not only between whole
    batches. The caller already chunks the document, but one batch is up to
    64 chunks and embedding those is the longest uninterruptible stretch in
    the document path: measured at 30s+ on a loaded 4-core box, which is long
    enough that an operator concludes the Stop button is broken. Slicing the
    embed also lets the resource governor throttle mid-batch, which it
    previously could not do at all.
    """
    if not chunks:
        return 0
    try:
        client = get_client(qdrant_path)
        collection = get_collection_name(case_id)
        ensure_collection(client, collection)

        # Embed in slices, checking for a stop between each.
        embeddings = []
        for start in range(0, len(chunks), EMBED_SLICE):
            if stop_check is not None and stop_check():
                raise StopIteration("Ingestion stopped by user")
            embeddings.extend(
                get_ollama_embeddings(chunks[start:start + EMBED_SLICE]))

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

    except StopIteration:
        # Must precede the handler below. StopIteration is a subclass of
        # Exception, so without this an operator's stop would be reported as
        # an indexing failure and the job would go red instead of Stopped.
        raise
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
    """
    Deletes entire Qdrant collection for a case, then releases the lock.

    The close is not optional. The caller goes on to remove the case's
    storage directory, and while this process still holds the client open
    that removal fails on Windows - the case disappears from the database
    while its vector store stays on disk, and reopening the case id later
    hits "Storage folder ... is already accessed by another instance".
    """
    try:
        client = get_client(qdrant_path)
        collection = get_collection_name(case_id)
        client.delete_collection(collection)
    except Exception as e:
        # A collection that was never created is not a failure worth
        # propagating: the caller's intent was for it to be gone.
        if "not found" not in str(e).lower():
            print(f"QDRANT DELETE ERROR: {e}")
    finally:
        close_client(qdrant_path)
