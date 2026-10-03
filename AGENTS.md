## Handoff: Storage management (added)

**What changed (§31, storage transparency):**

- `backend/routers/storage_router.py` — three endpoints under `/api/storage`:
  - `GET /overview` — system-wide. Scopes cases to those the user may see (non-Admin see only cases with a CaseAccess record). Reports `cases_hidden`, `scoped_to_your_cases` so totals are not presented as whole-install for a partially scoped viewer. Orphan case directories are **Admin-only** (reported as `orphan_case_dirs.count === null` and a reason for non-Admin); when Admin, lists directories with no DB row, sorted by size (never deleted). Each section returns `state` (ok/error/unavailable) and `reason`. `null` means *not measured*, **never `0`** (§16).
  - `GET /cases/{case_id}` — per-case breakdown (evidence/extracted/index/artifacts). Evidence and artifacts report both `db_bytes` (recorded at upload/write) and `disk_bytes` (measured now), plus `missing` counts; unclaimed files in `evidence/` are listed. Index checks **two homes** (canonical via `case_qdrant_path()`, legacy `in_cases`) and reports `location` (`canonical`/`in_cases`/`absent`), `duplicated`, and provenance from `index_provenance.check_index()` (match/mismatch/unattributed/never_indexed). Access enforced via `check_case_access`.
  - `GET /cases/{case_id}/files` — flat inventory with `kind` filter and `include_archived`; same `db_bytes`/`disk_bytes`/`missing` triple, `unmeasurable_count` and `measured_count`.

- Frontend: `frontend/src/pages/StoragePage.jsx`, `App.jsx` route `/storage`, `Sidebar.jsx` entry "Storage", `frontend/src/api/client.js` functions `getStorageOverview`, `getCaseStorage`, `getCaseStorageFiles`. The page follows the "null means not measured" rule and surfaces the scoped totals/orphan withholding.

**Important guardrails (from AGENTS.md):**

- **Two homes for indexes (B28/§21).** When the cases directory is on a slow disk the vector store relocates to `resolve_qdrant_dir()`; an index may remain in `cases/<id>/qdrant`. The router checks both and reports `location` and `duplicated`. Never assume only the canonical path.
- **Access scoping is load-bearing.** `GET /storage/overview` filters cases by `CaseAccess` for non-Admin and sets `scoped_to_your_cases`/`cases_hidden`. The per-case endpoints call `check_case_access` and return 403 without leaking names/sizes. The orphan list is Admin-only.
- **Honesty rule (§16):** `bytes: null` + `reason` when unmeasurable; `0` only when measured. A fabricated `0` is the defect this page was written to prevent. Recorded vs measured sizes are shown separately because they *differ* by design (DB columns are not re-measured).
- **Provenance is stdlib-only and never opens Qdrant.** `index_provenance` does not import torch or open `QdrantClient`; the index measurements are directory walks only. See §32.
- **Import safety (B15).** `vector_store` imports torch lazily; `storage_router.py` imports it only inside functions (`case_qdrant_path`, `resolve_qdrant_dir`, `EMBEDDER_ID`), so importing the router does not pull the embedding stack.

**Tests:** `tests/verify_storage.py` (53/53) guards the three rules above, including access scoping and the two-homes case. Registered in `tests/run_gate.py`.

**Notes for a successor:** do not collapse `db_bytes` and `disk_bytes` into one sum in the UI; do not "fix" `null` to `0`; do not make the orphan list visible to non-Admin; if you change the case-access query, change both `cases.py` and the overview's scoping together (they are duplicated by design with a comment explaining why).

**Build:** frontend builds clean (3388 modules). The full gate is running in background as requested; verify its result when the completion notification arrives.