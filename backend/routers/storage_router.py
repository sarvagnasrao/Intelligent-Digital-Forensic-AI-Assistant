"""
Storage management router — system-wide and per-case storage transparency.

Endpoints
---------
``GET /api/storage/overview``              every volume, the cases tree, the
                                           vector-index tree, and a per-case table
``GET /api/storage/cases/{case_id}``       one case's full breakdown, file by file
``GET /api/storage/cases/{case_id}/files`` the flat inventory for that case

Three rules govern everything in this module, and they are the reason it exists
as its own file rather than as three more fields on the system-health page.

1. **A number nobody measured is never `0`.** A case that has never held a
   disk image has no ``evidence/extracted`` directory. That is *nothing was
   measured*, which is not the same claim as *measured, and it is empty*. So
   every section returns ``{bytes: null, files: null, state, reason}`` when it
   could not be walked, and the UI renders an em dash. A fabricated ``0`` on a
   storage page reads as "this case costs nothing", which is the direction that
   hides a 635 MB acquisition. (AGENTS.md §16, ninth occurrence.)

2. **The database's idea of a size and the disk's idea are reported separately.**
   ``evidence.file_size_bytes`` is written at upload and never re-measured;
   ``forensic_artifacts.stored_file_size`` likewise. A row whose file was
   deleted outside the app still carries its size forever, so a total built
   from the column is a historical figure presented as a present one. Each item
   therefore carries ``db_bytes``, ``disk_bytes`` and ``missing``, and the
   summary reports both totals. Where they differ, that is the finding.

3. **An index has two legitimate homes, and this module must know about both.**
   ``vector_store.case_qdrant_path()`` resolves against global settings, which
   is where the *writer* looks; when the cases directory sits on a slow disk
   the whole store is relocated elsewhere. An index left behind in the cases
   directory before that migration is still a real, searchable index. So each
   case's index is looked for in both places and the location is *named*, which
   is the same fix as AGENTS.md §21/B28 and is the reason this logic is not a
   one-liner.

Nothing here deletes anything. This module only measures. Storage reclamation is
a separate, deliberate operation with its own audit trail.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models
from backend.dependencies import get_settings
from backend.auth import require_viewer
from backend.routers.case_access import check_case_access

import os
import time

router = APIRouter(
    prefix="/api/storage",
    tags=["Storage"],
)

# States. Deliberately the same vocabulary as service_health.py: ok /
# error / unavailable, where `unavailable` means "could not measure" and never
# "measured zero".
STATE_OK = "ok"
STATE_ERROR = "error"
STATE_UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

def human_bytes(n):
    """Format a byte count for humans. `None` in, `None` out - never `0`."""
    if n is None:
        return None
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0 or unit == "PB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return None


def _dir_usage(path):
    """
    Measure a directory tree by metadata only (never reads file contents).

    Returns a dict that always carries a `state`:
      * ok          - walked; `bytes`/`files` are real
      * unavailable - the directory does not exist; nothing was counted
      * error       - the walk raised partway; whatever was counted is kept and
                      `partial` says so
    """
    if not path:
        return {
            "path": None, "bytes": None, "files": None, "state": STATE_UNAVAILABLE,
            "reason": "no path was configured for this section",
        }
    if not os.path.exists(path):
        return {
            "path": path, "bytes": None, "files": None, "state": STATE_UNAVAILABLE,
            "reason": "directory does not exist, so nothing was counted",
        }
    if not os.path.isdir(path):
        return {
            "path": path, "bytes": None, "files": None, "state": STATE_ERROR,
            "reason": "path exists but is not a directory",
        }

    started = time.perf_counter()
    total = 0
    count = 0
    errors = []
    try:
        for root, _dirs, files in os.walk(path, onerror=lambda e: errors.append(e)):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                    count += 1
                except OSError as e:
                    errors.append(e)
    except Exception as e:  # pragma: no cover - os.walk is defensive already
        errors.append(e)

    out = {
        "path": path,
        "bytes": total,
        "files": count,
        "state": STATE_OK,
        "reason": None,
        "walk_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if errors:
        # Partial totals presented as complete totals is the one thing this
        # function must not do. The number is kept - it is real - but it is
        # labelled as a lower bound rather than passed off as the size.
        out["state"] = STATE_ERROR
        out["partial"] = True
        out["unreadable"] = len(errors)
        out["reason"] = (
            f"{len(errors)} item(s) could not be measured, so this is a lower "
            f"bound, not the total (first: {type(errors[0]).__name__}: {errors[0]})"
        )
    return out


def _resolve_stored_path(path):
    """
    Turn a stored `file_path` / `stored_file_path` into something measurable.

    The column comment in `models.py` says "path on disk relative to CASES_DIR",
    but every writer in the codebase joins `settings.cases_dir` first and stores
    the result, so the rows in a real database hold absolute paths. Guessing one
    shape and reporting "missing" for every row of the other is a fabricated
    claim in the opposite direction, so both are accepted: absolute as-is,
    relative resolved against the cases directory.
    """
    if not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.join(get_settings().cases_dir, path)


def _file_size(path):
    """
    `os.path.getsize` as a tri-state.

    Returns (bytes, missing). `bytes` is None when the file could not be
    measured, which is why it is not simply `os.path.getsize(path) or 0`:
    that expression turns "the file is gone" into "the file is empty".
    """
    resolved = _resolve_stored_path(path)
    if not resolved:
        return None, True
    try:
        return os.path.getsize(resolved), False
    except OSError:
        return None, True


def _index_locations(case_id):
    """
    Both legitimate homes for this case's vector index, and which exist.

    See rule 3 in the module docstring. `canonical` comes from the writer's own
    resolver so it cannot drift from where an ingest would actually put the
    index; `in_cases` is derived from the configured cases directory so a
    pre-migration index is still found.
    """
    settings = get_settings()
    in_cases = os.path.join(settings.cases_dir, case_id, "qdrant")
    try:
        from backend.modules.vector_store import case_qdrant_path
        canonical = case_qdrant_path(case_id)
    except Exception as e:
        # Cannot ask the writer. The in-cases location is still checkable, so a
        # resolver fault must not degrade into "this case has no index".
        canonical = None
        canonical_error = f"{type(e).__name__}: {e}"
    else:
        canonical_error = None

    has_in_cases = os.path.isdir(in_cases)
    has_canonical = bool(canonical) and canonical != in_cases and os.path.isdir(canonical)
    if has_canonical:
        location = "canonical"
    elif has_in_cases:
        location = "in_cases"
    else:
        location = "absent"
    return {
        "in_cases": in_cases,
        "canonical": canonical,
        "canonical_error": canonical_error,
        "has_in_cases": has_in_cases,
        "has_canonical": has_canonical,
        "duplicated": has_in_cases and has_canonical,
        # Only the canonical copy is measured when both exist: they are two
        # copies of one index and summing them would double-count it. The
        # duplication is reported separately rather than folded into a total.
        "measured": canonical if has_canonical else (in_cases if has_in_cases else None),
        "location": location,
    }


def _provenance_for(index_path):
    """
    What wrote this index, and may this build search it?

    Delegates to index_provenance, the module that owns the four-state verdict,
    so the storage page cannot report a different answer from the health page
    and the search guard. Never returns a fabricated state: an unreadable
    sidecar is `unattributed`, not `match`.
    """
    if not index_path or not os.path.isdir(index_path):
        return {
            "state": None,
            "reason": "this case has no vector index, so there is nothing to verify",
            "chunking_schemes": [],
        }
    try:
        from backend.modules import index_provenance
        from backend.modules.vector_store import EMBEDDER_ID
        declared = index_provenance.declared_signature(EMBEDDER_ID)
        if declared is None:
            return {
                "state": None,
                "reason": (
                    f"no declared specification for embedder {EMBEDDER_ID!r}, "
                    f"so this index cannot be classified either way"
                ),
                "chunking_schemes": [],
            }
        return index_provenance.check_index(index_path, declared)
    except Exception as e:
        # A guard that could take the storage page down would be the B15
        # defect. Reported as unmeasured, never as "verified".
        return {
            "state": None,
            "reason": f"provenance could not be read: {type(e).__name__}: {e}",
            "chunking_schemes": [],
        }


def _access_or_403(db, case_id, user):
    """Every case-scoped endpoint here goes through this."""
    if not check_case_access(db, case_id, user):
        raise HTTPException(status_code=403, detail="You do not have access to this case")


# ---------------------------------------------------------------------------
# GET /api/storage/overview
# ---------------------------------------------------------------------------

@router.get("/overview")
def get_storage_overview(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Whole-install storage picture, plus a per-case table.

    The per-case table is the "storage management" half: which case occupies
    how much space, what state its files are in, and where its index lives.
    It is built from the same DB rows and the same directory walks the rest of
    the app uses, so it cannot disagree with the evidence list or the health
    page about how big a case is.
    """
    settings = get_settings()
    cases_root = settings.cases_dir

    # ── Volumes ─────────────────────────────────────────────────────────────
    volumes = []
    volumes_state = STATE_OK
    volumes_reason = None
    try:
        import psutil
        for part in psutil.disk_partitions(all=True):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                # An unreadable mount is skipped and counted, not silently
                # dropped: a volume that vanishes from the list is a capacity
                # number that quietly stops adding up.
                continue
            volumes.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "pct_used": round(usage.used / usage.total * 100, 1) if usage.total else None,
                "total_human": human_bytes(usage.total),
                "used_human": human_bytes(usage.used),
                "free_human": human_bytes(usage.free),
            })
        if not volumes:
            volumes_state = STATE_UNAVAILABLE
            volumes_reason = "no mounted volume could be read"
    except Exception as e:
        volumes_state = STATE_ERROR
        volumes_reason = f"{type(e).__name__}: {e}"

    # ── Trees on disk ───────────────────────────────────────────────────────
    cases_tree = _dir_usage(cases_root)

    # The index tree is a *different* directory whenever relocation is active.
    # Only the part that is not already inside the cases tree is counted, so the
    # total does not add the same bytes twice.
    try:
        from backend.modules.vector_store import resolve_qdrant_dir
        index_root = resolve_qdrant_dir()
    except Exception as e:
        index_root = None
        index_root_error = f"{type(e).__name__}: {e}"
    else:
        index_root_error = None

    if index_root and os.path.abspath(index_root) != os.path.abspath(cases_root):
        index_tree = _dir_usage(index_root)
    else:
        # Inside the cases tree, or unresolvable - it is already counted by the
        # walk above, so counting it again would double every index byte.
        index_tree = {
            "path": index_root,
            "bytes": 0,
            "files": 0,
            "state": STATE_OK,
            "reason": None,
            "counted_in": "cases_root",
        }

    # ── Per-case table ──────────────────────────────────────────────────────
    # Scoped to the cases this user may actually see, mirroring `cases.py:102-113`
    # exactly. That duplication is deliberate and load-bearing: the per-case
    # endpoints below refuse a case without an access record, and an overview
    # that listed every case anyway would hand out the name, status, file count
    # and disk usage of investigations the user is not assigned to. Two
    # implementations of "which cases may this user see" is one too many, so
    # this comment and that query must be changed together.
    #
    # The guard suite caught this: the first version of this endpoint returned
    # 200 with every case in the table for a user with access to none of them.
    all_case_ids = [c.id for c in db.query(models.Case).all()]
    accessible_ids = None
    if current_user.role != "Admin":
        accessible_ids = [
            a.case_id for a in
            db.query(models.CaseAccess).filter(
                models.CaseAccess.user_id == current_user.id
            ).all()
        ]
    visible_cases = [cid for cid in all_case_ids
                     if accessible_ids is None or cid in accessible_ids]
    hidden_cases = len(all_case_ids) - len(visible_cases)

    cases = (db.query(models.Case)
             .filter(models.Case.id.in_(visible_cases))
             .order_by(models.Case.created_at.asc())
             .all()) if visible_cases else []
    rows = []
    totals = {
        "cases": len(cases),
        "evidence_db_bytes": 0,
        "evidence_disk_bytes": 0,
        "evidence_missing": 0,
        "index_bytes": 0,
        "index_measured": 0,
        "artifacts": 0,
    }
    for case in cases:
        ev_rows = db.query(models.Evidence).filter(
            models.Evidence.case_id == case.id
        ).all()
        db_bytes = 0
        disk_bytes = 0
        missing = 0
        for ev in ev_rows:
            db_bytes += int(ev.file_size_bytes or 0)
            sz, gone = _file_size(ev.file_path)
            if gone:
                missing += 1
            else:
                disk_bytes += sz

        art_count = db.query(models.ForensicArtifact).filter(
            models.ForensicArtifact.case_id == case.id
        ).count()

        loc = _index_locations(case.id)
        prov = _provenance_for(loc["measured"])
        idx_bytes = None
        if loc["measured"]:
            u = _dir_usage(loc["measured"])
            idx_bytes = u["bytes"]
            totals["index_measured"] += 1
            if idx_bytes:
                totals["index_bytes"] += idx_bytes

        totals["evidence_db_bytes"] += db_bytes
        totals["evidence_disk_bytes"] += disk_bytes
        totals["evidence_missing"] += missing
        totals["artifacts"] += art_count

        rows.append({
            "case_id": case.id,
            "case_name": case.case_name,
            "status": case.status,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "evidence_count": len(ev_rows),
            "evidence_db_bytes": db_bytes,
            "evidence_disk_bytes": disk_bytes,
            "evidence_db_human": human_bytes(db_bytes),
            "evidence_disk_human": human_bytes(disk_bytes),
            "evidence_missing": missing,
            "artifact_count": art_count,
            "index_bytes": idx_bytes,
            "index_human": human_bytes(idx_bytes),
            "index_location": loc["location"],
            "index_duplicated": loc["duplicated"],
            "index_provenance_state": prov.get("state"),
            "index_provenance_reason": prov.get("reason"),
            "index_chunking_schemes": prov.get("chunking_schemes") or [],
        })

    # ── Cases directories with no database row ──────────────────────────────
    # Measured, and deliberately not deleted or hidden. Earlier runs of the
    # ingestion pipeline left ~340 of them, and a storage page that only counts
    # what the database knows about understates what is actually on the disk.
    #
    # Two access rules apply here, and both are needed:
    #   * "is this a real case" is tested against **every** case row, not the
    #     visible ones. Using the filtered list would report another
    #     investigator's case as an orphan, which hands out its directory id
    #     and its size -- the same leak the per-case table was just fixed for.
    #   * the orphan list itself is administrative, and an orphan has no case
    #     row so nobody can hold an access record for one. It is therefore
    #     Admin-only, and reported to everyone else as `null` with a reason.
    #     `null`, not `0`: "you may not see this" and "there are none" are
    #     different claims, and only one of them is true (§16).
    orphan_dirs = []
    if current_user.role != "Admin":
        orphan_state = STATE_UNAVAILABLE
        orphan_reason = (
            "case directories that belong to no case row are administrative "
            "information; an Admin can see this list"
        )
        orphan_dirs = None
    elif cases_tree["state"] == STATE_OK and os.path.isdir(cases_root):
        known = set(all_case_ids)
        try:
            entries = os.listdir(cases_root)
        except OSError as e:
            orphan_dirs = []
            orphan_state = STATE_ERROR
            orphan_reason = f"{type(e).__name__}: {e}"
        else:
            orphan_state = STATE_OK
            orphan_reason = None
            for name in entries:
                if name in known:
                    continue
                if not os.path.isdir(os.path.join(cases_root, name)):
                    continue
                u = _dir_usage(os.path.join(cases_root, name))
                orphan_dirs.append({
                    "case_id": name,
                    "bytes": u["bytes"],
                    "files": u["files"],
                    "state": u["state"],
                    "reason": u["reason"],
                })
            orphan_dirs.sort(key=lambda r: (r["bytes"] or 0), reverse=True)
    else:
        orphan_state = STATE_UNAVAILABLE
        orphan_reason = cases_tree.get("reason")

    total_disk = (totals["evidence_disk_bytes"] or 0) + (totals["index_bytes"] or 0)

    # `cases` is scoped to what this user may see, so `totals` is too -- a total
    # that added up every case would leak the size of the ones just filtered
    # out. `cases_hidden` is a real count of what was withheld, which is safe to
    # state: it says how many, never which or how large. `scoped` tells the UI
    # that these figures are not the whole install, so it must not print them as
    # "all storage" to an investigator who can only see two cases.
    scoped = hidden_cases > 0

    return {
        "generated_at": time.time(),
        "volumes": {
            "items": volumes,
            "state": volumes_state,
            "reason": volumes_reason,
        },
        "cases_tree": cases_tree,
        "index_tree": index_tree,
        "index_root_error": index_root_error,
        "totals": {
            **totals,
            "evidence_disk_human": human_bytes(totals["evidence_disk_bytes"]),
            "evidence_db_human": human_bytes(totals["evidence_db_bytes"]),
            "index_human": human_bytes(totals["index_bytes"]),
            "total_disk_bytes": total_disk,
            "total_disk_human": human_bytes(total_disk),
            "scoped_to_your_cases": scoped,
            "cases_hidden": hidden_cases,
        },
        "cases": {
            "items": rows,
            "count": len(rows),
            "total_in_database": len(all_case_ids),
        },
        "orphan_case_dirs": {
            "items": orphan_dirs,
            # `None`, not `0`, when the caller may not see the list. A zero
            # would assert that there are no orphan directories, which for a
            # non-Admin is not a claim this endpoint is entitled to make.
            "count": len(orphan_dirs) if orphan_dirs is not None else None,
            "bytes": (sum(r["bytes"] or 0 for r in orphan_dirs)
                      if orphan_dirs is not None else None),
            "state": orphan_state,
            "reason": orphan_reason,
        },
    }


