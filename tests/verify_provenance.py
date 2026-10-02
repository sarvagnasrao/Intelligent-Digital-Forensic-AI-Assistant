"""Provenance guard - section P of the gate. READ-ONLY with respect to the product.

Every assertion is an OUTCOME: what the guard does to an index, and what a
searcher is told. None of them assert that a function was called.

Deliberately does not create a Qdrant client or import torch. `store_chunks`
and `search_chunks` are exercised through a fake client and a stubbed
`describe_embedder`, because embedded Qdrant takes an exclusive lock per
directory (B15) and because the claim under test is the guard's decision, not
Qdrant's behaviour. The one thing that must NOT be stubbed is the provenance
module itself - that is the code under test.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(r"D:\Users\Anon\Desktop\IDFA_main3")

from backend.modules import index_provenance as ip
from backend.modules import vector_store as vs

PASS = 0
FAIL = []


def check(cond, label, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [PASS] {label}" + (f"   {detail}" if detail else ""))
    else:
        FAIL.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


SIG_A = {"embedder_id": "all-MiniLM-L6-v2", "vector_size": 384,
         "max_seq_length": 256}
SIG_B = {"embedder_id": "bge-small-en-v1.5", "vector_size": 384,
         "max_seq_length": 512}
SIG_768 = {"embedder_id": "all-MiniLM-L6-v2", "vector_size": 768,
           "max_seq_length": 256}


class FakeClient:
    """Enough of QdrantClient for the guard to run against."""

    def __init__(self, path, fail_search=False):
        self.path = path
        self.collections = set()
        self.points = []
        self.upserts = 0
        self.fail_search = fail_search
        self.searched = 0

    def get_collections(self):
        class _R:
            collections = []
        return _R()

    def create_collection(self, collection_name=None, vectors_config=None):
        self.collections.add(collection_name)

    def upsert(self, collection_name=None, points=None):
        self.upserts += 1
        self.collections.add(collection_name)
        self.points.extend(points or [])

    def delete_collection(self, collection_name):
        self.collections.discard(collection_name)
        self.deleted = getattr(self, "deleted", 0) + 1

    def search(self, collection_name=None, query_vector=None, limit=7,
               with_payload=True, query_filter=None):
        self.searched += 1
        if collection_name not in self.collections:
            raise RuntimeError(f"Not found: Collection {collection_name}")
        if self.fail_search:
            raise RuntimeError("storage folder is locked")
        return []


print("=" * 74)
print("A. THE SIGNATURE IS MEASURED FROM THE MODEL, NOT READ FROM A TABLE")
print("=" * 74)

real_sig = vs.describe_embedder
measured = real_sig()
check(measured.get("embedder_id") == vs.EMBEDDER_ID,
      "describe_embedder names the model from one constant", vs.EMBEDDER_ID)
check(measured.get("vector_size") == vs.VECTOR_SIZE,
      "measured vector size matches VECTOR_SIZE", str(measured.get("vector_size")))
check(measured.get("max_seq_length") == 256,
      "measured max_seq_length is the model's own 256, not an assumption",
      str(measured.get("max_seq_length")))
# Deliberately NOT asserted as "measured != declared": on this box they agree,
# which is the *desired* outcome, and asserting they differ would fail a correct
# build. What matters is that the two are separate inputs and that the guard
# consumes the measurement -- proved in C5 below by patching the declaration.
check(ip.check_declaration(measured) == [],
      "the declaration agrees with the loaded model on this box",
      str(ip.check_declaration(measured)))
# The trap: a hand-edited max_seq_length must be reported, not silently trusted.
check(ip.check_declaration({**measured, "max_seq_length": 512}) != [],
      "a hand-edited max_seq_length is reported as a disagreement",
      str(ip.check_declaration({**measured, "max_seq_length": 512})))
check(ip.check_declaration(None) == ["no measured signature"],
      "an absent measurement is reported, not treated as agreement")
check(ip.declared_signature("some-unknown-model") is None,
      "an unknown embedder declares nothing rather than guessing",
      "None is correct: nothing to compare against")

print()
print("=" * 74)
print("B. FOUR DISTINGUISHABLE STATES - none of them a silent default")
print("=" * 74)

tmp = tempfile.mkdtemp(prefix="prov_b_", dir=r"C:\Windows\Temp")
try:
    # B1: no directory at all -> never indexed
    never = os.path.join(tmp, "no-such-case", "qdrant")
    v = ip.check_index(never, SIG_A)
    check(v["state"] == ip.NEVER_INDEXED,
          "a case with no index at all reads as never_indexed", v["state"])
    check("no vector index" in (v["reason"] or ""),
          "never_indexed says so in the reason", v["reason"])

    # B2: directory present, no record -> unattributed (NOT never_indexed)
    unattr = os.path.join(tmp, "case-unattr", "qdrant")
    os.makedirs(unattr, exist_ok=True)
    v = ip.check_index(unattr, SIG_A)
    check(v["state"] == ip.UNATTRIBUTED,
          "an index with no provenance record reads as unattributed", v["state"])
    check(v["state"] != ip.NEVER_INDEXED,
          "an index that exists is never reported as 'no index'")
    check(ip.read_record_error(unattr) is None,
          "a missing record reports no error - absent and corrupt differ")

    # B3: record written by the current config -> match
    match = os.path.join(tmp, "case-match", "qdrant")
    os.makedirs(match, exist_ok=True)
    ip.record_write(match, SIG_A, chunking={"chunk_size": 700,
                                            "chunk_overlap": 120},
                    evidence_id="ev1", source_filename="a.txt", chunks=5)
    v = ip.check_index(match, SIG_A)
    check(v["state"] == ip.MATCH, "a current-config record reads as match",
          v["state"])
    check(v["reason"] is None, "match carries no reason - nothing to say")

    # B4: record written by a DIFFERENT embedder -> mismatch
    stale = os.path.join(tmp, "case-stale", "qdrant")
    os.makedirs(stale, exist_ok=True)
    ip.record_write(stale, SIG_B, chunking={"chunk_size": 6000,
                                            "chunk_overlap": 200})
    v = ip.check_index(stale, SIG_A)
    check(v["state"] == ip.MISMATCH,
          "a different embedder reads as mismatch", v["state"])
    check("bge-small-en-v1.5" in v["reason"],
          "the mismatch names the embedder that wrote it", v["reason"])
    check("512" in v["reason"],
          "the mismatch names the window difference", v["reason"])

    # B5: same embedder, different dimensionality
    wrong_dim = os.path.join(tmp, "case-768", "qdrant")
    os.makedirs(wrong_dim, exist_ok=True)
    ip.record_write(wrong_dim, SIG_768)
    check(ip.check_index(wrong_dim, SIG_A)["state"] == ip.MISMATCH,
          "a dimensionality change alone is a mismatch")

    # B6: a corrupt record is unattributed, not a match and not a crash
    corrupt = os.path.join(tmp, "case-corrupt", "qdrant")
    os.makedirs(corrupt, exist_ok=True)
    with open(ip.provenance_path(corrupt), "w", encoding="utf-8") as fh:
        fh.write("{not json at all")
    v = ip.check_index(corrupt, SIG_A)
    check(v["state"] == ip.UNATTRIBUTED,
          "a corrupt record reads as unattributed, never as match", v["state"])
    check(ip.read_record_error(corrupt) is not None,
          "a corrupt record is reported as corrupt", ip.read_record_error(corrupt))

    # B7: an older signature_version cannot be field-compared
    oldver = os.path.join(tmp, "case-oldver", "qdrant")
    os.makedirs(oldver, exist_ok=True)
    ip._atomic_write(oldver, {**SIG_A, "signature_version": 0})
    v = ip.check_index(oldver, SIG_A)
    check(v["state"] == ip.UNATTRIBUTED,
          "a record from another signature version is unattributed", v["state"])
    check("signature version" in (v["reason"] or ""),
          "and the reason says the version is why")

    print()
    print("=" * 74)
    print("C. store_chunks REFUSES a mismatched index - and says why")
    print("=" * 74)

    clients = {}

    def fake_get_client(path, _f=clients):
        if path not in _f:
            os.makedirs(path, exist_ok=True)
            _f[path] = FakeClient(path)
        return _f[path]

    vs.get_client = fake_get_client
    vs.describe_embedder = lambda: dict(SIG_A)

    # C1: writing into a stale index must be refused.
    ip._atomic_write(stale, {**SIG_B, "signature_version":
                            ip.SIGNATURE_VERSION,
                            "chunking_schemes": ["6000/200"]})
    raised = None
    try:
        vs.store_chunks(["some evidence text here"],
                        source_filename="x.txt", evidence_id="ev1",
                        case_id="stale", qdrant_path=stale)
    except vs.VectorStoreError as e:
        raised = str(e)
    check(raised is not None, "store_chunks refuses a stale index")
    check(raised and "Refusing to index" in raised,
          "the refusal says it is refusing", raised)
    check(raised and "bge-small" in raised,
          "the refusal names the conflicting embedder", raised)
    # Stronger than "0 upserts", and it is what the code actually does: the
    # refusal happens *before* get_client, so no Qdrant client is ever opened.
    # My first version asserted `clients[stale].upserts == 0` and raised
    # KeyError - the product stopped earlier than the assertion assumed.
    check(stale not in clients,
          "and no Qdrant client was even opened - refusal precedes get_client")
    check((ip.read_provenance(stale) or {}).get("embedder_id")
          == "bge-small-en-v1.5",
          "the stale record was not overwritten by the refusal",
          str((ip.read_provenance(stale) or {}).get("embedder_id")))

    # C2: a good write records provenance.
    good = os.path.join(tmp, "case-good", "qdrant")
    n = vs.store_chunks(["evidence text one", "evidence text two"],
                        source_filename="good.txt", evidence_id="ev2",
                        case_id="good", qdrant_path=good,
                        chunking={"chunk_size": 700, "chunk_overlap": 120})
    rec = ip.read_provenance(good)
    # `rec` can legitimately be None here - that is exactly what happens when
    # the recording is reverted. The first version guarded the *condition* with
    # `rec and ...` and then passed `str(rec.get(...))` as the detail argument,
    # which is evaluated eagerly and crashed. A `rec and` in the condition
    # protects half the line and reads as if it protects all of it.
    r = rec or {}
    check(n == 2, "a healthy write stores every chunk", str(n))
    check(rec is not None, "and a provenance record was written at all")
    check(r.get("embedder_id") == SIG_A["embedder_id"],
          "and records the embedder that produced the vectors", str(r))
    check(r.get("max_seq_length") == 256,
          "and the window", str(r.get("max_seq_length")))
    check(r.get("chunking_schemes") == ["700/120"],
          "and the chunking scheme, as a short stable label",
          str(r.get("chunking_schemes")))
    check(r.get("last_write", {}).get("chunks") == 2,
          "and the last write's chunk count", str(r.get("last_write")))
    check("points" not in r,
          "and NO running point total - archiving deletes points, so a "
          "retained count would drift (B29)", str(sorted(r)))
    check(ip.check_index(good, SIG_A)["state"] == ip.MATCH,
          "and the case now reads as match",
          ip.check_index(good, SIG_A)["state"])

    # C3: two schemes accumulate -> the mosaic becomes visible.
    vs.store_chunks(["evidence text three"], source_filename="good2.txt",
                    evidence_id="ev3", case_id="good", qdrant_path=good,
                    chunking={"chunk_size": 6000, "chunk_overlap": 200})
    rec = ip.read_provenance(good) or {}
    check(rec.get("chunking_schemes") == ["6000/200", "700/120"],
          "a second scheme accumulates rather than overwriting",
          str(rec.get("chunking_schemes")))
    check(rec.get("writes") == 2, "the write count is kept",
          str(rec.get("writes")))
    check(rec.get("last_write", {}).get("chunking") == "6000/200",
          "and last_write names the most recent one, as history",
          str(rec.get("last_write")))
    check(ip.check_index(good, SIG_A)["state"] == ip.MATCH,
          "mixed granularity is still MATCH - it is reported, not refused")
    check(len(ip.check_index(good, SIG_A)["chunking_schemes"]) == 2,
          "and the mixed schemes are readable from the verdict")

    # C4: an unattributed index (pre-guard) is still writable.
    n = vs.store_chunks(["legacy evidence text"], source_filename="l.txt",
                        evidence_id="ev4", case_id="unattr",
                        qdrant_path=unattr)
    check(n == 1, "a pre-guard index accepts writes rather than refusing",
          str(n))
    check(ip.check_index(unattr, SIG_A)["state"] == ip.MATCH,
          "and becomes attributed by that write")

    # C5: the guard consumes the MEASUREMENT, not the declaration table.
    #
    # The distinction that cannot be read off the code and is the whole reason
    # `describe_embedder` exists: if store/search compared the record against
    # `EMBEDDER_SPECS`, then a build whose declaration had drifted would either
    # refuse a perfectly good index or pass a stale one, and no amount of reading
    # would reveal it - the table and the model would simply be the same source.
    # So patch the declaration to say something absurd and require the verdict
    # not to move.
    saved_spec = dict(ip.EMBEDDER_SPECS)
    ip.EMBEDDER_SPECS[vs.EMBEDDER_ID] = {"vector_size": 1024,
                                          "max_seq_length": 4096}
    try:
        check(ip.check_index(good, SIG_A)["state"] == ip.MATCH,
              "a corrupted declaration does not change the verdict (C5)",
              ip.check_index(good, SIG_A)["state"])
        check(ip.check_index(stale, SIG_A)["state"] == ip.MISMATCH,
              "and does not rescue a stale index either (C5)",
              ip.check_index(stale, SIG_A)["state"])
        problems = ip.check_declaration(SIG_A)
        check(problems and "1024" in " ".join(problems) and
              "4096" in " ".join(problems),
              "but the disagreement IS reported, with both numbers (C5)",
              str(problems))
    finally:
        ip.EMBEDDER_SPECS.clear()
        ip.EMBEDDER_SPECS.update(saved_spec)

    print()
    print("=" * 74)
    print("D. search_chunks refuses, and the refusal is not a clean result")
    print("=" * 74)

    # D1: a stale index must refuse to be searched.
    raised = None
    try:
        vs.search_chunks("who is the suspect", case_id="stale",
                         qdrant_path=stale)
    except vs.VectorStoreError as e:
        raised = str(e)
    check(raised is not None, "search_chunks refuses a stale index")
    check(raised and "will not be searched" in raised,
          "the message says it declined, not that it found nothing",
          raised)
    check(raised and "Re-ingest" in raised,
          "and it says what to do about it", raised)
    check(stale not in clients,
          "and Qdrant was never asked at all - no client, no search",
          "absent from the client table" if stale not in clients else "opened")

    # D2: THE load-bearing assertion. A refusal must NOT be [].
    #
    # [] means "the search ran and nothing matched", which is the sentence
    # that clears a suspect (B30). If the guard returned [] instead of
    # raising, every property above would still pass and the tool would
    # still be lying in the one direction that matters.
    check(raised is not None,
          "CRITICAL: the refusal raises rather than returning []")

    # D3: no index at all -> a clear error, not a Qdrant 404 about internals
    raised = None
    try:
        vs.search_chunks("q", case_id="none", qdrant_path=never)
    except vs.VectorStoreError as e:
        raised = str(e)
    check(raised and "no vector index" in raised,
          "a case with no index gets an actionable message", raised)
    check(raised and "Ingest the evidence first" in raised,
          "which names the next action")

    # D4: a current index IS searched.
    res = vs.search_chunks("q", case_id="good", qdrant_path=good)
    check(clients[good].searched == 1,
          "a matching index is searched normally",
          str(clients[good].searched))
    check(res == [], "and an empty result from a working index is [] - "
                     "genuinely nothing matched")

    # D5: an unattributed index is served, once, with a warning.
    #
    # My first version wrote a *matching* record into this path before
    # searching, so the verdict was correctly `match`, correctly emitted no
    # warning, and the assertion failed - with the fixture contradicting the
    # claim under test. Section F then counted 2 matches instead of 1 for the
    # same reason. An index with no record at all is what is wanted here, which
    # is exactly what C4's write then `clear_provenance` leaves behind.
    with vs._unattributed_lock:
        vs._unattributed_warned.clear()
    ip.clear_provenance(unattr)
    check(ip.check_index(unattr, SIG_A)["state"] == ip.UNATTRIBUTED,
          "fixture: the index really has no record",
          ip.check_index(unattr, SIG_A)["state"])
    clients[unattr].collections.add(vs.get_collection_name("unattr"))
    try:
        vs.search_chunks("q", case_id="unattr", qdrant_path=unattr)
        served = True
    except vs.VectorStoreError:
        served = False
    check(served,
          "an index with no record is still searched, not refused - "
          "refusing would lock the operator out of every pre-guard case")
    check(unattr in vs._unattributed_warned,
          "and it is reported as unvouched-for")
    first = len(vs._unattributed_warned)
    vs.search_chunks("q", case_id="unattr", qdrant_path=unattr)
    check(len(vs._unattributed_warned) == first,
          "the warning does not repeat per query - it is on the query path")

    # D6: an embedder failure surfaces as the failure it is
    vs.describe_embedder = lambda: (_ for _ in ()).throw(
        RuntimeError("Embedding requires torch and sentence-transformers"))
    raised = None
    try:
        vs.search_chunks("q", case_id="good", qdrant_path=good)
    except vs.VectorStoreError as e:
        raised = str(e)
    check(raised and "torch" in raised,
          "an unavailable embedder is named, not degraded to 'no match'",
          raised)
    vs.describe_embedder = lambda: dict(SIG_A)

    # D7: the StopIteration re-raise ordering survives (B15/B19)
    vs.describe_embedder = lambda: (_ for _ in ()).throw(
        StopIteration("Ingestion stopped by user"))
    sentinel = None
    try:
        vs.store_chunks(["text"], source_filename="s.txt",
                        evidence_id="e", case_id="good", qdrant_path=good)
    except BaseException as e:
        sentinel = type(e).__name__
    check(sentinel == "StopIteration",
          "a stop sentinel is still re-raised as itself, not wrapped",
          str(sentinel))
    vs.describe_embedder = lambda: dict(SIG_A)

    print()
    print("=" * 74)
    print("E. delete_case_collection takes the record with the collection")
    print("=" * 74)

    vs.delete_case_collection("good", good)
    check(ip.read_provenance(good) is None,
          "the record is removed with the collection")
    check(good not in vs._unattributed_warned,
          "and the warn-once set forgets the path, so a re-ingested case "
          "is reported again if it needs to be")

    print()
    print("=" * 74)
    print("F. survey() - the aggregate, and one honest refusal to guess")
    print("=" * 74)

    s = ip.survey([never, unattr, match, stale, corrupt], SIG_A)
    check(s["total"] == 5, "every path surveyed", str(s["total"]))
    check(s[ip.NEVER_INDEXED] == 1, "one never indexed", str(s[ip.NEVER_INDEXED]))
    check(s[ip.MISMATCH] == 1, "one mismatched", str(s[ip.MISMATCH]))
    # Two, not one: `unattr` (D5's pre-guard index) and `corrupt` (a sidecar
    # that is not readable). Both are "there is an index, nothing can vouch
    # for it", and collapsing them would be the mistake the module exists to
    # avoid - they need the same verdict for *opposite* reasons.
    check(s[ip.UNATTRIBUTED] == 2,
          "two unattributed - the pre-guard index and the corrupt record",
          str(s[ip.UNATTRIBUTED]))
    check(ip.check_index(corrupt, SIG_A)["state"] == ip.UNATTRIBUTED and
          ip.check_index(unattr, SIG_A)["state"] == ip.UNATTRIBUTED,
          "and they are distinguishable from each other by their reason")
    check(s[ip.MATCH] == 1, "one matching", str(s[ip.MATCH]))
    check(sum(s[k] for k in (ip.MATCH, ip.MISMATCH, ip.UNATTRIBUTED,
                             ip.NEVER_INDEXED)) == s["total"],
          "the four states partition the survey - none is double counted")
    check(s["state"] == ip.MISMATCH,
          "a mismatch dominates the aggregate state", s["state"])
    check(s["mismatched_detail"] and
          s["mismatched_detail"][0]["indexed_with"]["embedder_id"]
          == SIG_B["embedder_id"],
          "the detail carries both sides of the difference")
    check(s["embedder_ids"] == [SIG_A["embedder_id"], SIG_B["embedder_id"]],
          "both embedders seen are listed, in encounter order",
          str(s["embedder_ids"]))
    check(ip.survey([], SIG_A)["total"] == 0,
          "an empty survey is 0 of 0, not an error")
    check(ip.survey([], SIG_A)["state"] == ip.MATCH,
          "and nothing to report is not a fault")

    # mixed granularity counted
    ip.record_write(match, SIG_A, chunking={"chunk_size": 3000,
                                            "chunk_overlap": 300})
    s = ip.survey([match], SIG_A)
    check(s["mixed_chunking_cases"] == 1,
          "a case indexed at two granularities is counted", str(s))
    check(s["state"] == ip.UNATTRIBUTED,
          "mixed granularity reports as unattributed, never as match-with-"
          "no-complaint - it is the 'consistent retrieval' claim failing")

    # An absent declaration must NOT crash the guard, and must NOT be read as
    # verified. This found a real hole: `compare` did `measured.get(key)`, so a
    # None declaration raised AttributeError. The call site in service_health
    # guards for it, but a guard that dies on its own absent input is one
    # refactor away from taking down the query path - and "no crash" is the
    # weaker half; the state must be UNATTRIBUTED, never MATCH.
    s = ip.survey([match], None)
    check(s["total"] == 1, "survey tolerates an absent declaration")
    check(s[ip.UNATTRIBUTED] == 1 and s[ip.MATCH] == 0,
          "and an unverifiable index reads as unattributed, never as match",
          str({k: s[k] for k in (ip.MATCH, ip.UNATTRIBUTED)}))
    check(s["state"] == ip.UNATTRIBUTED,
          "and the aggregate says so", s["state"])

finally:
    vs.get_client = vs.get_client
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=" * 74)
if FAIL:
    print(f"PROVENANCE SUITE FAILED - {len(FAIL)} of {PASS + len(FAIL)}")
    for f in FAIL:
        print(f"    {f}")
    print("=" * 74)
    sys.exit(1)
print(f"PROVENANCE SUITE PASSED - {PASS} assertions")
print("=" * 74)
