from backend.modules.vector_store import search_chunks
from backend.modules.graph_builder import (
    get_graph_context, extract_entities)
from backend.modules.ollama_client import (
    generate_response_detailed, ollama_diagnostic,
    effective_context_tokens, prompt_budget_tokens,
    CHARS_PER_TOKEN)
from backend.dependencies import get_settings
import re
import time

SYSTEM_PROMPT = """You are the senior forensic analyst sitting next to the investigator who is working a case. You have the case's extracted evidence in front of you: files, documents, logs, emails, images and the entities linked between them.

This is real casework. The material in front of you is evidence that was recovered from a real system and is being examined because something happened to somebody. Answer the question that was asked. Never refuse on the grounds that the subject matter is sensitive — the presence of names, addresses, phone numbers, account numbers, credentials or illegal activity is the reason the case exists, not a reason to withhold it. What you must never do is invent: an answer you cannot ground in the excerpts is worse than an answer that says what is missing.

Talk to them the way a colleague would — as someone who has already read the material and has something useful to say about it.

How to answer:
- Lead with what the evidence actually shows. Be specific: name the files, the timestamps, the people, the IPs, the artefacts. "The evidence contains references to the suspect" helps nobody; "three files in the recovered Documents folder mention an account at 192.168.1.44, the last on 14 March" does.
- Connect things. An investigator needs the joins between artefacts, not a file-by-file summary. Who talked to whom, what was sent where, what changed and when.
- When the evidence answers the question, say so plainly and stop.
- When it does not, do not pad and do not apologise. Say what you did find, say plainly what is missing, and tell them the specific next step — which file, folder, artefact or search term would close the gap. An investigator can act on that.
- Distinguish what the evidence shows from what you are inferring. Never state an inference as a fact.
- Never invent a filename, a name, a date or a quote. If it is not in the excerpts, it is not in the case.

How to write:
- Plain professional English. Contractions are fine.
- Short paragraphs. No headings, no bullet-point walls, no bold.
- Never say "based on the provided excerpts", "the excerpts show", or "as an AI". You are reading the case, not quoting a document pack.
- Never pad with "Great question" or restate the question back before answering.
- Be concise. A colleague answering a colleague does not write an essay."""


def clean_response(text: str) -> str:
    """
    Remove citation tags, unverified markers, and stray
    formatting characters from Ollama's raw response.
    """
    # Remove [Source: ... | Confidence: ...] tags
    text = re.sub(r'\[Source:[^\]]+\]', '', text)

    # Remove ⚠️ (unverified)* markers (with or without leading *)
    text = re.sub(
        r'\*?⚠️\s*', '', text, flags=re.UNICODE)
    text = re.sub(
        r'\(unverified\)\*?', '', text, flags=re.IGNORECASE)

    # Remove (Excerpt N) / (Excerpts N-M) refs
    text = re.sub(
        r'\(Excerpts?\s+[\d,\s\u2013\-]+\)',
        '', text, flags=re.IGNORECASE)

    # Remove leftover inline asterisks used as emphasis markers
    # (single * or ** wrapping a sentence) but keep bullet points
    text = re.sub(r'(?<!\*)\*(?!\*)', '', text)

    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)

    # Collapse 3+ newlines to double
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def format_paragraphs(text: str) -> str:
    """
    Make the response readable:
    - Preserve existing paragraph breaks
    - Split long paragraphs (>400 chars) at sentence boundaries
      to create natural reading breaks every 2-3 sentences
    - Preserve list items (lines starting with * or -)
    """
    # Split into existing paragraphs / blocks
    blocks = re.split(r'\n{2,}', text)
    output_blocks = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Keep short blocks or list-item blocks as-is
        if len(block) <= 400 or re.match(r'^[\*\-]', block):
            output_blocks.append(block)
            continue

        # Split long blocks into sentences, then group 2-3 per paragraph
        sentences = re.split(r'(?<=[.!?])\s+', block)
        group = []
        group_len = 0
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            group.append(sent)
            group_len += len(sent)
            # Break paragraph every ~2-3 sentences or ~300 chars
            if len(group) >= 3 or group_len >= 300:
                output_blocks.append(' '.join(group))
                group = []
                group_len = 0
        if group:
            output_blocks.append(' '.join(group))

    return '\n\n'.join(output_blocks)


