# Workstream G — Stage 6 (NLP / graph) + A9 stream hash

Owner: WS-G. Files I own and edited:

- `backend/modules/graph_builder.py` (A11, A12)
- `backend/modules/forensic_ingestion.py` (A7, A9)
- `tests/verify_graph_nlp.py` (new, A11+A12)
- `tests/verify_graph_forensic.py` (new, A7+A9)
- `reports/ws_g_graph.md` (this file)

Nothing else was edited. `tests/run_gate.py` is the integrator's; **the two new
suites must be registered there** (they match `tests/verify_graph_*.py`).

No commit/branch/stash/reset. No data deleted.

---

## 1. Results (observed, not claimed)

| suite | before | after |
|---|---|---|
| `tests/verify_graph_nlp.py` (A11+A12) | **4 passed / 5 failed** | **10 passed / 0 failed** |
| `tests/verify_graph_forensic.py` (A7+A9) | **3 passed / 14 failed** | **23 passed / 0 failed** |
| `tests/verify_file_formats.py` (regression) | 161 / 0 | **161 / 0** |
| `tests/verify_split_images.py` (regression) | 48 / 0 | **48 / 0** |

Commands (PowerShell):

```powershell
cd E:\Users\sarva\Documents\IDFA
$env:PYTHONPATH="."
venv\Scripts\python.exe tests\verify_graph_nlp.py
venv\Scripts\python.exe tests\verify_graph_forensic.py
venv\Scripts\python.exe tests\verify_file_formats.py
venv\Scripts\python.exe tests\verify_split_images.py
```

I did **not** run `tests/run_gate.py` and did **not** run any retrieval/perf
suite.

### Pre-fix failures (recorded before any source edit)

`verify_graph_nlp.py`:
```
FAIL  the co-mention cap is a named, documented constant  -- CO_MENTION_MAX_PERSONS=None
FAIL  a 60-person chunk does not produce the quadratic edge count  -- got 1770 co-mention edges
FAIL  the NER budget is a named constant  -- NER_BUDGET_CHARS=None
FAIL  one oversized chunk cannot exceed the NER budget  -- fed 100003 chars, budget 30000
FAIL  extract_entities cannot run an unbounded NER pass  -- fed 120000 chars, budget 30000
PASSED: 4    FAILED: 5
```
(The three passes were the guards that must stay true: a 5-person chunk keeps
all 10 pairwise edges, nobody is dropped from the graph, and many small chunks
already stopped at the budget.)

`tests/verify_graph_forensic.py`: **3 passed / 14 failed** — all six hive names
returned `unsupported` (12 checks), `extract_file_content` reported a hive as
`unsupported`, and `hash_entry_sha256` did not exist. The two "hash/extract
still work" checks passed before and after.

---

## 2. A12 — cap `CO_MENTIONED_WITH`

`build_graph` gave every pair of people in a chunk an edge, so a chunk naming
`n` people produced `n(n-1)/2` inserts with no limit. Measured before: a chunk
with 60 distinct people produced **1770** co-mention edges.

**Change:** new module constant `CO_MENTION_MAX_PERSONS = 20`; the pairwise pass
now iterates `min(len(persons_resolved), CO_MENTION_MAX_PERSONS)` on *both*
loop bounds, so one chunk adds at most `C(20,2) = 190` co-mention edges.
Recorded in the constant's comment.

**Why this shape.** The cap is on the number of people considered for the
*pairwise* relation only. Every person still becomes a `Person` node and still
gets a `MENTIONED_IN` edge to the file, so entity coverage is unchanged — only
the quadratic co-occurrence relation is bounded. Capping only the outer `j`
loop would still leave `O(n·20)` work (each capped person would connect to every
uncapped one); both bounds must be capped for the relation to be bounded. 20 is
well above what a 700-char prose chunk names. The suite asserts all 60 people
remain `MENTIONED_IN`.

---

## 3. A11 — bound the NER work

Two gaps, both real:

1. `build_graph` *did* have a 30,000-char budget, but its loop
   (`if budgeted and budget_used + len(c) > NER_BUDGET_CHARS: break`) always
   admitted the **first chunk whatever its size** — exactly the oversized shape
   a budget exists to bound. Measured before: a single 100,003-char chunk was
   fed to spaCy whole.
2. `extract_entities()` (the standalone entry point used by
   `get_graph_context` and the grounded-answer check) called `nlp(text)` with
   **no bound at all**. Measured before: a 120,000-char input was fed whole.

**Change:**
- `NER_BUDGET_CHARS = 30_000` is now a module-level constant (was local to
  `build_graph`), and the gather loop spends a `remaining` allowance: normal
  700-char chunks are still taken whole; only a chunk that alone overflows the
  remainder is sliced, so the total handed to spaCy can never exceed the budget.
- `extract_entities()` slices its input to the same budget.

The one comment ("chunks are taken whole rather than sliced") was corrected to
say that only a single oversized chunk is sliced.

---

## 3b. A7 — registry hives reach a real extractor

**Correcting the finding first (measured):** `is_supported_upload` does **not**
accept hives — I measured `is_supported_upload("SYSTEM"/"SOFTWARE"/.../.DAT")`
all `False` (they have no allowlisted extension). Only the in-image walk's
`is_supported_file` admits them by name. So the dead branch was on the in-image
path only.

The cascade: `extract_text_from_bytes` dispatches on extension; registry hives
have none (`SYSTEM`) or one in no allowlist (`.dat`), so they reached the final
`_sniff_unknown_text(data)` and were reported `unsupported` (measured for all
six hive names). `media_extractor.extract_media` already contains a registry
branch, but `extract_text_from_bytes` only routes to `extract_media` for the
Office/audio/video/email extension sets — which a hive is not.

