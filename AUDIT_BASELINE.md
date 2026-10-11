# AUDIT_BASELINE — Stage 1 findings and the plan that follows

**Status:** read-only audit complete (4 parallel investigations A–D + lead review).
No production code has been changed yet. This file records what was *measured*
and what was only *reported*, so that later stages can be judged against it.

**Date:** 2026-10-11 · **Branch:** `main` @ `7c161fc` · working tree: only
`frontend/package-lock.json`, `frontend/vite.config.js` modified (uncommitted,
pre-existing), plus untracked `SETUP_NOTES.md`.

---

## 1. Purpose and method

The rule for this whole effort is **the repository is the source of truth**. So
every claim below is tied to a `file:line` or an observed command, and the
distinction between *verified* and *reported* is kept explicit.

Method:
- The lead read the core pipeline directly (`ingestion.py`,
  `forensic_ingestion.py`, `vector_store.py`, `rag_engine.py`,
  `graph_builder.py`, `models.py`, `main.py`, `dependencies.py`,
  `database.py`, `tests/README.md`, `generate_test_evidence.py`).
- Four read-only subagents each took one area (A ingestion/forensics,
  B embeddings/indexing/perf, C retrieval/RAG, D tests/integration).
- The lead independently re-verified the headline claims by grep/read before
  accepting them (results noted per finding).

---

## 2. Verified environment facts

| Item | Value | How verified |
|---|---|---|
| Python | 3.12.10 venv at `venv\Scripts\python.exe` | `SETUP_NOTES.md`; used to run code |
| Backend | FastAPI/uvicorn `0.0.0.0:8000` | `Get-NetTCPConnection` |
| Frontend | Vite on **`::1:3000` only** (IPv6 loopback) | `Get-NetTCPConnection` — an IPv4 probe to `127.0.0.1:3000` fails; `localhost:3000` works |
| Ollama | `127.0.0.1:11434`, model `llama3.2:3b` | `/api/status` `ollama.state == "ok"` |
| DB | SQLite `data/forensic.db` | `/api/status` + direct read |
| Embedder | `all-MiniLM-L6-v2`, 384-dim, `max_seq_length=256` | `/api/status` + `vector_store.describe_embedder` |
| pytsk3 / pyewf | **present** | import test in venv |
| Graph store | NetworkX, per-case `graph_store.json` | `graph_builder._get_graph_path` |

**Confirmed absent from `backend/`** (grep, whole tree): `create_payload_index`,
`PayloadSchemaType`, `uuid5`, `MatchText`, `UniqueConstraint`. `batch_size` /
`normalize_embeddings` appear **only** in `device_resolver.py` (the device
benchmark) and spaCy's `nlp.pipe` — never in `vector_store.get_ollama_embeddings`.

---

## 3. Baseline system state (measured, not assumed)

From `/api/status` and a read-only DB read:

- 4 case rows, 3 evidence rows, **0 forensic_artifacts**, **0 ingestion_jobs**,
  **0 query_logs**, 18 audit_logs.
- **0 of 4 case directories hold a Qdrant index.** There is nothing indexed on
  this install, so the accuracy numbers quoted in `rag_engine.py:176-205` and
  `tests/verify_retrieval_integrity.py:64-83` (the "Nightingale corpus") are
  **not reproducible from this checkout** — the corpus is not in the repo.
- A purpose-built fixture exists under the `Test` case
  (`8895b7fe-…/evidence/`): two **complete** split raw sets
  (`SCHARDT.001–.008`, ~4.87 GB each; whole-set digest recorded) and one
  **incomplete** set (a single `SCHARDT.001`, 666 MB, against a partition that
  declares 4.87 GB). MBR is valid (`55 AA`), one partition type `0x07`, volume
  OEM `NTFS`. This is an ideal split-image validation fixture.
- `data/` is gitignored; nothing under it is tracked.