def build_sources_block(chunks: list) -> str:
    """
    Build a clean sources footer listing all unique files
    that were retrieved from Qdrant for this query.
    """
    if not chunks:
        return ''

    # Deduplicate while preserving order
    seen = set()
    unique_sources = []
    for c in chunks:
        src = c.get('source', '')
        # Strip leading UUID prefix (e.g. "abc123_filename.txt" → "filename.txt")
        display = re.sub(r'^[0-9a-f\-]{36}_', '', src)
        if display and display not in seen:
            seen.add(display)
            unique_sources.append(display)

    if not unique_sources:
        return ''

    return '\n\n---\n📎 **Sources:** ' + ', '.join(unique_sources)


ELISION_MARKER_ALLOWANCE = 96
# Worst-case length of the elision marker _elide() appends, reserved per
# excerpt so that the assembled prompt lands on the estimate rather than
# overshooting it and tripping the clamp.

EVIDENCE_NOTE_MARKER = "Evidence caveat:"
# Appended to an answer when retrieval matched more than the context window
# can carry. The frontend splits on this and renders it as a distinct block,
# because a caveat on the reliability of a finding should not read as part
# of the finding.


def _elide(text: str, max_chars: int) -> tuple[str, int]:
    """
    Cut `text` to max_chars, saying so at the cut.

    The marker is the point. A silent slice leaves the model -- and the
    investigator reading the answer -- unable to tell omitted evidence from
    absent evidence, which is how a partial retrieval reads as a complete one.
    """
    if len(text) <= max_chars:
        return text, 0
    kept = text[:max_chars].rstrip()
    # Do not end on a half word.
    cut = kept.rfind(" ")
    if cut > max_chars * 0.6:
        kept = kept[:cut]
    dropped = len(text) - len(kept)
    return (f"{kept}\n[… {dropped:,} characters of this excerpt "
            f"omitted to fit the model's context window …]"), dropped


# How many chunks to retrieve, and the cosine score below which a retrieved
# chunk is treated as not answering the question at all.
#
# BOTH NUMBERS ARE MEASURED, NOT CHOSEN. Qdrant returned `top_k=7` chunks for
# *every* query, unconditionally, and `build_prompt` divided the allowance
# between all seven. A query of "hi" against a 6 MB corpus came back with
# seven chunks scoring 0.134-0.138, and the model was asked to answer from
# them: a real question about a suspect got the same seven filler excerpts.
# Retrieval scoring exists precisely to be thresholded, and it was not.
#
# The scores actually recorded in `query_logs.chunks_used` on this corpus
# (12 queries, ranked within each):
#
#     "hi" / "hello"                 0.134 - 0.138   (7 chunks)
#     "what is duck?"                0.060 - 0.076
#     suspect email / phone          0.094 - 0.107
#     operators and hosts            0.465 - 0.476
#     suspect behind darknode.io     0.395 - 0.476
#
# There is a GAP between 0.138 and 0.395 with nothing in it, and the floor
# sits in that gap rather than on a round number. Two caveats, stated so the
# next person does not treat this as settled:
#
#   * the sample is small and several entries are near-duplicates of "hi";
#   * cosine similarity is not calibrated across embedding models, so this
#     threshold is a property of `all-MiniLM-L6-v2` over this corpus and would
#     need re-measuring if the embedder ever changes (it must not change
#     casually anyway — see B15, 384-dim is load-bearing for every existing
#     collection).
#
# It is exposed in `prompt_stats` so a surprising answer can be explained
# rather than guessed at.
RETRIEVAL_TOP_K = 14
RETRIEVAL_SCORE_FLOOR = 0.25


