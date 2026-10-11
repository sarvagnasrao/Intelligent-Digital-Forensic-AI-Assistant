# PROGRESS.md — continuation ledger for the backend-hardening job

**Read this before touching anything.** It is the single source of truth for
*what is done*, *what is in flight*, and *what is next*. The detailed findings
and `file:line` references live in `AUDIT_BASELINE.md`; this file is the map.

Owner of a workstream == the only agent allowed to edit those files. Do not edit
another workstream's files. If you must, stop and coordinate by writing to
`reports/` instead.

---

## 1. Environment (verified — do not re-derive)

- Python: `venv\Scripts\python.exe` (3.12.10). Always `$env:PYTHONPATH="."` from
  the repo root before running tests. Node 18 at `E:\tools\node-v18.20.8-win-x64`.
- Repo: `E:\Users\sarva\Documents\IDFA` — **it IS a git repo** (HEAD `7c161fc`,
  "Make split disk-image sets ingestable end to end"). An earlier env note said
  otherwise; that was wrong.
- Servers currently up: backend `0.0.0.0:8000`, Ollama `127.0.0.1:11434`
  (`llama3.2:3b`), Vite on `::1:3000` only (use `localhost`). Logins:
  `admin/Admin@IDF2025`, `det_markov/Markov@2025`, `analyst_chen/Chen@2025`.
- DB: `data/forensic.db` (SQLite). 3 real demo cases + one `Test` case
  (`8895b7fe-dde1-457e-b0bc-0035f483bc6d`) that is scheduled for deletion (see §7).
- Qdrant has **two homes** (B28): canonical via `case_qdrant_path()`, else
  relocated to `%LOCALAPPDATA%\IDFA\qdrant` when the cases dir is on a rotating
  disk. Never assume the canonical path alone.
- Embedder is local `all-MiniLM-L6-v2` (384-dim). `get_ollama_embeddings` is a
  misnomer — no Ollama call is involved in embedding.

---

## 2. DONE (each line is a measured result, not a claim)

- **Gate totals cleanly for the first time.** `tests/run_gate.py` →
  `GATE PASSED - 1158 passed, 0 failed across 20 scripts` (`logs/gate_stage3.log`).
  The blocker was `tests/verify_provenance.py:21` hard-coding
  `os.chdir(r"D:\Users\Anon\Desktop\IDFA_main3")`; removed (nothing depended on
  cwd). Standalone: `PROVENANCE SUITE PASSED - 79 assertions`.
- **Stage 2 — split-image correctness. DONE.**
  `tests/verify_split_images.py`: 6 failed → **48 passed / 0 failed**.
  `route_for_filename()` in `ingestion.py`; `set_incomplete` from
  `result["missing_segments"]`; no first-segment hash overwrite;
  `hash_evidence_set()` in `routers/evidence.py`.
- **Stage 3 — re-index idempotency. DONE.**
  `tests/verify_reindex_idempotency.py`: 7 failed → **13 passed / 0 failed**.
  Deterministic point ids `uuid5(case_id|evidence_id|source_filename|chunk_index|text)`
  (`_point_id()` in `vector_store.py`); one `delete_evidence_points()` call at the
  top of `run_ingestion_with_progress` (`ingestion.py`).
- **Stage 4.1 — hybrid (exact-identifier) retrieval. DONE.**
  `tests/verify_hybrid_retrieval.py`: 0 passed / 4 failed → **21 passed / 0 failed**.
  - `backend/modules/lexical.py` (NEW, stdlib-only): `identifier_terms`,
  - `QUERY_STOPWORDS`, BM25 `bm25_idf`, `document_frequencies`,
    `weighted_coverage`. No torch/Qdrant import (B15 import safety).
  - `vector_store.py`: `lexical_search(query, case_id, qdrant_path, limit,
    evidence_id)` (payload scan, IDF-weighted coverage); `search_chunks` now
    returns `point_id`.
  - `rag_engine.py`: `retrieve(query, case_id, qdrant_path, top_k, evidence_id)`
    fuses dense + exact-term with Reciprocal Rank Fusion (`RRF_K = 60`), dedups
    by `(source, chunk_index)`; `run_rag_query` uses it. `score` keeps its OLD
    meaning (dense cosine, or `None` for an exact-term-only hit) so the 0.15
    floor still means what it meant. `_QUERY_STOPWORDS` now aliases
    `lexical.QUERY_STOPWORDS`.
  - Baseline that motivated it (`bench_baseline.json`): the query `203.0.113.77`
    ranked the chunk that literally contains it **3rd at 0.133**, below the 0.15
    floor, behind an unrelated `transactions.csv` at 0.268.
