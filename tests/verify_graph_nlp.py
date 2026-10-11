"""
NER budget and co-mention cap in backend/modules/graph_builder.py.

Two findings:

  A11 - the NER budget. ``build_graph`` already limited NER to a 30,000-char
        budget, but the loop that filled it always admitted the FIRST chunk
        whatever its size (``if budgeted and budget_used + len(c) > budget``),
        so a single oversized chunk ran the pipeline in full. The standalone
        ``extract_entities`` entry point had no budget at all.

  A12 - ``CO_MENTIONED_WITH`` edges are quadratic across every person in a
        chunk (``C(n,2)``), with no limit, so a chunk naming a few hundred
        people becomes tens of thousands of graph inserts.

Both are measured against a stub ``nlp`` pipeline (no model weights, fully
deterministic). The suite measures the budget and the edge count, not spaCy.

Pure: temp dirs only, no DB, no network. Run:
    PYTHONPATH=. python tests/verify_graph_nlp.py
"""

import atexit
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

# graph_builder loads spaCy at import time. If that fails, emit clean FAILs
# rather than dying with a traceback the gate has to call "unreadable".
try:
    from backend.modules import graph_builder
    _IMPORT_ERROR = None
except Exception as exc:                                # noqa: BLE001
    graph_builder = None
    _IMPORT_ERROR = exc


PASS, FAIL = 0, 0
FAILED = []


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"PASS  {label}")
    else:
        FAIL += 1
        FAILED.append(label)
        print(f"FAIL  {label}  -- {detail}")


TMP = tempfile.mkdtemp(prefix="idfa_graph_nlp_")
atexit.register(shutil.rmtree, TMP, True)

# Names are short and mutually dissimilar ("P00".."P59"): the resolver folds
# strings whose fuzzy ratio exceeds 0.85, and near-identical names would be
# merged before the cap could be measured.


class _FakeEnt:
    def __init__(self, text, label):
        self.text = text
        self.label_ = label


class _FakeDoc:
    def __init__(self, ents):
        self.ents = ents


class _Recorder:
    """Stands in for the spaCy pipeline.

    Records the character count of every text processed and returns PERSON
    entities for whitespace tokens like ``P12``. Enough for ``build_graph`` to
    build the same edges real NER would, while making the budget and the edge
    count the only things under measurement.
    """

    def __init__(self):
        self.pipe_lengths = []
        self.call_lengths = []

    def _doc(self, text):
        ents = [
            _FakeEnt(tok, "PERSON")
            for tok in text.split()
            if tok[:1] == "P" and tok[1:].isdigit()
        ]
        return _FakeDoc(ents)

    def pipe(self, texts, batch_size=32):
        for text in texts:
            self.pipe_lengths.append(len(text))
            yield self._doc(text)

    def __call__(self, text):
        self.call_lengths.append(len(text))
        return self._doc(text)


def _person_chunk(n):
    return " ".join(f"P{i}" for i in range(n))