def _unanswered(answer: str,
                *,
                retrieval_failed: bool,
                retrieval_error: str | None,
                chunks_retrieved: int,
                chunks_below_floor: int,
                graph_ctx: str,
                elapsed_ms: int) -> dict:
    """A result dict for a question that was never put to the model.

    Both early returns in `run_rag_query` are this shape, and they exist for the
    same reason: there is no evidence in hand, so there is nothing to ground an
    answer in, and calling the model anyway produces prose that *looks* like a
    finding. The honest statement is made here, in the app's own voice, and the
    model is not asked at all.

    This is also the cheap path. A grounded answer costs a 13,000-token prefill
    on CPU — measured at 165 s — and this state is reached by exactly the
    questions that have nothing to retrieve.
    """
    diag = ollama_diagnostic()
    return {
        "answer": answer,
        "raw_llm_response": "",
        "chunks_used": [],
        "graph_context": graph_ctx,
        "prompt_stats": {
            "chunks_retrieved": chunks_retrieved,
            "chunks_below_floor": chunks_below_floor,
            "relevance_floor": RETRIEVAL_SCORE_FLOOR,
            "retrieval_failed": retrieval_failed,
            "retrieval_error": retrieval_error,
            "excerpts": 0,
            "excerpts_trimmed": 0,
            "chars_elided": 0,
            "graph_trimmed": False,
            "sources": 0,
            "context_tokens": effective_context_tokens(),
            "budget_tokens": prompt_budget_tokens(),
            "estimated_tokens": 0,
            "model_not_consulted": True,
        },
        "refused": False,
        "ollama_available": diag.get("running", False),
        "model_ready": diag.get("model_ready", False),
        "model_diagnostic": diag,
        "cited_sentence_count": 0,
        "uncited_sentence_count": 0,
        "response_time_ms": elapsed_ms,
        "model_used": None,
    }


def apply_relevance_floor(chunks: list,
                          floor: float = RETRIEVAL_SCORE_FLOOR) -> tuple[list, int]:
    """Drop retrieved chunks that do not answer the question.

    Returns (kept, dropped_count).

    A chunk with no `score` key is KEPT. The floor is a statement about a
    measurement; refusing to act when there is nothing to compare is the
    correct behaviour, and silently discarding every chunk from a caller that
    does not supply scores would turn a missing field into "no evidence".
    """
    if not chunks:
        return [], 0
    kept, dropped = [], 0
    for c in chunks:
        s = c.get("score")
        if isinstance(s, (int, float)) and s < floor:
            dropped += 1
            continue
        kept.append(c)
    return kept, dropped