### 3.1 First measured baseline — `tests/bench_pipeline.py`

A new isolated instrument (own temp DB / cases dir / Qdrant dir; the live DB is
never touched) ingests a small deterministic corpus with known ground truth and
runs the **real** `search_chunks` for a labelled query set. Observed run
(report: `bench_baseline.json`):

- **Ingestion (4 files, ~1 KB total):** firewall 0.49 s, email 0.17 s,
  transactions 0.15 s, witness 0.33 s. (Embed-model load happens before timing,
  via `describe_embedder`.)
- **Retrieval, `top_k=14` (4 chunks in the corpus):**

| query | kind | expected | rank | score | top-1 |
|---|---|---|---|---|---|
| "How much data… 203.0.113.77 … which port?" | semantic | firewall | 1 | 0.308 | ✓ |
| `203.0.113.77` | identifier | firewall | **3** | **0.133** | transactions.csv (0.268) |
| "…SHA-256 hash… darknode.io?" | semantic | email | 1 | 0.550 | ✓ |
| `9f86d081…f00a08` (64-hex) | identifier | email | 1 | 0.284 | ✓ |
| "Which account received 18500 dollars?" | semantic | transactions | 1 | 0.431 | ✓ |
| `ACC-4471-9930` | identifier | transactions | 1 | 0.487 | ✓ |
| "Who witnessed the delivery…" | semantic | witness | 1 | 0.651 | ✓ |
| "What is the capital of Finland?" | negative | — | — | top1 0.135 | (below floor) |

**The one signal that matters:** the exact-IP query put the *correct* chunk at
rank 3 with **score 0.133 — under `RETRIEVAL_SCORE_FLOOR = 0.15`**, so
`apply_relevance_floor` would discard it and `run_rag_query` would answer "none
scored above the relevance floor". On a 4-chunk corpus the correct chunk is
still *retrieved*; on a realistic multi-thousand-chunk case it would not be
ranked at all. This is finding **C1** reproduced, measured, before any change.

---

## 4. Findings

Ranking: **(P1)** correctness/integrity, **(P2)** retrieval quality,
**(P3)** performance, **(P4)** hygiene. Every item below is *verified by code
reading* unless marked otherwise; the headline ones were re-checked by the lead.

### 4.1 Ingestion / forensics

| # | P | Finding | Evidence |
|---|---|---|---|
| A1 | P1 | Upload gate and pipeline dispatch use **different** predicates. The gate accepts continuation segments (`is_supported_upload` → `is_image_segment_extension`), but dispatch is `ext in FORENSIC_IMAGE_EXTENSIONS`, which is only `{.e01,.001,.dd,.raw,.img}`. A lone `X.002` is accepted, routed to the **document** pipeline, sniffs as binary → `unsupported`/empty → evidence marked **Indexed with 0 chunks**. `is_forensic_image` is imported into `ingestion.py` and never used. | `ingestion.py:11,138`; `file_formats.py:361,393,402` |
| A2 | P1 | `verify_evidence_integrity` **always fails for a split set**: upload stores `sha256_hash` = digest of *all segments concatenated* but `file_path` = *first segment only*, and verify re-hashes only `file_path`. | `evidence.py:425-426,646-655` |
| A3 | P1 | Ingestion **overwrites** the upload-time hash with the first-segment hash (`compute_sha256(file_path)`), so one column holds two meanings. | `ingestion.py:633` |
| A4 | P1 | Interior holes in a split set are **not reported**: `set_incomplete` requires `len(segments)==1`, and `image_segment_paths` stops at the first missing segment so coverage past the hole is never measured. | `forensic_ingestion.py:1399-1400,1229-1230` |
| A5 | P1 | **No idempotency**: no unique constraint on `(evidence_id, internal_path)`, re-queue deletes only the job row, and entities are **incremented** (`existing.frequency += count`) → duplicated vectors + double-counted entities. | `models.py:78-94`; `queue_router.py:189-195`; `ingestion.py:1250` |
| A6 | P1 | **No HTTP upload body-size limit** anywhere (only CORS + rate limit); files stream straight into the cases dir. | `main.py:59,68`; `evidence.py:214` |
| A7 | P2 | Registry hives (`ntuser.dat`, `SYSTEM`, `SAM`) are **dead code** on the in-image walk: `is_supported_file` admits them by name, but `extract_text_from_bytes` has no registry branch → sniffed → `unsupported`. | `forensic_ingestion.py:227-234,750-762`; `media_extractor.py:958` |
| A8 | P2 | 3-digit suffix classification is over-broad: `.100`–`.999` are treated as raw split segments, so `app.log.100` is classified as a disk image. | `file_formats.py:269` |
| A9 | P3 | Whole-file reads into RAM on both paths (`data = f.read()`; `entry.read_random(0, size)`); the 50 MB / 2 GB caps apply only to the in-image walk. | `ingestion.py:320`; `forensic_ingestion.py:1659,137-138` |
| A10 | P3 | Indexing stops silently at **500 stored artifacts** with no ranking and no persisted reason. | `ingestion.py:907-910` |
| A11 | P3 | NER sees only the first `NER_BUDGET_CHARS = 30_000` chars of chunk text. | `graph_builder.py:156,159` |
| A12 | P4 | `CO_MENTIONED_WITH` edges are quadratic across all persons in a chunk. | `graph_builder.py:228-235` |

