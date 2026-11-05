# Current exhibition samples

Both samples are **entirely synthetic fiction**, built by deterministic scripts
and safe to rebuild offline:

- **`aurora_fiction/`** — the small five-minute story (11 files). Start here.
  See that folder's README for the evidence, expected source-backed
  observations, preparation instructions and demonstration.
- **`aurora_expanded/`** — the larger 36-file companion with many cross-file
  identifiers, designed to populate the entity/relationship graph. Same story,
  more correlation material. See its README for the identifier table and
  expectation limits.

Create labelled cases from a terminal with the service-based importer:

```powershell
.venv\Scripts\python.exe scripts\prepare_aurora_demo.py --create --confirm-gui-not-in-aurora --username admin
.venv\Scripts\python.exe scripts\prepare_aurora_demo.py --create --confirm-gui-not-in-aurora --username admin --dataset expanded
```

The importer refuses an existing case, uses the local worker, persists explicit
no-model analysis parameters before dispatch and performs no embeddings or model
calls.

Harbor is retained in `harbor_fiction/` at the user's request. The older generic
sample is retained under `tests/fixtures/legacy_demo/` for regression use only.
Do not present any sample as real evidence or an AI verdict as a verified finding.