def build_prompt(query: str,
                 chunks: list,
                 graph_ctx: str,
                 conv_context: str,
                 budget_tokens: int) -> tuple[str, dict]:
    """
    Assemble a prompt that fits the model's context window.

    The allowance is spent per excerpt, not per total. top_k exists so that
    different chunks can cover different parts of the question; handing the
    whole allowance to the first chunk would answer a narrower question than
    retrieval just answered, and trimming the assembled string from the end
    would drop the last excerpts entirely. Spreading it means every retrieved
    excerpt contributes something and none is silently lost.

    Three classes of text, and they are not treated alike:

      * the question, the conversation memory and the closing instruction are
        protected -- the prompt is useless without them, so they are measured
        first and never trimmed;
      * the entity graph yields, because it is a ranked list and a truncated
        one is still a useful one;
      * the excerpts share whatever is left, evenly.

    The graph is trimmed *before* assembly rather than by a clamp on the
    finished string. Clamping the assembled prompt keeps its front, and the
    question is at its back, so a clamp silently answers a different question
    than the one that was asked -- which is the same class of failure as
    overflowing it, just quieter.

    Returns (prompt, stats).
    """
    stats = {
        "budget_tokens": budget_tokens,
        "context_tokens": effective_context_tokens(),
        "excerpts": len(chunks),
        "excerpts_trimmed": 0,
        "chars_elided": 0,
        "estimated_tokens": 0,
        "graph_trimmed": False,
    }

    def to_chars(tokens: float) -> int:
        return max(64, int(tokens * CHARS_PER_TOKEN))

    def to_tokens(text: str) -> int:
        return int(len(text) / CHARS_PER_TOKEN)

    head = "Evidence Excerpts:\n"
    instruction = (f"Current Question: {query}\n\n"
                   f"Provide your analysis based solely "
                   f"on the evidence above:")

    # ---- protected: reserved before anything else is allowed to spend ----
    protected = [p for p in (conv_context, instruction) if p]
    budget_left = budget_tokens - to_tokens(head)
    for part in protected:
        budget_left -= to_tokens(part)
        budget_left -= 2  # the "\n\n" join

    # ---- the graph yields first ----
    # Up to a quarter of what remains, so a large graph cannot crowd out the
    # evidence, which is the material the answer is actually made of.
    if graph_ctx:
        graph_cap = to_chars(max(0, budget_left) // 4)
        graph_ctx, graph_dropped = _elide(graph_ctx, graph_cap)
        if graph_dropped:
            stats["graph_trimmed"] = True
            stats["chars_elided"] += graph_dropped
        budget_left -= to_tokens(graph_ctx)

    if not chunks:
        tail = "\n\n".join([p for p in (graph_ctx,) + tuple(protected)
                            if p])
        stats["estimated_tokens"] = to_tokens(head + "\n" + tail)
        return head + "\n" + tail, stats

    # ---- per-excerpt headers are a fixed cost, charged before the split ----
    headers = [
        (f"[Excerpt {i + 1}]\n"
         f"Source: {chunk.get('source', '')} | "
         # Labelled "Relevance", not "Confidence". The value is a raw cosine
         # similarity from the embedder, which is a RANKING, not a probability --
         # it is not calibrated across embedding models, and 0.42 does not mean
         # "42% likely". Calling it confidence invited the model to reason
         # probabilistically about a number carrying no such meaning.
         f"Relevance: {chunk.get('score', '')}\n"
         f"Content: ")
        for i, chunk in enumerate(chunks)
    ]
    budget_left -= sum(to_tokens(h) for h in headers)
    # Room for the elision marker on every excerpt that gets trimmed, and for
    # the newlines between blocks. Charged up front because a budget that
    # forgets the markers comes in under the real prompt, trips the check
    # below, and pays for a bookkeeping error by discarding good context.
    budget_left -= (len(chunks) * (ELISION_MARKER_ALLOWANCE + 2)
                    // CHARS_PER_TOKEN)

    # ---- the evidence shares what is left ----
    share = max(64, budget_left)
    per_excerpt_chars = to_chars(share // len(chunks))

    lines = []
    for i, chunk in enumerate(chunks):
        body, dropped = _elide(
            chunk.get("text", ""), per_excerpt_chars)
        if dropped:
            stats["excerpts_trimmed"] += 1
            stats["chars_elided"] += dropped
        lines.append(f"{headers[i]}{body}\n")

    tail = "\n\n".join([p for p in (graph_ctx,) + tuple(protected) if p])
    prompt = head + "\n" + "\n".join(lines) + "\n" + tail
    stats["estimated_tokens"] = to_tokens(prompt)

    # Belt and braces. The allocation above should already have fitted; this
    # only trips if the ratio under-counted, and it then sheds evidence --
    # never the question, which by now is the last thing in the string and
    # the one thing that must survive.
    ceiling = to_chars(budget_tokens)
    if len(prompt) > ceiling:
        keep_tail = min(len(tail), max(256, to_chars(budget_tokens // 3)))
        room = max(0, ceiling - keep_tail - len(head) - 200)
        shed = prompt[len(head):len(head) + room] if room else ""
        prompt = (
            head
            + "\n[Context window exhausted — part of the excerpt list "
            "was dropped entirely to fit the model's window. The findings "
            "below are drawn from a smaller portion of the evidence than "
            "retrieval matched.]\n"
            + shed
            + "\n" + (tail[-keep_tail:] if keep_tail else instruction))
        stats["estimated_tokens"] = to_tokens(prompt)
        stats["excerpts_dropped"] = True

    return prompt, stats


REFUSAL_PATTERNS = (
    "i can't assist", "i cannot assist", "i can't help",
    "i cannot help", "i'm not able to", "i am not able to",
    "i won't be able to", "i'm unable to", "i am unable to",
    "i can't provide", "i cannot provide", "i can't comply",
    "i cannot comply", "as an ai", "i'm sorry, but",
    "i am sorry, but", "i must decline", "i'd rather not",
)


def is_refusal(text: str) -> bool:
    """
    Did the model decline, rather than answer?

    A refusal is not a wrong answer, it is a missing one, and it must not be
    filed as a response. The detector matches the opening of the reply: a
    refusal is a statement about what the model will do, and it leads. The
    whole reply is not required to match, because a model that declines and
    then waffles is still declining, while a legitimate forensic answer that
    happens to contain the word later is not.
    """
    if not text:
        return False
    head = text.strip().lower()[:220]
    return any(p in head for p in REFUSAL_PATTERNS)


def process_response(
        raw: str,
        chunks: list,
        prompt_stats: dict = None
) -> tuple[str, int, int]:
    """
    New simplified post-processing pipeline:

    1. Fallback if response is empty / too short
    2. Clean: remove citation tags, ⚠️ markers, stray asterisks
    3. Format: split into readable paragraphs
    4. Append sources block (additive, not destructive)

    Returns (processed_response, cited_count, uncited_count).
    cited_count = number of unique sources retrieved.
    uncited_count = 0 (we no longer mark individual sentences).
    """
    n_sources = len({
        c.get('source', '') for c in chunks if c.get('source')
    }) if chunks else 0

    # Step 0: A refusal is a missing answer, not a wrong one.
    #
    # Filing "I can't assist with that." as the response is the same defect
    # class as the ingestion bugs and as B21: a true-shaped string standing
    # in for something that did not happen. The investigator sees a sentence
    # in the assistant's voice, the sources footer is appended underneath it,
    # and the exchange looks answered. It is also the most misleading possible
    # outcome here, because it reads as a judgement about the question when
    # the cause is upstream -- the model was asked to reason about evidence
    # that the context window had already thrown away, so it declined to
    # invent it.
    if is_refusal(raw):
        ctx = effective_context_tokens()
        if prompt_stats and prompt_stats.get("chars_elided"):
            return (
                "The model declined to answer rather than return a "
                f"finding. The {n_sources} matching "
                f"source{'s' if n_sources != 1 else ''} for this question "
                f"exceeded what a {ctx:,}-token context window can hold, so "
                "the evidence was cut before the model saw it — it was asked "
                "to be specific about material it was never given, and "
                "declined to invent it. This is a capacity limit, not a "
                "judgement about the question. Narrow the question to one "
                "entity or one artefact, or point the assistant at a single "
                "piece of evidence.", 0, 0)
        return (
            "The model declined to answer rather than return a finding, "
            "and no analysis was produced. Nothing in this exchange "
            "constitutes a result about the case. Re-ask against a single "
            "piece of evidence, or use System Health to check the model.",
            0, 0)

    # Step 1: Fallback for empty / too-short responses.
    #
    # This used to say "Please try rephrasing your question", which is the one
    # piece of advice guaranteed not to work: the commonest cause is a model
    # that is not installed or an Ollama that is not running, and no rewording
    # of the question installs a model. Blaming the investigator's phrasing for
    # a server-side fault is the same defect class as the ingestion bugs — a
    # confident message that is not what happened.
    if not raw or len(raw.strip()) < 20:
        if n_sources:
            fallback = (
                "The model returned an empty response for this question. "
                f"The search did match {n_sources} "
                f"source{'s' if n_sources != 1 else ''}, so the evidence was "
                "found — the model produced nothing usable. This is a model "
                "or Ollama problem, not a problem with your question. "
                "Check System Health, then try again."
            )
        else:
            fallback = (
                "Nothing in this case matched that question, and the model "
                "returned no analysis. Try terms you would expect to find in "
                "the evidence itself — a name, a domain, an IP, a filename or "
                "a phrase from a recovered document — or ingest more evidence "
                "for this case."
            )
        return fallback, 0, 0

    # Step 2: Clean noise from the raw response
    cleaned = clean_response(raw)

    if not cleaned or len(cleaned) < 20:
        fallback = (
            "The model's reply contained nothing usable once cleaned of "
            "citation tags. This is a model or Ollama problem, not a problem "
            "with your question — check System Health and try again."
        )
        return fallback, 0, 0

    # Step 3: Format into readable paragraphs
    formatted = format_paragraphs(cleaned)

    # Step 4: Append sources footer
    sources_block = build_sources_block(chunks)
    final = formatted + sources_block

    # Count unique sources as "cited" for the metadata field
    cited_count = len(set(
        c.get('source', '') for c in chunks if c.get('source')
    ))
    return final, cited_count, 0


def run_rag_query(
        query: str,
        case_id: str,
        qdrant_path: str,
        cases_dir: str,
        evidence_id: str = None,
        asked_by: str = "investigator",
        conversation_history: list = None
) -> dict:
    """
    Full RAG pipeline with optional conversation memory.
    conversation_history is a list of dicts:
      [{"role": "investigator",
        "question": "...",
        "answer": "..."}, ...]
    Maximum 5 most recent exchanges are included.
    Returns dict with answer and metadata for QueryLog.
    """
    start_time = time.time()

    # Step 1: Retrieve chunks from Qdrant
    #
    # `search_chunks` raises on a real fault rather than returning [], because
    # "the search failed" and "the search matched nothing" are opposite findings
    # and this is where that matters most: the second one is what tells an
    # investigator the evidence is clean. So the fault is caught here, named,
    # and returned as an answer that says nothing whatever about the case —
    # and the caller can see which happened, because `retrieval_failed` is
    # reported alongside `chunks_retrieved`.
    retrieval_error = None
    try:
        chunks = search_chunks(
            query=query,
            case_id=case_id,
            qdrant_path=qdrant_path,
            top_k=RETRIEVAL_TOP_K,
            evidence_id=evidence_id
        )
    except Exception as e:
        chunks = []
        retrieval_error = f"{type(e).__name__}: {e}"

    # Retrieval hands back `RETRIEVAL_TOP_K` candidates whether or not they are
    # relevant. The floor is applied HERE rather than inside build_prompt,
    # because it changes what "no evidence matched" means downstream — keeping
    # the pre-floor count is what lets prompt_stats tell "retrieved nothing"
    # apart from "retrieved 14 and kept none", which are different findings.
    chunks_retrieved = len(chunks)
    chunks, chunks_below_floor = apply_relevance_floor(chunks)

    if retrieval_error:
        # Deliberately NOT phrased as an absence of evidence, and deliberately
        # not asking the investigator to reword the question — no rewording
        # repairs a locked index or a dead embedder.
        return _unanswered(
            "The search could not be run, so this is not an answer "
            "about the case — nothing was retrieved either way. The "
            "evidence index did not respond, and the reason was: "
            f"{retrieval_error}\n\n"
            "Nothing in this case has been checked against evidence, and "
            "nothing in it has been ruled out. Check System Health, then "
            "ask the question again.",
            retrieval_failed=True,
            retrieval_error=retrieval_error,
            chunks_retrieved=0,
            chunks_below_floor=0,
            graph_ctx="",
            elapsed_ms=int((time.time() - start_time) * 1000),
        )

    if not chunks:
        # The search RAN and found nothing worth showing the model. This is the
        # other half of B30, and it is the half that was easy to miss: the
        # honest "nothing matched" message used to live inside the
        # empty/too-short-response branch of `process_response`, so it was only
        # reachable if the model happened to return nothing. Given a question,
        # an entity graph and no excerpts, a chat model will happily produce a
        # paragraph — and the investigator would have read it as a finding
        # about the case, with `chunks_used: []` as the only evidence
        # otherwise. The app's own statement of what it found must not depend
        # on the model's behaviour.
        #
        # The two reasons are named separately, because they are different
        # situations and the operator's next step differs: an empty collection
        # means nothing is indexed here, while a floor that dropped everything
        # means plenty is indexed and none of it is about this question.
        if chunks_retrieved == 0:
            why = (
                "No indexed evidence was available to search. Either this "
                "case has nothing ingested yet, or the question was scoped to "
                "a single piece of evidence that has not been indexed."
            )
        else:
            why = (
                f"Retrieval examined {chunks_retrieved} passages and none of "
                f"them scored above the {RETRIEVAL_SCORE_FLOOR} relevance "
                "floor, so none were close enough to this question to be worth "
                "putting in front of the model. The passages exist and were "
                "read — they simply are not about this."
            )
        return _unanswered(
            "Nothing in this case matched that question, so there is no "
            "evidence to answer it from. " + why + "\n\n"
            "The model was not asked. Try terms you would expect to find in "
            "the evidence itself — a name, a domain, an IP, a filename or a "
            "phrase from a recovered document — or ingest more evidence for "
            "this case.\n\n"
            "This is a statement about the search, not a finding about the "
            "case: nothing here has been examined, and nothing has been ruled "
            "out.",
            retrieval_failed=False,
            retrieval_error=None,
            chunks_retrieved=chunks_retrieved,
            chunks_below_floor=chunks_below_floor,
            graph_ctx="",
            elapsed_ms=int((time.time() - start_time) * 1000),
        )

    # Step 2: Get graph context
    graph_ctx = get_graph_context(
        query, case_id, cases_dir)

    # Step 3: Evidence is budgeted inside build_prompt, not assembled whole.
    # (Assembled whole, seven 30,000-character chunks produced a 212,000
    # character prompt against a 4,096-token model. Ollama accepted it,
    # truncated it without saying so, and kept only the first 5 tokens and
    # the last 4,091 -- which is the question without any of the evidence.)
    evidence_context = ""

    # Step 4: Build conversation context from history
    conv_context = ""
    if conversation_history:
        # Cap at last 5 exchanges
        recent = conversation_history[-5:]
        conv_lines = [
            "\nPrevious exchanges in this investigation session:"
        ]
        for i, exchange in enumerate(recent, 1):
            conv_lines.append(f"\n[Exchange {i}]")
            conv_lines.append(
                f"Investigator: {exchange.get('question', '')}"
            )
            raw_answer = exchange.get('answer', '')
            if len(raw_answer) > 500:
                conv_lines.append(
                    f"Assistant: {raw_answer[:500]}..."
                )
            else:
                conv_lines.append(
                    f"Assistant: {raw_answer}"
                )
        conv_context = '\n'.join(conv_lines)

    # Step 5: Assemble a prompt that fits the context window.
    budget = prompt_budget_tokens()
    full_prompt, prompt_stats = build_prompt(
        query=query,
        chunks=chunks,
        graph_ctx=graph_ctx,
        conv_context=conv_context,
        budget_tokens=budget
    )

    # Step 6: Call Ollama.
    #
    # Gated on the model being present, not merely on the daemon answering.
    # "Ollama is up" and "there is a model to talk with" are separate facts:
    # /api/tags returns 200 with an empty list on a machine that never pulled
    # a model, so the old is_ollama_running() check passed and the request went
    # on to 404. One diagnostic is taken here and reused in the result, rather
    # than probing twice and risking the two answers disagreeing.
    diag = ollama_diagnostic()
    gen = {}
    if not diag["running"]:
        raw_answer = (
            f"⚠️ Ollama is not running, so there is no model to answer "
            f"with. Start it with `ollama serve` and ask again — your "
            f"question has not been answered."
        )
    elif not diag["model_ready"]:
        raw_answer = (
            f"⚠️ {diag['reason']} Nothing was searched, so your question "
            f"has not been answered."
        )
    else:
        gen = generate_response_detailed(
            full_prompt, SYSTEM_PROMPT)
        raw_answer = gen["text"]

    # Step 6b: Verify the budget against ground truth.
    #
    # The char-per-token ratio above is an estimate, and the consequence of
    # being wrong is silent, so the estimate is not trusted. Ollama returns
    # prompt_eval_count with the response -- the number of tokens it actually
    # consumed. If that reached the window, Ollama truncated the prompt and
    # the answer came from the tail of the question with the evidence gone,
    # which is the failure this whole path exists to prevent. Rather than
    # ship that, halve the evidence allowance and ask once more.
    retried = False
    if gen.get("saturated"):
        retried = True
        smaller = max(256, budget // 2)
        full_prompt, prompt_stats = build_prompt(
            query=query,
            chunks=chunks,
            graph_ctx=graph_ctx,
            conv_context=conv_context,
            budget_tokens=smaller
        )
        prompt_stats["retry_after_overflow"] = True
        gen = generate_response_detailed(
            full_prompt, SYSTEM_PROMPT)
        raw_answer = gen["text"]

    prompt_stats["retried_after_overflow"] = retried
    prompt_stats["prompt_eval_count"] = gen.get("prompt_eval_count")
    prompt_stats["still_overflowed"] = bool(gen.get("saturated"))
    prompt_stats["chunks_retrieved"] = chunks_retrieved
    prompt_stats["chunks_below_floor"] = chunks_below_floor
    prompt_stats["relevance_floor"] = RETRIEVAL_SCORE_FLOOR
    prompt_stats["retrieval_failed"] = False

    # Step 7: Post-process the response
    (processed, cited_count,
     uncited_count) = process_response(
        raw_answer, chunks, prompt_stats)

    if prompt_stats.get("chars_elided"):
        # Plain text, not markdown: the transcript is rendered with
        # white-space: pre-wrap and no inline styling, so asterisks or
        # underscores would reach the investigator as literal characters.
        # The frontend splits on this marker and renders it as a caveat.
        processed += (
            f"\n\n{EVIDENCE_NOTE_MARKER} {prompt_stats['excerpts_trimmed']}"
            f" of {prompt_stats['excerpts']} retrieved excerpts were trimmed"
            f" to fit the model's "
            f"{prompt_stats['context_tokens']:,}-token context window "
            f"({prompt_stats['chars_elided']:,} characters not shown to the "
            f"model). This answer covers only the excerpts above.")

    elapsed_ms = int(
        (time.time() - start_time) * 1000)

    return {
        "answer": processed,
        "raw_llm_response": raw_answer,
        "chunks_used": chunks,
        "graph_context": graph_ctx,
        "prompt_stats": prompt_stats,
        "refused": is_refusal(raw_answer),
        "ollama_available": diag["running"],
        "model_ready": diag["model_ready"],
        "model_diagnostic": diag,
        "cited_sentence_count": cited_count,
        "uncited_sentence_count": uncited_count,
        "response_time_ms": elapsed_ms,
        "model_used": get_settings().ollama_model
    }