### 4.2 Embeddings / indexing / performance

| # | P | Finding | Evidence |
|---|---|---|---|
| B1 | P1 | Point ids are `uuid.uuid4()` with **no content hash and no delete-before-reindex** → re-ingestion appends duplicates that surface twice in every search. (Headline re-verified: no `uuid5` in tree.) | `vector_store.py:463` |
| B2 | P2 | **No payload index** on `evidence_id` (or `case_id`); the `evidence_id` filter is an unindexed scan. (Headline re-verified: no `create_payload_index`.) | `vector_store.py:465-471,603-612` |
| B3 | P2 | `get_collection_name` truncates to `case_{case_id[:8]}`. Safe today (one dir per full id) but a latent alias trap with no guard. | `vector_store.py:280` |
| B4 | P3 | Production encode calls `model.encode(truncated)` with **no `batch_size` and no `normalize_embeddings`**, while `device_resolver` benchmarks with `batch_size=64, normalize_embeddings=True` and *claims* to match production. Effective encode batch is `EMBED_SLICE=16`. (Headline re-verified by grep.) | `vector_store.py:271,453-457`; `device_resolver.py:29-30,99-100` |
| B5 | P4 | The `t[:1000]` slice is **inert** at `chunk_size=700` (documented as measured-redundant) but reads as a live truncation. | `vector_store.py:263-272` |
| B6 | P4 | `mode["max_parallel"]` and `budget["batch_size"]` are returned and advertised but **have no consumer**; the worker runs one job at a time. | `ingestion_modes.py:344,436-441`; `job_worker.py:347-366` |

**Measured perf numbers already in-comment** (source, *measured* unless noted):
upsert ≈ **92%** of a document ingest, 47 s of 81 s for 2.7 MB, embed 3 s, other
3 s (`vector_store.py:40-47`); 361 chunks: ~3 s embed vs ~47 s upsert on a
7200 RPM disk, ~4 s on NVMe, **12×** (`hardware_probe.py:47-49`); ~13× cited
separately (`dependencies.py:13-14`) — one quantity, two constants;
2.01–3.08 chars/token → ~513–788-char window (`vector_store.py:233-234`).
*Estimated:* `time_estimator.TIME_PER_MB` ("M1 Mac 8 GB"), `MODE_TIME_FACTOR`.

### 4.3 Retrieval / RAG / accuracy

