"""Stage 4.3 (findings C2, C4, C6): the answer pipeline must be honest.

Three separate defects, all of the same family -- a statement the app makes
that nothing in the code backs:

C2  **No grounding check.** Nothing verified that an identifier the model
    wrote down (an IP, an email, a hash, a person) actually occurs in the
    retrieved text. `extract_entities` was imported into `rag_engine.py` and
    never used. An answer can therefore invent `198.51.100.9` and be filed
    with an `chunks_used` footer as if it were grounded.

C4  **The refusal overclaims its scope.** "Your question shares no wording
    with anything indexed in this case" is a statement about the whole index,
    but the check only ever inspected the retrieved passages. The claim has to
    match what was measured.

C6  **`conv_context` is unbounded and protected.** The model's context window
    is shared between the question, the history and the evidence, and history
    was reserved before evidence and capped per answer but not per question.
    A client could crowd the evidence out of the window with history alone.

This suite is pure -- no network, no database -- exactly like
`verify_prompt_budget.py`. It is written BEFORE the fixes, so the pre-fix run
records the real failure count rather than crashing.

Run:  PYTHONPATH=. python tests/verify_grounding.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Isolate any accidental backend side-effect from the live install. The suite
# never opens the database, but the rule from tests/_purge.py is that a test
# script must not be one import away from touching the production record.
_TMP = tempfile.mkdtemp(prefix="grounding_")
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(_TMP, "grounding.db").replace("\\", "/"))
os.environ.setdefault("CASES_DIR", os.path.join(_TMP, "cases"))
os.environ.setdefault("QDRANT_DIR", os.path.join(_TMP, "qdrant"))

from backend.modules import rag_engine as rag                        # noqa: E402
from backend.modules.ollama_client import CHARS_PER_TOKEN            # noqa: E402

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' — ' + str(detail)) if detail else ''}")


CHUNKS = [
    {"text": "Firewall: inbound connection from 203.0.113.77 to 10.0.0.5 "
             "accepted.",
     "source": "fw.log", "chunk_index": 0, "score": 0.9},
    {"text": "Mail: m.webb@northwind-corp.com wrote about the transfer at "
             "02:31Z.",
     "source": "mail.txt", "chunk_index": 1, "score": 0.8},
]


# ---------------------------------------------------------------------------
# A. The grounding primitive
# ---------------------------------------------------------------------------
def part_a():
    print("\n=== A. grounding_check: identifiers in the answer vs the excerpts ===")
    check("A1 grounding_check exists",
          callable(getattr(rag, "grounding_check", None)))

    g = getattr(rag, "grounding_check", None)
    if g is None:
        for n in range(2, 9):
            check(f"A{n} (grounding_check missing: C2 unfixed)", False)
        return

    # A grounded answer: every identifier it names is in the excerpts.
    grounded = g(
        "The host 203.0.113.77 connected, and m.webb@northwind-corp.com was "
        "the sender.", CHUNKS)
    check("A2 a fully grounded answer reports no ungrounded identifier",
          grounded.get("ungrounded") == 0
          and grounded.get("ungrounded_identifiers") == [],
          grounded)
    check("A3 the grounding ratio is a measured 1.0 when all are grounded",
          grounded.get("grounded_ratio") == 1.0, grounded.get("grounded_ratio"))
    check("A4 grounding actually checked something (a vacuous pass is a fail)",
          (grounded.get("checked") or 0) >= 2, grounded.get("checked"))

    # An invented identifier: nothing backs it.
    invented = g("The host 198.51.100.9 connected to the server.", CHUNKS)
    check("A5 an identifier absent from every excerpt is flagged",
          invented.get("ungrounded") == 1, invented)
    vals = [u.get("value") for u in invented.get("ungrounded_identifiers", [])]
    check("A6 the flagged identifier is named, so it can be checked by hand",
          "198.51.100.9" in vals, vals)
    check("A7 a partially grounded answer reports a ratio below 1.0",
          (invented.get("grounded_ratio") or 0) < 1.0,
          invented.get("grounded_ratio"))

    # The honesty case. No identifiers -> NOT a pass.
    none_found = g("Nothing in this case matched that question.", CHUNKS)
    check("A7b an answer with no identifiers reports checked == 0",
          invented.get("checked") is not None and
          (g("hello there", CHUNKS).get("checked") == 0),
          g("hello there", CHUNKS).get("checked"))
    check("A8 with nothing to check the ratio is None (unmeasured), not 1.0 "
          "or 0",
          invented is not None and _ratio(g("hello there", CHUNKS)) is None,
          g("hello there", CHUNKS).get("grounded_ratio"))
    check("A9 an empty/None answer does not raise and reports unmeasured",
          g(None, CHUNKS).get("grounded_ratio") is None
          and g("", CHUNKS).get("checked") == 0,
          g(None, CHUNKS))


def _ratio(d):
    return d.get("grounded_ratio")


# ---------------------------------------------------------------------------
# B. run_rag_query surfaces the grounding verdict
# ---------------------------------------------------------------------------
def _stub_run(chunks, model_text, *, diag_running=True, model_ready=True,
              retrieve_raises=False):
    """Drive run_rag_query with every external seam stubbed. Returns
    (result, captured_prompt_list)."""
    saved = {k: getattr(rag, k) for k in (
        "retrieve", "get_graph_context", "generate_response_detailed",
        "effective_context_tokens", "prompt_budget_tokens", "is_refusal",
        "ollama_diagnostic")}
    captured = []

    def _retrieve(**kw):
        if retrieve_raises:
            raise RuntimeError("index locked")
        return chunks

    def _gen(prompt, system):
        captured.append(prompt)
        return {"text": model_text, "prompt_eval_count": 10,
                "saturated": False}

    rag.retrieve = _retrieve
    rag.get_graph_context = lambda *a, **k: ""
    rag.generate_response_detailed = _gen
    rag.effective_context_tokens = lambda: 16384
    rag.prompt_budget_tokens = lambda: 15104
    rag.is_refusal = lambda t: False
    rag.ollama_diagnostic = lambda: {
        "running": diag_running, "model_ready": model_ready,
        "available": diag_running, "models": [], "reason": "no model"}
    try:
        r = rag.run_rag_query(
            query="transfer", case_id="c", qdrant_path="x",
            cases_dir="data/cases", evidence_id=None, asked_by="x",
            conversation_history=None)
    finally:
        for k, v in saved.items():
            setattr(rag, k, v)
    return r, captured


def part_b():
    print("\n=== B. run_rag_query reports whether the answer is grounded ===")
    r, _ = _stub_run(
        CHUNKS,
        "The host 198.51.100.9 moved the data, and 203.0.113.77 saw it.")
    check("B1 the result dict carries a grounding verdict",
          isinstance(r.get("grounding"), dict), r.get("grounding"))
    g = r.get("grounding") or {}
    check("B2 an invented identifier is surfaced, not silently passed",
          g.get("ungrounded", 0) >= 1, g)
    check("B3 the grounded identifier is counted as grounded",
          g.get("grounded", 0) >= 1, g)

    # A model that was never consulted cannot produce a grounded answer.
    r, _ = _stub_run(CHUNKS, "ignored", retrieve_raises=True)
    g = r.get("grounding") or {}
    check("B4 a search fault reports grounding as unmeasured, not as a pass",
          g.get("grounded_ratio") is None and g.get("checked") == 0, g)

    r, _ = _stub_run(CHUNKS, "ignored", diag_running=False)
    g = r.get("grounding") or {}
    check("B5 with no model there is nothing to ground: unmeasured, not 0",
          g.get("grounded_ratio") is None, g)


# ---------------------------------------------------------------------------
# C. The lexical refusal must claim only what it measured (C4)
# ---------------------------------------------------------------------------
def part_c():
    print("\n=== C. the 'shares no wording' refusal is scoped honestly ===")
    check("C1 query_shares_no_terms exists",
          callable(getattr(rag, "query_shares_no_terms", None)))
    if not callable(getattr(rag, "query_shares_no_terms", None)):
        for n in range(2, 8):
            check(f"C{n} (C4 unfixed surface missing)", False)
        return

    qsnt = rag.query_shares_no_terms
    no_terms = [{"text": "alpha beta gamma", "source": "f", "chunk_index": 0}]
    tripped, cov, terms = qsnt("the of and", no_terms)
    check("C2 a stopword-only query has no terms and does NOT trip the gate",
          tripped is False and terms == 0, (tripped, cov, terms))

    tripped, cov, terms = qsnt("zebracorn", no_terms)
    check("C3 a query whose content term matches nothing trips the gate",
          tripped is True and terms == 1, (tripped, cov, terms))

    shared = [{"text": "contact phantomlabs for the transfer",
               "source": "f", "chunk_index": 0}]
    tripped, cov, terms = qsnt("phantomlabs", shared)
    check("C4 a query sharing a term with a chunk does NOT trip the gate",
          tripped is False and cov > 0, (tripped, cov, terms))

    # The refusal text itself. Four passages, none sharing a term.
    four = [{"text": "alpha beta gamma", "source": f"f{i}.txt",
             "chunk_index": i, "score": 0.9} for i in range(4)]
    # Drive run_rag_query with a query that has content terms none of the
    # passages share, which is exactly the gate's trigger.
    saved = rag.retrieve
    rag.retrieve = lambda **kw: four
    try:
        r = rag.run_rag_query(
            query="zebracorn marmalade", case_id="c", qdrant_path="x",
            cases_dir="data/cases", evidence_id=None, asked_by="x",
            conversation_history=None)
    finally:
        rag.retrieve = saved
    answer = (r.get("answer") or "")
    low = answer.lower()
    check("C5 the refusal no longer claims scope over the whole case",
          "anything indexed in this case" not in low, answer[:180])
    check("C6 it names how many passages were actually inspected",
          "4" in answer and "passage" in low, answer[:220])
    check("C7 it still says the question shares no wording with the searched text",
          "shares no" in low and "wording" in low, answer[:160])
    check("C8 it still refuses to call the case clean",
          "not a finding that the case is clean" in low
          or "ruled out" in low or "has been ruled out" in low, answer[-220:])


# ---------------------------------------------------------------------------
# D. Conversation history is bounded (C6)
# ---------------------------------------------------------------------------
def part_d():
    print("\n=== D. conv_context is bounded and cannot crowd out evidence ===")
    budget = rag.prompt_budget_tokens()
    big = ("HISTORY " * 30000)  # ~240 KB, far larger than any window

    p, s = rag.build_prompt(
        query="who moved the data?", chunks=list(CHUNKS), graph_ctx="",
        conv_context=big, budget_tokens=budget)
    check("D1 an oversized conv_context is trimmed, and says so",
          s.get("conv_trimmed") is True and s.get("conv_chars_elided", 0) > 0,
          {k: s.get(k) for k in ("conv_trimmed", "conv_chars_elided")})
    check("D2 the prompt still fits the budget",
          s.get("estimated_tokens", 0) <= budget,
          (s.get("estimated_tokens"), budget))
    check("D3 the evidence is not crowded out of the prompt",
          "Firewall:" in p or "203.0.113.77" in p, p[:200])
    check("D4 the question and instruction survive verbatim",
          "Current Question: who moved the data?" in p
          and "Provide your analysis based solely" in p)
    # Trimming history must NOT be reported as elided EVIDENCE: the router
    # turns chars_elided into a "the model did not see the evidence" caveat.
    check("D5 history trimming is not counted as evidence elision",
          s.get("chars_elided", 0) == 0,
          f"chars_elided={s.get('chars_elided')}")

    # The producer must bound questions as well as answers, and use at most
    # the last five exchanges.
    hist = [{"question": f"q{i} " + "Q" * 5000,
             "answer": f"a{i} " + "A" * 5000} for i in range(8)]
    saved = {k: getattr(rag, k) for k in ("retrieve", "get_graph_context",
            "generate_response_detailed", "effective_context_tokens",
            "prompt_budget_tokens", "is_refusal", "ollama_diagnostic")}
    prompts = []
    rag.retrieve = lambda **kw: CHUNKS
    rag.get_graph_context = lambda *a, **k: ""
    rag.generate_response_detailed = lambda pr, sy: (
        prompts.append(pr) or {"text": "Firewall 203.0.113.77 grounded "
                                       "answer.", "prompt_eval_count": 10,
                               "saturated": False})
    rag.effective_context_tokens = lambda: 16384
    rag.prompt_budget_tokens = lambda: 15104
    rag.is_refusal = lambda t: False
    rag.ollama_diagnostic = lambda: {"running": True, "model_ready": True,
                                     "available": True, "models": []}
    try:
        rag.run_rag_query(
            query="transfer", case_id="c", qdrant_path="x",
            cases_dir="data/cases", evidence_id=None, asked_by="x",
            conversation_history=hist)
    finally:
        for k, v in saved.items():
            setattr(rag, k, v)

    prompt = prompts[0] if prompts else ""
    check("D6 a huge question is truncated in the conversation memory",
          "Q" * 5000 not in prompt, f"len={len(prompt)}")
    check("D7 only the most recent exchanges are carried",
          "q0 " not in prompt and "q7 " in prompt, prompt[:200])
    check("D8 the assembled prompt is bounded despite the history",
          len(prompt) <= 15104 * CHARS_PER_TOKEN + 500, len(prompt))
    check("D9 the evidence is still in the prompt",
          "Firewall:" in prompt, prompt[-300:])
    # Discriminating for the crowding-out failure: with an unbounded history
    # the protected reservation drove the per-excerpt allowance to its 64-char
    # floor, so only the first few words of each excerpt survived. A healthy
    # prompt carries the excerpt's opening in full.
    check("D12 the excerpt body keeps a real share of the window, not 64 chars",
          "accepted." in prompt, prompt[:400])

    # The schema default must be a factory, and the list must be bounded.
    try:
        from backend.schemas import QueryCreate
        a = QueryCreate(question_text="q")
        b = QueryCreate(question_text="q")
        check("D10 QueryCreate's default history list is not shared",
              a.conversation_history == []
              and a.conversation_history is not b.conversation_history)
        bounded = QueryCreate(
            question_text="q",
            conversation_history=[{"question": "q", "answer": "a"}] * 500)
        check("D11 a client cannot submit an unbounded history list",
              len(bounded.conversation_history) <= 50,
              len(bounded.conversation_history))
    except Exception as exc:                                  # pragma: no cover
        check("D10 QueryCreate schema is importable", False, repr(exc))


def main():
    print("=" * 66)
    print("Stage 4.3 -- grounding, honest refusals, bounded history")
    print("=" * 66)

    part_a()
    part_b()
    part_c()
    part_d()

    print(f"\n{'=' * 66}")
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f in FAIL:
        print(f"  FAIL  {f}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
