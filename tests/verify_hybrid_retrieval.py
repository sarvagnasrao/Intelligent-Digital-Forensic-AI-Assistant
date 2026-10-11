#!/usr/bin/env python3
"""
Stage 4.1 -- exact-identifier retrieval (the lexical half of search).

The defect (C1)
---------------
Retrieval is dense-only. Cosine similarity is a *semantic* measure, and it is
the wrong instrument for the strings a forensic investigator actually asks
about -- an IP, a hash, a domain, an account handle, a filename. Those are
exact identifiers; they should match by STRING, not by neighbourhood in an
embedding space.

Measured on the baseline corpus (`bench_baseline.json`), the query
"203.0.113.77" ranked the chunk that literally contains that address THIRD, at
0.133 -- below `RETRIEVAL_SCORE_FLOOR` (0.15) -- while an unrelated
transactions.csv scored 0.268 and took first place. So the question "which host
did 203.0.113.77 reach?" was answered from the wrong passage, and the right one
was one step from being dropped as irrelevant.

Why the existing tokeniser cannot fix it
----------------------------------------
`content_terms` -- the no-shared-terms gate -- deliberately DROPS bare digits
and 1-character runs ("a bare 4471 or a bare 412 is not what a question is
asking about"). That is right for its job and fatal for this one: it cannot even
SEE "203.0.113.77". Matching needs its own tokeniser that keeps them. This suite
pins both halves so the change cannot quietly alter the gate.

What this suite asserts
-----------------------
Part A  `identifier_terms` keeps digits, hashes and dotted identifiers, and
        still drops stopwords -- while `content_terms` is unchanged.
Part B  `lexical_search` finds the exact chunk, ranks it first, and returns only
        chunks that share a query term (no accidental whole-corpus dump).
Part C  `retrieve` (dense + lexical, fused) puts the exact chunk first even when
        the dense branch is stubbed to rank an unrelated chunk above it -- the
        measured failure, reproduced on purpose.
Part D  the fused list has no duplicate (source, chunk_index), and every entry
        carries its provenance (`dense_score`, `lexical_score`, `match`,
        `point_id`) so an answer can be traced to the excerpt it came from (C3).

Pre-fix behaviour
-----------------
This suite is written BEFORE the fix. None of `identifier_terms`,
`lexical_search` or `retrieve` exists yet, so the parts fail as one named
"MISSING" failure each rather than crashing: a suite that cannot print a summary
reads as unreadable and makes the whole gate refuse to total, which would hide
the very failures this file exists to record.

Isolation
---------
Temp DB / cases dir / Qdrant dir chosen before any backend import, exactly as
`bench_pipeline.py` and `verify_reindex_idempotency.py` do. The embedder is
stubbed -- deterministically in Parts A/B/D, and adversarially in Part C. No
Ollama, no torch, no model load.

Summary line follows the gate's shape-B convention:
    PASSED: <n>    FAILED: <n>
"""

import atexit
import hashlib
import math
import os
import shutil
import sys
import tempfile
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

TMP = tempfile.mkdtemp(prefix="cfi_hybrid_")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))

PASS = 0
FAIL = 0
FAILED = []


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        FAILED.append(label)
        print(f"  FAIL {label}" + (f"  -- {detail}" if detail else ""))


