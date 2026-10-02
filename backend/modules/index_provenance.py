"""
What produced a vector index, and whether the current configuration may search it.

A Qdrant collection knows nothing about what wrote it. It holds 384-dimensional
floats and a payload, and it will happily answer a query from vectors produced
by a different embedder, at a different window, or at a different granularity
than the ones already in it -- returning a ranked list with confident scores and
no indication that the comparison is meaningless. `search_chunks` did not check,
because there was nothing recorded to check against.

That matters here more than it would in an ordinary app. This repository's
defining defect is a true-shaped message carrying no information (B1, B10, B11,
B19, B23, B30): a stale index searched with a new embedder produces
"nothing in this case matched that question", which is the answer that clears a
suspect. A refusal is strictly better than a confident wrong ranking.

Two kinds of difference, deliberately treated differently:

**HARD -- refuse to search.**
    `embedder_id`, `vector_size`, `max_seq_length`. If any of these differs from
    what is loaded now, the stored vectors and the query vector are not in the
    same space, or the stored ones were truncated at a different point inside
    each chunk. Similarity scores across such vectors are not merely
    imprecise, they are undefined. This is the case the guard exists for.

**SOFT -- report, do not refuse.**
    The chunking scheme. A collection indexed at several granularities returns
    *worse but valid* results: retrieval still works, it is just coarse in some
    places. Refusing would break every case in the migration window for no
    safety gain. So the schemes are accumulated and surfaced instead. That makes
    a real and currently invisible inconsistency legible -- today's chunk size
    *is* the ingestion profile, so a case worked in `fastest` and then in
    `accurate` holds a mosaic of granularities and presents as one consistent
    index.

Storage is a JSON sidecar inside the per-case Qdrant directory, not a payload
field, for three reasons:

1. It is deleted with the case directory, so it cannot outlive the index or
   migrate to another case (B14's lesson: one directory, one case).
2. It is readable **without opening a QdrantClient**. Embedded mode takes an
   exclusive lock per storage directory, so a health probe that opened one
   would collide with the running application.
3. It is not returned by a search, so it cannot perturb retrieval.

`signature_version` exists so a future change to the hard set is detectable
rather than silently incomparable. An index written by an older signature
version reads as `unattributed`, which is the honest verdict: we cannot check
what we do not know how to check.

Stdlib only, no qdrant import, no torch import. A guard that could take the
backend down would be the B15 defect again.
"""

import json
import os
import tempfile
import time

# Bumped whenever the HARD fields change meaning. An index written under a
# different version cannot be compared field-by-field, so it reads as
# unattributed rather than as a match or a mismatch.
SIGNATURE_VERSION = 1

PROVENANCE_FILENAME = "idfa_provenance.json"

# The fields a mismatch on which makes similarity undefined. Compared exactly.
HARD_FIELDS = ("embedder_id", "vector_size", "max_seq_length")

# Declared specifications for the embedders this build knows about.
#
# This is what lets `service_health.probe_vector_store` render a verdict without
# loading torch -- it may not import it, deliberately, because a health page must
# not pay for (or fail on) the embedding stack just to count directories.
#
# It is a *declaration*, not a measurement. `vector_store.describe_embedder()`
# measures the loaded model and `check_declaration()` reports any disagreement
# between the two rather than letting either be silently trusted. The measured
# value is what gets written; the declaration only ever produces the warning.
EMBEDDER_SPECS = {
    "all-MiniLM-L6-v2": {
        "vector_size": 384,
        # The tokenizer's own cap is 512; the model config's max_seq_length is
        # 256, and that is what actually truncates. Measured on this corpus at
        # 2.01-3.08 chars/token, i.e. a ~513-788 CHARACTER window, which is why
        # the embedding window rather than chunk size decides coverage.
        "max_seq_length": 256,
    },
}

# Verdicts. Every one of these is a *measured* state, never a default.
MATCH = "match"              # signature verified against the live embedder
MISMATCH = "mismatch"        # hard fields differ -- must not be searched
UNATTRIBUTED = "unattributed"  # index exists, nothing recorded what wrote it
NEVER_INDEXED = "never_indexed"  # no index at all


def provenance_path(qdrant_path: str) -> str:
    """Where the sidecar for one case's index lives."""
    return os.path.join(qdrant_path, PROVENANCE_FILENAME)


