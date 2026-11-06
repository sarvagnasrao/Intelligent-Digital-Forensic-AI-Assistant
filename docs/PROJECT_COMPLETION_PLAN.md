# IDFA — Project Completion and Verification Plan

**Project:** Intelligent Digital Forensic AI Assistant (IDFA)  
**Baseline:** `Desktop-Application` at `0cd0ddcf8bd32fa473d2fdb34d184d9d26296a02`  
**Working branch:** `improvement/forensic-hardening-roadmap`  
**Status:** Engineering roadmap; tasks below are NOT claims of completed implementation or passing tests.

## 1. Product objective and finish line

Deliver a Windows desktop, local-first digital forensic assistant that allows an authorized investigator to register and verify disk evidence, examine and extract artifacts, search and reason over case-scoped evidence, maintain provenance and custody history, build findings and timelines, and generate clearly sourced investigative reports. Local models must work without cloud access; optional cloud AI must require explicit per-case consent.

**Final-year demonstration definition of done:** In a fresh Windows installation, an investigator can complete the entire synthetic-case workflow below with no network dependency beyond intentional model installation, see repeatable outputs, and generate an internally consistent report. No part of the app is represented as guaranteeing legal admissibility or AI factual correctness.

## 2. Architecture to preserve

- **UI:** PySide6 Windows desktop application (`app/ui/`).
- **Local worker:** FastAPI forensic/AI backend (`worker/main.py`), started by the desktop workflow, using pytsk3/libewf for disk evidence and Ollama for local models.
- **Persistence:** SQLite, SQLAlchemy ORM and Alembic migrations (`app/db/`, `migrations/`).
- **Retrieval:** Case-scoped artifact search; FTS, regex, embedding and hybrid retrieval (Qdrant where configured).
- **Outputs:** Findings, custody/audit entries, entity/relationship/timeline views, PDF reports.
- **Packaging:** PowerShell install/start/stop scripts, Inno Setup, synthetic Aurora and Harbor fixtures.

Do not replace the architecture or rewrite major UI pages merely for stylistic reasons.

## 3. Prioritized engineering backlog

| Priority | ID | Workstream | Exit criteria |
| --- | --- | --- | --- |
| P0 | SEC-01 | Worker authentication | Desktop and worker share a per-launch secret; every sensitive HTTP endpoint rejects requests without it; binding defaults to loopback; untrusted API callers cannot use arbitrary file paths/cloud credentials. |
| P0 | DATA-01 | Reversible case archive | No ordinary GUI path hard-deletes a case; an active admin can archive and restore with an auditable reason; evidence, custody, hashes, findings and reports remain intact; archived cases do not accept investigation mutations. |
| P0 | SEC-02 | Evidence-path validation | Worker processes only explicitly registered/authorized evidence sources, with canonical path checks, case linkage, and traversal protection; synthetic image extraction still works. |
| P0 | CON-01 | Isolate simultaneous examinations | Eliminate or serialize global `_img_info`/`_fs_info` state; concurrency tests prove one examination cannot corrupt another's filesystem handles or job tracking. |
| P0 | AUTH-01 | Credential security | Require a unique first-run administrator credential and password change; migrate legacy fast-SHA-256 to Argon2id (or supported adaptive KDF), verify with constant-time safe APIs; add auth failure tests. |
| P0 | INTEG-01 | Acquisition integrity | Calculate independent source and stored-image digests, compare before registration success, detect changed sources, and enforce integrity at service—not only UI—boundaries. |
| P1 | AI-01 | Grounded answers | Scope context by case, present exact cited artifact identifiers, handle insufficient evidence explicitly, and distinguish generated hypotheses from verified findings. |
| P1 | AI-02 | Cloud privacy and secret storage | Enforce consent in backend; fail closed if DPAPI fails; never log/send cloud secrets; cloud use is disabled by default and testable with a fake endpoint. |
| P1 | DATA-02 | Deletion and report consistency | Ensure removed evidence does not reappear as active in reports/search/AI; preserve tamper-evident history and handle missing files without accidental deletion. |
| P1 | QUALITY-01 | CI and repeatability | GitHub Actions lint + portable unit tests, pinned test tooling, deterministic synthetic fixtures; Windows workflow for GUI/worker packaging; capture skipped tests as skips. |
| P1 | UI-01 | End-to-end usability | Clear case/evidence status, permissions, archive restore, progress/cancel/retry, errors and privacy notices; no silent worker failure. |
| P1 | DIST-01 | Offline packaging | Verify clean-machine Windows installation, bundled model/package manifests, LFS artifacts, offline workflow and clean uninstall; no hard-coded user paths. |
| P2 | PERF-01 | Scaling | Bound memory for large text/document extraction; use batched persistence and progress; benchmark synthetic large disk images without blocking UI. |
| P2 | MAINT-01 | Maintainability | Split oversized modules incrementally behind tests; document module interfaces, error classes, background-worker lifecycle and data migration policy. |
| P2 | DOC-01 | Submission | Update README, setup guide, architecture diagram, threat model, test evidence, demo script, result screenshots and project limitations. |

## 4. Staged implementation

### Stage A — Establish a safe, reviewable baseline

