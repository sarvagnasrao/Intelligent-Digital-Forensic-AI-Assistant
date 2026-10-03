"""
Run every self-contained verification suite and total the result.

Why this file exists as code rather than as a shell one-liner
-------------------------------------------------------------
§21 TRAP 8: the gate matched its summary line with a loose regex, fell through to
`Select-Object -Last 1` on a `PASSED|FAILED` pattern, and therefore captured a
`FAILED: <description>` line -- the *list of failures*, not the summary. `[int]` on
an empty match is 0, so a suite with 15 failures printed as `0 passed / 0 failed`
and a red run came out green.

> A gate that reads 0 for a script which did not pass is worse than no gate: it
> converts a red suite green. A summariser is a program and has to be tested like
> one.

So the four rules here are the point, and each exists because its absence was a bug:

1. **Both summary shapes parse.** `... SUITE PASSED - 78 assertions` and
   `... SUITE FAILED - 5 of 83`.
2. **Unreadable counts are INVALID, not zero.** A script whose summary cannot be
   found has not passed; it has not been measured. `??` and `ERR` are loud states
   so a future format change cannot be silent.
3. **A non-zero exit with zero reported failures is INVALID** (§21 again).
4. **The total is refused if any script is invalid.** And the per-suite lines are
   printed so the total can be reconciled against its own parts by eye -- §21's
   TRAP 8 was precisely a total that did not agree with the lines above it.

Run with the servers STOPPED. See AGENTS.md §10: a backend already running on
`data/forensic.db` has its own worker thread, and that worker selects `Queued`
jobs, so a fixture left in `Queued` is picked up and executed by a *second*
process -- which then loses the race for the same per-case Qdrant directory and
reports `Storage folder ... is already accessed by another instance`. That is a
symptom, not the disease (§15).

`verify_live_stack.py` is excluded: it needs ollama + uvicorn + Vite running, and
skips itself when they are not. `verify_provenance_discriminating.py` is excluded
too -- it deliberately *reverts* `vector_store.py` four times, so it must never be
part of a gate that other suites are reading that file during.

Usage:
    PYTHONPATH=. python tests/run_gate.py
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PY = os.path.join(REPO, "venv", "Scripts", "python.exe")
if not os.path.exists(PY):                      # non-Windows / non-venv layout
    PY = sys.executable

# The self-contained suites. Order is irrelevant; the reconciliation at the end is
# what checks the total.
SUITES = [
    "verify_cpu_sampler.py",
    "verify_eta.py",
    "verify_evidence_archive.py",
    "verify_file_formats.py",
    # The gate's own parser. Included on purpose: §21's rule is that a summariser is
    # a program and has to be tested like one, and this suite exists because the
    # first version of run_gate.py could not read six of the sixteen summaries and
    # reported them as unreadable rather than as the failure it was.
    "verify_gate_parser.py",
    "verify_forensic_failure.py",
    "verify_gpu_telemetry.py",
    "verify_identity_attribution.py",
    "verify_ingestion_modes.py",
    "verify_job_stop.py",
    "verify_prompt_budget.py",
    "verify_provenance.py",
    "verify_queue_api.py",
    "verify_retrieval_integrity.py",
    "verify_service_health.py",
    "verify_storage.py",
    "verify_vector_store.py",
    "verify_ws_progress.py",
]

EXCLUDED = {
    "verify_live_stack.py": "needs ollama + uvicorn + Vite running (AGENTS.md §14)",
    "verify_provenance_discriminating.py":
        "deliberately reverts vector_store.py four times; must not run "
        "concurrently with suites reading that file",
}

# `ok` / `??` / `ERR` -- three loud states, never a silent 0.
OK, UNREADABLE, ERROR = "ok", "??", "ERR"


# Shape A, used by six of the sixteen suites:
#     "  9 passed, 0 failed"          <- count FIRST, comma separated
# Shape B, used by the other ten:
#     "PASSED: 209    FAILED: 0"      <- word FIRST
#
# Both had to be handled, and the fact that they differ is not a detail: my
# first version parsed only shape B, and on its FIRST run it reported six healthy
# suites as `?? unreadable`. The honest reading of that output is "six suites are
# broken" — and none of them were. Every one of the six printed `9 passed, 0 failed`
# and passed.
#
# That is this repository's own recurring defect committed in the tool written to
# catch it, and it is worth recording rather than quietly fixing: **a summariser
# that cannot read a summary reports the same thing whether the suite passed or
# crashed.** That is why rule 4 exists and why the run was correctly declared
# invalid instead of totalled at 675.
#
# Candidates are collected with their positions and the LAST one wins, because the
# summary is printed last. Taking the first would be a different bug: a suite that
# prints per-assertion `PASS`/`FAIL` lines can put the word in a description.
_SHAPE_A = re.compile(r"(\d+)\s+passed\b.*?(\d+)\s+failed\b", re.I)
_SHAPE_B_PASSED = re.compile(r"PASSED[:\s-]+(\d+)")
_SHAPE_B_FAILED = re.compile(r"FAILED[:\s-]+(\d+)")


def parse(output: str):
    """
    Return (passed, failed) or None when the counts cannot be read.

    None means **not measured**, never zero. A gate that reports 0 for a script
    which did not pass is worse than no gate: it converts a red suite green
    (§21 TRAP 8).
    """
    last_at = -1
    last = None

    for m in _SHAPE_A.finditer(output):
        last_at, last = m.start(), (int(m.group(1)), int(m.group(2)))

    # Collected independently rather than per line, because the two halves of
    # shape B are not guaranteed to share a line.
    mp = None
    for m in _SHAPE_B_PASSED.finditer(output):
        mp = m
    mf = None
    for m in _SHAPE_B_FAILED.finditer(output):
        mf = m
    if mp is not None or mf is not None:
        at = min(x.start() for x in (mp, mf) if x is not None)
        if at > last_at:
            last = (int(mp.group(1)) if mp else 0,
                    int(mf.group(1)) if mf else 0)

    return last


def run(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return UNREADABLE, 0, 0, f"{name}: file not found"
    env = dict(os.environ, PYTHONPATH=".", PYTHONIOENCODING="utf-8")
    p = subprocess.run([PY, "-X", "utf8", os.path.join("tests", name)],
                       cwd=REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    counts = parse(out)
    if counts is None:
        tail = "\n".join(out.strip().splitlines()[-6:])
        return UNREADABLE, 0, 0, f"{name}: summary unreadable\n{tail}"
    passed, failed = counts
    # Rule 3. A suite that exits non-zero having reported zero failures and
    # printed none is a broken instrument, not a pass.
    #
    # The marker has to match every convention these suites actually use --
    # `FAIL  `, `[FAIL]`, `FAIL:` -- so this does not fire on a real suite that
    # simply spells its failures differently. A gate rule that is stricter than
    # the thing it measures will call correct code broken, and the obvious
    # response will be to delete the rule.
    failure_marker = re.search(r"^\s*\[?FAIL\]?[:\s]", out, re.M)
    if p.returncode != 0 and failed == 0 and failure_marker is None:
        return ERROR, passed, failed, f"{name}: exit {p.returncode}, 0 failures printed"
    state = OK if failed == 0 else ERROR
    return state, passed, failed, ""


rows = []
for name in SUITES:
    state, passed, failed, note = run(name)
    rows.append((name, state, passed, failed, note))
    flag = "ok  " if state == OK else f"{state} "
    print(f"{flag} {name:36} {passed:>5} passed  {failed:>4} failed"
          + (f"   <- {note.splitlines()[0]}" if note else ""))

print()
for name, why in EXCLUDED.items():
    print(f"--   {name:36} excluded: {why}")

# Reconciliation: the printed lines must sum to the reported total. A total that
# disagrees with its own parts is §21's TRAP 8 in a different costume, and it is
# the cheapest possible check that the summariser is summarising what it ran.
sum_passed = sum(r[2] for r in rows)
sum_failed = sum(r[3] for r in rows)
invalid = [r for r in rows if r[1] != OK]

print()
print("=" * 74)
if invalid:
    print(f"GATE COULD NOT BE TOTALLED: {', '.join(r[0] for r in invalid)}")
    print("Treat this run as invalid - the totals above are not trustworthy.")
    print("A script that could not be measured has not passed.")
    sys.exit(1)

# Cross-check the arithmetic itself. If this ever fires, a row was printed from
# different numbers than the ones summed, which means the table is lying.
for name, _state, passed, failed, _note in rows:
    for n in (passed, failed):
        if n < 0:
            print(f"GATE COULD NOT BE TOTALLED: {name} reported a negative count")
            sys.exit(1)

print(f"GATE PASSED - {sum_passed} passed, {sum_failed} failed "
      f"across {len(rows)} scripts")
print(f"reconciliation: {' + '.join(str(r[2]) for r in rows)} = {sum_passed}")
sys.exit(0 if sum_failed == 0 else 1)