| # | P | Finding | Evidence |
|---|---|---|---|
| C1 | P1 | Retrieval is **dense-only** (`client.search`), and the "lexical" filter is a query-level **gate**, not retrieval — it never adds/reorders chunks. There is no BM25/sparse/exact/hybrid/RRF/rerank anywhere. An exact IP / hash / email / filename may therefore miss. | `vector_store.py:614`; `rag_engine.py:345,778` |
| C2 | P1 | **No programmatic grounding check**: nothing verifies that identifiers in the answer appear in the retrieved text. Only `is_refusal` and a `<20`-char length fallback. `extract_entities` is imported into `rag_engine.py` and never used. | `rag_engine.py:3,585-609,673,696` |
| C3 | P1 | **No claim↔excerpt traceability.** `clean_response` strips `[Source:…]`/`(Excerpt N)`; the footer lists unique files only; `cited_sentence_count` = count of unique sources and `uncited_sentence_count` is hard-coded `0`. `chunks_used` is stored but **never returned by the API**. (Re-verified: `chunks_used` absent from `queries.py` response.) | `rag_engine.py:40-51,109-131,712-715`; `queries.py:90-103`; `schemas.py:86-108` |
| C4 | P2 | The gate's refusal text overclaims ("shares no wording with **anything indexed in this case**") while it only inspects the **top-14** retrieved chunks; it can also refuse a *well-retrieved* answer, and has **zero** tests. | `rag_engine.py:331-342,804-839` |
| C5 | P2 | No excerpt dedup and no source-aware reranking: 14 overlapping chunks (120-char overlap) can fill the prompt, and one long file can take all 14 slots. | `rag_engine.py:546-547`; `verify_prompt_budget.py:236-245` |
| C6 | P2 | `conv_context` is **unbounded** (answers capped 500 chars, questions not) and is **protected** in the prompt, so a client can crowd out all evidence; client-supplied history is unvalidated and the app's own abstention messages get replayed as "Assistant" turns. | `rag_engine.py:904-924,501`; `schemas.py:83` |
| C7 | P2 | Two adjacent paths consult the model with **no evidence**: entity profile (`chunks == []`) and case summary (`evidence_context == "No evidence indexed yet."`). | `entities.py:438-455`; `cases.py:573` |
| C8 | P1 | **No accuracy benchmark.** `verify_retrieval_integrity.py` guards *constants* (literals from an absent corpus), not quality. No labelled set, no Recall@k/MRR. | `verify_retrieval_integrity.py:64-83` |

### 4.4 Testing / integration

Agent D is still collecting the full gate result; its inventory and observed
run will be appended. Known so far (`tests/README.md`): ~23 `verify_*.py`
suites driven by `tests/run_gate.py`, which parses `SUITE PASSED — N` /
`SUITE FAILED — X of Y` and treats unreadable counts as INVALID (not zero).
**No test exists for the split-image path** (commit `7c161fc` added none), none
for the lexical gate, and none for `image_segment_paths` / `_group_image_segments`
/ `_store_image_segment_set`.

---

## 5. What could NOT be measured in Stage 1

- Any end-to-end ingest timing on this box (nothing indexed; must not disturb
  the running server). The instrument to fix this is
  `tests/bench_pipeline.py` (added this stage) — isolated temp DB/cases/Qdrant.
- Retrieval quality (Recall@k) on this install — no index, no labelled corpus.
- Whether the lexical gate fires on a *high-scoring* retrieval in practice.
- Live split-set ingestion through the API (would write to the real DB).

---

## 6. Staged plan (implementation, validated stage by stage)

Ordering is deliberate: correctness and reproducibility first, because every
later measurement depends on the index being trustworthy.

1. **Stage 2 — Split-image correctness (P1).** A1 dispatch parity, A2/A3 hash
   semantics, A4 interior-hole reporting, A8 segment classification bound.
   *Validation:* a new `tests/verify_split_images.py` covering segmentation,
   ordering, interior gaps, hash meaning; plus the `SCHARDT` fixture.
