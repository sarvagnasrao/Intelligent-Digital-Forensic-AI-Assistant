"""
Test the gate's own parser. §21's rule: **a summariser is a program and has to be
tested like one.**

Why this file exists at all
---------------------------
`run_gate.py` reported six healthy suites as `?? summary unreadable` on its first
run. All six had passed; all six had printed their counts. They print
`  9 passed, 0 failed` — **count first, comma separated** — while the other ten
print `PASSED: 209    FAILED: 0` — **word first**. The parser handled only the
second shape.

> A summariser that cannot read a summary reports exactly the same thing whether the
> suite passed or crashed, so the honest reading of that output is "six suites are
> broken" — which would have sent the next agent to debug six healthy scripts.

§23 recorded the mirror image: an ad-hoc gate that converted a **red** run green.
This is the same class, and the fix is the same: parse both shapes explicitly, and
make "could not measure" a loud state rather than a zero.

What is asserted
----------------
- both shapes the suites actually print, so narrowing the parser again fails here
  in a second rather than after a six-minute gate run;
- **failures are counted, not swallowed** — the reason TRAP 8 existed;
- the two halves of shape B are read independently, because they are not
  guaranteed to share a line;
- per-assertion `FAIL` lines above the summary are not mistaken for it (the last
  candidate wins, since the summary is printed last);
- and **the four inputs that must return `None` rather than `0`**. §16's rule,
  ninth instance in this repo: a value nobody measured is `None` plus a reason,
  never a fabricated zero.

Run:  PYTHONPATH=. python tests/verify_gate_parser.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "run_gate.py")

_passed = 0
_failed = 0


def check(description, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {description}")
    else:
        _failed += 1
        print(f"  FAIL  {description}  got {got!r}, want {want!r}")


def load_parse():
    """
    Execute run_gate.py's source up to the runner body, so the parser can be tested
    without running sixteen suites.

    Split on the first function *after* parse, not on a comment. An earlier version
    of this test split on a comment that sits ABOVE parse(), so it truncated the
    wrong part and died with `KeyError: 'parse'` while appearing to test the parser.
    Same class as the count-first bug one layer up: a marker assumed to be on the
    right side of the thing it marks.
    """
    if not os.path.exists(GATE):
        return None, "run_gate.py not found next to this suite"
    try:
        src = open(GATE, encoding="utf-8").read()
        head = src.split("\ndef run(name):")[0]
        ns = {"__file__": GATE, "__name__": "run_gate_under_test"}
        exec(compile(head, GATE, "exec"), ns)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if "parse" not in ns:
        return None, ("run_gate.py no longer defines parse() above run() - if the "
                      "layout changed, update this loader")
    return ns["parse"], None


def main():
    parse, err = load_parse()
    if parse is None:
        print(f"  FAIL  the gate's parser could not be loaded: {err}")
        print(f"\nGATE PARSER SUITE FAILED - 0 passed, 1 failed")
        sys.exit(1)

    # Section A - the shapes the suites actually print.
    print("\nA. both summary shapes the suites really use")
    check("cpu_sampler: 9 passed, 0 failed", parse("  9 passed, 0 failed"), (9, 0))
    check("forensic_failure: 15 passed, 0 failed",
          parse("  15 passed, 0 failed"), (15, 0))
    check("gpu_telemetry: 171 passed, 0 failed",
          parse("  171 passed, 0 failed"), (171, 0))
    check("job_stop / vector_store: 17 passed, 0 failed",
          parse("  17 passed, 0 failed"), (17, 0))
    check("prompt_budget: 86 passed, 0 failed",
          parse("  86 passed, 0 failed"), (86, 0))
    check("service_health: PASSED: 209  FAILED: 0",
          parse("PASSED: 209    FAILED: 0"), (209, 0))
    check("provenance: SUITE PASSED - 79 assertions",
          parse("PROVENANCE SUITE PASSED - 79 assertions"), (79, 0))

    # Section B - failures must be counted. This is the whole of TRAP 8.
    print("\nB. failures are counted, never swallowed")
    check("a red count-first summary", parse("  177 passed, 15 failed"), (177, 15))
    check("a red word-first summary", parse("PASSED: 177    FAILED: 15"), (177, 15))
    check("halves in the other order", parse("  FAILURES: 0   PASSED: 38"), (38, 0))

    # Section C - the last summary wins, so per-assertion lines cannot be read as one.
    print("\nC. per-assertion lines are not mistaken for the summary")
    check("a FAIL line above the summary does not win",
          parse("[PASS] a thing\n  FAIL  another thing\n  86 passed, 2 failed"),
          (86, 2))

    # Section D - the direction that matters most. §16, ninth instance.
    print("\nD. unmeasurable is None, NEVER 0")
    check("empty output", parse(""), None)
    check("a traceback with no summary",
          parse("Traceback (most recent call last):\n  File x\n"
                "NameError: name 'foo' is not defined"), None)
    check("a FAIL line and no summary",
          parse("  [FAIL] something died and never printed a summary"), None)
    check("a summary shape with no numbers", parse("PASSED:\nFAILED:"), None)

    print()
    print("=" * 74)
    print(f"GATE PARSER SUITE {'PASSED' if _failed == 0 else 'FAILED'} - "
          f"{_passed} passed, {_failed} failed")
    print("=" * 74)
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()