- **Targeted regressions after Stage 4.1 — all green:**
  `verify_vector_store` 17/0, `verify_retrieval_integrity` 37/0,
  `verify_prompt_budget` 86/0, `verify_reindex_idempotency` 13/0,
  `verify_provenance` 79/0, `verify_ingestion_modes` 45/0,
  `verify_hybrid_retrieval` 21/0.
- `tests/verify_split_images.py`, `verify_reindex_idempotency.py`,
  `verify_hybrid_retrieval.py` are registered in `tests/run_gate.py` `SUITES`.

---

## 2b. In flight (background agents) — **ALL COMPLETE**

Each workstream agent owns the listed files and wrote a running report to
`reports/<file>.md`. They did NOT edit `tests/run_gate.py` (the integrator
owns it) and did NOT run the full gate.

| WS | scope | files owned | report | status |
|----|-------|-------------|--------|--------|
| R | Stage 4.2 + 4.3 (retrieval accuracy/traceability) | `backend/modules/rag_engine.py`, `backend/routers/queries.py`, `backend/schemas.py`, `tests/verify_query_traceability.py`, `tests/verify_grounding.py` | `reports/ws_r_retrieval.md` | **DONE** |
| P | Stage 5 (performance) | `backend/modules/vector_store.py`, `backend/ingestion.py`, `tests/bench_pipeline.py`, `tests/verify_perf_*.py` | `reports/ws_p_perf.md` | **DONE** |
| G | Stage 6 (NLP/graph) | `backend/modules/graph_builder.py`, `backend/modules/forensic_ingestion.py`, `tests/verify_graph_*.py` | `reports/ws_g_graph.md` | **DONE** |
| T | Stage 7/8 (test hygiene + integration) | `tests/run_gate.py`, `tests/**` (no source edits), report files | `reports/ws_t_integration.md` | **DONE** |

`verify_retrieval_integrity.py` sections B and E stub `rag_engine.retrieve`
(not `search_chunks`) — that seam moved in Stage 4.1. Keep it that way.

---

## 3. To do (exact targets)

### 3a. Stage 4.2 — expose claim↔excerpt traceability (finding C3, P1) — **DONE**
- `backend/routers/queries.py`: `POST /ask` response now includes `"chunks_used"`.
- `backend/schemas.py`: `QueryResponse` adds optional `chunks_used` with a
  `mode="before"` validator that parses JSON strings; absent/malformed → `None`,
  never `[]`.
- Suite: `tests/verify_query_traceability.py` **21/0** (schema + API via TestClient).
- Additive, backward-compatible; `chunks_used` was already persisted, now exposed.

### 3b. Stage 4.3 — grounding + honesty in answers (findings C2, C4, C6) — **DONE**
- C2: `grounding_check(answer, chunks)` extracts identifiers from the answer
  and verifies them against retrieved text. Returns dict with `checked`,
  `grounded`, `ungrounded`, `grounded_ratio`, and named ungrounded identifiers.
  Integrated into `run_rag_query` result as `grounding` key.
- C4: refusal message narrowed from "anything indexed in this case" to
  "the N passages retrieval returned for it in this case"; names passage count
  and searchable terms.
- C6: `conv_context` bounded: history truncated to last 5 exchanges, long
  questions/answers trimmed, trimming reported as `conv_trimmed`/`conv_chars_elided`
  (separate from evidence elision). `QueryCreate` schema validates history
  length ≤ 50.
- Suite: `tests/verify_grounding.py` **35/0** (grounding_check, run_rag_query
  integration, honest refusal scope, bounded history, schema validation).