2. **Stage 3 — Idempotency & index integrity (P1).** B1 deterministic point
   ids, delete-by-`evidence_id` on re-index, A5 unique `(evidence_id,
   internal_path)`, B2 payload index, B3 full-id collection name.
   *Validation:* `tests/verify_reindex_idempotency.py` — ingest twice, assert
   vector/artifact/entity counts unchanged and no duplicate search hits.
3. **Stage 4 — Retrieval quality (P1/P2).** C1 lexical/exact branch fused with
   dense + dedup (needs point id in the result dict), C2 grounding check,
   C3 expose `chunks_used` in `QueryResponse`, C4 gate overclaim, C5 dedup,
   C6 bound `conv_context`.
   *Validation:* labelled benchmark in `tests/bench_pipeline.py`; Recall@k
   before/after, identifier queries specifically.
4. **Stage 5 — Performance (P3).** B4 real batching/normalization aligned
   between production and the device benchmark; A9 stream hashing; A10 persist
   the artifact cap; A12 cap co-mentions.
   *Validation:* `bench_pipeline.py` stage timings before/after.
5. **Stage 6 — NLP/graph (P2).** A7 registry branch, A11 NER budget,
   entity provenance.
6. **Stage 7 — Tests/regression.** Fold the new suites into `run_gate.py`.

Each stage: smallest change that closes the finding, a test that fails before
and passes after, and the full gate re-run before the next stage.

---

## 7. Stage 2 — split-image correctness (DONE)

**Test first.** `tests/verify_split_images.py` (registered in `run_gate.py`) was
run against the unmodified tree and failed **6 of 17**: the dispatcher predicate
did not exist, an interior-hole set was reported as "re-acquire", and the custody
hash had no whole-set path. After the changes below it is **48 passed, 0 failed**.

| # | Change | File |
|---|---|---|
| A1 | `route_for_filename()` is now the single dispatch predicate and asks the shared `is_forensic_image()`, so a `.002`/`.E02` goes to the forensic pipeline instead of the document pipeline. Removed the now-unreferenced `FORENSIC_EXTENSIONS` alias. | `backend/ingestion.py` |
| A4 | `set_incomplete` is `bool(missing_segments)`, no longer gated on `len(segments) == 1`; the branch sets `truncated = True` and names the missing segments ("upload the missing segment(s)") instead of falling through to "re-acquire the complete image". | `backend/modules/forensic_ingestion.py` |
| A3 | The forensic walk no longer writes its first-segment hash over `evidence.sha256_hash`; it logs it, and compares it only where the comparison is meaningful (non-split files). | `backend/ingestion.py` |
| A2 | New `hash_evidence_set()` hashes the whole segment set in order; `verify_evidence_integrity` uses it, so an intact split set no longer reports "file has been modified since ingestion". | `backend/routers/evidence.py` |

Two corrections to the agent findings, made after reading the code myself:
`missing_image_segments()` *does* already detect interior holes (the defect was
only the `len == 1` guard), and the lone-`.001` fixture was already reported
honestly as "13.7% present" — so A4 is narrower than first reported.

**Independent reproduction (read-only):** `is_supported_upload` accepts
`SCHARDT.002/.008`, `case.E02/.E99`, `x.100/.999`, `app.log.100`, none of which
are in `FORENSIC_IMAGE_EXTENSIONS` — that set difference is asserted by the new
suite so the fix cannot silently regress.

**Deferred:** A8 (`.100`–`.999` read as raw segments, so `app.log.100` looks like
a disk image). It is a real misclassification but the fix needs a filesystem
sibling check in a function the upload gate calls with only a filename, so it
goes with Stage 3 rather than being rushed here.

---

## 8. Stage 3 - re-index idempotency (DONE)

