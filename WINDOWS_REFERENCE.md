# IDFA - Window/Page Reference Guide

## Quick Reference: All Windows & Pages

### Top-Level Shells
| Short Name | Class | File | Description |
|------------|-------|------|-------------|
| **MainWindow** | `MainWindow` | `app/ui/main_window.py` | Root `QMainWindow` - holds everything |
| **GlobalShell** | `GlobalShell` | `app/ui/main_window.py` | Pre-case shell (login → case list) |
| **CaseShell** | `CaseShell` | `app/ui/main_window.py` | In-case shell (9 tabs + header) |

---

### Global Shell Pages (before opening a case)
| Short Name | Class | File | Stack Index |
|------------|-------|------|-------------|
| **CaseList** | `CaseManagementPage` | `app/ui/pages/case_management_page.py` | 0 |
| **GlobalAudit** | `GlobalAuditPage` | `app/ui/pages/global_audit_page.py` | 1 |
| **Tools** | `ToolsPage` | `app/ui/pages/tools_page.py` | 2 |
| **Users** | `UserManagementPage` | `app/ui/pages/user_management_page.py` | 3 (admin only) |
| **Settings** | `SettingsPage` | `app/ui/pages/settings_page.py` | 4 |

> The stack always holds all five pages. `GlobalShell.set_user()` rebuilds the
> sidebar from `_GLOBAL_PAGES` so the **Users** entry only exists for
> `UserRole.ADMIN`, and `show_page_by_key()` refuses to switch a non-admin to it.

### Case Shell Pages (after opening a case)
| Short Name | Class | File | Tab Index |
|------------|-------|------|-----------|
| **Overview** | `OverviewPage` | `app/ui/pages/overview_page.py` | 0 |
| **Evidence** | `EvidencePage` | `app/ui/pages/evidence_page.py` | 1 |
| **Examination** | `ExaminationPage` | `app/ui/pages/examination_page.py` | 2 |
| **Artifacts & Search** | `ArtifactsSearchPage` | `app/ui/pages/artifacts_search_page.py` | 3 |
| **AI Analysis** | `AIAnalysisPage` | `app/ui/pages/ai_analysis_page.py` | 4 |
| **Entities & Timeline** | `EntitiesTimelinePage` | `app/ui/pages/entities_timeline_page.py` | 5 |
| **Findings** | `FindingsPage` | `app/ui/pages/findings_page.py` | 6 |
| **Reports** | `ReportsPage` | `app/ui/pages/reports_page.py` | 7 |
| **Audit & Custody** | `AuditPage` | `app/ui/pages/audit_page.py` | 8 |

> Case pages are registered by key in `_CASE_PAGES` (`(key, title)`), so the
> sidebar labels, the stack contents and `CaseShell.show_page_by_key()` cannot
> drift apart. `OverviewPage.next_action_requested` is connected to that method,
> which is how the six **Next Actions** buttons open the page they name, and
> `OverviewPage.edit_case_requested` drives `CaseShell._edit_current_case()`.

---