**Change:** a registry branch at the end of `extract_text_from_bytes`, before
the content-sniff fallback, that matches by basename via
`registry_parser.is_registry_hive()` and calls the existing
`parse_registry_hive(data, name, temp_dir)`. Returns the uniform 3-tuple with
`extraction_type='registry'`. Guarded by `try/except ImportError` so a missing
`registry_parser` degrades to the old sniff path rather than breaking the walk.
Chosen over "make the accepted-set honest" because the extractor already exists
and the walk already admits the format — the honest fix is to route, not to
start refusing evidence. (`python-registry` is installed on this machine;
`parse_registry_hive` returns a truthful "not installed" advisory if it is not.)

---

## 3c. A9 — stream the entry hash (in-image path)

`extract_file_content` read a whole TSK entry with one
`entry.read_random(0, size)` and hashed the buffer afterwards.

**Change:** new `hash_entry_sha256(entry, size, chunk_size=_HASH_CHUNK,
stop_check=None)` streams the entry in bounded reads, updating the digest as it
goes, and returns `(hexdigest, data)`. `extract_file_content` now uses it (the
old `compute_sha256_bytes(data)` line is gone). The short-read check and its
IOError are unchanged. `compute_sha256_bytes` is left in place (public helper).

**Honest limitation (recorded in the function docstring):** `data` is still the
whole entry, because entropy, `stored_file_path` writing and extraction all need
the bytes. So this bounds each read *request* and removes the second full-buffer
hashing pass; it does **not** by itself cap peak RSS. A true fix needs a
streaming entropy counter (`entropy_analyzer.calculate_shannon_entropy` builds a
`Counter` over the whole buffer) and streaming extractors — neither is in a file
WS-G owns. Left documented rather than half-implemented.

**Residual observed and left unfixed:** `is_supported_file` gives an
extensionless hive (`SYSTEM`, `SAM`, `SOFTWARE`, `SECURITY`) **no size cap at
all** — measured `is_supported_file("SYSTEM", 2 GiB + 1) is True`, while
`NTUSER.DAT` (which has an extension) is correctly capped at 50 MB. I did *not*
change admission semantics, because capping a legitimately large SOFTWARE hive
at 50 MB would start *skipping evidence*, and that is a product decision, not a
hardening one. Flagged for the next agent; the read is now at least streamed.

---

## 4. Entity double-count — DECIDED and DOCUMENTED, not implemented

Decided approach, in order of preference:

1. **Provenance table (recommended).** Add `EntityMention(entity_id` or
   `(case_id, entity_type, name)`, `evidence_id`, `count)` and make it the
   source of truth. Ingest upserts the count **for that evidence** (replace, not
   `+=`); `Entity.frequency` is recomputed as `SUM(count)` over the provenance
   rows. Re-indexing an evidence item deletes its provenance rows first,
   exactly mirroring Stage 3's `delete_evidence_points()` +
   deterministic-point-id pattern.

2. **Delete-by-evidence on re-ingest (minimal).** Delete the evidence's
   `Entity` rows before saving. **Not safe today**: `models.Entity.evidence_id`
   is set only when the row is *created* (`ingestion.py:1310`); an entity first
   seen in evidence A and again in evidence B keeps `evidence_id = A`, so a
   delete-by-evidence would erase B's contribution and silently undercount. It
   also cannot recompute a case-wide frequency from per-evidence rows.

Why not implemented by WS-G:
- It needs a schema change in `backend/models.py` and a migration for the
  existing `data/forensic.db`, plus logic changes in `backend/ingestion.py`
  (`_save_entities_to_db`). Both files are owned by other workstreams (P owns
  `ingestion.py`), and I was explicitly told not to edit them.
- Doing it in `graph_builder.py` alone cannot fix it: the `+=` happens in
  `ingestion.py`; `build_graph` only reports per-chunk counts.

Concrete evidence for the next agent: `ingestion.py:1298-1315` is the only
`frequency` mutation (`existing.frequency += ent_data["count"]`); the
`Entity.evidence_id` column (`models.py:192`) is written once at creation and
never updated.

---

## 5. Files changed (exact)

```
backend/modules/graph_builder.py   +53/-?  (A11, A12)
backend/modules/forensic_ingestion.py  (A7, A9 only — see note)
tests/verify_graph_nlp.py          NEW
tests/verify_graph_forensic.py     NEW
reports/ws_g_graph.md              NEW (this file)
```

Note: `backend/modules/forensic_ingestion.py` already carried an uncommitted,
pre-existing Stage-2 A4 hunk in `inspect_raw_image` before I started (visible in
`git diff`). I did **not** author or modify it; my hunks in that file are only
`hash_entry_sha256`, the registry branch, and the `extract_file_content` hash.

## 6. For a successor

- Register `tests/verify_graph_nlp.py` and `tests/verify_graph_forensic.py` in
  `tests/run_gate.py` (integrator).
- Constants are load-bearing and pinned by tests: `NER_BUDGET_CHARS = 30_000`,
  `CO_MENTION_MAX_PERSONS = 20`. Changing either without updating the suite will
  fail it.
- `extract_entities` now truncates input to `NER_BUDGET_CHARS`. The grounding
  check (Stage 4.3, WS-R) uses it on the *answer* text, which is short, so this
  is inert there — but keep answers below ~30 K chars or a trailing identifier
  would not be seen.
- A9 peak-RSS reduction and the uncapped-extensionless-hive admission are both
  still open (see §3c).
- Entity double-count needs the provenance table in §4 before any code change.
