# Controlled native Windows rehearsal: fictional Harbor case

Use a separate, stable Windows machine and a disposable IDFA data directory with
no real cases or evidence. This is a manual checklist, not a record that the
rehearsal passed. All names and events are fictional; see `README.md` for the
four exact source texts and image hash.

## Before the session

- [ ] Record the app build, Windows version, display resolution, scaling, and
  operator/date. Agree on a stop point and an offline fallback presenter.
- [ ] Isolate the machine from the internet and cloud; independently block
  outbound access for IDFA and any local services. Inspect provider and worker
  routing; loopback URLs alone do not prove containment. Do not use cloud APIs.
- [ ] Use only `harbor_fiction.img` and a disposable case/store. Verify the
  image SHA-256 against `README.md`; retain the original unchanged. Confirm
  sufficient disk space and prepare a writable disposable export folder.
- [ ] Before opening the disposable case or starting any job, verify there are
  no pending/queued or running examination or analysis jobs and no indexing in
  progress in the disposable session. Use a fresh disposable store if this
  cannot be established; do not modify real data or real configuration.
- [ ] In a **disposable configuration only**, set `analysis.llm_enabled: false`
  and verify that it is the effective configuration before any job can be
  queued or run. It defaults to `true` (including in `config.example.yaml`);
  Balanced inherits that setting, so choosing Balanced alone does **not** disable
  model calls. Analysis jobs capture parameters when enqueued: changing the
  setting afterward does not rewrite existing jobs. Pausing the runner does not
  stop an in-flight job and is not a substitute for checking the queue.
- [ ] Disable live AI generation and ensure embeddings/semantic indexing will
  not run; do not invoke indexing or semantic search during this workflow. Verify
  the no-model setting, empty queues and absence of indexing before starting,
  and verify the safeguards remain in effect. Completed examinations can be
  automatically queued for analysis. If any condition cannot be verified, stop
  and use the static fallback rather than risk an unapproved model request.
  Examination and deterministic analysis may run only in the isolated
  disposable environment.
- [ ] Default: no live AI. Only consider it with explicit user approval and
  independently verified outbound containment, local routing and synthetic-only
  context; otherwise skip it. Do not download anything. See `BENCHMARK.md` for
  additional limitations, not as permission to run it.
- [ ] Before the demo, close IDFA cleanly and make a restorable backup of the
  disposable data directory and configuration, including the database and case
  store. Verify the backup is readable and keep it separate. Never overwrite a
  real installation or its data when restoring.
- [ ] Prepare clearly labelled static screenshots or source-text fallback from
  this fixture. Decide who will stop the demo on a hang or unexpected prompt.

## Native display and pickers

- [ ] At **100%, 125%, and 150%** Windows display scaling, separately apply the
  scale, sign out/restart the app if Windows requires it, and record resolution
  and results. Check login, navigation, case pages, tables, dialogs and buttons
  for clipping, overlap, scrolling and keyboard accessibility. Do not assume a
  pass at one scale covers another.
- [ ] In each scale, use the actual Windows file picker to select the synthetic
  image during intake and the native save/location picker for a disposable
  report or export. Check visible path, long-path readability, cancel without
  changes, and successful selection; do not select or overwrite real files.

## Source-to-graph workflow

- [ ] Create a clearly labelled disposable fictional Harbor case. Register the
  image as disk-image evidence and record its displayed path and hash. Examine
  with file traversal and the Balanced preset only after the no-model and
  no-indexing checks above; wait for completion and check errors/coverage before
  drawing conclusions.
- [ ] In keyword search, search the exact quoted
  `"lantern-bridge-73@example.test"`. Inspect `NOTE.TXT` and `REPLY.TXT` in
  their artifact details, including evidence association, path and source text.
  Compare both with `README.md`; record missing or extra results, not just hits.
- [ ] Inspect `STATUS.TXT` and `GARDEN.TXT` separately. The former says
  collection was cancelled and the package remained in storage; the latter is
  unrelated on the supplied text. Ready for collection is not proof of collection.
- [ ] After deterministic background analysis finishes, inspect the shared
  address entity and any relationship/graph edge, then follow each available
  source link back to the evidence and the two artifact texts. Check labels,
  counts, provenance and any missing/ambiguous link. Graph creation and layout
  are not guaranteed: record absence or mismatch rather than inventing an edge.
- [ ] If creating a finding, mark it as an unverified lead, attach the actual
  sources available in the UI, and include the later status and alternative
  explanations. Review it and any disposable report for accurate source paths
  and limitations; open the exported file and check it. Do not imply mailbox
  ownership, real email delivery, verified times, identity or culpability.

## Status, failures and fallback

- [ ] Label every service/status display as **live** or **mocked/static**.
  A mock, screenshot or disabled check demonstrates presentation only, not
  service health; a live indicator is an observation at that moment, not proof
  of isolation, successful indexing or model correctness. Record unavailable or
  stale indicators without presenting them as healthy.
- [ ] If the GUI crashes, hangs, shows unexpected network/model activity, or
  risks real data, stop the rehearsal. Note the action, scale and visible error;
  do not repeatedly retry or claim success. Close/stop only the disposable
  session's processes safely, then preserve relevant logs and the affected
  disposable data separately before any recovery.
- [ ] If recovery is needed, restore the verified backup only to a fresh
  disposable location after processes have stopped; confirm the intended config
  and case before reopening. If recovery is uncertain, do not restore over the
  affected data. Switch to the labelled static source-text/screenshots fallback
  and explicitly say the native workflow was not completed.
- [ ] Record pass/fail/blocked per scale and workflow step, observed deviations,
  live versus mocked status, whether AI was skipped or explicitly approved, and
  fallback use. Native results apply only to the tested machine and build; this
  image does not establish deleted recovery, partitions, E01 or physical-device
  provenance. Printed timestamps are unverified and have no timezone.
