"""
Lexical matching for exact-identifier retrieval.

Why this module exists (Stage 4.1, finding C1)
----------------------------------------------
Retrieval was dense-only, and cosine similarity is the wrong instrument for the
strings a forensic investigator actually asks about. An IP, a hash, a domain, an
account handle or a filename is an EXACT identifier: it should match by string,
not by neighbourhood in an embedding space. Measured on the baseline corpus
(`bench_baseline.json`), the query "203.0.113.77" ranked the chunk that contains
that address THIRD at 0.133 -- below the 0.15 floor -- behind an unrelated
transactions.csv at 0.268.

`content_terms` in `rag_engine` cannot be reused for this. It deliberately drops
bare digits and 1-character runs, because its job is deciding whether a question
and a corpus share ANY content word at all ("a bare 4471 or a bare 412 is not
what a question is asking about"). That is correct for its job and useless for
matching: it cannot even see "203.0.113.77". So matching has its own tokeniser,
`identifier_terms`, which keeps digits and short numeric runs, and this module is
stdlib-only on purpose -- `vector_store` imports it, and `vector_store` must not
drag in the embedding stack to tokenise a string (B15).
"""

import math
import re

# Split on EVERY non-alphanumeric run, exactly as the gate does, so a question
# that spells an identifier with spaces still matches evidence that spells it
# with dots. `exfil.darknode.io` -> exfil, darknode, io; `203.0.113.77` ->
# 203, 113, 77.
_IDENT_TOKEN = re.compile(r"[^a-z0-9]+")

# The canonical stopword list. `rag_engine._QUERY_STOPWORDS` aliases THIS object,
# so the gate and the matcher can never drift apart -- two copies of a stopword
# list is two answers to "is 'was' a content word?".
QUERY_STOPWORDS = frozenset("""
    a an the is are was were be been being do does did has have had of in on at
    to from by for with about into through over under and or but if then than
    so as it its this that these those i you he she we they them his her their
    our my me us who whom whose which what when where why how all any both each
    more most other some such no not only own same too very can will just also
    there here am up out down off again further once
""".split())


def identifier_terms(text: str) -> set:
    """Lowercase alphanumeric runs of length >= 2, minus stopwords.

    The difference from `content_terms` is one line and it is the whole point:
    bare digits are KEPT. A hash, an IP octet, a port, a file size and a case
    number are all digits, and they are frequently the most discriminative
    tokens a forensic question contains. Stopwords are still dropped (they
    appear in nearly every chunk and carry no signal) and 1-character runs with
    them ("a", "0" in "203.0.113.0").
    """
    out = set()
    for raw in _IDENT_TOKEN.split((text or "").lower()):
        if len(raw) < 2 or raw in QUERY_STOPWORDS:
            continue
        out.add(raw)
    return out


def bm25_idf(document_frequency: int, n_documents: int) -> float:
    """BM25's inverse document frequency, which is always positive.

    The classic `log(N / df)` maps a term present in every document to 0 and
    needs a guard for df == 0; this form is bounded below by
    `log(1 + 0.5/(N + 0.5)) > 0` and needs neither. A term that occurs once in a
    3-passage corpus scores ~0.98; a term in every passage scores ~0.13. That
    ratio IS the fix: the identifier outvotes the filler.
    """
    n = max(1, n_documents)
    df = max(0, min(document_frequency, n))
    return math.log((n - df + 0.5) / (df + 0.5) + 1.0)


def document_frequencies(term_sets) -> dict:
    """{term: number of passages containing it}, over an iterable of term sets."""
    dfs = {}
    for terms in term_sets:
        for t in terms:
            dfs[t] = dfs.get(t, 0) + 1
    return dfs


def weighted_coverage(query_terms, chunk_terms, dfs, n_documents) -> float:
    """Fraction of the query's *rarity weight* that the chunk contains, 0..1.

    The denominator is the query's total weight, so this is a coverage of the
    question rather than of the passage -- a 700-character chunk must not be
    scored down for being long. Weighting by IDF is what stops a question such
    as "how much data was moved" matching every passage that contains "data":
    "data" carries ~0.13 of weight, an IP octet ~0.98.

    Returns 0.0 when the query has no terms at all; that is a real zero (nothing
    to match with), not an unmeasurable, and the caller filters on `> 0`.
    """
    if not query_terms:
        return 0.0
    total = sum(bm25_idf(dfs.get(t, 0), n_documents) for t in query_terms)
    if total <= 0:
        return 0.0
    hit = sum(bm25_idf(dfs.get(t, 0), n_documents)
              for t in query_terms if t in chunk_terms)
    return hit / total
