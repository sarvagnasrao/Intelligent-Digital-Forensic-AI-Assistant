from qdrant_client import QdrantClient
from qdrant_client.models import (Distance,
    VectorParams, PointStruct)
import uuid
import os
import threading
import requests
from typing import Optional

from backend.dependencies import get_settings

VECTOR_SIZE = 384

# Chunks per embed call inside store_chunks. Purely a responsiveness knob:
# smaller slices mean a shorter worst-case wait for a Stop, and more places
# for the governor to throttle. The resulting vectors are identical.
EMBED_SLICE = 16

# Resolved once, because it consults the disk and the settings on first use.
_resolved_qdrant_dir: Optional[str] = None


def resolve_qdrant_dir() -> str:
    """
    Base directory holding every per-case Qdrant index.

    Resolution order:

    1. ``QDRANT_DIR``, when set explicitly.
    2. A fast (SSD) location, when the cases directory is on a rotating disk.
    3. The cases directory, when it is already on a fast disk - no split.

    Why (2) exists: the per-point Qdrant upsert is ~92% of a document
    ingestion (measured: 47s of 81s for a 2.7 MB file, against 3s for the
    embedding and 3s for everything else combined). That cost is dominated by
    disk *seek latency*, not CPU, so it measures ~13x slower on a 7200 RPM
    SATA disk than on the NVMe system disk. The index is derived data -
    rebuildable by re-ingesting the evidence - so keeping it on the fast disk
    costs nothing in forensic integrity, and the evidence itself stays where
    the operator put it.

    Returns the cases directory unchanged when the disk type cannot be
    determined: an unknown disk is not evidence of an SSD, and the caller
    must not move data onto a drive it has misidentified.
    """
    global _resolved_qdrant_dir
    if _resolved_qdrant_dir:
        return _resolved_qdrant_dir

    settings = get_settings()
    configured = (settings.qdrant_dir or "").strip()
    if configured:
        _resolved_qdrant_dir = os.path.normpath(configured)
        return _resolved_qdrant_dir

    # abspath first: cases_dir is usually relative ("./data/cases"), and
    # splitdrive on a relative path returns an empty drive - which would fall
    # through to the system drive and conclude the cases dir is already fast.
    cases_dir = os.path.abspath(os.path.normpath(settings.cases_dir or "."))
    # The Windows system drive, NOT the current working directory: the backend
    # is routinely started from the repo, which on this box is on D:, and
    # treating the CWD as "the system drive" would conclude that the cases dir
    # is already on the fast disk and skip the split.
    system_drive = (os.environ.get("SystemDrive", "C:")
                    .rstrip(":") or "C")
    cases_drive = (os.path.splitdrive(cases_dir)[0]
                   .rstrip(":") or system_drive)

    # Already on the system (fast) disk - nothing to gain from a split.
    if cases_drive.upper() == system_drive.upper():
        _resolved_qdrant_dir = cases_dir
        return _resolved_qdrant_dir

    from backend.modules.hardware_probe import disk_media_type
    if disk_media_type(cases_dir) == "HDD":
        # User-writable by construction: %LOCALAPPDATA% needs no elevation,
        # unlike the system-drive root.
        base = os.environ.get("LOCALAPPDATA") or (system_drive + os.sep)
        target = os.path.join(base, "IDFA", "qdrant")
        print(f"[QDRANT] cases dir is on a rotating disk ({cases_drive}:); "
              f"putting the vector index on the faster {system_drive}: disk at "
              f"{target}. Set QDRANT_DIR to override.")
        _resolved_qdrant_dir = target
        return _resolved_qdrant_dir

    _resolved_qdrant_dir = cases_dir
    return _resolved_qdrant_dir


def case_qdrant_path(case_id: str) -> str:
    """
    The Qdrant storage path for one case. The single source of truth.

    This replaces the ``f"{cases_dir}/{case_id}/qdrant"`` literal that was
    duplicated across ingestion.py, queries.py, entities.py, evidence.py and
    cases.py - and spelled two different ways (os.path.join vs a forward-slash
    f-string), which is the B14 trap where one directory was opened under two
    different cache keys. Routing every caller through here means the storage
    location can change once, in one place, and the per-case client cache can
    never again hold two keys for one directory.
    """
    return os.path.join(resolve_qdrant_dir(), case_id, "qdrant")


def migrate_qdrant_layout() -> int:
    """
    Move per-case Qdrant indexes from the old in-cases location to wherever
    ``resolve_qdrant_dir()`` now points.

    A no-op (returns 0) when QDRANT_DIR is unset and the cases directory is
    already on a fast disk - the common case on an all-SSD box. Returns the
    number of collections moved.

    A collection that already exists at the destination is left alone rather
    than overwritten: two indexes for one case is a problem, but silently
    destroying one is a worse one.
    """
    import shutil

    new_base = resolve_qdrant_dir()
    settings = get_settings()
    old_base = os.path.normpath(settings.cases_dir or ".")
    if os.path.normpath(new_base) == old_base:
        return 0
    if not os.path.isdir(old_base):
        return 0

    moved = 0
    for name in os.listdir(old_base):
        old_path = os.path.join(old_base, name, "qdrant")
        if not os.path.isdir(old_path):
            continue
        new_path = os.path.join(new_base, name, "qdrant")
        if os.path.exists(new_path):
            print(f"[QDRANT] {new_path} already exists - leaving "
                  f"{old_path} in place rather than overwriting it.")
            continue
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(old_path, new_path)
            moved += 1
        except Exception as e:
            print(f"[QDRANT] could not move {old_path} -> {new_path}: {e}")
    if moved:
        print(f"[QDRANT] moved {moved} collection(s) to {new_base}")
    return moved

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

    Returns [] ONLY when the search genuinely matched nothing.

    This used to end in `except Exception: print(...); return []`, which made
    a broken index indistinguishable from a clean one — and those two states
    produce opposite findings. "Nothing in this case matched that question"
    is the answer that clears a suspect; if a locked Qdrant directory, a
    missing collection or a dead embedder produces it, the tool is
    reporting an absence of evidence that it never actually looked for. That
    is this repo's defining defect (B1, B10, B11, B19, B23) in the one place
    where the consequence is a person's freedom rather than a stale row.

    So it raises instead, exactly as `store_chunks` does. A caller that
    swallows this now has to work much harder to be wrong in the same way.
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

    except StopIteration:
        # Must precede the handler below: StopIteration is a subclass of
        # Exception, so without this an operator's stop would be reported as
        # an index fault.
        raise
    except Exception as e:
        raise VectorStoreError(
            f"Could not search case {case_id} for "
            f"{'evidence ' + str(evidence_id) if evidence_id else 'the case'}"
            f" (top_k={top_k}): {type(e).__name__}: {e}"
        ) from e


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