### Dialogs / Modals
| Short Name | Class | File | Trigger |
|------------|-------|------|---------|
| **Login** | `LoginDialog` | `app/ui/login_dialog.py` | App start |
| **NewCase** | `NewCaseDialog` | `case_management_page.py` | "+ New Case" button |
| **EditCase** | `EditCaseDialog` | `case_management_page.py` | Right-click → Edit |
| **NewUser** | `UserDialog` | `user_management_page.py` | Users → "+ New User" |
| **EditUser** | `UserDialog` | `user_management_page.py` | Users → double-click / Edit / right-click → Edit User |
| **ResetPassword** | `PasswordResetDialog` | `user_management_page.py` | Users → Reset Password / right-click → Reset Password |
| **CaseDetails** | inline in `_view_case_details` | `case_management_page.py` | Right-click → View Details |
| **DB Mgmt** | `DatabaseManagementDialog` | `tools_page.py` | Tools → Database |
| **Cache Mgmt** | `CacheManagementDialog` | `tools_page.py` | Tools → Cache |
| **Log Viewer** | `LogViewerDialog` | `tools_page.py` | Tools → Logs |
| **System Info** | `SystemInfoDialog` | `tools_page.py` | Tools → System Info |
| **DB Mgmt (case)** | inline in `_open_db_management` | `tools_page.py` | Tools → Database |
| **Generate Report** | `ReportGenerateDialog` | `reports_page.py` | Reports → "Generate Report" |
| **Report Templates** | `ReportTemplatesDialog` | `reports_page.py` | Reports → "Report Templates" |
| **Record Custody Event** | `RecordCustodyDialog` | `audit_page.py` | Audit & Custody → Chain of Custody → "Record Custody Event" |
| **Register Evidence** | `RegisterEvidenceDialog` | `evidence_page.py` | Evidence → Register Evidence |
| **Remove / Delete Evidence** | `RemoveEvidenceDialog`, `DeleteEvidenceDialog` | `evidence_page.py` | Evidence → Remove or Delete |
| **Reference Hash** | `ReferenceHashDialog` | `evidence_page.py` | Evidence → Reference Hash |
| **New Examination Job** | `NewExamJobDialog` | `examination_page.py` | Examination → New Job (Advanced expands every parameter) |
| **Document Viewer** | `ArtifactDocumentDialog` | `artifacts_search_page.py` | Artifacts & Search → Open viewer |
| **New Finding / Identity Hypothesis** | `NewFindingDialog`, `IdentityHypothesisDialog` | `findings_page.py` | Findings → New Finding / Identity review |
| **Physical Devices** | `DeviceDialog` | `app/ui/device_dialog.py` | Evidence → Physical devices |
| **First Run / Missing or Change Data Folder** | `FirstRunDialog`, `MissingDataFolderDialog`, `ChangeDataFolderDialog` | `app/ui/dialogs/data_folder_dialog.py` | Startup / Settings → Data & Storage |

---

### Header Bar (GlobalShell & CaseShell)
| Component | Class | File | Description |
|-----------|-------|------|-------------|
| **AppHeaderBar** | `AppHeaderBar` | `app/ui/header_bar.py` | Top header with search, bell, user menu |
| **CaseHeaderBar** | `CaseHeaderBar` | `app/ui/main_window.py` | Case-scoped header with back button |

---

### Worker Endpoints (native Windows :8000)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Service health |
| `/examine` | POST | Forensic operations |
| `/generate` | POST | AI analysis |
| `/search` | POST | Semantic search |
| `/embed` | POST | Vector indexing |

---

### Key Files Reference
| File | Purpose |
|------|---------|
| `app/__main__.py` | Entry point; login flow, relogin handler |
| `app/ui/main_window.py` | Navigation controller + shells |
| `app/ui/header_bar.py` | **AppHeaderBar** – search, bell, user menu |
| `app/ui/base.py` | Shared UI components (StatCard, NavList, etc.) |
| `app/processing/service.py` | Explicit-approval, in-memory processing coordinator (not durable) |
| `app/ai/case_briefing.py` | Deterministic, source-grounded briefing data helper |
| `app/ui/theme/professional.qss` | Stylesheet |
| `worker/main.py` | Native Windows FastAPI worker |
| `config.example.yaml` | Configuration template; the active file is `%APPDATA%\IDFA\config.yaml` |

---

### Quick Commands
```powershell
# First-time prerequisites
SETUP_IDFA.bat

# Start services and launch the GUI (default)
START_IDFA.bat

# Start services only / check services
START_IDFA.bat -NoGui
START_IDFA.bat -Status

# Stop services
STOP_IDFA.bat
```

---

