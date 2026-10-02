"""§28 TRAP 12: is the provenance guard's suite actually discriminating?

"Verified discriminating" is TWO measurements, and the first is about this
harness, not the suite:

  1. the revert APPLIED  - asserted on the ABSENCE of the change afterwards,
     never on the presence of it before. My first attempt in this repo checked
     `PATTERN in original`, which proved the guard existed and said nothing
     about whether I removed it; against a CRLF file the replace matched
     nothing, the file was rewritten unchanged, and the suite ran twice against
     identical code - producing "passes with the fix, passes without it", which
     is byte-identical to a decorative guard and reads as the alarming result.

  2. the suite went RED on assertions naming the behaviour, and not on some
     unrelated one.

Also follows §30's layering note: the guard has independent layers (the store
refusal, the search refusal, the never-indexed message, the unattributed
warning), and a *single*-block revert is expected to stay green where another
layer covers the same state. Only the pre-guard state - all of them gone - must
be red. Requiring every single-block revert to go red would call a correct
two-layer fix decorative, and the obvious "fix" would be to delete the
redundant layer.

Deleting by explicit text span with a match-count assertion. §30: an
indentation heuristic once deleted `extract_media` outright, producing a red
result for a reason unrelated to the behaviour under test.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

# Derived from this file's own location, not hardcoded. A harness that names an
# absolute path is a harness that silently measures a *different checkout* the
# moment anyone clones the repo elsewhere - and it would report the other tree's
# result as this one's.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(REPO, "backend", "modules", "vector_store.py")
SUITE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "verify_provenance.py")

# Each revert is (label, exact whole-block text to delete, replacement).
#
# WHOLE blocks, not prefixes. My first version deleted only the opening lines
# and the harness's own absence check caught it: "will not be searched" was
# still in the file, so the guard had survived and the suite would have run
# against nearly-unmodified code. That is precisely what TRAP 12's measurement
# (1) exists to catch, and it did - it refused to print a verdict rather than
# reporting a green suite.
REVERTS = {
    "search guard": (
        "    try:\n"
        "        from backend.modules import index_provenance\n"
        "\n"
        "        measured = describe_embedder()\n"
        "        verdict = index_provenance.check_index(qdrant_path, measured)\n"
        "\n"
        "        if verdict[\"state\"] == index_provenance.MISMATCH:\n"
        "            raise VectorStoreError(\n"
        "                f\"Case {case_id} will not be searched: {verdict['reason']}\"\n"
        "            )\n"
        "\n"
        "        if verdict[\"state\"] == index_provenance.NEVER_INDEXED:\n"
        "            # Previously this reached Qdrant and came back as a 404 for a\n"
        "            # missing collection, wrapped with a status code and an HTTP\n"
        "            # library name. Same class of outcome, actionable message.\n"
        "            raise VectorStoreError(\n"
        "                f\"Case {case_id} has no vector index, so it cannot be \"\n"
        "                \"searched. Ingest the evidence first.\"\n"
        "            )\n"
        "\n"
        "        if verdict[\"state\"] == index_provenance.UNATTRIBUTED:\n"
        "            # Served, deliberately. Every index written before provenance\n"
        "            # existed reads this way, and refusing would lock the operator out\n"
        "            # of all of them - on this install that is 77 cases. The state is\n"
        "            # counted on the health page so it is visible rather than implied,\n"
        "            # which is the difference between a known unknown and an\n"
        "            # unrecorded one (B22's rule).\n"
        "            _warn_unattributed_once(qdrant_path, case_id, verdict[\"reason\"])\n"
        "\n",
        "    try:\n",
    ),
    "store guard": (
        "        from backend.modules import index_provenance\n"
        "\n"
        "        # Measured before anything is written, so the record describes the\n"
        "        # vectors that are actually about to exist rather than the ones the\n"
        "        # build believes in.\n"
        "        measured = describe_embedder()\n"
        "\n"
        "        verdict = index_provenance.check_index(qdrant_path, measured)\n"
        "        if verdict[\"state\"] == index_provenance.MISMATCH:\n"
        "            # Writing here would be worse than refusing. Qdrant accepts a\n"
        "            # same-dimensional upsert from a different embedder without\n"
        "            # complaint, so the collection would end up holding a mixture of\n"
        "            # two vector spaces and no record that it had.\n"
        "            raise VectorStoreError(\n"
        "                f\"Refusing to index into case {case_id}: \"\n"
        "                f\"{verdict['reason']}\"\n"
        "            )\n"
        "\n",
        "",
    ),
    # The record_write call. It has to go WITH the store guard, not separately:
    # removing only the guard left `record_write` referencing the import the
    # guard had brought in, and the suite died with NameError. A revert that
    # leaves the file in a state nobody ever shipped is not the pre-fix state,
    # and the crash reported as a nonsense "no provenance recorded" instead of
    # the behaviour being tested.
    "record write": (
        "\n"
        "        # After the upsert, not before: a record written first and lost to a\n"
        "        # failed upsert would attribute vectors that do not exist. A failure\n"
        "        # here is non-fatal to the store -- the points are written and usable,\n"
        "        # and the case simply reads as unattributed until the next write.\n"
        "        try:\n"
        "            index_provenance.record_write(\n"
        "                qdrant_path, measured,\n"
        "                chunking=chunking,\n"
        "                evidence_id=evidence_id,\n"
        "                source_filename=source_filename,\n"
        "                chunks=len(points))\n"
        "        except Exception as pe:\n"
        "            print(f\"[VECTOR] could not record provenance for case {case_id}: \"\n"
        "                  f\"{type(pe).__name__}: {pe}\")\n",
        "",
    ),
}

# Markers that must be GONE after a revert. Asserting absence is the whole
# point of TRAP 12.
MARKERS = {
    "search guard": "will not be searched",
    "store guard": "Refusing to index into case",
    "record write": "index_provenance.record_write",
}

# Things the suite imports and the revert must NOT be able to remove. §30:
# a revert that deletes code the suite needs produces a red run for an unrelated
# reason, which is a red result that means nothing.
SURVIVORS = [
    "def store_chunks(",
    "def search_chunks(",
    "def delete_case_collection(",
    "def describe_embedder(",
    "def _load_embed_model(",
    "def get_collection_name(",
    "class VectorStoreError",
    "def _warn_unattributed_once(",
]


def read_norm():
    with open(TARGET, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def write_norm(text):
    # newline='' + explicit \n => LF on disk, byte-for-byte what we read after
    # normalisation, so a revert that removes nothing is detectable as "the file
    # did not change" rather than as a silent CRLF/LF churn.
    with open(TARGET, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def apply_revert(labels):
    src = read_norm()
    removed = []
    for label in labels:
        needle, repl = REVERTS[label]
        count = src.count(needle)
        if count != 1:
            raise SystemExit(
                f"ABORT: {label!r} matched {count} times, expected exactly 1. "
                "A revert that matches 0 times changes nothing and the suite "
                "would then run twice against identical code - TRAP 12."
            )
        src = src.replace(needle, repl, 1)
        removed.append(label)
    return src, removed


def verify_reverted(src, labels):
    """TRAP 12, measurement (1): prove the change is GONE, not merely absent."""
    for label in labels:
        marker = MARKERS[label]
        if marker in src:
            raise SystemExit(
                f"ABORT: revert {label!r} did not apply - {marker!r} is still "
                "present in the file."
            )
    for survivor in SURVIVORS:
        if survivor not in src:
            raise SystemExit(
                f"ABORT: revert removed {survivor!r}, which the suite imports. "
                "A red run from a broken import proves nothing (section 30)."
            )


def run_suite():
    env = dict(os.environ, PYTHONPATH=".", PYTHONIOENCODING="utf-8")
    p = subprocess.run([os.path.join(REPO, "venv", "Scripts", "python.exe"),
                        "-X", "utf8", SUITE],
                       cwd=REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    # Two summary shapes exist across this repo's suites and both must parse:
    #   "... SUITE PASSED - 78 assertions"
    #   "... SUITE FAILED - 5 of 83"
    # An earlier version of this harness matched `PASSED|FAILED - <n>` twice and
    # indexed the second match, which crashed on the PASSED shape - and a
    # harness that dies reading its own instrument measures nothing.
    mp = re.search(r"PASSED\s*-\s*(\d+)", out)
    mf = re.search(r"FAILED\s*-\s*(\d+)\s*(?:of\s*(\d+))?", out)
    if mp is None and mf is None:
        print(out[-4000:])
        raise SystemExit("ABORT: suite summary unreadable. An unreadable summary "
                         "is an INVALID run, never a failure count (TRAP 8).")
    passed = int(mp.group(1)) if mp else 0
    failed = int(mf.group(1)) if mf else 0
    fails = re.findall(r"\[FAIL\]\s*(.+)", out)
    # A suite that exits non-zero having reported zero failures is a broken
    # instrument, not a pass (§21 TRAP 8).
    if p.returncode != 0 and failed == 0 and not fails:
        print(out[-4000:])
        raise SystemExit(
            f"ABORT: suite exited {p.returncode} but reported 0 failures and "
            "printed none. Treating that as a pass is exactly TRAP 8.")
    # Whether the suite *ran to completion*. This is the structural stand-in for
    # "the failures are about the behaviour": a suite that died on an ImportError
    # or a NameError also prints a failure list, and reading that as evidence
    # would be §30's revert-deleted-the-code mistake.
    #
    # Keyed on CPython's own traceback header, and on nothing else. My first
    # version added `"Error:" in out and "FAIL" not in out` - which is keyed on
    # the ABSENCE of a FAIL line, and a fully green run has no FAIL lines at all,
    # so any incidental "Error:" string anywhere in 79 passing assertions
    # declared the suite crashed. That is this file's own recurring defect
    # (a detector reading the wrong variable) committed for the fourth time,
    # now in the tool whose entire job is to read the right variable.
    #
    # Deliberately NOT matching bare "Error:": the suite's own product messages
    # are of the form "RuntimeError: Not found: Collection case_stale", which is
    # exactly the behaviour being asserted and must never read as a crash.
    crashed = "Traceback (most recent call last)" in out
    return passed, failed, fails, crashed


def trial(labels):
    backup = read_norm()
    try:
        src, removed = apply_revert(labels)
        verify_reverted(src, labels)
        write_norm(src)
        return run_suite()
    finally:
        write_norm(backup)


print("=" * 74)
print("0. the pristine file must actually contain the guards")
print("=" * 74)
pristine = read_norm()
for label, (needle, _repl) in REVERTS.items():
    print(f"   {label:14} present: {pristine.count(needle) == 1}  "
          f"(count={pristine.count(needle)})")
    if pristine.count(needle) != 1:
        raise SystemExit("The revert needles no longer describe the code. "
                         "Fix the harness before trusting any verdict below.")

# A revert is a GROUP of blocks, because some of them are not independent. The
# store guard cannot be removed on its own: `record_write` is what the guard's
# import is for, so deleting the guard alone left a NameError and the suite
# died - a red run for a reason that has nothing to do with the behaviour under
# test. A revert must reconstruct a state somebody actually shipped.
REVERT_GROUPS = {
    "search guard only": ["search guard"],
    "store guard + record write": ["store guard", "record write"],
    "ALL (pre-guard state)": ["search guard", "store guard", "record write"],
}

print()
print("=" * 74)
print("1. WITH the guard")
print("=" * 74)
p1, f1, _, crashed1 = run_suite()
print(f"=== 1. with the guard ===      {p1} passed, {f1} failed")
if crashed1:
    raise SystemExit("The suite crashes on the UNMODIFIED file. Fix that first; "
                     "a revert check against a crashing suite measures nothing.")
if f1:
    raise SystemExit("The suite is red on the unmodified file. Fix that first; "
                     "a revert check against a red suite measures nothing.")

print()
print("=" * 74)
print("2. PARTIAL reverts")
print("=" * 74)
single_results = {}
for label, keys in REVERT_GROUPS.items():
    if label.startswith("ALL"):
        continue
    ps, fs, fails, crashed = trial(keys)
    single_results[label] = (ps, fs)
    print(f"=== revert {label:26} {ps} passed, {fs} failed"
          f"{'   [CRASHED - run is INVALID]' if crashed else ''}")
    for f in fails:
        print(f"      FAIL  {f}")

print()
print("=" * 74)
print("3. COMBINED revert - the pre-guard state. This one MUST be red.")
print("=" * 74)
pc, fc, fails_c, crashed_c = trial(REVERT_GROUPS["ALL (pre-guard state)"])
print(f"=== revert ALL (pre-guard)      {pc} passed, {fc} failed"
      f"{'   [CRASHED - run is INVALID]' if crashed_c else ''}")
for f in fails_c:
    print(f"      FAIL  {f}")

print()
print("=" * 74)
print("VERDICT")
print("=" * 74)

# The guard's own verdict must be robust too: the file was restored in the
# finally block of trial(), so confirm the markers are back.
restored = read_norm()
ok_restore = all(MARKERS[l] in restored for l in REVERTS)
print(f"file restored after the reverts: {ok_restore}")
if not ok_restore:
    raise SystemExit("The harness left the working tree reverted.")

problems = []
if fc == 0:
    problems.append(
        "the combined revert stayed GREEN, so the suite cannot fail when the "
        "guard is removed (TRAP 12's exact signature)")

# The red must be a clean report of failures, not a suite that died. This is
# STRUCTURAL, and that is the whole point.
#
# My first version checked that every failure line contained one of a hand-picked
# list of phrases ("refuse", "stale", "mismatch", ...). It printed GUARD IS
# DECORATIVE on a run whose failures plainly named the behaviour - the list was
# too narrow. That is §26 verbatim in the instrument rather than the product: a
# filter that excludes what it is looking for, reporting a confident wrong
# verdict. Keyword-matching assertion *text* is the wrong instrument entirely;
# the question is whether the suite ran to completion, and that is a property of
# its output, not of its prose.
if crashed_c:
    problems.append(
        "the pre-guard run CRASHED rather than reporting failures, so the "
        "failure count says nothing about the guard (a broken tree, not a "
        "regression - §23)")
else:
    print("the pre-guard run reported its failures cleanly - no traceback, so "
          "every failure is a real assertion, not a dead import")

print(f"combined-revert failures: {fc}")
print(f"single-revert results: "
      + ", ".join(f"{k}={v[0]}/{v[1]}" for k, v in single_results.items()))
if problems:
    print("GUARD IS DECORATIVE - the suite does not check the guard")
    for p in problems:
        print(f"    {p}")
    sys.exit(1)
print("VERDICT: guard is real - the suite fails when it is removed, and the "
      "failures name the behaviour")
