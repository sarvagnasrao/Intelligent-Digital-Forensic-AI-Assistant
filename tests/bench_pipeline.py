#!/usr/bin/env python3
"""
Isolated pipeline benchmark — the measurement instrument for the hardening work.

Why this file exists
--------------------
Every claim of the form "this made ingestion faster" or "this improved
retrieval" needs a *before* number produced by the same instrument as the
*after* number. Without one, an optimisation is a story. So this script:

  1. Builds a fresh, fully isolated environment in a temp directory
     (its own SQLite DB, its own cases dir, its own Qdrant dir) and points the
     real backend settings at it. The running server's database and the real
     case data under data/cases are NEVER touched.
  2. Writes a small DETERMINISTIC corpus with known ground truth (no random
     amounts, no random names) plus a labelled query set.
  3. Runs the REAL ingestion pipeline (`run_ingestion_with_progress`) per file,
     timing every stage it can observe.
  4. Runs the REAL retrieval path (`search_chunks`) for each labelled query and
     records rank/score of the expected source, so Recall@k is measurable.
     With --llm it also runs the full `run_rag_query` (needs Ollama) and
     records answer latency and whether the query abstained.

It is deliberately dependency-free: stdlib + the project's own modules.

Usage (from the repository root):
    venv\\Scripts\\python.exe tests/bench_pipeline.py
    venv\\Scripts\\python.exe tests/bench_pipeline.py --llm
    venv\\Scripts\\python.exe tests/bench_pipeline.py --keep --out bench.json

Exit code is 0 if the run completed (regardless of measured quality), non-zero
only if the harness itself could not run. Quality numbers are data, not
pass/fail — that is the point of a baseline.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ---------------------------------------------------------------------------
# Deterministic corpus
# ---------------------------------------------------------------------------
# Ground truth is stated once, here, and referenced by the query set below so
# the two cannot drift apart.

HASH_9F86 = ("9f86d081884c7d659a2feaa0c55ad015"
             "a3bf4f1b2b0b822cd15d6c15b0f00a08")
EGRESS_IP = "203.0.113.77"
EGRESS_PORT = "8443"
ACCOUNT = "ACC-4471-9930"

CORPUS = {
    "firewall_2025-03-14.log": (
        "sensor=fw-edge-01 log=conntrack\n"
        "2025-03-14T02:11:07Z src=198.51.100.23 dst=10.0.4.19 dport=443 "
        "proto=TCP action=ALLOW bytes=184320\n"
        "2025-03-14T02:13:44Z src=10.0.4.19 dst=203.0.113.77 dport=8443 "
        "proto=TCP action=ALLOW bytes=4980736000\n"
        "2025-03-14T02:41:12Z src=10.0.4.19 dst=203.0.113.77 dport=8443 "
        "proto=TCP action=ALLOW bytes=512000\n"
        "2025-03-14T03:02:01Z src=203.0.113.77 dst=10.0.4.19 dport=22 "
        "proto=TCP action=DENY bytes=0\n"
        "2025-03-14T07:55:30Z src=10.0.4.19 dst=10.0.4.5 dport=445 "
        "proto=TCP action=ALLOW bytes=2048\n"
    ),
    "email_thread.txt": (
        "From: m.blackwell@vortexcorp.com\n"
        "To: c.rivera@phantomlabs.net\n"
        "Date: Fri, 14 Mar 2025 06:02:00 +0000\n"
        "Subject: Re: final batch\n"
        "\n"
        "Carlos - the overnight job finished clean. We moved 4.7 GB to the "
        "darknode.io staging host between 02:13 and 02:45. The archive hash "
        "is " + HASH_9F86 + ". Wipe the local copies once you have confirmed "
        "the checksum on your side. Do not route this through the corporate "
        "mail relay again.\n"
        "- Marcus\n"
    ),
    "transactions.csv": (
        "date,account,amount_usd,beneficiary,reference\n"
        "2025-03-12,ACC-4471-9930,18500.00,Phantom Labs LLC,INV-8841\n"
        "2025-03-12,ACC-4471-9930,4200.00,Phantom Labs LLC,INV-8842\n"
        "2025-03-13,ACC-9012-3310,900.00,Havenport Couriers,INV-8843\n"
    ),
    "witness_statement.txt": (
        "Statement of Diana Sokolov, taken 16 March 2025.\n"
        "\n"
        "On the afternoon of 14 March 2025 I was at the loading bay on "
        "Havenport Road. Priya Mehta was present and signed for the delivery. "
        "A white van with a Havenport Couriers logo left at about 17:40. I did "
        "not see who was driving.\n"
    ),
}

# (query, expected_source_filename, kind)
# kind is our label for why the query is interesting: 'semantic' should be
# findable by meaning, 'identifier' is an exact string (IP/hash/account) where
# dense-only retrieval is expected to be weakest.
QUERIES = [
    ("How much data was transferred to " + EGRESS_IP +
     " and on which port?", "firewall_2025-03-14.log", "semantic"),
    (EGRESS_IP, "firewall_2025-03-14.log", "identifier"),
    ("What is the SHA-256 hash of the archive sent to darknode.io?",
     "email_thread.txt", "semantic"),
    (HASH_9F86, "email_thread.txt", "identifier"),
    ("Which account received 18500 dollars?", "transactions.csv", "semantic"),
    (ACCOUNT, "transactions.csv", "identifier"),
    ("Who witnessed the delivery on Havenport Road on 14 March 2025?",
     "witness_statement.txt", "semantic"),
    # A negative control: the lexical gate should reject this before the model
    # is consulted. It is not a quality metric, it is a guardrail check.
    ("What is the capital of Finland?", None, "negative"),
]

TOP_K = 14  # must match rag_engine.RETRIEVAL_TOP_K for the eval to mean anything


def _make_env(root: str):
    """Point the backend at an isolated temp environment. MUST run before any
    backend import: backend.dependencies.get_settings() is lru_cached and
    backend.database builds its engine at import time."""
    db_path = os.path.join(root, "bench.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path
    os.environ["CASES_DIR"] = os.path.join(root, "cases")
    os.environ["QDRANT_DIR"] = os.path.join(root, "qdrant")
    os.environ["DEBUG"] = "False"


def _seed_corpus(root: str):
    """Write the corpus and a case/evidence row per file."""
    from backend.database import init_db, SessionLocal
    from backend import models
    import uuid

    init_db()
    db = SessionLocal()
    case_id = str(uuid.uuid4())
    db.add(models.Case(
        id=case_id,
        case_name="BENCH baseline",
        case_number=None,
        status="Active",
        created_by="bench",
    ))
    db.commit()

    ev_dir = os.path.join(root, "cases", case_id, "evidence")
    os.makedirs(ev_dir, exist_ok=True)

    evidence = []
    for filename, text in CORPUS.items():
        ev_id = str(uuid.uuid4())
        stored = os.path.join(ev_dir, f"{ev_id}_{filename}")
        data = text.encode("utf-8")
        with open(stored, "wb") as f:
            f.write(data)
        db.add(models.Evidence(
            id=ev_id,
            case_id=case_id,
            filename=filename,
            original_filename=filename,
            file_type=os.path.splitext(filename)[1].lstrip(".") or "txt",
            file_size_bytes=len(data),
            file_path=stored,
            ingested_by="bench",
            status="Uploaded",
        ))
        db.commit()
        evidence.append((ev_id, filename, stored))
    db.close()
    return case_id, evidence


def _run_ingestion(case_id, evidence):
    from backend.ingestion import run_ingestion_with_progress

    results = []
    for ev_id, filename, path in evidence:
        marks = []

        def cb(cid, jid, eid, percent, step, _m=marks):
            _m.append((round(time.time() - t0, 3), percent, step))

        t0 = time.time()
        err = None
        try:
            run_ingestion_with_progress(
                evidence_id=ev_id,
                case_id=case_id,
                file_path=path,
                filename=filename,
                job_id=None,
                progress_callback=cb,
            )
        except Exception as e:  # noqa: BLE001 - recorded, not swallowed
            err = f"{type(e).__name__}: {e}"
        elapsed = round(time.time() - t0, 3)
        results.append({
            "filename": filename,
            "elapsed_s": elapsed,
            "error": err,
            "progress": marks,
        })
    return results


def _retrieval_eval(case_id):
    """Evaluate BOTH dense (search_chunks) and hybrid (retrieve) retrieval.
    Returns rows with both sets of metrics for comparison. Baseline keys are
    preserved under "dense"; hybrid results are under "hybrid"."""
    from backend.modules.vector_store import search_chunks, case_qdrant_path
    from backend.modules.rag_engine import retrieve
    qpath = case_qdrant_path(case_id)

    rows = []
    for query, expected, kind in QUERIES:
        # Dense branch (baseline)
        t0 = time.time()
        err_dense = None
        try:
            dense_hits = search_chunks(query=query, case_id=case_id,
                                       qdrant_path=qpath, top_k=TOP_K)
        except Exception as e:  # noqa: BLE001
            dense_hits, err_dense = [], f"{type(e).__name__}: {e}"
        dense_ms = round((time.time() - t0) * 1000, 1)

        dense_rank, dense_score = None, None
        if expected:
            for i, h in enumerate(dense_hits, 1):
                if h.get("source") == expected:
                    dense_rank, dense_score = i, h.get("score")
                    break

        # Hybrid branch (Stage 4.1)
        t0 = time.time()
        err_hybrid = None
        try:
            hybrid_hits = retrieve(query=query, case_id=case_id,
                                   qdrant_path=qpath, top_k=TOP_K)
        except Exception as e:  # noqa: BLE001
            hybrid_hits, err_hybrid = [], f"{type(e).__name__}: {e}"
        hybrid_ms = round((time.time() - t0) * 1000, 1)

        hybrid_rank, hybrid_score = None, None
        if expected:
            for i, h in enumerate(hybrid_hits, 1):
                if h.get("source") == expected:
                    hybrid_rank, hybrid_score = i, h.get("score")
                    break

        rows.append({
            "query": query[:70],
            "kind": kind,
            "expected": expected,
            "dense": {
                "retrieved": len(dense_hits),
                "rank": dense_rank,
                "score": dense_score,
                "top1_source": dense_hits[0].get("source") if dense_hits else None,
                "top1_score": dense_hits[0].get("score") if dense_hits else None,
                "latency_ms": dense_ms,
                "error": err_dense,
            },
            "hybrid": {
                "retrieved": len(hybrid_hits),
                "rank": hybrid_rank,
                "score": hybrid_score,
                "top1_source": hybrid_hits[0].get("source") if hybrid_hits else None,
                "top1_score": hybrid_hits[0].get("score") if hybrid_hits else None,
                "latency_ms": hybrid_ms,
                "error": err_hybrid,
            },
        })
    return rows


def _llm_eval(case_id):
    from backend.modules.rag_engine import run_rag_query
    from backend.modules.vector_store import case_qdrant_path
    from backend.dependencies import get_settings

    qpath = case_qdrant_path(case_id)
    cases_dir = get_settings().cases_dir
    out = []
    for query, expected, kind in QUERIES:
        t0 = time.time()
        err = None
        try:
            res = run_rag_query(query=query, case_id=case_id,
                                qdrant_path=qpath, cases_dir=cases_dir)
        except Exception as e:  # noqa: BLE001
            res, err = None, f"{type(e).__name__}: {e}"
        out.append({
            "query": query[:70],
            "kind": kind,
            "elapsed_s": round(time.time() - t0, 3),
            "chunks_retrieved": (res or {}).get("chunks_retrieved"),
            "retrieval_failed": (res or {}).get("retrieval_failed"),
            "answer_head": ((res or {}).get("answer") or "")[:160],
            "error": err,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true",
                    help="also run full RAG (needs Ollama running)")
    ap.add_argument("--keep", action="store_true",
                    help="do not delete the temp environment")
    ap.add_argument("--out", default=None, help="write the JSON report here")
    args = ap.parse_args()

    root = tempfile.mkdtemp(prefix="idfa_bench_")
    _make_env(root)

    report = {"root": root, "corpus_files": list(CORPUS), "top_k": TOP_K}
    try:
        from backend.modules.vector_store import describe_embedder
        report["embedder"] = describe_embedder()
    except Exception as e:  # noqa: BLE001
        report["embedder"] = {"error": f"{type(e).__name__}: {e}"}

    print(f"[bench] isolated root: {root}")
    t_start = time.time()
    case_id, evidence = _seed_corpus(root)
    report["case_id"] = case_id

    print(f"[bench] ingesting {len(evidence)} file(s)...")
    report["ingestion"] = _run_ingestion(case_id, evidence)

    print("[bench] retrieval eval...")
    report["retrieval"] = _retrieval_eval(case_id)

    if args.llm:
        print("[bench] full RAG eval (Ollama)...")
        report["rag"] = _llm_eval(case_id)

    report["total_s"] = round(time.time() - t_start, 3)

    # Dense recall (baseline)
    dense_hits = sum(1 for r in report["retrieval"] if r["dense"]["rank"] is not None)
    hybrid_hits = sum(1 for r in report["retrieval"] if r["hybrid"]["rank"] is not None)
    positives = sum(1 for r in report["retrieval"] if r["expected"])
    print(f"\n[bench] Recall@k (expected source present):")
    print(f"  dense:  {dense_hits}/{positives}")
    print(f"  hybrid: {hybrid_hits}/{positives}")

    print(json.dumps(report, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"[bench] report written to {args.out}")

    if not args.keep:
        print("[bench] cleaning temp env")
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