### Recent Changes (2026-10-26)
- **Header Bar**: New `AppHeaderBar` with search (420×36), notification bell (popup with "Clear all"), user menu (signed-in name/role, Settings, About, Log out).
- **Login Dialog**: Custom title bar, "Show"/"Hide" password via QAction in trailing position, footer version shortened to "v0.1.0 • KSIT Bengaluru". The "Forgot password?" link was removed (there is no self-service recovery; admins reset accounts), and the dialog now sizes its height to the laid-out content instead of a hardcoded 535px, which previously let the footer collide with the sign-in button.
- **Settings Page**: Loads all settings on init, saves all categories (General, Worker, AI, Database, Security), resets to defaults in YAML.
- **Settings Layout**: Cards centred in a 912px column (fills the page at the 1200px window minimum, capped on wide screens); fields use caption-above-field cells in a two-column grid; `Save Settings` / `Reset to Defaults` moved into a pinned footer bar so they no longer sit below the scroll fold.
- **Login Flow**: Refactored into `show_login()` returning `User|None`; registered via `window.set_relogin_handler(show_login)`.
- **NavList Model**: Now an attribute (`nav_list.model`), not a method.
- **Case Management**: Added `set_search_text(text)` for header search integration.
- **StatCard**: Value font enlarged to DISPLAY_LG (32px).
- **Labels**: Added `QLabel[fieldLabel="true"]` rule for field labels (11px, muted, 4px bottom margin).
- **GlobalShell Navigation**: Fixed `_on_nav_clicked` validity check + sidebar sync.
- **Tools Page**: Header reduced to title + "Run Full Diagnostics" (category actions live in their tabs); all five tabs use the same 16px content inset so tables, toolbars, and button rows align; Cache/System Info/Logs populate on open; bottom status bar reports diagnostics progress.
- **Tools Dialogs**: `DatabaseManagementDialog`, `CacheManagementDialog`, `LogViewerDialog`, and `SystemInfoDialog` now use token-based spacing/typography, aligned `fieldLabel` captions, secondary button styling, and read-only text areas with `ClickFocus` so they no longer open with a bright focus ring.
- **Global Audit**: Date filters replaced the minimum-date sentinel (which rendered `2001-01-01`/`To` and opened the calendar on January 2000) with a `Date` preset combo — Any time / Today / Last 7·30·90 days / This year / Custom range. Custom range reveals two pickers defaulting to the last 30 days. Added a `Reset` action that clears every filter in one call; table columns size to content (action column elides) and the redundant Details column hides on narrow windows, leaving the detail pane as the single source for the full JSON. `QCalendarWidget` popup is now themed in `professional.qss`.
- **User Management (admin only)**: New `UserManagementPage` with search + role/status filters, a `Username / Full Name / Email / Role / Status / Last Login` table (no sorting, so row index always maps to the same account), and a pinned action bar (`Edit`, `Reset Password`, `Deactivate`/`Activate`, disabled until a row is selected). Double-click or the context menu opens `UserDialog` (create/edit; usernames are immutable after creation) and `PasswordResetDialog`; validation errors appear inline and the dialog grows to fit them. Guards block deactivating your own account, removing your own admin role, and demoting/deactivating the last active admin. Every create/update/reset/activate/deactivate writes an `event_type="user"` audit event.
- **Global Navigation Keys**: `_PAGE_TITLES` (list) became `_GLOBAL_PAGES` — `(key, title, admin_only)` — and pages are registered by key (`show_page_by_key`, `_pages_by_key`). `GlobalShell.set_user()` rebuilds the sidebar per role, so administrators see five entries (Case Management, Global Audit, Tools, User Management, Settings) and everyone else sees four; the stack itself always holds all five pages and sign-in/sign-out both land on Case Management.
- **Case Shell Navigation Keys**: `_CASE_PAGES` — `(key, title)` — now drives the sidebar labels, the page stack and the new `CaseShell.show_page_by_key()`, replacing the two hand-maintained parallel lists in `_setup_ui` and `set_case_context`. The six **Next Actions** buttons on Overview ("Register Evidence", "Start Examination", "Search Artifacts", "AI Analysis", "Create Finding", "Generate Report") previously called an empty `_on_action` stub; they now emit `OverviewPage.next_action_requested(key)` and the case shell opens that page while moving the sidebar selection to match. The **Edit Case** button is wired too: `OverviewPage.edit_case_requested` runs `CaseShell._edit_current_case()`, which reopens `EditCaseDialog` for the loaded case (same fields/validation as Case Management), saves through `CaseService.update_case`, and refreshes the case header, sidebar context and Overview title/meta without leaving the case shell.
- **Evidence Integrity**: Registration wrote through the page's `EvidenceService` but committed a *different* session
  (and the service had been handed a session already closed by `app/__main__.py`), so nothing was ever persisted —
  evidence disappeared on restart and **Verify Integrity** failed with "Evidence N not found". `_on_register` and
  `_on_verify` now use and commit the service's own session (rolling back on error), `app/__main__.py` keeps the
  case-shell service sessions open instead of closing them in a `with` block, and registration records the hashes it
  computes as *reference* hashes (previously it stored none, so verification would then fail with "No reference hashes
  found"). `EvidencePage.refresh()` also re-selects the row it had selected, so the detail pane and a second
  verification keep working after a refresh.
- **Evidence → Start Examination**: The Evidence page button no longer shows a "navigate to the Examination tab"
  dialog. It emits `EvidencePage.examine_requested(evidence_pk)`; `CaseShell._start_examination_for()` switches to the
  Examination page and calls `ExaminationPage.start_examination_for()`, which refreshes and selects that evidence in the
  page's `Evidence:` selector (the choice now survives refreshes, and `New Job` opens prefilled with it). With no row
  selected the button still warns and stays put.
- **Examination Page**: The `Evidence:` selector was filled only once, when the case was first opened, so evidence
  registered afterwards never appeared and `New Job` silently did nothing; pages with an `on_page_shown()` hook are
  now refreshed by `CaseShell.show_page_by_key()`, and the selector (plus the `Operation:` selector, which was never
  populated at all) reloads with the page. `New Job` writes through the service's own session and commits it, validates
  the parameters JSON instead of raising, warns when the case has no evidence, and selects the job it just created.
  `Start Examination` had no connection from `start_finished` to `_finish_start`, so it stayed on "Starting…" forever:
  the handler is connected, the run happens on a thread with its own session (sessions are not thread-safe), the
  service commits the resulting status/results/artifacts/evidence status, and the outcome — including worker errors —
  is reported in the log with the job re-selected. `Cancel` and `Refresh` persist and keep the selection, and buttons
  now enable only for the states they apply to. The service also honours the worker's `success: false` reply and stores
  `EvidenceStatus.EXAMINED` instead of the raw string `"examined"`; `create_job` coerces the operation to the enum
  because Qt returns `str`-based enum values from combo boxes as plain strings (which broke the jobs table).
- **Evidence Page Reload**: `EvidencePage` gained an `on_page_shown()` hook so the list reloads when the page is opened
  (previously it only refreshed in response to its own actions).
- **Single-File Evidence**: The worker now examines evidence that is not a disk image as a single artifact (name, size,
  MIME type, timestamps, SHA-256, text content for small text files) instead of reporting "No partition table" and zero
  findings, so a document registered as evidence produces a real result and an artifact row. The New Job dialog says so.
- **Worker Unreachable**: A `ConnectError`/timeout from the worker is reported as "Cannot reach the forensic worker at
  http://127.0.0.1:8000" with the command to start it, instead of the raw "All connection attempts failed"; failed jobs
  now mark the evidence `EXAMINATION_FAILED`, and retrying a failed job clears the previous error message.
- **Tools Diagnostics**: `DiagnosticWorker` called `QApplication.instance().version()`, which does not exist, so the
  PySide6 row always failed; it now reports `PySide6.__version__` plus `qVersion()`. The pytsk3 row used to import
  pytsk3 into the GUI virtual environment, where it is not needed, so it always failed; it now reads the worker's
  `/health` `pytsk3` flag and reports whether disk examination is available in the worker.
- **Case-Shell Services**: Examination could open with empty Evidence/Operation selectors and an empty jobs table because
  its services were injected by monkey-patching `overview_page.set_case_context` in `app/__main__.py` (and the Evidence
  service fallback was built inside a `with session_scope()` block, whose session is closed on exit). `CaseShell` now owns
  one long-lived `EvidenceService` and `ExaminationService` (`_ensure_case_services`) and injects them *before* pages load;
  the monkey-patch is gone. `ExaminationPage` also self-heals: `_ensure_services()` creates the services when nothing was
  injected, so the page works on its own.
- **Examination Selectors**: The Evidence selector never showed evidence without a service and stayed at "Select evidence..."
  forever, the Operation selector could be empty before a service existed, and choosing evidence did nothing. Empty states
  now read "No evidence registered" / "No evidence available", a hint line explains the flow (or sends the investigator to
  the Evidence page), choosing evidence selects its newest job, and clicking a row in **Supported Operations** sets the
  Operation selector. The fallback operation list no longer offers `metadata_extraction`, which the worker does not
  implement. `NewExamJobDialog.get_data()` stores a real `ExaminationOperation` (Qt hands str-enums back as plain strings)
  and `New Job` defaults to the first registered evidence when none is chosen.
- **AI Analysis — Status Strip**: The strip used to show hardcoded 🔴/⚪ icons forever. It now reports live state for
  **Worker** (`/health`), **Ollama** (`/api/tags`), **Model** (the configured chatter model is pulled), **Embedding**
  (an embeddings probe), **Qdrant** (`/collections`) and **Index** (this case's embedded artifacts vs. Qdrant points),
  with a Refresh button and a one-line explanation underneath. Checks run on a background thread, so a missing Qdrant or
  embedding model marks that item red/yellow ("keyword retrieval is used") instead of blocking the page.
- **AI Analysis — Assistant**: `Send` was a `QTimer` placeholder. It now retrieves this case's artifacts through the
  existing `SearchService` (FTS5 keyword + Qdrant semantic + RRF) with a newest-artifacts fallback, shows the retrieved
  artifacts with scores/snippets in the right-hand panel, POSTs them to the worker's `/generate` (mode `analysis`) on a
  background thread with its own session, and renders the answer with its citations. Worker outages, empty answers, timeouts
  and missing evidence produce actionable messages instead of a fake response, and Send is disabled while a request runs.
  Both request threads are tracked so closing/switching a case cannot free a running `QThread`.
- **AI Analysis — Save as Draft Finding**: The button was a "to be implemented" dialog. It now creates a real
  `Finding` (`origin=ai_suggested`, `status=draft`) with the question, answer, citation JSON, model name, a
  verification-required conclusion, and `FindingArtifactLink` rows for the cited artifacts, then refreshes the Findings
  page. A second save of the same answer is blocked until a new answer arrives.
- **Evidence Copy Safety**: `_copy_to_case_store` opened the destination with `"wb"` before reading the source, so
  registering a file that was already at its destination path truncated it (a 4.5 MB docx became 0 bytes). It now treats a
  same-path copy as a no-op and writes to a `.part` file before `os.replace`, so an interrupted copy never leaves a
  truncated evidence file.
- **Worker Office Text**: The worker's `extract_text_content` returned `[Office Document - N bytes]` for `.docx/.xlsx/.pptx`,
  which gave AI analysis nothing to reason about. `_extract_ooxml_text` now pulls real text out of the OOXML ZIP with the
  standard library (`word/document.xml` paragraphs, header/footer parts, spreadsheet shared strings, slide XML), falling
  back to the old placeholder only when extraction fails.
- **Keyword Search Index**: `artifacts_fts` exists (the migration creates the virtual table) but nothing ever inserted into
  it, and no triggers maintained it, so FTS5 keyword search returned zero hits for every examined artifact — keyword mode
  on Artifacts & Search and the assistant's keyword retrieval included. `init_db()` now calls `ensure_fts_index()`, which
  creates the external-content table if missing, installs `AFTER INSERT/DELETE/UPDATE` triggers on `artifacts`, and runs
  an FTS `rebuild` the first time (backfilling older artifacts). The table/trigger definitions live in
  `app/db/session.py`; startup tolerates a SQLite build without FTS5 by logging a warning instead of failing.
- **Reports — Court-Admissible Default Template**: `Reports` previously generated a thin PDF with a single "sections"
  list and no way to change it. `app/reports/templates.py` now defines a built-in default template
  (`court-admissible-v1`, code-defined, always present, cannot be deleted) holding the wording courts expect:
  authority/scope/purpose with the standards relied on (ISO/IEC 27037, 27041, NIST SP 800-86, SWGDE), an examiner
  declaration, methodology and examination-environment table, evidence inventory with hashes, verified findings kept
  apart from unverified/AI work product, limitations, a signed certification page, Appendix A (SHA-256 evidence
  integrity) and Appendix B (chain-of-custody audit log). Jurisdiction and laboratory name come from
  `report.jurisdiction` / `report.organization` in `%APPDATA%\IDFA\config.yaml`; the old "tool does not guarantee legal admissibility"
  disclaimer was replaced with scope-limiting wording.
- **Reports — Investigator Template Upload**: `Report Templates` (new button on the Reports header) lists the built-in
  default and every uploaded template, shows which court sections a template omits, and offers Upload / Save As… /
  Delete. Upload accepts `.json` (full template: sections and order, authority, methodology, declaration,
  certification, limitations, signature lines, custom sections), plus `.docx`, `.html`, `.txt` and `.md`, which are
  imported as an *Examiner Narrative* section inside the default court skeleton (OOXML/stdlib text extraction — no
  extra dependency). `{{placeholders}}` are validated at import against a fixed allow-list (`case_id`, `case_title`,
  `examiner`, `organization`, `jurisdiction`, `report_id`, counts, dates …), so a bad template is rejected with the
  offending name instead of failing at generation. Uploads are copied to `<data_dir>/report_templates/` and survive
  restarts; the built-in id is reserved, and exporting the default writes an editable `custom-court-admissible` copy.
- **Reports — Generation**: `Generate Report` chooses the template, title and which of that template's sections to
  include (the cover is locked; integrity/certification carry tooltips explaining why they matter), then renders on a
  background `QThread` with its own session and examiner identity (a closed/shared session used to make generation fail
  or hang). PDFs get a "Page X of Y" footer with case/report/classification, wrapped table cells (long paths and
  hashes no longer overflow), `SHA-256` algorithm labels, and monotonic report IDs (`-2`, `-3` suffix) so two reports in
  the same second no longer collide on the unique constraint. The table gained a **Template** column, and
  `ReportService` is now a long-lived case-shell service (it was created inside a `with session_scope()` block, so the
  page lost its service as soon as wiring finished).
- **Audit & Custody**: The case page now has separate **Audit Trail** and **Chain of Custody** tabs. Both show case-scoped
  records with full detail panes; type/result filters apply to the audit trail, user/date filters apply to both, and the
  page reloads whenever it is opened. Added date presets/custom ranges, reset/refresh controls, result counts and JSON/CSV
  export of the currently filtered tab. Investigators can append custody handling/transfer records for case evidence;
  entries capture the signed-in operator, description, time, locations and tool/method, and are written with a matching
  audit event. Evidence registration, integrity verification and examination start/completion also write case-scoped
  audit entries; custody history includes evidence identity, operator, locations, tool and metadata. The audit service uses
  a case-shell session rather than one closed immediately after injection. This is the application's event history, not a
  cryptographically signed or tamper-evident legal record.
- **New Case Assignment**: The Assignee selector is shown only to administrators in the New Case dialog. Investigator
  accounts do not see or submit an assignee choice; administrators can still assign cases to active investigators.
- **Artifacts & Search — Date Filter**: Date presets default to **Any time** (no date constraint); selecting a preset or
  custom range constrains keyword searches in SQLite and filters semantic candidates by artifact creation date. The date
  range is passed into search rather than only trimming the already-returned result list.
- **AI Analysis — Case-Focused Chat and Services**: Greetings and brief small talk receive a fast, friendly reply tied to
  the active case without doing artifact retrieval; unrelated prompts are gently redirected to the case. Embeddings
  come from Ollama's `all-minilm` model (384 dimensions), the same vectors the retired
  `sentence-transformers/all-MiniLM-L6-v2` model produced, so existing Qdrant collections stay valid and no model
  directory ships with the application. Failed artifact indexing is retryable and uses stable Qdrant point IDs, and
  the status strip counts only text-bearing artifacts as eligible for semantic indexing. If the model is missing,
  press **Pull Embedding Model** (it runs `ollama pull all-minilm`), then index the case from Artifacts & Search.
- **AI Analysis — Context**: Max output and requested Ollama context window are separate settings. Defaults are 2,048
  output tokens and an 8,192-token context window. The context window is not free memory: phi3:mini needs roughly
  384 KiB of key/value cache per token, so asking for 131,072 tokens made Ollama allocate ~48 GiB and the model never
  loaded (`failed to allocate buffer for kv cache`). The worker clamps the request to 8,192 tokens (override with
  `IDFA_MAX_CONTEXT_TOKENS`), caps the reply at 2,048 tokens, and trims the evidence budget to the window that will
  actually load. If Ollama still reports out-of-memory, the worker retries once with half the window before reporting
  the reason in the chat. **Clear Context** clears the visible conversation, casual-chat history, citations and
  unsaved AI answer without deleting case records or saved findings.