def read_provenance(qdrant_path: str):
    """
    The recorded provenance, or None.

    None is returned for "no record", "unreadable record" and "corrupt record"
    alike on purpose: from the caller's side those are one state -- we do not
    know what wrote this index -- and treating them differently would mean
    inventing a distinction the data does not support. `read_record_error`
    exposes the difference for the health page, where a corrupt file is
    actionable and a missing one is not.
    """
    try:
        with open(provenance_path(qdrant_path), "r", encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    return record


def read_record_error(qdrant_path: str):
    """Why there is no usable record, or None when there simply is not one."""
    path = provenance_path(qdrant_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            record = json.load(fh)
    except OSError as e:
        return f"unreadable: {type(e).__name__}: {e}"
    except ValueError as e:
        return f"corrupt JSON: {e}"
    if not isinstance(record, dict):
        return f"corrupt: top level is {type(record).__name__}, expected object"
    return None


def index_exists(qdrant_path: str) -> bool:
    """
    Whether an index is actually there.

    Directory presence is the honest test available without opening Qdrant: a
    collection cannot exist in a directory that does not. It deliberately does
    NOT look for the sidecar, because the sidecar is the record *about* the
    index, and a record is not the thing being recorded.
    """
    return bool(qdrant_path) and os.path.isdir(qdrant_path)


def _signature_of(record):
    return {k: record.get(k) for k in HARD_FIELDS}


def declared_signature(embedder_id: str = None):
    """
    What this build *says* it embeds with, from the table above.

    Returns None for an embedder the table has never heard of. An unknown model
    is not a mismatch and not a match: without a declaration there is nothing
    to compare against, and inventing one would be the fabricated-zero shape.
    """
    embedder_id = embedder_id or next(iter(EMBEDDER_SPECS))
    spec = EMBEDDER_SPECS.get(embedder_id)
    if spec is None:
        return None
    sig = {"embedder_id": embedder_id}
    sig.update(spec)
    return sig


def check_declaration(measured):
    """
    Compare a measured signature against the declared table.

    Returns a list of disagreement strings, empty when they agree. Called once
    per process, when the model loads.

    The point is that neither side is trusted silently: if a build raises
    max_seq_length to 512 by hand, the mismatch is reported once, loudly, with
    both numbers -- rather than the health page comparing recorded signatures
    against a stale declaration and declaring a good index stale, or the
    converse.
    """
    problems = []
    if not measured:
        return ["no measured signature"]
    declared = declared_signature(measured.get("embedder_id"))
    if declared is None:
        return [
            f"embedder {measured.get('embedder_id')!r} is not in "
            "EMBEDDER_SPECS, so the health page cannot classify any index it "
            "wrote"
        ]
    for key in HARD_FIELDS:
        want, got = declared.get(key), measured.get(key)
        if want != got:
            problems.append(
                f"{key}: loaded model reports {got!r}, EMBEDDER_SPECS declares "
                f"{want!r}"
            )
    return problems


def compare(record, measured, qdrant_path: str):
    """
    Decide whether `record`'s index may be searched by `measured` config.

    `measured` is the signature of the embedder that is loaded *now*, as
    measured by `vector_store.describe_embedder()`.

    `qdrant_path` is needed to tell "no record" from "no index" -- two states
    with opposite meanings, and the same `None`. It is passed in rather than
    reached for through module state on purpose: the backend serves requests on
    a thread pool, and a module-level holder of the last path checked would be a
    race between two cases being queried at once.

    Returns (verdict, reason). The reason is written for an investigator, and
    is None only when there is nothing to say.
    """
    if record is None:
        if not index_exists(qdrant_path):
            return (NEVER_INDEXED,
                    "this case has no vector index at all.")
        return (UNATTRIBUTED,
                "this case's index carries no provenance record, so "
                "nothing can confirm which embedder wrote it. It was "
                "written before provenance was recorded.")

    if not measured:
        # No declaration and no measurement - there is nothing to compare
        # against. Returning MATCH here would be the fabricated-verdict shape
        # this whole module exists to avoid: an index nobody checked reporting
        # as checked. Found by the suite asserting `survey(paths, None)`
        # survives; production guards the call site, but a guard that crashes on
        # its own absent input is one refactor away from taking down the query
        # path.
        return (UNATTRIBUTED,
                "this build cannot state which embedder it uses, so this "
                "index cannot be verified either way. Nothing confirms it is "
                "current, and nothing says it is not.")

    if record.get("signature_version") != SIGNATURE_VERSION:
        return (UNATTRIBUTED,
                f"this case's index was written under signature version "
                f"{record.get('signature_version')!r} and this build uses "
                f"{SIGNATURE_VERSION}, so its embedder cannot be confirmed.")

    diffs = []
    for key in HARD_FIELDS:
        was, now = record.get(key), measured.get(key)
        if was != now:
            diffs.append(f"{key} {was!r} -> {now!r}")
    if diffs:
        return (MISMATCH,
                "this case's index was built with a different embedding "
                "configuration (" + "; ".join(diffs) + "), so its vectors "
                "cannot be compared against queries embedded now. Re-ingest "
                "the evidence to rebuild it.")

    return (MATCH, None)


def check_index(qdrant_path: str, measured) -> dict:
    """
    The full verdict for one case: state, reason, and the record if any.

    This is the function both `store_chunks` and `search_chunks` call, so the
    two can never disagree about whether an index is usable.
    """
    record = read_provenance(qdrant_path)
    state, reason = compare(record, measured, qdrant_path)
    return {
        "state": state,
        "reason": reason,
        "record": record,
        "record_error": read_record_error(qdrant_path),
        "chunking_schemes": (record or {}).get("chunking_schemes") or [],
    }


def _atomic_write(qdrant_path: str, payload: dict):
    """
    Write the sidecar without leaving a truncated file behind.

    A half-written JSON file reads as corrupt, and a corrupt record reads as
    `unattributed` -- which would turn a successful ingest into a case whose
    provenance cannot be confirmed. Write to a temporary file in the same
    directory (so os.replace stays on one filesystem and is therefore atomic)
    and swap it in.
    """
    os.makedirs(qdrant_path, exist_ok=True)
    target = provenance_path(qdrant_path)
    fd, tmp = tempfile.mkstemp(prefix=".idfa_prov_", suffix=".tmp",
                               dir=qdrant_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        # A stop sentinel can arrive here (the caller checks between slices),
        # and leaving the temporary file behind would litter the index dir.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_write(qdrant_path: str,
                 measured: dict,
                 chunking=None,
                 evidence_id: str = None,
                 source_filename: str = None,
                 chunks: int = None) -> dict:
    """
    Fold one successful store into the case's provenance record.

    `measured` is the signature of the embedder that actually produced the
    vectors just written -- never a declaration, because the declaration is the
    thing being checked.

    Chunking schemes accumulate rather than overwrite, and `last_write` records
    only what is history and cannot drift: the evidence it came from and how
    many chunks that write added. No running point count is kept, because
    archiving deletes points while leaving this file (B29's `chunk_count`
    lesson) -- a retained total that no longer matches the collection is the
    same kind of lie.
    """
    existing = read_provenance(qdrant_path) or {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    schemes = list(existing.get("chunking_schemes") or [])
    scheme = _scheme_label(chunking)
    if scheme and scheme not in schemes:
        schemes.append(scheme)
        schemes.sort()

    record = {
        "signature_version": SIGNATURE_VERSION,
        "first_written": existing.get("first_written") or now,
        "last_written": now,
        "writes": int(existing.get("writes") or 0) + 1,
        "chunking_schemes": schemes,
    }
    record.update(_signature_of(measured))

    if scheme:
        record["last_write"] = {
            "chunking": scheme,
            "evidence_id": evidence_id,
            "source_filename": source_filename,
            "chunks": chunks,
        }

    _atomic_write(qdrant_path, record)
    return record


def _scheme_label(chunking):
    """Render a chunking scheme as the short stable label shown in the UI."""
    if not chunking:
        return None
    if isinstance(chunking, str):
        return chunking
    size = chunking.get("chunk_size")
    overlap = chunking.get("chunk_overlap")
    if size is None:
        return None
    return f"{size}/{overlap if overlap is not None else 0}"


def clear_provenance(qdrant_path: str) -> bool:
    """
    Drop the record, because the index it described is being deleted.

    Returns True when a file was actually removed.

    Called from `delete_case_collection`. Without this, deleting and re-ingesting
    a case would carry the old chunking schemes forward into the new record --
    so the mosaic the soft check exists to reveal would report granularities
    that no longer exist in the collection.
    """
    try:
        os.remove(provenance_path(qdrant_path))
        return True
    except OSError:
        return False


def survey(qdrant_paths, measured) -> dict:
    """
    Summarise provenance across many cases, for the health page.

    Counts by verdict, and -- the part worth surfacing -- how many cases were
    built at more than one chunking granularity. A case with three schemes is
    not broken, but it is not the uniform index the UI presents it as.
    """
    out = {
        "total": 0,
        MATCH: 0,
        MISMATCH: 0,
        UNATTRIBUTED: 0,
        NEVER_INDEXED: 0,
        "mixed_chunking_cases": 0,
        "embedder_ids": [],
        "mismatched_detail": [],
        "state": MATCH,
    }
    for path in qdrant_paths:
        verdict = check_index(path, measured)
        state = verdict["state"]
        out["total"] += 1
        out[state] = out.get(state, 0) + 1

        if state == MISMATCH:
            rec = verdict["record"] or {}
            out["mismatched_detail"].append({
                "collection": os.path.basename(os.path.dirname(path)) or path,
                "indexed_with": _signature_of(rec),
                "current": _signature_of(measured),
                "reason": verdict["reason"],
            })
        if len(verdict["chunking_schemes"]) > 1:
            out["mixed_chunking_cases"] += 1

        eid = (verdict["record"] or {}).get("embedder_id")
        if eid and eid not in out["embedder_ids"]:
            out["embedder_ids"].append(eid)

    # Mismatch is the only state that must change how the page reads. An
    # unattributed index is a pre-guard index on a working install and is
    # reported as a count, not as a fault -- refusing it would lock the operator
    # out of every case they already have.
    if out[MISMATCH]:
        out["state"] = MISMATCH
    elif out[UNATTRIBUTED] or out["mixed_chunking_cases"]:
        out["state"] = UNATTRIBUTED
    return out
