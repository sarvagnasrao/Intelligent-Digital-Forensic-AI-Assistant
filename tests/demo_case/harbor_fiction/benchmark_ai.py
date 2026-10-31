"""Opt-in local benchmark; see BENCHMARK.md before running."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IMAGE_SHA256 = "1eb86b58edfc966c49dce4637daa659e990a351d4f016e09a5abaee50ee2da8e"
QUESTION = 'What connects the request and reply about the Harbor package?'
TEXTS = {
    "NOTE.TXT": "2026-10-29 09:15\nMira: use lantern-bridge-73@example.test to request the Harbor package.\n",
    "REPLY.TXT": "2026-10-29 10:40\nTo: lantern-bridge-73@example.test\nThe Harbor package is ready for collection. Signed: Rowan.\n",
    "STATUS.TXT": "2026-10-30 08:00\nHarbor package status: collection cancelled; package remains in storage.\n",
    "GARDEN.TXT": "2026-10-30 12:00\nGarden club list: mint, beans, and watering cans.\n",
}


def local_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"}
            and parsed.username is None and parsed.password is None)


def validate_config(config):
    if config.ollama.provider != "ollama" or config.embeddings.provider != "ollama":
        raise ValueError("Both chat and embeddings must use local Ollama")
    if not all(local_url(url) for url in (config.worker.url, config.ollama.host, config.qdrant.url)):
        raise ValueError("Worker, Ollama and Qdrant URLs must be literal loopback HTTP addresses")


def validate_case(session, case_id):
    from sqlalchemy import select
    from app.artifacts.models import Artifact, ArtifactChunk
    from app.evidence.models import Evidence

    evidence = session.scalars(select(Evidence).where(Evidence.case_id == case_id)).all()
    if len(evidence) != 1 or evidence[0].removed_at is not None:
        raise ValueError("Case must contain exactly one active evidence item")
    path = Path(evidence[0].stored_path or evidence[0].source_path)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != IMAGE_SHA256:
        raise ValueError("Evidence bytes do not match the fictional Harbor image")
    artifacts = session.scalars(select(Artifact).where(Artifact.case_id == case_id)).all()
    ids = set()
    allowed = []
    for artifact in artifacts:
        name = artifact.name
        if name not in TEXTS and not (artifact.content_text or "").strip():
            continue  # Filesystem metadata is never allowed into generation.
        text = artifact.content_text or ""
        if (name not in TEXTS or text != TEXTS[name] or artifact.evidence_id != evidence[0].id
                or name in ids or not re.fullmatch(rf"ART-{case_id:04d}-[0-9]{{4,}}", artifact.artifact_id or "")
                or getattr(artifact.artifact_type, "value", artifact.artifact_type) != "file"):
            raise ValueError("Unexpected artifact in case")
        # Source paths are sent to the model; allow only the synthetic root filename.
        if artifact.source_path not in (name, "/" + name):
            raise ValueError("Unexpected artifact source path")
        ids.add(name)
        allowed.append(artifact)
    if ids != set(TEXTS) or len({a.artifact_id for a in allowed}) != 4:
        raise ValueError("Case must contain all four distinct fictional text artifacts")
    chunks = session.scalars(select(ArtifactChunk).where(ArtifactChunk.case_id == case_id)).all()
    by_id = {a.id: a for a in allowed}
    for chunk in chunks:
        artifact = by_id.get(chunk.artifact_id)
        if not artifact:
            continue
        text = artifact.content_text
        if chunk.char_start < 0 or chunk.char_end > len(text) or chunk.char_end < chunk.char_start or text[chunk.char_start:chunk.char_end] != chunk.text:
            raise ValueError("Unexpected indexed passage; rebuild the synthetic index")
    return {a.artifact_id: a for a in allowed}


def measure(worker, session, allowed, clock=time.perf_counter):
    start = clock()
    retrieved = worker._retrieve(session)
    retrieved_at = clock()
    for item in retrieved:
        context = item["context"]
        artifact = allowed.get(context.get("artifact_id"))
        if not artifact:
            raise ValueError("Retrieval returned an unexpected source")
        start_offset, end_offset = context.get("passage_start"), context.get("passage_end")
        text = TEXTS[artifact.name]
        if (type(start_offset) is not int or type(end_offset) is not int
                or not 0 <= start_offset < end_offset <= len(text)):
            raise ValueError("Retrieval returned invalid passage offsets")
        source = context.get("retrieval_source")
        if source not in {"keyword", "semantic", "keyword + semantic", "semantic + keyword", "keyword/fallback"}:
            raise ValueError("Retrieval returned an unexpected retrieval source")
        expected = {"artifact_id": artifact.artifact_id, "name": artifact.name,
                    "path": artifact.source_path, "artifact_type": "file", "content_warning": "",
                    "content_text": text[start_offset:end_offset], "passage_start": start_offset,
                    "passage_end": end_offset, "retrieval_source": source}
        if context != expected:
            raise ValueError("Retrieval returned unexpected context")
    if not retrieved:
        return {"retrieval_seconds": retrieved_at - start, "error": "No sources retrieved; generation skipped"}
    generation_start = clock()
    answer, reported = worker._generate([item["context"] for item in retrieved])
    end = clock()
    supplied = [item["context"]["artifact_id"] for item in retrieved]
    # Literal matches only, not an evaluation of whether claims are supported.
    cited = [artifact_id for artifact_id in supplied if artifact_id.casefold() in answer.casefold()]
    return {"retrieval_seconds": retrieved_at - start, "validation_seconds": generation_start - retrieved_at,
            "generation_seconds": end - generation_start,
            "total_seconds": end - start, "supplied_source_ids": supplied,
            "worker_reported_citations": reported, "answer_literal_supplied_ids": cited,
            "answer_bracket_markers": re.findall(r"\[[^\]\n]{1,100}\]", answer), "answer": answer}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="explicitly permit two model requests")
    parser.add_argument("--confirm-isolated-worker", action="store_true", help="attest independent outbound containment of worker, Ollama and benchmark, and verified local service configuration; not enforced by this script")
    parser.add_argument("--case-id", type=int, help="disposable prepared Harbor case database ID")
    args = parser.parse_args(argv)
    if not args.run:
        parser.print_help()
        return 0
    if not args.confirm_isolated_worker or not args.case_id or args.case_id < 1:
        parser.error("--run requires --case-id and --confirm-isolated-worker")
    from app.config import get_config
    from app.db.session import get_session_factory
    from app.ui.pages.ai_analysis_page import AskWorker

    validate_config(get_config())
    with get_session_factory()() as session:
        allowed = validate_case(session, args.case_id)
        worker = AskWorker(args.case_id, QUESTION, 0, provider="ollama")
        results = []
        for label in ("first (cold only if services/model were cold)", "second (warm candidate)"):
            result = measure(worker, session, allowed)
            results.append({"run": label, **result})
            if "error" in result:
                break
        print(json.dumps({"case_id": args.case_id, "model": worker.model, "question": QUESTION,
                          "runs": results}, indent=2, ensure_ascii=False))
        return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