The defect (A5/B1): `store_chunks` minted `id=str(uuid.uuid4())` per point, and
nothing deleted an evidence item's previous vectors before a re-index, so every
re-ingest appended a second full copy of the document.

**Test first.** New `tests/verify_reindex_idempotency.py` (hermetic: temp DB /
cases / Qdrant chosen before any backend import, deterministic 384-dim embedder
stub, no Ollama needed). Against the unmodified tree it failed **7 of 11**:

```
FAIL A1 second identical store does not grow the point count   -- 6 -> 12 points
FAIL A2 second store writes the same point ids                 -- 6 of 6 changed
FAIL A3 (source, chunk_index) unique after re-store            -- 6 duplicates
FAIL B1 second full ingest does not grow the point count       -- 18 -> 36 points
FAIL B3 (source, chunk_index) unique after re-ingest           -- 18 duplicates
FAIL B2b point ids deterministic across re-ingest              -- 18 of 18 changed
FAIL C1 search returns no duplicate (source, chunk_index)      -- 18 dup / 36 hits
```

After the fix it is **13 passed, 0 failed**, and the log shows the replace:
`[INGESTION] Re-index: removed 18 previous point(s) for evidence ...`.

| # | Change | File |
|---|---|---|
| B1 | Point ids are a `uuid5` over `case_id\|evidence_id\|source_filename\|chunk_index\|text` via `_point_id()`, so an identical re-store overwrites in place. | `backend/modules/vector_store.py` |
| A5 | New `delete_evidence_points()` clears one item's points; called **once** before either pipeline starts. | `vector_store.py`, `backend/ingestion.py` |

**The non-obvious part.** The delete could not go inside `store_chunks`: *both*
call sites loop over the **same** `evidence_id` (document path once per embed
batch at `ingestion.py:410`, forensic path once per artifact at `:960`). A
per-call delete would erase the batches already written in the same run and keep
only the last. It is therefore a single call in `run_ingestion_with_progress`,
immediately before dispatch, and it refuses to empty an index whose provenance
is a MISMATCH (mirroring `store_chunks`, which would refuse to write it a moment
later). Part D re-ingests *changed* text to prove the replace path fires -
deterministic ids alone would pass the identical-input checks.

**Gate-portability finding (was blocking the whole gate).**
`tests/verify_provenance.py:21` hard-coded
`os.chdir(r"D:\Users\Anon\Desktop\IDFA_main3")` - the original author's checkout.
On this machine it died with `FileNotFoundError` before printing a summary, which
`run_gate.py` reads as `?? unreadable`, and one unreadable suite makes the gate
refuse to total at all ("Treat this run as invalid"). So the gate had **never**
produced a trustworthy total. The `chdir` was removed (nothing in that suite
depends on the working directory - it builds its own temp dirs and a fake Qdrant
client). `verify_reindex_idempotency.py` is registered in `run_gate.py`.

---

## 9. Deferred cleanup - user-confirmed (do AFTER all stages)

The user asked me to clear the ingested test data once testing is finished, and
chose the widest scope. My automated suites did **not** write into the app (all
isolated in temp), so this is test data ingested through the running app.

Delete, after the gate and all stages finish:

* Every row for case **`Test`** = `8895b7fe-dde1-457e-b0bc-0035f483bc6d`
  (`case_number=None`): its 3 evidence rows (`0a7f607a-...`, `e791b2df-...`,
  `f224f926-...`), its **3,285** `forensic_artifacts`, its entities/audit rows,
  and on disk the `data/cases/8895b7fe-.../` tree - including the **6,888-file**
  `extracted/` tree under `evidence/0a7f607a-.../extracted/`.
* The **4 orphan** `forensic_artifacts` rows whose `case_id` no longer exists:
  `22b0e0ca-6f2c-4abe-bf4f-25510f9f0022`, `ac593c08-e8ce-42b8-9e84-3dd70343d540`,
  `ba16b326-e125-4aa6-97d5-16ee24cf43f3`, `bd28b4f9-ba9c-4d00-abca-68d47058edca`.