def _read_graph(case_id):
    with open(os.path.join(TMP, case_id, "graph_store.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _comention_count(case_id):
    return sum(1 for e in _read_graph(case_id)["edges"]
               if e.get("relationship") == "CO_MENTIONED_WITH")


if graph_builder is None:
    check("graph_builder imports", False, repr(_IMPORT_ERROR))
    print("\n" + "=" * 66)
    print(f"PASSED: {PASS}    FAILED: {FAIL}")
    print("=" * 66)
    sys.exit(1)

# ── A12: the co-mention cap ──────────────────────────────────────────────────

graph_builder.nlp = _Recorder()
cap = getattr(graph_builder, "CO_MENTION_MAX_PERSONS", None)
check("the co-mention cap is a named, documented constant",
      isinstance(cap, int) and cap > 1,
      f"CO_MENTION_MAX_PERSONS={cap!r}")

# A chunk naming 60 distinct people. Uncapped that is C(60,2) = 1770 edges.
graph_builder.build_graph(
    [_person_chunk(60)], "big.txt", "ev-1", "case-cap", TMP)
edges = _comention_count("case-cap")
check("a 60-person chunk does not produce the quadratic edge count",
      edges < 60 * 59 // 2,
      f"got {edges} co-mention edges")
if isinstance(getattr(graph_builder, "CO_MENTION_MAX_PERSONS", None), int):
    cap = graph_builder.CO_MENTION_MAX_PERSONS
    expected = cap * (cap - 1) // 2
    check(f"  and is bounded by C({cap},2) = {expected}",
          edges <= expected, f"got {edges}")

# The cap must not touch ordinary chunks.
graph_builder.build_graph(
    [_person_chunk(5)], "small.txt", "ev-2", "case-small", TMP)
small_edges = _comention_count("case-small")
check("a 5-person chunk keeps every pairwise co-mention",
      small_edges == 10, f"got {small_edges}")

# No person is dropped from the graph by the cap: everyone still gets a
# MENTIONED_IN edge to the file even when co-mentions are capped.
mentioned = {
    e["source"] for e in _read_graph("case-cap")["edges"]
    if e.get("relationship") == "MENTIONED_IN"
}
dropped = [f"P{i}" for i in range(60) if f"P{i}" not in mentioned]
check("the cap does not drop any person from the graph",
      not dropped, f"missing {len(dropped)}")

# ── A11: the NER budget ──────────────────────────────────────────────────────

_declared_budget = getattr(graph_builder, "NER_BUDGET_CHARS", None)
check("the NER budget is a named constant",
      isinstance(_declared_budget, int) and _declared_budget > 1,
      f"NER_BUDGET_CHARS={_declared_budget!r}")

# Fall back to the documented 30,000 so the behavioural checks still run (and
# fail) against a tree where the budget is not yet exposed at module level.
budget = _declared_budget if isinstance(_declared_budget, int) else 30_000

if isinstance(budget, int):
    # One chunk far larger than the budget must still stop at the budget.
    rec = _Recorder()
    graph_builder.nlp = rec
    graph_builder.build_graph(
        ["P0 " + ("x" * 100_000)], "huge.txt", "ev-h", "case-huge", TMP)
    check("one oversized chunk cannot exceed the NER budget",
          sum(rec.pipe_lengths) <= budget,
          f"fed {sum(rec.pipe_lengths)} chars, budget {budget}")

    # Many small chunks stop at the budget (a guard on existing behaviour).
    rec2 = _Recorder()
    graph_builder.nlp = rec2
    chunks = [f"P{i} " + ("x" * 600) for i in range(200)]
    graph_builder.build_graph(
        chunks, "many.txt", "ev-m", "case-many", TMP)
    check("many chunks stop at the NER budget",
          sum(rec2.pipe_lengths) <= budget,
          f"fed {sum(rec2.pipe_lengths)} chars, budget {budget}")

    # The standalone entry point is bounded too.
    rec3 = _Recorder()
    graph_builder.nlp = rec3
    graph_builder.extract_entities("x " * 60_000)
    check("extract_entities cannot run an unbounded NER pass",
          (sum(rec3.call_lengths) or 0) <= budget,
          f"fed {sum(rec3.call_lengths) or 0} chars, budget {budget}")

    # A small input is untouched.
    rec4 = _Recorder()
    graph_builder.nlp = rec4
    small = "P1 met P2 at the docks"
    graph_builder.extract_entities(small)
    check("a small input is fed whole",
          rec4.call_lengths == [len(small)],
          f"calls {rec4.call_lengths}, len {len(small)}")

print("\n" + "=" * 66)
for label in FAILED:
    print(f"  FAILED: {label}")
print(f"PASSED: {PASS}    FAILED: {FAIL}")
print("=" * 66)

sys.exit(1 if FAIL else 0)
