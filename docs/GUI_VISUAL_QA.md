# IDFA Desktop GUI — Visual QA and acceptance checklist

**Implementation branch:** `improvement/gui-polish`  
**Based on:** `improvement/forensic-hardening-roadmap`  
**Review PR:** #4

## Product design principles

The UI is an **evidence-centric investigator workspace**. It should feel calm, readable and professional under long sessions. Important forensic state must be visible in text, not only conveyed by color. A screen must never imply a calculation, AI answer, evidence verification or export was completed until the corresponding operation actually succeeded.

This improvement pass intentionally uses the existing PySide6 widgets and palette tokens. It does not replace case/evidence services, change migrations, or add front-end web dependencies.

## What changed in this pass

- `Ctrl+Shift+P` opens **Quick Navigation** from either the global shell or an open case. The list is limited to accessible destinations; the normal navigation permission gate still applies.
- Keyboard: type to filter, Up/Down to select, Enter to open, Escape to dismiss. `Ctrl+K` continues to focus the existing case search in the global header.
- Case dashboard cards now filter by their exact metrics: **Active** includes open and active; **Needs Attention** means open and high/critical priority; **Total** clears filters. Cards can be activated using Enter/Space.
- A **Showing X of Y cases** indicator and **Clear filters** action make table state obvious; date columns sort by timestamps, not localized date strings.
- Case status/priority remains readable in text with supplemental color/tooltip.
- A designed empty state offers **Create Case** for new cases and **Clear filters** when search results are empty.
- The header accurately describes its search scope; it does not imply a global artifact search.

## Manual native Windows checks (must be performed, not assumed)

1. **Window sizes:** 1366×768, 1920×1080, and a narrow resizable window. Inspect case cards, filters, table, header, sidebar, report preview and dialog buttons. No controls should be cut off or permanently covered by the taskbar.
2. **Display scaling:** 100%, 125%, 150%, 200%. Check for truncated labels, overlap, clipping or unusable dropdowns, particularly on high-DPI displays.
3. **Appearance:** Switch light/dark modes in Settings; verify legible contrast for text, selected rows, case priorities, focus outlines, cards, modal dialogs and tooltips.
4. **Keyboard-only:** Tab through controls; open Quick Navigation with Ctrl+Shift+P; filter; select using arrows; open with Enter; dismiss with Esc. Use Ctrl+K to search cases. Activate KPI cards with Tab then Enter/Space.
5. **Role-specific:** Sign in as admin, investigator and read-only user. The quick switcher must not list User Management for non-admins; archived case management must remain admin-only; read-only users cannot create cases through empty-state actions.
6. **Real states:** An empty database, 1 case, many cases, a filtered zero-result state, archived cases, an active examination, missing worker, cloud AI disabled and no configured model.
7. **Case dashboard filters:** Check Active, On Hold, Closed and Needs Attention cards against actual case status/priority; use Clear filters; search by ID, title and investigator; sort timestamps ascending and descending.
8. **Navigation continuity:** From an opened case, navigate to Findings and Reports using the quick switcher, return to All cases, then open another case. Confirm no cross-case data leakage or stale headings.
9. **Forensic task path:** Register synthetic evidence, check hash/integrity, examine, search extracted artifacts, review AI source citations, create a finding, produce a report and verify audit/custody entries remain present.
10. **Dialog safety:** Archive/restore, edit-case confirmation, create-case validation, cancellation and permission-denied dialogs. Ensure prompts clearly distinguish irreversible operations from reversible actions.
11. **Accessibility:** Read every status without relying on color; check keyboard focus is visible; verify accessible names for the case search, filtered list, result count and quick-navigation dialog.
12. **No performance regressions:** Check responsiveness with a synthetic case list of hundreds of cases and a long investigation title. Do not scan real drives for the UI test.

## GUI automation

The GitHub Actions workflow `.github/workflows/portable-quality.yml` includes a Windows offscreen Qt job:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q tests/test_gui_quick_switcher.py tests/test_gui_case_dashboard.py tests/test_case_management_actions.py
```

The tests verify interaction and permissions contracts. They do **not** prove the full native Windows presentation, installer, DPI scaling, worker lifecycle or real disk-image extraction. A human visual pass is still required.

## OpenCode debugging / handoff protocol

Work from `improvement/gui-polish` (or a focused follow-up branch targeting it), preserve `Desktop-Application`, use synthetic cases only, and report:

- Windows version, display resolution, scale factor and current theme.
- Exact action sequence and screen involved.
- Screenshot showing clipped/misaligned content **with synthetic data only**.
- Actual exception logs, failing test output and before/after screenshots when fixing defects.
- Focused commit SHA and whether changes were pushed to the GUI PR.

Avoid unnecessary global QSS changes that reduce contrast or break forensic tables. Do not change forensic extraction logic as part of cosmetic UI work.

**Release gate:** Do not call the GUI "finished" until Windows offscreen CI passes and the user signs off on visual, functional and accessibility checks above.