1. Work on feature branches off `improvement/forensic-hardening-roadmap` where useful; do not commit to `Desktop-Application`.
2. Record exact base revision; preserve existing tests; add a short verification command matrix for Windows and portable Python.
3. Implement independent, low-risk fixes with regression tests first. Avoid destructive DB migrations without a verified copy/restore path.
4. Make every change reviewable in a focused commit. **Do not claim a GitHub push, test pass or implementation is complete without evidence.**

### Stage B — Forensic evidence preservation (DATA-01, INTEG-01)

- Prefer reversible archiving over deleting cases. Use an explicit `archived_at` field, not a `closed` status alias.
- Audit archive and restore within the same DB transaction; enforce active-admin authorization inside the service.
- Ensure evidence and custody rows are not orphaned or destroyed. `custody_events.evidence_id` is NOT nullable and currently uses `ON DELETE CASCADE`: simply removing ORM cascade is unsafe.
- Ensure migration of existing SQLite databases through Alembic **and** the application's startup reconciliation path.
- Define expected effects on case lists, recent activity, reports, examination, analysis, indexing, all exports and service writes.
- Hash source and destination independently; reject mismatches before marking evidence verified.

### Stage C — Worker boundary (SEC-01, SEC-02, CON-01)

- Inventory every app-to-worker call and endpoint, including health/status, extraction, examination, embedding, search and generation.
- Introduce an ephemeral shared credential to protect *all sensitive* worker routes; avoid embedding a static password in source code or config.
- Restrict arbitrary image paths to case-authorized/registered evidence, and avoid accepting arbitrary external cloud inference hosts from unauthenticated callers.
- Replace global image/FS objects with per-job state or a rigorously tested serialization lock.
- Test parallel launch, rapid cancel/resume, oversized inputs and worker restarts.

### Stage D — Authentication, privacy and AI reliability (AUTH-01, AI-01, AI-02)

- Upgrade legacy credentials opportunistically after a successful verified login without locking out existing installations.
- Remove known default passwords and require an explicit administrator provisioning/migration path.
- Guarantee AI analysis never silently treats a model answer as a fact. Display retrievable source references, extraction context, limitations and unsupported-answer messaging.
- Ensure local-first mode has no network egress and secrets never fall back to plaintext on encryption errors.

### Stage E — Product completion and distribution (QUALITY-01, UI-01, DIST-01)

- Build automated CI against portable test subsets and a Windows job for native dependencies.
- Exercise fresh and upgraded installations; test Python environment setup, worker start, local model availability and data-folder permissions.
- Freeze reproducible dependencies and verify LFS/large dataset availability in a clean clone.
- Review navigation and every supported artifact/report screen for consistency and clear missing-dependency messages.

## 5. Synthetic acceptance test

Using **synthetic evidence only**:

1. Install IDFA on a clean Windows VM or user profile.
2. Provision an admin securely; authenticate; create an investigator.
3. Create a case; register synthetic Aurora and Harbor evidence.
4. Independently hash source and stored evidence; verify integrity.
5. Examine FAT disk images; extract known files and metadata deterministically.
6. Perform keyword, regex and semantic searches; confirm case-scoped results.
7. Build timelines and entity relationships; inspect file/evidence provenance.
8. Ask an evidence-grounded question via local AI; inspect citations and refusal on unsupported claims.
9. Record a finding and custody activity; generate a PDF report containing matching evidence and source identifiers.
10. Archive as admin, verify that all rows and files persist and ordinary operation is blocked, then restore and reopen.
11. Restart the app and re-check case, hashes, reports and audit history.
12. Run with cloud access disabled and demonstrate no unintended outbound activity.

**Artifacts for submission:** executed test command logs, Windows installer result, synthetic expected-vs-actual table, screenshots, architecture/threat-model diagrams, identified limitations and demo script.

## 6. Testing expectations

- **Portable:** `python -m compileall -q app worker tests`, targeted `pytest` modules that do not need Windows GUI, explicit synthetic fixtures.
- **Windows:** complete `pytest` (including PySide6/pytsk3/libewf), installer smoke test, full synthetic-case workflow, safe cancellation and restart.
- **Migration:** test clean DB, historical DB upgrades, idempotent `init_db`, rollback on failure, index and FK integrity.
- **Security:** non-admin attempts, inactive users, arbitrary worker requests, invalid shared token, unauthorized paths, network binding, DPAPI failure.
- **Regressions:** report filtering, archive state, duplicate evidence handling, concurrent worker calls, repeated installation.

Do not label tests passed if they were only planned or reasoned about.

## 7. Collaboration / release rules

- OpenCode implements and runs local Windows checks; GitHub is the source of truth for code review.
- Each completed change set: test, commit, push, report full SHA and actual test output.
- ChatGPT independently inspects diffs and issues corrections before approval.
- PR targets `Desktop-Application` only after feature work is verified, reviewed and ready; never auto-merge.
- No destructive operations on real cases. Before migrating an existing data folder, back up the DB and evidence manifest.
- Document behavior changes and unresolved risks. Use a conservative release status until the Windows end-to-end test passes.

## 8. Current limitations / honest status

This plan is based on repository source review. A connected GitHub service can inspect and edit committed text files, but it cannot execute Windows-native PySide6, pytsk3/libewf and installer workflows on the user's machine. Missing LFS objects, bundled model availability, performance, true offline behavior and court admissibility cannot be inferred from source alone. Those require on-machine validation.

**Completion requires both merged, tested code and a successful clean-install synthetic demonstration.**