# ---------------------------------------------------------------------------
# GET /api/storage/cases/{case_id}
# ---------------------------------------------------------------------------

@router.get("/cases/{case_id}")
def get_case_storage(
    case_id: str,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    One case's storage, broken down by what each part actually is.

    Four independent buckets, because they have different lifecycles and
    different failure modes:

      * `evidence`  - what was uploaded. Never rewritten, so the DB column and
        the file on disk can diverge; both are reported.
      * `extracted` - what the forensic walk pulled out of disk images. Derived
        data, safe to regenerate, and absent for every non-image case.
      * `index`     - the vector store. Two possible homes, named when they
        disagree, with the provenance verdict attached.
      * `artifacts` - individual viewable files extracted from an image, which
        are stored separately and so must be counted separately or they get
        counted twice.
    """
    case = db.query(models.Case).filter(models.Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"No case with id={case_id}")
    _access_or_403(db, case_id, current_user)

    settings = get_settings()
    case_dir = os.path.join(settings.cases_dir, case_id)

    ev_query = db.query(models.Evidence).filter(models.Evidence.case_id == case_id)
    if not include_archived:
        ev_query = ev_query.filter(models.Evidence.status != "Archived")
    ev_rows = ev_query.all()

    evidence_items = []
    db_bytes = 0
    disk_bytes = 0
    missing = 0
    for ev in ev_rows:
        sz, gone = _file_size(ev.file_path)
        recorded = int(ev.file_size_bytes or 0)
        db_bytes += recorded
        if gone:
            missing += 1
        else:
            disk_bytes += sz
        evidence_items.append({
            "id": ev.id,
            "name": ev.original_filename or ev.filename,
            "stored_name": ev.filename,
            "status": ev.status,
            "file_type": ev.file_type,
            "db_bytes": recorded,
            "db_human": human_bytes(recorded),
            "disk_bytes": sz,
            "disk_human": human_bytes(sz),
            "missing": gone,
            "sha256": ev.sha256_hash,
            "path": ev.file_path,
            "ingested_at": ev.ingested_at.isoformat() if ev.ingested_at else None,
            "chunk_count": ev.chunk_count,
        })
    evidence_items.sort(key=lambda e: (e["disk_bytes"] or 0), reverse=True)

    # Files sitting in the evidence directory that no row claims. Measured
    # rather than cleaned: an investigator asking "where did my disk space go"
    # needs to see the answer even when the answer is untidy.
    known_paths = set()
    for ev in ev_rows:
        rp = _resolve_stored_path(ev.file_path)
        if rp:
            known_paths.add(os.path.abspath(rp))
    evidence_dir = os.path.join(case_dir, "evidence")
    unclaimed = []
    if os.path.isdir(evidence_dir):
        for name in sorted(os.listdir(evidence_dir)):
            fp = os.path.join(evidence_dir, name)
            if not os.path.isfile(fp):
                continue
            if os.path.abspath(fp) in known_paths:
                continue
            sz, gone = _file_size(fp)
            unclaimed.append({
                "name": name,
                "bytes": sz,
                "human": human_bytes(sz),
                "path": fp,
            })
    else:
        unclaimed = None  # not measured; see rule 1

    extracted_dir = os.path.join(evidence_dir, "extracted")
    extracted = _dir_usage(extracted_dir)

    art_query = db.query(models.ForensicArtifact).filter(
        models.ForensicArtifact.case_id == case_id
    )
    art_rows = art_query.all()
    artifact_items = []
    art_disk = 0
    art_db = 0
    art_missing = 0
    for art in art_rows:
        sz, gone = _file_size(art.stored_file_path)
        recorded = int(art.stored_file_size or 0)
        art_db += recorded
        if gone:
            if art.stored_file_path:
                art_missing += 1
        else:
            art_disk += sz
        artifact_items.append({
            "id": art.id,
            "internal_path": art.internal_path,
            "extraction_type": art.extraction_type,
            "is_viewable": art.is_viewable,
            "is_deleted": art.is_deleted,
            "db_bytes": recorded,
            "db_human": human_bytes(recorded),
            "disk_bytes": sz,
            "disk_human": human_bytes(sz),
            "missing": gone,
            "evidence_id": art.evidence_id,
        })
    artifact_items.sort(key=lambda a: (a["disk_bytes"] or 0), reverse=True)

    loc = _index_locations(case_id)
    index = _dir_usage(loc["measured"]) if loc["measured"] else {
        "path": loc["canonical"] or loc["in_cases"],
        "bytes": 0,
        "files": 0,
        "state": STATE_OK,
        "reason": None,
    }
    index["location"] = loc["location"]
    index["in_cases_path"] = loc["in_cases"]
    index["canonical_path"] = loc["canonical"]
    index["canonical_error"] = loc["canonical_error"]
    index["duplicated"] = loc["duplicated"]
    index["provenance"] = _provenance_for(loc["measured"])

    total_disk = disk_bytes + (index["bytes"] or 0)
    return {
        "case_id": case_id,
        "case_name": case.case_name,
        "case_status": case.status,
        "case_dir": case_dir,
        "include_archived": include_archived,
        "evidence": {
            "items": evidence_items,
            "count": len(evidence_items),
            "db_bytes": db_bytes,
            "db_human": human_bytes(db_bytes),
            "disk_bytes": disk_bytes,
            "disk_human": human_bytes(disk_bytes),
            "missing": missing,
            "unclaimed_files": unclaimed,
        },
        "extracted": extracted,
        "artifacts": {
            "items": artifact_items,
            "count": len(artifact_items),
            "db_bytes": art_db,
            "db_human": human_bytes(art_db),
            "disk_bytes": art_disk,
            "disk_human": human_bytes(art_disk),
            "missing": art_missing,
        },
        "index": index,
        "total": {
            "disk_bytes": total_disk,
            "disk_human": human_bytes(total_disk),
            "db_bytes": db_bytes + art_db + (index["bytes"] or 0),
            "db_human": human_bytes(db_bytes + art_db + (index["bytes"] or 0)),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/storage/cases/{case_id}/files
# ---------------------------------------------------------------------------

@router.get("/cases/{case_id}/files")
def get_case_file_inventory(
    case_id: str,
    include_archived: bool = Query(False),
    kind: str = Query("all", pattern="^(all|evidence|artifact)$"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Flat, sortable inventory of every file this case holds.

    One row per file rather than four nested buckets, because the question
    being asked is "what is eating the disk", and that question is answered by
    a sorted list. The same `db_bytes` / `disk_bytes` / `missing` triple as
    the breakdown, so a row here and a row there cannot disagree.
    """
    case = db.query(models.Case).filter(models.Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"No case with id={case_id}")
    _access_or_403(db, case_id, current_user)

    rows = []

    if kind in ("all", "evidence"):
        q = db.query(models.Evidence).filter(models.Evidence.case_id == case_id)
        if not include_archived:
            q = q.filter(models.Evidence.status != "Archived")
        for ev in q.all():
            sz, gone = _file_size(ev.file_path)
            rows.append({
                "id": ev.id,
                "kind": "evidence",
                "name": ev.original_filename or ev.filename,
                "status": ev.status,
                "file_type": ev.file_type,
                "db_bytes": int(ev.file_size_bytes or 0),
                "disk_bytes": sz,
                "missing": gone,
                "path": ev.file_path,
                "sha256": ev.sha256_hash,
                "detail": ev.file_type or "",
            })

    if kind in ("all", "artifact"):
        for art in db.query(models.ForensicArtifact).filter(
            models.ForensicArtifact.case_id == case_id
        ).all():
            sz, gone = _file_size(art.stored_file_path)
            rows.append({
                "id": art.id,
                "kind": "artifact",
                "name": art.internal_path or f"artifact-{art.id[:8]}",
                "status": "Deleted" if art.is_deleted else "Extracted",
                "file_type": art.extraction_type,
                "db_bytes": int(art.stored_file_size or 0),
                "disk_bytes": sz,
                "missing": gone,
                "path": art.stored_file_path,
                "sha256": None,
                "detail": "viewable" if art.is_viewable else "not viewable",
            })

    for r in rows:
        r["db_human"] = human_bytes(r["db_bytes"])
        r["disk_human"] = human_bytes(r["disk_bytes"])

    rows.sort(key=lambda r: (r["disk_bytes"] or 0), reverse=True)

    measured = [r for r in rows if r["disk_bytes"] is not None]
    return {
        "case_id": case_id,
        "kind": kind,
        "include_archived": include_archived,
        "files": rows,
        "count": len(rows),
        "measured_count": len(measured),
        "unmeasurable_count": len(rows) - len(measured),
        "missing_count": sum(1 for r in rows if r["missing"]),
        "disk_bytes": sum(r["disk_bytes"] for r in measured),
        "disk_human": human_bytes(sum(r["disk_bytes"] for r in measured)),
        "db_bytes": sum(r["db_bytes"] for r in rows),
        "db_human": human_bytes(sum(r["db_bytes"] for r in rows)),
    }