### 3c. Stage 5 — performance (findings B2, B4, A9, A10, A12) — **DONE**
- B4: `get_ollama_embeddings` calls `model.encode(batch_size=64,
  normalize_embeddings=True)`; `store_chunks` hands 64 texts per call (was 16).
  Verified by `tests/verify_perf_batching.py` Part A & B (**13/0**).
- B2: `ensure_payload_indexes` requests KEYWORD index on `evidence_id`;
  `ensure_collection` and `store_chunks` wire it in; deduped so embedded Qdrant
  warns once per storage path. Verified by `tests/verify_perf_batching.py`
  Part C (**13/0**).
- A9 (document path): `_read_media_bytes` streams file reads with size caps
  (50 MB text / 2 GB video) and `stop_check`; oversized files fail loudly
  naming the limit. `tests/verify_perf_ingestion.py` Part A & B (**17/0**).
- A10: `_artifact_cap_report` returns structured dict; forensic run persists
  `FILE_INGEST_ARTIFACT_CAP` audit log and writes reason to `evidence.notes`;
  all artifacts still recovered, only capped number embedded. Verified by
  `tests/verify_perf_ingestion.py` Part C (**17/0**).
- A12: Already done in Stage 6 (WS-G): `CO_MENTION_MAX_PERSONS=20` cap on both
  loop bounds (≤190 edges/chunk).
- `tests/bench_pipeline.py` extended: `_retrieval_eval` now evaluates BOTH
  `search_chunks` (dense) and `retrieve` (hybrid); reports both side-by-side
  with preserved baseline keys. Ready for before/after comparison.

### 3d. Stage 6 — NLP / graph — **DONE (WS-G)** with documented residuals
- **A12 DONE.** `graph_builder.py`: co-mention capped at `CO_MENTION_MAX_PERSONS=20`
  on both loop bounds (≤ `C(20,2)=190` edges/chunk); every person still gets a
  `Person` node + `MENTIONED_IN` edge. Measured: a 60-person chunk went 1770 → 190.
- **A11 DONE.** `NER_BUDGET_CHARS=30_000`; the gather loop spends an allowance (an
  oversized chunk is sliced) and `extract_entities()` is bounded too.
- **A7 DONE — and the original finding was partly WRONG (measured).**
  `is_supported_upload` does NOT accept hives; only the in-image
  `is_supported_file` does. Fixed by ROUTING hives to a real extractor (a registry
  branch at the end of `extract_text_from_bytes` via
  `registry_parser.is_registry_hive`/`parse_registry_hive`, `extraction_type=
  'registry'`), not by refusing them.
- **A9 DONE (in-image half).** `hash_entry_sha256()` streams a TSK entry in bounded
  reads; the monolithic `read_random(0, size)` + `compute_sha256_bytes(data)` is gone.
- **RESIDUAL (documented, unfixed on purpose):** peak RSS is still the whole entry
  (entropy/extraction need the bytes); and **extensionless hives (`SYSTEM`, `SAM`)
  bypass the 50 MB cap in `is_supported_file`** — a >2 GB hive is admitted.
  Changing it would start *skipping evidence*, so it is flagged, not guessed.
