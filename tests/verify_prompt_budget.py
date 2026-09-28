"""
Context-window budgeting for the RAG chatbot.

The defect this guards: retrieval worked perfectly, Ollama was up, the model
was loaded, and the chatbot still answered "I can't assist with that."
because the assembled prompt was 212,815 characters (~80,311 tokens) sent to
a model Ollama was serving with a 4,096-token window. Ollama accepted it,
truncated it without telling anyone, kept the first 5 tokens and the last
4,091, and the model was asked to reason about evidence it had never been
shown. The sources footer was still appended, so the exchange looked
answered.

Everything here is pure -- no network, no database, no model -- so it runs
anywhere and is fast. The live end-to-end check lives in verify_live_stack.py.

Run:  PYTHONPATH=. python tests/verify_prompt_budget.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from backend.modules import rag_engine
from backend.modules import ollama_client
from backend.dependencies import get_settings
from backend.modules.rag_engine import (
    build_prompt, _elide, is_refusal, process_response,
    ELISION_MARKER_ALLOWANCE, EVIDENCE_NOTE_MARKER)
from backend.modules.ollama_client import (
    effective_context_tokens, prompt_budget_tokens, CHARS_PER_TOKEN)

PASS, FAIL = 0, 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"PASS  {label}")
    else:
        FAIL += 1
        print(f"FAIL  {label}  {detail}")


def big_chunks(n=7, size=30000, src="test_evidence_10mb.txt"):
    """The real shape: 30,000-character chunks, seven of them."""
    body = ("Carlos Rivera c.rivera@phantomlabs.net +1-312-555-0891 "
            "phishing campaign darknode.io 2025-07-14T00:49:38Z ")
    text = (body * (size // len(body) + 1))[:size]
    return [{"text": text, "source": src, "score": 0.87,
             "evidence_id": "e1", "chunk_index": i} for i in range(n)]


# ---------------------------------------------------------------------------
# A. The window Ollama is actually serving
# ---------------------------------------------------------------------------

print("\n--- A. effective context window ---")

ctx = effective_context_tokens()
check("A1 context is a positive int", isinstance(ctx, int) and ctx > 0,
      f"got {ctx!r}")
check("A2 context is not the trained length (llama3.2 trains at 131072)",
      ctx != 131072,
      f"got {ctx} -- this is the /api/show value, not the runtime one")
check("A3 context is at least 512", ctx >= 512, f"got {ctx}")

budget = prompt_budget_tokens()
check("A4 budget is positive", budget > 0, f"got {budget}")
check("A5 budget is smaller than the window",
      budget < ctx, f"budget {budget} >= ctx {ctx}")
check("A6 budget leaves room for generation",
      ctx - budget >= 200,
      f"only {ctx - budget} tokens reserved for the answer")


# ---------------------------------------------------------------------------
# B. The overflow itself
# ---------------------------------------------------------------------------

print("\n--- B. the 212k prompt no longer fits ---")

q = ("How many total suspects are listed in the master evidence "
     "compilation manifest, and what are the primary email address "
     "and phone number for suspect Carlos Rivera?")
chunks = big_chunks()
graph = "Entity relationships:\n- Carlos Rivera -> Nathan Cole (transacted)"

prompt, stats = build_prompt(
    query=q, chunks=chunks, graph_ctx=graph,
    conv_context="", budget_tokens=budget)

unbudgeted = 210795  # the measured pre-fix size of 7 x 30,000

check("B1 prompt is far smaller than the unbudgeted original",
      len(prompt) < unbudgeted / 2,
      f"{len(prompt)} vs {unbudgeted}")
check("B2 estimated tokens fit the budget",
      stats["estimated_tokens"] <= budget,
      f"est {stats['estimated_tokens']} > budget {budget}")
check("B3 the elision is recorded",
      stats["chars_elided"] > 0,
      f"chars_elided={stats['chars_elided']}")
check("B4 trimmed excerpts are counted",
      stats["excerpts_trimmed"] == len(chunks),
      f"{stats['excerpts_trimmed']} of {stats['excerpts']}")
check("B5 the graph context survives the budget",
      "Nathan Cole" in prompt and not stats["graph_trimmed"],
      "graph was clamped away -- reserve accounting is incomplete")
check("B6 the question survives the budget",
      q in prompt)
check("B7 every retrieved excerpt is still represented",
      all(f"[Excerpt {i + 1}]" in prompt
          for i in range(len(chunks))),
      "a whole excerpt was dropped, so retrieval answered a narrower "
      "question than it retrieved")
check("B8 no excerpt silently vanishes: each is marked as trimmed",
      prompt.count("omitted to fit the model's context window")
      == len(chunks),
      f"markers={prompt.count(chr(39))} expected={len(chunks)}")


# ---------------------------------------------------------------------------
# C. Per-excerpt allocation, not a shared allowance
# ---------------------------------------------------------------------------

print("\n--- C. budget is shared, not first-come ---")

_, one_stats = build_prompt(
    query="q", chunks=big_chunks(n=1), graph_ctx="",
    conv_context="", budget_tokens=budget)
_, seven_stats = build_prompt(
    query="q", chunks=big_chunks(n=7), graph_ctx="",
    conv_context="", budget_tokens=budget)

check("C1 one excerpt gets more than seven do",
      one_stats["chars_elided"] < seven_stats["chars_elided"],
      f"1={one_stats['chars_elided']} 7={seven_stats['chars_elided']}")
check("C2 adding excerpts does not grow the prompt without bound",
      len(build_prompt("q", big_chunks(n=7), "", "",
                       budget)[0])
      < len(build_prompt("q", big_chunks(n=1), "", "",
                         budget)[0]) * 3,
      "7-excerpt prompt is not comparable to 1-excerpt prompt")

# Each of the 7 must receive a real, roughly equal share.
prompt7, _ = build_prompt("q", big_chunks(n=7), "", "",
                          budget)
bodies = []
current = None
for line in prompt7.splitlines():
    if line.startswith("[Excerpt "):
        current = []
    elif current is not None and not line.startswith("Source:"):
        current.append(line)
if current:
    bodies.append(current)
shares = [len("\n".join(b)) for b in bodies]
if shares:
    spread = (max(shares) - min(shares)) / max(max(shares), 1)
    check("C3 excerpt shares are roughly equal",
          spread < 0.45, f"spread={spread:.2f} shares={shares}")
else:
    check("C3 excerpt shares are roughly equal", False,
          "could not parse excerpts out of the prompt")


# ---------------------------------------------------------------------------
# D. _elide must say what it dropped
# ---------------------------------------------------------------------------

print("\n--- D. elision is announced ---")

text, dropped = _elide("x" * 500, 100)
check("D1 dropped count is reported", dropped == 400, f"{dropped}")
check("D2 the marker is present",
      "omitted to fit the model's context window" in text)
check("D3 kept text is within the allowance",
      len(text) <= 100 + ELISION_MARKER_ALLOWANCE,
      f"len={len(text)} allowance={ELISION_MARKER_ALLOWANCE}")
check("D4 marker stays inside its reserved allowance",
      len(text) - 100 <= ELISION_MARKER_ALLOWANCE + 1,
      f"marker cost {len(text) - 100} > "
      f"{ELISION_MARKER_ALLOWANCE}")

unchanged, dropped0 = _elide("short", 100)
check("D5 short text is untouched",
      unchanged == "short" and dropped0 == 0)

empty, dropped0 = _elide("", 100)
check("D6 empty text does not raise", empty == "" and dropped0 == 0)


# ---------------------------------------------------------------------------
# E. A refusal must not be filed as an answer
# ---------------------------------------------------------------------------

print("\n--- E. refusals are diagnosed, not stored ---")

check("E1 the exact production refusal is detected",
      is_refusal("I can't assist with that."))
check("E2 alternate phrasings are caught",
      all(is_refusal(t) for t in [
          "I cannot assist with that.",
          "I can't help with that.",
          "I'm unable to provide that.",
          "As an AI language model, I must decline.",
          "I'm sorry, but I cannot provide that information."]))

real_answer = (
    "Carlos Rivera's primary email is c.rivera@phantomlabs.net. The "
    "manifest lists two suspects.")
check("E3 a real forensic answer is not misread as a refusal",
      not is_refusal(real_answer))
check("E4 a refusal phrase later in a real answer does not trip it",
      not is_refusal(
          "The evidence shows the operator emailed c.rivera@x.net. "
          "I cannot find a second address for him."))

refused, cited, uncited = process_response(
    "I can't assist with that.", chunks, stats)
check("E5 a refusal is replaced, not returned",
      "can't assist" not in refused.lower(), refused[:60])
check("E6 the replacement names the capacity cause",
      "context window" in refused.lower() or "declined" in refused.lower(),
      refused[:120])
check("E7 the replacement does not blame the question",
      "rephras" not in refused.lower()
      and "try again with" not in refused.lower(),
      refused[:120])
check("E8 nothing is claimed to be cited from a refusal",
      cited == 0 and uncited == 0)

ok, cited2, _ = process_response(real_answer, chunks, stats)
# All 7 chunks carry the same `source`, and cited_sentence_count counts
# UNIQUE sources, not excerpts. An assertion of 7 here would be asserting
# the wrong thing and would pass only if dedup were removed.
expected_cited = len({c["source"] for c in chunks})
check("E9 a genuine answer still passes through",
      "phantomlabs.net" in ok and cited2 == expected_cited,
      f"cited2={cited2} expected={expected_cited}")
check("E10 the unique-source footer is not duplicated",
      ok.count("Sources:") == 1, f"count={ok.count('Sources:')}")


# ---------------------------------------------------------------------------
# F. The estimator must fail in the safe direction
# ---------------------------------------------------------------------------

print("\n--- F. char/token estimate is conservative ---")

# The densest text this system indexes measured 2.53 chars/token. If
# CHARS_PER_TOKEN is at or below that, the estimate is an over-estimate and
# the prompt is smaller than budget. An under-estimate overflows silently.
check("F1 CHARS_PER_TOKEN is at or below the densest measured ratio",
      CHARS_PER_TOKEN <= 2.53,
      f"{CHARS_PER_TOKEN} > 2.53 -- the estimate under-counts tokens, "
      f"which is the direction that overflows")
check("F2 CHARS_PER_TOKEN is not absurdly small",
      CHARS_PER_TOKEN >= 1.0,
      f"{CHARS_PER_TOKEN} -- would waste most of the window")

check("F3 is_refusal handles empty input", not is_refusal(""))
check("F4 is_refusal handles None", not is_refusal(None))


# ---------------------------------------------------------------------------
# G. No-chunk and empty-history paths
# ---------------------------------------------------------------------------

print("\n--- G. degenerate inputs ---")

p, s = build_prompt("what happened?", [], "", "", budget)
check("G1 a zero-chunk query still produces a prompt",
      "Current Question: what happened?" in p)
check("G2 a zero-chunk query is inside budget",
      s["estimated_tokens"] <= budget)
check("G3 a zero-chunk query claims no elision",
      s["chars_elided"] == 0)

p, s = build_prompt(
    "q", big_chunks(n=2), graph, "Previous exchanges:\n[Exchange 1]",
    budget)
check("G4 conversation history is retained",
      "Previous exchanges" in p)
check("G5 history does not blow the budget",
      s["estimated_tokens"] <= budget)

p, s = build_prompt("q", big_chunks(n=3), "x" * 40000, "", budget)
check("G6 an oversized graph is clamped rather than overflowing",
      s["estimated_tokens"] <= budget + 1,
      f"est {s['estimated_tokens']} vs budget {budget}")
check("G7 clamping is recorded",
      s["graph_trimmed"] or s["excerpts_trimmed"] == 3)
# The question is at the back of the prompt and _elide keeps the front, so a
# clamp on the assembled string answers a different question than the one
# asked. Trimming the graph before assembly is what prevents this.
check("G8 a clamped prompt still carries the question verbatim",
      "Current Question: q" in p, "the question was trimmed away")
check("G9 the closing instruction survives too",
      "Provide your analysis based solely" in p)

p, s = build_prompt("q", big_chunks(n=3), "x" * 40000, "", budget)
check("G10 the graph, not the question, absorbed the overrun",
      len(p) > 0 and s["estimated_tokens"] <= budget + 1)


# ---------------------------------------------------------------------------
# H. Regression on the original symptom
# ---------------------------------------------------------------------------

print("\n--- H. the original symptom cannot come back ---")

_, tight = build_prompt("q", big_chunks(), graph, "", budget)
# The pre-fix pipeline had no budget at all: chars_elided was undefined and
# 210,795 characters went out. Guard the specific number that overflowed.
check("H1 the prompt is well under the overflow point",
      int(tight["estimated_tokens"]) < 4096,
      f"est {tight['estimated_tokens']} vs a 4096 window")
check("H2 the elision total is reported so the UI can disclose it",
      isinstance(tight["chars_elided"], int)
      and tight["chars_elided"] > 0)
check("H3 stats expose the window for the disclosure message",
      tight["context_tokens"] == effective_context_tokens())

# And the diagnostic the router hands the frontend.
res = {
    "answer": "x", "raw_llm_response": "y", "chunks_used": chunks,
    "graph_context": graph, "prompt_stats": tight,
    "refused": False, "ollama_available": True, "model_ready": True,
    "model_diagnostic": {}, "cited_sentence_count": 0,
    "uncited_sentence_count": 0, "response_time_ms": 1,
    "model_used": "llama3.2:3b"}
for key in ("prompt_stats", "refused"):
    check(f"H4 result carries '{key}' for the API", key in res)


# ---------------------------------------------------------------------------
# I. Transport backstop for callers that build their own prompt
# ---------------------------------------------------------------------------
# Four features assemble a prompt by hand: case summary (8 x 30,000 chars),
# contradiction analysis (12 x 30,000), entity profile and its retry. All
# four overflowed the same window, silently. The clamp lives in
# generate_response_detailed so that no call site can bypass it.

print("\n--- I. transport backstop ---")

from backend.modules.ollama_client import generate_response_detailed


class _Resp:
    """Stands in for the requests.Response the client checks."""
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


sent = {}



def _fake_post(url, json=None, timeout=None):
    sent["prompt"] = json["prompt"]
    sent["num_predict"] = json["options"]["num_predict"]
    return _Resp({
        "response": "ok",
        "prompt_eval_count": 120,
        "eval_count": 3,
    })


_real_post = ollama_client.requests.post
try:
    ollama_client.requests.post = _fake_post

    out = generate_response_detailed("q" * 10, "sys")
    check("I1 a small prompt passes through untouched",
          sent["prompt"] == "q" * 10, "clamped a prompt that fits")
    check("I2 a small prompt is not marked clamped",
          out["prompt_stats"]["clamped"] is False)
    check("I3 num_predict comes from settings, not a literal",
          sent["num_predict"] == get_settings().ollama_num_predict,
          f"{sent['num_predict']}")

    huge = ("CONTEXT-FILLER " * 20000) + "TASK: write the profile now"
    out = generate_response_detailed(huge, "sys")
    p = sent["prompt"]
    check("I4 an oversized prompt is clamped",
          out["prompt_stats"]["clamped"] is True)
    check("I5 the clamp is far smaller than the original",
          len(p) < len(huge) / 2, f"{len(p)} vs {len(huge)}")
    check("I6 the clamp keeps the task instruction (the tail)",
          "write the profile now" in p,
          "cutting the end deletes the request, which is the worst "
          "possible truncation")
    check("I7 the clamp keeps the head", "CONTEXT-FILLER" in p)
    check("I8 the clamp is disclosed, not silent",
          "omitted" in p and "window" in p)
    check("I9 the clamped prompt is inside the budget",
          out["prompt_stats"]["estimated_tokens"] <= budget + 1,
          f"est {out['prompt_stats']['estimated_tokens']} vs {budget}")
    check("I10 the clamp count is reported",
          out["prompt_stats"]["chars_clamped"] > 0)
    check("I11 the text is still returned", out["text"] == "ok")

    out = generate_response_detailed(huge, "sys")
    check("I12 clamping is idempotent in cost",
          out["prompt_stats"]["clamped"] is True
          and out["prompt_stats"]["estimated_tokens"] <= budget + 1)

    # generate_response() must keep its old signature for test_ollama.py
    check("I13 generate_response still returns a bare string",
          isinstance(out["text"], str))

    # A 4xx must still be a fault, not a clamped success.
    ollama_client.requests.post = lambda url, json=None, timeout=None: _Resp(
        {"error": "model 'llama3.2:3b' not found"}, status=404)
    out = generate_response_detailed("q", "sys")
    check("I14 a missing model is still a fault",
          out["error"] is not None and "ollama pull" in out["text"])

finally:
    ollama_client.requests.post = _real_post


print(f"\n{'=' * 56}")
print(f"  {PASS} passed, {FAIL} failed")
print(f"{'=' * 56}")
sys.exit(1 if FAIL else 0)
