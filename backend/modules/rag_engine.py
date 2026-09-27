from backend.modules.vector_store import search_chunks
from backend.modules.graph_builder import (
    get_graph_context, extract_entities)
from backend.modules.ollama_client import (
    generate_response, ollama_diagnostic)
from backend.dependencies import get_settings
import re
import time

SYSTEM_PROMPT = """You are the senior forensic analyst sitting next to the investigator who is working a case. You have the case's extracted evidence in front of you: files, documents, logs, emails, images and the entities linked between them.

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


def process_response(
        raw: str,
        chunks: list
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
    # Step 1: Fallback for empty / refused responses.
    #
    # This used to say "Please try rephrasing your question", which is the one
    # piece of advice guaranteed not to work: the commonest cause is a model
    # that is not installed or an Ollama that is not running, and no rewording
    # of the question installs a model. Blaming the investigator's phrasing for
    # a server-side fault is the same defect class as the ingestion bugs — a
    # confident message that is not what happened.
    if not raw or len(raw.strip()) < 20:
        n_sources = len({
            c.get('source', '') for c in chunks if c.get('source')
        }) if chunks else 0
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
    chunks = search_chunks(
        query=query,
        case_id=case_id,
        qdrant_path=qdrant_path,
        top_k=7,
        evidence_id=evidence_id
    )

    # Step 2: Get graph context
    graph_ctx = get_graph_context(
        query, case_id, cases_dir)

    # Step 3: Build evidence context
    evidence_lines = ["Evidence Excerpts:\n"]
    for i, chunk in enumerate(chunks):
        evidence_lines.append(
            f"[Excerpt {i + 1}]\n"
            f"Source: {chunk['source']} | "
            f"Confidence: {chunk['score']}\n"
            f"Content: {chunk['text']}\n"
        )
    evidence_context = "\n".join(evidence_lines)

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

    # Step 5: Assemble full prompt
    full_prompt = (
        f"{evidence_context}\n\n"
        f"{graph_ctx}\n\n"
        f"{conv_context}\n\n"
        f"Current Question: {query}\n\n"
        f"Provide your analysis based solely "
        f"on the evidence above:"
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
        raw_answer = generate_response(
            full_prompt, SYSTEM_PROMPT)

    # Step 7: Post-process the response
    (processed, cited_count,
     uncited_count) = process_response(raw_answer, chunks)

    elapsed_ms = int(
        (time.time() - start_time) * 1000)

    return {
        "answer": processed,
        "raw_llm_response": raw_answer,
        "chunks_used": chunks,
        "graph_context": graph_ctx,
        "ollama_available": diag["running"],
        "model_ready": diag["model_ready"],
        "model_diagnostic": diag,
        "cited_sentence_count": cited_count,
        "uncited_sentence_count": uncited_count,
        "response_time_ms": elapsed_ms,
        "model_used": get_settings().ollama_model
    }