- **Entity double-count: DECIDED + DOCUMENTED, not implemented.** It needs an
  `EntityMention(case_id, type, name, evidence_id, count)` table with per-evidence
  upsert + re-index delete and `Entity.frequency` recomputed as a sum — requiring
  `models.py` + `ingestion.py` (currently another agent's files). The minimal
  delete-by-evidence fix is UNSAFE today because `Entity.evidence_id` is written
  only at creation.
- Suites added (register in `run_gate.py`): `tests/verify_graph_nlp.py` (10/0),
  `tests/verify_graph_forensic.py` (23/0). `verify_file_formats` 161/0 and
  `verify_split_images` 48/0 still green. Details: `reports/ws_g_graph.md`.

### 3e. Stage 7/8 — test hygiene + integration — **DONE**
- **FIXED (2026-10-11):** `tests/verify_ingestion_modes.py` now uses full
  isolation (temp `DATABASE_URL`/`CASES_DIR`/`QDRANT_DIR` before any backend
  import; deterministic embedder stub; `atexit` cleanup). **45/0**.
- **VERIFIED:** every `tests/verify_*.py` on disk (23 files) is either in
  `run_gate.py` `SUITES` (now 27) or `EXCLUDED` (2). No orphan suites. The two
  exclusions (`verify_live_stack.py`, `verify_provenance_discriminating.py`) are
  legitimate. All new Stage-4/5/6 suites registered.
- **FULL GATE: 1179 passed / 0 failed across 27 scripts** (includes 6 new suites:
  `verify_hybrid_retrieval.py` 21, `verify_graph_nlp.py` 10, `verify_graph_forensic.py` 23,
  `verify_query_traceability.py` 21, `verify_grounding.py` 35, `verify_perf_batching.py` 15,
  `verify_perf_ingestion.py` 17).

### 3f. Final gate + cleanup — **GATE PASSED; CLEANUP PENDING**
- **Final gate:** `venv\Scripts\python.exe tests\run_gate.py` → **1179 passed, 0 failed across 27 scripts** (includes all 6 new regression suites).
- **Deferred cleanup:** Per `AUDIT_BASELINE.md` §9 and `PROGRESS.md` §3f, delete the entire `Test` case (`8895b7fe-dde1-457e-b0bc-0035f483bc6d`), its 3 evidence rows, its ~3,285 `forensic_artifacts`, its `data/cases/8895b7fe-.../` tree (incl. ~6,888-file `extracted/`), the 4 orphan `forensic_artifacts` rows, and scratch files (`%TEMP%\cfi_split_*`, `%TEMP%\cfi_formats_*`, `%TEMP%\cfi_forensic_*`, `%TEMP%\idfa_bench_*`, repo-root `bench_baseline.json`, `bench_run.log`). **Preserve the 3 real demo cases.** No hard-delete API exists; model on `backend/clear_demo_cases.py`.

---

## 4. Hard rules (unchanged from the user)

1. **Honesty over green.** Never claim a command/test passed unless observed.
   Never disable a test, weaken an assertion, or convert a failure into a pass.
   `None` means *not measured* — never rewrite it to `0`.
2. **Do not commit, branch, stash, checkout, or reset.** The user said "NOT NOW".
   `frontend/vite.config.js` and `package-lock.json` stay modified/uncommitted.
3. **Do not delete data** until §3f, and never real evidence. No hard-delete of
   cases before then.
4. **Do not run the full gate while another agent is mid-edit.** The integrator
   runs it once at the end. Do not run `tests/verify_provenance_discriminating.py`
   concurrently with anything reading `vector_store.py` (it reverts the file).
5. **Two homes for indexes** (B28): always consider both `case_qdrant_path()` and
   the relocated `%LOCALAPPDATA%\IDFA\qdrant` path.
6. **Import safety** (B15): `vector_store` imports torch lazily; do not import the
   embedding stack at module import time.
7. **Test-first per stage**: write the suite, run it against the unmodified tree
   to record the real failures, then fix, then re-run.
8. **A live worker** picks up `Queued` jobs and races on the per-case Qdrant dir;
   test suites that create jobs must stop the worker (see `verify_queue_api.py`).

---

## 5. Exact commands

```powershell
cd E:\Users\sarva\Documents\IDFA
$env:PYTHONPATH="."
venv\Scripts\python.exe tests\run_gate.py            # full gate (integrator only)
venv\Scripts\python.exe tests\verify_hybrid_retrieval.py
venv\Scripts\python.exe tests\verify_reindex_idempotency.py
venv\Scripts\python.exe tests\verify_split_images.py
venv\Scripts\python.exe tests\bench_pipeline.py --keep --out bench_after.json
```

## 6. Where things are
`AUDIT_BASELINE.md` (findings A1–A12/B1–B6/C1–C8 with `file:line`, staged plan,
§9 cleanup manifest), `lexical.py` (matcher), `bench_baseline.json` (dense
baseline), `reports/` (per-workstream agent logs).