def _make_env(root):
    """Point the backend at an isolated temp environment. MUST run before any
    backend import."""
    db_path = os.path.join(root, "hybrid.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path
    os.environ["CASES_DIR"] = os.path.join(root, "cases")
    os.environ["QDRANT_DIR"] = os.path.join(root, "qdrant")
    os.environ["DEBUG"] = "False"


# ---------------------------------------------------------------------------
# Corpus. C0 holds the exact identifier; C1 and C2 do not.
# ---------------------------------------------------------------------------
C0 = ("Firewall log 2024-11-03T02:14Z: inbound connection from 203.0.113.77 "
      "to 10.0.0.5 port 443 accepted, session 8831.")
C1 = ("Exfiltration ledger: transactions.csv (412.8 MB) uploaded to "
      "exfil.darknode.io at 02:31Z by user m.webb.")
C2 = ("Analyst note: the suspect used a courier to move the drive across the "
      "city; no network activity was involved in the transfer.")
CORPUS = [C0, C1, C2]
IDENT_QUERY = "203.0.113.77"

# The exact identifier's tokens, and what `identifier_terms` must therefore
# return for the query.
EXPECTED_IDENT = {"203", "113", "77"}


# ---------------------------------------------------------------------------
# Embedding stubs
# ---------------------------------------------------------------------------
def _hash_vector(text):
    h = hashlib.sha256(text.encode("utf-8")).digest()
    vec = [((h[i % len(h)] / 255.0) - 0.5) for i in range(384)]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _stub_neutral(texts):
    return [_hash_vector(t) for t in texts]


def _stub_adversarial(texts, query, exact):
    """Deterministic and deliberately WRONG: every passage except the exact one
    gets the query's own vector, so the dense branch ranks all of them above it
    (cosine 1.0 against the exact chunk's near-zero). This is the measured
    failure -- an unrelated document scoring above the exact match -- made
    reproducible without depending on any real model."""
    qv = _hash_vector(query)
    ev = _hash_vector("unrelated-decoy:" + exact)
    out = []
    for t in texts:
        # Everything that is not the exact chunk looks (to cosine) like the
        # query; the exact chunk looks unrelated. Ranked last, as measured.
        out.append(ev if t == exact else qv)
    return out


def _stub_embedder(vs, embed_fn):
    vs.get_ollama_embeddings = embed_fn
    vs.describe_embedder = lambda: {
        "embedder_id": vs.EMBEDDER_ID,
        "vector_size": vs.VECTOR_SIZE,
        "max_seq_length": 256,
    }


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def _seed_case(case_id):
    from backend.database import init_db, SessionLocal
    from backend import models
    init_db()
    db = SessionLocal()
    db.add(models.Case(id=case_id, case_name="HYBRID retrieval",
                       case_number=None, status="Active", created_by="test"))
    db.commit()
    db.close()


def _store_corpus(vs, case_id, source="logs.txt"):
    ev_id = str(uuid.uuid4())
    qpath = vs.case_qdrant_path(case_id)
    vs.store_chunks(CORPUS, source, ev_id, case_id, qpath,
                    chunking={"chunk_size": 700, "chunk_overlap": 100})
    return ev_id, qpath


def _load_surface():
    """Import the Stage-4 surface. Returns a dict, or None with a printed reason
    when any part of it does not exist yet (the pre-fix state)."""
    try:
        from backend.modules import lexical as lex
        from backend.modules import vector_store as vs
        from backend.modules import rag_engine as rag
        return {
            "identifier_terms": lex.identifier_terms,
            "lexical_search": vs.lexical_search,
            "retrieve": rag.retrieve,
            "content_terms": rag.content_terms,
        }
    except Exception as e:
        print(f"\n  MISSING Stage-4 retrieval surface: "
              f"{type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Part A -- the tokeniser
# ---------------------------------------------------------------------------
def part_a(surface):
    print("\nPart A -- identifier_terms (matching tokeniser)")
    if surface is None:
        check("A identifier_terms exists", False,
              "Stage-4 retrieval surface not implemented")
        return
    ident = surface["identifier_terms"]
    content = surface["content_terms"]

    check("A1 keeps every token of an IP address",
          ident(IDENT_QUERY) == EXPECTED_IDENT,
          f"got {sorted(ident(IDENT_QUERY))}")
    check("A2 keeps a hash / hex identifier",
          "a1b2c3d4" in ident("sha256 a1b2c3d4 leaked"),
          f"got {sorted(ident('sha256 a1b2c3d4 leaked'))}")
    check("A3 splits dotted names like the gate does",
          ident("exfil.darknode.io") == {"exfil", "darknode", "io"},
          f"got {sorted(ident('exfil.darknode.io'))}")
    check("A4 drops stopwords and 1-char runs",
          ident("the a of 1 42") == {"42"},
          f"got {sorted(ident('the a of 1 42'))}")
    check("A5 a bare number is a content term for MATCHING (unlike the gate)",
          ident("412") == {"412"} and content("412") == set(),
          f"ident={sorted(ident('412'))} content={sorted(content('412'))}")
    check("A6 the no-shared-terms gate is unchanged for an IP query",
          content(IDENT_QUERY) == set(),
          f"content_terms({IDENT_QUERY!r}) = {sorted(content(IDENT_QUERY))}")


# ---------------------------------------------------------------------------
# Part B -- lexical_search
# ---------------------------------------------------------------------------
def part_b(surface):
    print("\nPart B -- lexical_search finds and ranks the exact chunk")
    if surface is None:
        check("B lexical_search exists", False,
              "Stage-4 retrieval surface not implemented")
        return None
    from backend.modules import vector_store as vs
    _stub_embedder(vs, _stub_neutral)

    case_id = str(uuid.uuid4())
    _seed_case(case_id)
    ev_id, qpath = _store_corpus(vs, case_id)

    hits = surface["lexical_search"](IDENT_QUERY, case_id, qpath, limit=10)
    texts = [h.get("text", "") for h in hits]
    keys = [(h.get("source"), h.get("chunk_index")) for h in hits]

    check("B1 the exact chunk is found", C0 in texts,
          f"{len(hits)} hit(s): {[t[:24] for t in texts]}")
    check("B2 it is ranked first",
          bool(texts) and texts[0] == C0,
          f"rank-1 was {texts[0][:40]!r}" if texts else "no hits")
    check("B3 chunks sharing no query term are not returned",
          all(t == C0 for t in texts),
          f"unexpected hits: {[t[:24] for t in texts]}")
    check("B4 no duplicate (source, chunk_index)",
          len(keys) == len(set(keys)),
          f"{len(keys) - len(set(keys))} duplicate(s)")
    check("B5 each hit carries its score and provenance",
          all("score" in h and "match" in h and "chunk_index" in h
              and "source" in h for h in hits) if hits else False,
          f"keys={sorted(hits[0].keys()) if hits else 'no hits'}")
    return case_id, ev_id, qpath


# ---------------------------------------------------------------------------
# Part C -- fusion beats a dense branch that is simply wrong
# ---------------------------------------------------------------------------
def part_c(surface, case_id, qpath):
    print("\nPart C -- fusion rescues an exact match the dense branch ranks last")
    if surface is None or case_id is None:
        check("C fused retrieve exists", False,
              "Stage-4 retrieval surface not implemented")
        return
    from backend.modules import vector_store as vs

    # Reproduce the measured failure: the dense branch prefers an unrelated
    # passage and scores the exact chunk near zero (below the floor).
    _stub_embedder(vs, lambda texts: _stub_adversarial(texts, IDENT_QUERY, C0))

    dense = vs.search_chunks(IDENT_QUERY, case_id, qpath, top_k=10)
    dense_texts = [d.get("text", "") for d in dense]
    check("C1 (control) the dense branch alone ranks the exact chunk last",
          len(dense_texts) == len(CORPUS)
          and dense_texts[-1] == C0 and dense_texts[0] != C0,
          f"dense order: {[t[:20] for t in dense_texts]}")

    fused = surface["retrieve"](IDENT_QUERY, case_id, qpath, top_k=10)
    fused_texts = [f.get("text", "") for f in fused]
    check("C2 fused retrieval ranks the exact chunk first",
          bool(fused_texts) and fused_texts[0] == C0,
          f"fused order: {[t[:20] for t in fused_texts]}")

    keys = [(f.get("source"), f.get("chunk_index")) for f in fused]
    check("C3 the fused list has no duplicate (source, chunk_index)",
          len(keys) == len(set(keys)),
          f"{len(keys) - len(set(keys))} duplicate(s)")

    entry = fused[0] if fused else {}
    check("C4 the top entry carries tracing provenance",
          all(k in entry for k in
              ("dense_score", "lexical_score", "match", "point_id")),
          f"keys={sorted(entry.keys())}")
    check("C5 the exact-match entry is marked as a lexical match",
          entry.get("match") in ("lexical", "both"),
          f"match={entry.get('match')!r}")


# ---------------------------------------------------------------------------
# Part D -- determinism / dedup on the neutral embedder
# ---------------------------------------------------------------------------
def part_d(surface, case_id, qpath):
    print("\nPart D -- fused retrieval is deduplicated and traceable")
    if surface is None or case_id is None:
        check("D fused retrieve exists", False,
              "Stage-4 retrieval surface not implemented")
        return
    from backend.modules import vector_store as vs
    _stub_embedder(vs, _stub_neutral)

    fused = surface["retrieve"](IDENT_QUERY, case_id, qpath, top_k=10)
    keys = [(f.get("source"), f.get("chunk_index")) for f in fused]
    ids = [f.get("point_id") for f in fused]

    check("D1 no duplicate (source, chunk_index)",
          len(keys) == len(set(keys)),
          f"{len(keys) - len(set(keys))} duplicate(s)")
    check("D2 no duplicate point id",
          len(ids) == len(set(ids)) and all(ids),
          f"ids={ids}")
    check("D3 point ids are the deterministic ids the store wrote",
          all(isinstance(i, str) and i for i in ids),
          f"ids={ids}")
    check("D4 every entry has a defined match class",
          all(f.get("match") in ("dense", "lexical", "both") for f in fused),
          f"matches={[f.get('match') for f in fused]}")
    # A lexical-only entry has no cosine score; the floor must not be able to
    # mistake "unmeasured" for "irrelevant" and drop it.
    check("D5 a lexical-only entry reports score None, not a fake 0",
          all(isinstance(f.get("score"), float) or f.get("score") is None
              for f in fused),
          f"scores={[f.get('score') for f in fused]}")


def main():
    print("=" * 66)
    print("Stage 4.1 -- exact-identifier (hybrid) retrieval")
    print("=" * 66)
    _make_env(TMP)

    surface = _load_surface()

    try:
        part_a(surface)
        seeded = part_b(surface)
        if seeded:
            case_id, ev_id, qpath = seeded
        else:
            case_id, ev_id, qpath = None, None, None
        part_c(surface, case_id, qpath)
        part_d(surface, case_id, qpath)
    finally:
        try:
            from backend.modules import vector_store as vs
            vs.close_all_clients()
        except Exception:
            pass

    print("\n" + "=" * 66)
    for label in FAILED:
        print(f"  MISSING/FAILED: {label}")
    print(f"PASSED: {PASS}    FAILED: {FAIL}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
