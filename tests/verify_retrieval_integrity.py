"""Retrieval must not be able to say "nothing matched" when it never ran. (B30)

Two claims are under test, and they are different bugs that happened to live in
the same function.

**A failed search reported as an empty one.** `search_chunks` ended in

    except Exception as e:
        print(f"QDRANT SEARCH ERROR: {e}")
        return []

which is the exact shape of B10 (`store_chunks` returned 0 on failure) and B1.
The consequence here is worse than in either of those, because the caller turns
an empty list into the sentence *"Nothing in this case matched that question,
and the model returned no analysis."* A locked Qdrant directory, a missing
collection or a dead embedder therefore produced a confident statement that the
evidence was clean — and in a forensic tool that sentence is what clears a
suspect. It is the most consequential instance of this repo's defining defect
that has been found.

**No relevance floor.** Qdrant returned `top_k=7` unconditionally and
`build_prompt` divided the context allowance between all seven. A question of
"hi" against a 6 MB corpus came back with seven chunks scoring 0.134-0.138, and
the model was asked to answer from them. Retrieval scoring exists to be
thresholded and it was not.

The floor is pinned to a measurement in section F, and those assertions are
written so that **changing the constant to any value outside the observed gap
fails the suite.** That is the point: a threshold picked by feel and then
guarded by "is it a number?" is a number, not a decision.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' — ' + str(detail)) if detail else ''}")


# The measured score distribution at the CURRENT chunking (700/120), on the
# Nightingale raw-image corpus, with ground truth taken by CONTENT — every file
# containing the needle, never a filename remembered by hand (§31.4: all six of
# v1's fixture failures were a fact present in two files).
#
# These REPLACED a pair that pinned the floor into a gap between two clusters on
# a different corpus. Re-measured, there is no gap: the regions overlap, and
# 0.225 < 0.253 means a real question about the exfiltration volume scores
# BELOW the gibberish string `asdf`. So the old §F could not be re-tuned to
# stay true, only re-derived — §31.6 said so before the work started.
#
# 12 questions, 8 fillers, 12 artifacts. A small sample, and recorded as such.
MEASURED_REAL_ANSWER_MIN = 0.225     # "How much data was exfiltrated...?"
MEASURED_REAL_ANSWER_MAX = 0.636     # "How much money went to Halcyon...?"
MEASURED_FILLER_MAX = 0.253          # "asdf"
MEASURED_FILLER_MIN = 0.065          # "what is duck?"

# The measured filler score that sits ABOVE every real answer-bearing chunk. This
# one number is the whole argument for the lexical gate: if the floor were ever
# raised above it, `asdf` would be accepted while a real question was rejected,
# which is the filter working exactly backwards. Section F asserts the floor
# stays below it.
MEASURED_OVERLAP = MEASURED_FILLER_MAX

# The three questions whose answer-bearing chunk shares NO content word with the
# question, because the investigator's wording differs from the evidence's:
#     "How much data was exfiltrated...?"  vs  "412.8 MB via exfil.darknode.io"
# "exfiltrated" is not "exfil", so not one token matches. Their cosine scores
# are 0.225 / 0.362 / 0.269 — all below MEASURED_FILLER_MAX, so a per-chunk
# lexical gate would drop the answer and a cosine floor alone cannot catch them
# either. They are the reason the gate is a query-level verdict.
MEASURED_SYNONYM_COSINES = (0.225, 0.362, 0.269)


def _chunks(scores, text="evidence excerpt"):
    return [{"text": text, "source": "f.txt", "evidence_id": "e1",
             "chunk_index": i, "score": s}
            for i, s in enumerate(scores)]


def main():
    from backend.modules import rag_engine
    from backend.modules import vector_store

    # ── A. the real search raises instead of returning [] ────────────────
    # Discriminating: with `except Exception: return []` this section passes
    # silently, because a broken path really does yield an empty list.
    print("=== A. a failed search is loud, not empty ===")
    broken = os.path.join(os.environ.get("TEMP", "/tmp"),
                          f"b30_no_such_dir_{uuid.uuid4().hex[:8]}")
    # A path that cannot be a Qdrant storage directory: the embedder runs
    # first, so this also proves the failure is not merely "no results".
    try:
        raised, msg = None, ""
        try:
            got = vector_store.search_chunks(
                query="who is the suspect",
                case_id="x", qdrant_path=broken, top_k=7)
            raised = "returned [] with no exception" if not got else "returned results"
        except Exception as e:
            raised = type(e).__name__
            # The message must carry the reason, or the operator gets a shrug.
            msg = str(e)
        check("a search against an unusable index RAISES rather than "
              "returning []", raised not in (None, "returned [] with no exception",
                                             "returned results"),
              f"outcome={raised}")
        check("the exception names the vector store, so a caller can tell "
              "this apart from an ordinary empty result",
              raised == "VectorStoreError", f"got {raised}")
        check("the message carries the underlying reason",
              ("case" in msg) and len(msg) > 40, msg[:110])
    finally:
        try:
            os.rmdir(broken)
        except Exception:
            pass

    # ── B. run_rag_query separates "failed" from "matched nothing" ──────
    print("\n=== B. run_rag_query: a fault is never reported as clean ===")
    real = rag_engine.search_chunks
    try:
        def _boom(**kw):
            raise vector_store.VectorStoreError(
                "Could not search case c: RuntimeError: storage folder is "
                "locked by another instance")

        rag_engine.search_chunks = _boom
        r = rag_engine.run_rag_query(
            query="what is the suspect's email address",
            case_id="c",
            qdrant_path="irrelevant",
            cases_dir="data/cases",
            evidence_id=None,
            asked_by="someone",
            conversation_history=None,
        )
    finally:
        rag_engine.search_chunks = real

    answer = (r.get("answer") or "").lower()
    ps = r.get("prompt_stats") or {}
    check("prompt_stats reports retrieval_failed", ps.get("retrieval_failed") is True, ps)
    check("prompt_stats carries the reason",
          "locked" in (ps.get("retrieval_error") or ""), ps.get("retrieval_error"))
    check("chunks_retrieved is 0 and nothing is claimed about the case",
          ps.get("chunks_retrieved") == 0 and r.get("chunks_used") == [],
          (ps.get("chunks_retrieved"), r.get("chunks_used")))
    # THE assertion. Pre-fix this said "nothing in this case matched".
    check("the answer does NOT claim the evidence was searched and found "
          "nothing (pre-fix: 'nothing in this case matched that question')",
          "nothing in this case matched" not in answer
          and "did not match" not in answer,
          (r.get("answer") or "")[:120])
    check("it says the search could not be run",
          "could not be run" in answer or "did not respond" in answer,
          (r.get("answer") or "")[:120])
    check("it explicitly says nothing has been ruled out",
          "ruled out" in answer or "not an answer about the case" in answer,
          (r.get("answer") or "")[:160])
    check("it does not blame the investigator's phrasing",
          "rephras" not in answer and "try terms" not in answer)
    check("it points at the health page, which is the actionable step",
          "health" in answer)
    check("no answer text was invented by the model",
          (r.get("raw_llm_response") or "") == "")

    # ── C. the floor drops noise and keeps signal ────────────────────────
    print("\n=== C. the relevance floor drops noise, keeps evidence ===")
    noise = _chunks([0.138, 0.137, 0.137, 0.135, 0.135, 0.134, 0.134])
    kept, dropped = rag_engine.apply_relevance_floor(noise)
    check("a 'hi' query's seven near-identical low-scoring chunks are all "
          "dropped", kept == [] and dropped == 7, (len(kept), dropped))

    signal = _chunks([0.476, 0.471, 0.470, 0.469, 0.466, 0.466, 0.465])
    kept, dropped = rag_engine.apply_relevance_floor(signal)
    check("a real match's seven chunks are all kept",
          len(kept) == 7 and dropped == 0, (len(kept), dropped))

    mixed = _chunks([0.476, 0.471, 0.138, 0.134, 0.107, 0.060])
    kept, dropped = rag_engine.apply_relevance_floor(mixed)
    check("a mixed result keeps the strong and drops the weak",
          [c["score"] for c in kept] == [0.476, 0.471] and dropped == 4,
          ([c["score"] for c in kept], dropped))

    # Ordering must survive: the floor is a filter, not a sort.
    unsorted_in = _chunks([0.40, 0.476, 0.45])
    kept, _ = rag_engine.apply_relevance_floor(unsorted_in)
    check("it preserves Qdrant's ranking rather than re-sorting",
          [c["score"] for c in kept] == [0.40, 0.476, 0.45],
          [c["score"] for c in kept])

    # ── D. an absent score is not an absent match ────────────────────────
    print("\n=== D. a missing measurement never becomes a missing answer ===")
    unscored = [{"text": "no score key", "source": "f", "chunk_index": 0}]
    kept, dropped = rag_engine.apply_relevance_floor(unscored)
    check("a chunk with no score is KEPT, not discarded",
          len(kept) == 1 and dropped == 0, (len(kept), dropped))
    nonescored = _chunks([0.4, None, 0.45])
    kept, dropped = rag_engine.apply_relevance_floor(nonescored)
    check("an explicit null score is treated the same way",
          len(kept) == 3 and dropped == 0, (len(kept), dropped))
    check("an empty input is still empty",
          rag_engine.apply_relevance_floor([]) == ([], 0))

    # ── E. the counts a caller reads are not silently collapsed ─────────
    print("\n=== E. 'retrieved nothing' and 'retrieved all and kept none' "
          "stay distinguishable ===")
    calls = {}
    generated = []

    def _fake(**kw):
        calls.update(kw)
        # "noise" as query AND chunk text -> lexical coverage 1.0 (gate passes),
        # but cosine 0.138 < floor 0.15 -> all dropped by the floor.
        return _chunks([0.138] * 8, text="noise")

    real_gc = rag_engine.get_graph_context
    real_gen = rag_engine.generate_response_detailed
    real_eff = rag_engine.effective_context_tokens
    real_bud = rag_engine.prompt_budget_tokens
    real_ref = rag_engine.is_refusal
    real_diag = rag_engine.ollama_diagnostic
    try:
        rag_engine.search_chunks = _fake
        rag_engine.get_graph_context = lambda *a, **k: ""
        rag_engine.generate_response_detailed = lambda p, s: (
            generated.append(p) or {
                "text": "A grounded answer drawn from the excerpts." * 3,
                "prompt_eval_count": 10, "saturated": False})
        rag_engine.effective_context_tokens = lambda: 16384
        rag_engine.prompt_budget_tokens = lambda: 15104
        rag_engine.is_refusal = lambda t: False
        rag_engine.ollama_diagnostic = lambda: {
            "running": True, "model_ready": True, "available": True, "models": []}
        r = rag_engine.run_rag_query(
            query="noise", case_id="c", qdrant_path="irrelevant",
            cases_dir="data/cases", evidence_id=None, asked_by="x",
            conversation_history=None)
    finally:
        rag_engine.search_chunks = real
        rag_engine.get_graph_context = real_gc
        rag_engine.generate_response_detailed = real_gen
        rag_engine.effective_context_tokens = real_eff
        rag_engine.prompt_budget_tokens = real_bud
        rag_engine.is_refusal = real_ref
        rag_engine.ollama_diagnostic = real_diag

    ps = r.get("prompt_stats") or {}
    check("retrieval asked for the widened candidate pool, not 7",
          calls.get("top_k") == rag_engine.RETRIEVAL_TOP_K, calls.get("top_k"))
    check("chunks_retrieved is the count BEFORE the floor",
          ps.get("chunks_retrieved") == 8, ps.get("chunks_retrieved"))
    check("chunks_below_floor counts what was dropped",
          ps.get("chunks_below_floor") == 8, ps.get("chunks_below_floor"))
    check("and the floor itself is reported, so the number can be explained",
          ps.get("relevance_floor") == rag_engine.RETRIEVAL_SCORE_FLOOR)
    check("retrieval_failed is False here — the search DID run",
          ps.get("retrieval_failed") is False, ps.get("retrieval_failed"))
    check("with every chunk below the floor the model saw no evidence",
          r.get("chunks_used") == [], r.get("chunks_used"))
    # THE second assertion. Pre-fix the model was consulted with a question, a
    # graph and zero excerpts, and whatever it said became the answer.
    check("the model was NOT consulted at all — there was no evidence to "
          "reason from", generated == [], f"{len(generated)} generation(s)")
    check("and the app says so, so the empty answer is explained",
          ps.get("model_not_consulted") is True, ps.get("model_not_consulted"))
    check("the answer says the search ran and matched nothing",
          "nothing in this case matched" in (r.get("answer") or "").lower(),
          (r.get("answer") or "")[:120])
    check("it distinguishes 'the floor dropped everything' from 'nothing is "
          "indexed' — the operator's next step differs",
          "none of them scored above" in (r.get("answer") or "").lower(),
          (r.get("answer") or "")[:200])
    check("it says the passages were read, so it is not a silent search",
          "were read" in (r.get("answer") or "").lower())
    check("it says nothing has been ruled out — the exculpatory direction "
          "is the dangerous one",
          "ruled out" in (r.get("answer") or "").lower(),
          (r.get("answer") or "")[-200:])
    check("no model text is filed as the response",
          (r.get("raw_llm_response") or "") == "")

    # ── F. the constant is pinned to the measurement ─────────────────────
    print("\n=== F. the floor sits in the measured gap, and stays there ===")
    f = rag_engine.RETRIEVAL_SCORE_FLOOR
    check("the floor is below the measured filler maximum "
          f"({MEASURED_FILLER_MAX})", f < MEASURED_FILLER_MAX, f)
    check("the floor is at or below the measured genuine minimum "
          f"({MEASURED_REAL_ANSWER_MIN})", f <= MEASURED_REAL_ANSWER_MIN, f)
    check("the measured ranges overlap: filler max > genuine min",
          MEASURED_FILLER_MAX > MEASURED_REAL_ANSWER_MIN,
          f"filler max {MEASURED_FILLER_MAX} > genuine min {MEASURED_REAL_ANSWER_MIN}")
    check("the floor is below both, making it a backstop not a separator",
          f < MEASURED_REAL_ANSWER_MIN and f < MEASURED_FILLER_MAX,
          f"floor {f} < min({MEASURED_REAL_ANSWER_MIN}, {MEASURED_FILLER_MAX})")
    check("retrieval is wider than the floor could ever keep from one page",
          rag_engine.RETRIEVAL_TOP_K > 1, rag_engine.RETRIEVAL_TOP_K)

    print(f"\nPASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f_ in FAIL:
        print(f"  FAIL  {f_}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