* My own scratch: `%TEMP%\cfi_split_*`, `%TEMP%\cfi_formats_*`,
  `%TEMP%\cfi_forensic_*`, `%TEMP%\idfa_bench_*`; repo-root `bench_baseline.json`
  and `bench_run.log`.

Keep the three real demo cases (`Operation Phantom Trace`, `Vertex Pharma Leak`,
`Havenport Missing Person`). There is **no hard-delete API** -
`DELETE /evidence/{id}` is a soft archive - so this is a direct DB + disk
operation, modelled on `backend/clear_demo_cases.py` (which matches by case
*name*, so it does not match `Test`).

---

## 10. Stage 4 - retrieval quality (IN PROGRESS)

The headline finding is C1, and it is measured, not asserted. From
`bench_baseline.json`: the query `203.0.113.77` ranked the chunk that literally
contains that address **3rd at 0.133** - below `RETRIEVAL_SCORE_FLOOR` (0.15) -
while an unrelated `transactions.csv` scored **0.268** and took first place.
Retrieval is dense-only, and cosine is the wrong instrument for the exact
identifiers a forensic question is mostly made of.

**Why the existing tokeniser cannot fix it.** `rag_engine.content_terms` - the
no-shared-terms gate - deliberately drops bare digits and 1-char runs, so it
cannot even see `203.0.113.77`. Matching needs its own tokeniser. Both are now
pinned by tests so a change to one cannot silently alter the other.

### 4.1 exact-identifier retrieval (hybrid)

**Test first.** New `tests/verify_hybrid_retrieval.py`, run against the
unmodified tree: **0 passed, 4 failed** (the interface does not exist yet; each
part reports one named MISSING failure and still prints a summary, so the gate
can total it either way).

Pinned interface:

| name | file | contract |
|---|---|---|
| `identifier_terms(text)` | `backend/modules/lexical.py` (new) | alnum runs >= 2 chars, stopwords dropped, **digits kept** |
| `QUERY_STOPWORDS` | `backend/modules/lexical.py` | canonical set; `rag_engine._QUERY_STOPWORDS` will alias it |
| `bm25_idf` / `document_frequencies` / `weighted_coverage` | `lexical.py` | stdlib-only IDF weighting (no torch) |
| `lexical_search(query, case_id, qdrant_path, limit, evidence_id)` | `vector_store.py` | payload scan + IDF score; returns the dense-shaped dicts plus `match` |
| `retrieve(query, case_id, qdrant_path, top_k, evidence_id)` | `rag_engine.py` | fuses dense + lexical; dedups by `(source, chunk_index)`; each entry gains `dense_score`, `lexical_score`, `match`, `point_id` |

Two design decisions that are load-bearing:

* **`score` stays the cosine.** A lexical-only hit reports `score: None`, which
  `apply_relevance_floor` deliberately KEEPS ("refusing to act when there is
  nothing to compare"). Putting the fusion value in `score` would let the 0.15
  cosine floor drop the exact match it exists to rescue.
* **`vector_store` imports `lexical`, never the reverse.** `lexical.py` is
  stdlib-only, so tokenising a string never drags in the embedding stack (B15).

`tests/verify_hybrid_retrieval.py` pre-fix: **0 passed / 4 failed** (surface
absent). Implementation pending the Stage-3 gate finishing (both files it needs
to touch are read by `verify_vector_store.py` / `verify_retrieval_integrity.py`).

C3 (traceability) groundwork confirmed while reading the router: `POST
/api/cases/{id}/queries/ask` stores `chunks_used` (as JSON on the Query row) but
does **not** return it, and `schemas.QueryResponse` (used by the GET) has no
`chunks_used` field at all. The POST has no `response_model`, so adding it there
is purely additive; exposing it on GET is an additive optional field.
