import networkx as nx
import spacy
from rapidfuzz import fuzz
import re
import json
import os

nlp = spacy.load("en_core_web_sm", disable=["tagger", "parser", "attribute_ruler", "lemmatizer", "tok2vec"])


# NER_BUDGET_CHARS bounds how much text one build_graph / extract_entities call
# may hand to spaCy. It is a CHARACTER budget, not a chunk count: a chunk count
# is only an amount-of-text proxy while every chunk is the same size, and
# chunking has changed size before (see the note in build_graph). At the
# measured ~42 KiB/s single-threaded this is ~0.7 s per call. It is enforced as
# a hard ceiling on the total fed in, including a single oversized chunk, so no
# input shape can run the pipeline unbounded.
NER_BUDGET_CHARS = 30_000

# CO_MENTION_MAX_PERSONS caps the pairwise CO_MENTIONED_WITH relation within a
# single chunk. Every distinct pair is one graph insert, so the relation is
# quadratic: a chunk naming 300 people is 44,850 inserts, and a real document
# that lists a directory of names reaches that easily. The cap is on the number
# of people considered for the pairwise pass, giving at most
# C(CO_MENTION_MAX_PERSONS, 2) = 190 edges per chunk. It does NOT drop anyone:
# every person still becomes a Person node with a MENTIONED_IN edge to the file
# (see the mention loops), so entity coverage is unchanged and only the
# quadratic co-occurrence relation is bounded. 20 is well above the number of
# people a normal prose chunk names (a 700-char chunk names a handful).
CO_MENTION_MAX_PERSONS = 20


def _get_graph_path(case_id: str,
                    cases_dir: str) -> str:
    return os.path.join(
        cases_dir, case_id, "graph_store.json")


def load_graph(case_id: str,
               cases_dir: str) -> nx.DiGraph:
    """Loads case graph from disk."""
    path = _get_graph_path(case_id, cases_dir)
    if not os.path.exists(path):
        return nx.DiGraph()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        G = nx.DiGraph()
        for node in data.get("nodes", []):
            node_id = node.pop("id")
            G.add_node(node_id, **node)
        for edge in data.get("edges", []):
            G.add_edge(
                edge["source"],
                edge["target"],
                relationship=edge.get(
                    "relationship", "RELATED")
            )
        return G
    except Exception as e:
        print(f"GRAPH LOAD ERROR: {e}")
        return nx.DiGraph()


def save_graph(G: nx.DiGraph,
               case_id: str,
               cases_dir: str):
    """Saves case graph to disk."""
    path = _get_graph_path(case_id, cases_dir)
    os.makedirs(os.path.dirname(path),
                exist_ok=True)
    data = {
        "nodes": [
            {"id": n, **G.nodes[n]}
            for n in G.nodes()
        ],
        "edges": [
            {
                "source": u,
                "target": v,
                "relationship": G.edges[u, v].get(
                    "relationship", "RELATED")
            }
            for u, v in G.edges()
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _resolve_entities(
        entity_list: list[str]) -> list[str]:
    resolved = []
    for entity in entity_list:
        entity = entity.strip()
        if not entity or len(entity) < 2:
            continue
        duplicate = False
        for i, existing in enumerate(resolved):
            if fuzz.ratio(entity.lower(),
                          existing.lower()) > 85:
                if len(entity) > len(existing):
                    resolved[i] = entity
                duplicate = True
                break
        if not duplicate:
            resolved.append(entity)
    return resolved


def extract_entities(text: str) -> dict:
    # Bounded: this is the standalone entry point used by get_graph_context
    # (the query text) and by the grounding check. A caller can pass anything,
    # so the same NER ceiling build_graph enforces applies here, otherwise a
    # long input runs the pipeline unbounded.
    if text and len(text) > NER_BUDGET_CHARS:
        text = text[:NER_BUDGET_CHARS]
    doc = nlp(text)
    persons, locations, organizations = [], [], []

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            persons.append(ent.text.strip())
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            locations.append(ent.text.strip())
        elif ent.label_ in ("ORG", "NORP"):
            organizations.append(ent.text.strip())

    ips = re.findall(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b', text)

    return {
        "persons": _resolve_entities(
            list(set(persons))),
        "locations": _resolve_entities(
            list(set(locations))),
        "organizations": _resolve_entities(
            list(set(organizations))),
        "ips": list(set(ips))
    }


def build_graph(chunks: list[str],
                source_filename: str,
                evidence_id: str,
                case_id: str,
                cases_dir: str,
                governor=None) -> tuple[dict, list[dict]]:
    """
    Builds or updates the case graph with
    entities from new evidence.
    Returns (entity counts, list of extracted entities per chunk).
    """
    G = load_graph(case_id, cases_dir)

    # Add file node
    G.add_node(source_filename,
               type="File",
               label=source_filename,
               evidence_id=evidence_id)

    counts = {
        "persons": 0, "locations": 0,
        "organizations": 0, "ips": 0
    }

    # A CHARACTER budget, not a chunk count.
    #
    # This was `chunks[:10]` with the comment "to guarantee < 1 min ingestion for
    # large files" — a count standing in for an amount of text, which is only a
    # proxy while every chunk is the same size. Chunking is now 700 characters
    # globally (§31.7 item 5), so the same 10 chunks is 7 KB where it used to be
    # 30 KB: a silent 4.3x cut in the evidence NER sees, landing the same way a
    # deliberate smaller budget would and looking like nothing at all.
    #
    # Measured NER throughput is ~42 KiB/s single-threaded, so 30 KB is ~0.7 s
    # and this budget keeps that. The < 1 min figure it was protecting was never
    # a hardware limit but a workaround for spaCy running in-process with no
    # `n_process` pool; that is item 7 and it is where the real parallelism
    # belongs.
    #
    # Chunks are taken whole, so a document boundary is not cut mid-passage.
    # Only a single chunk that alone exceeds the remaining budget is sliced,
    # because otherwise no budget could bound it.
    #
    # The old loop (`if budgeted and budget_used + len(c) > NER_BUDGET_CHARS`)
    # always admitted the FIRST chunk whatever its size, so one oversized chunk
    # - which is exactly the shape a budget exists to bound - ran in full. The
    # loop below spends a `remaining` allowance instead; a chunk that does not
    # fit the remainder is sliced, so the total handed to spaCy can never
    # exceed NER_BUDGET_CHARS.
    budgeted, remaining = [], NER_BUDGET_CHARS
    for c in chunks or []:
        if remaining <= 0:
            break
        if len(c) > remaining:
            c = c[:remaining]
        budgeted.append(c)
        remaining -= len(c)

    docs = list(nlp.pipe(budgeted, batch_size=32))
    all_extracted = []

    for i, doc in enumerate(docs):
        chunk = budgeted[i]
        if governor and i % 50 == 0:
            governor.check_and_throttle()

        persons, locations, organizations = [], [], []
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                persons.append(ent.text.strip())
            elif ent.label_ in ("GPE", "LOC", "FAC"):
                locations.append(ent.text.strip())
            elif ent.label_ in ("ORG", "NORP"):
                organizations.append(ent.text.strip())

        ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', chunk)

        entities = {
            "persons": _resolve_entities(list(set(persons))),
            "locations": _resolve_entities(list(set(locations))),
            "organizations": _resolve_entities(list(set(organizations))),
            "ips": list(set(ips))
        }
        all_extracted.append(entities)
        persons_resolved = entities["persons"]

        for person in persons_resolved:
            G.add_node(person, type="Person",
                       label=person,
                       case_id=case_id)
            G.add_edge(person, source_filename,
                       relationship="MENTIONED_IN")
            counts["persons"] += 1

        for loc in entities["locations"]:
            G.add_node(loc, type="Location",
                       label=loc, case_id=case_id)
            G.add_edge(loc, source_filename,
                       relationship="MENTIONED_IN")
            counts["locations"] += 1

        for org in entities["organizations"]:
            G.add_node(org, type="Organization",
                       label=org, case_id=case_id)
            G.add_edge(org, source_filename,
                       relationship="MENTIONED_IN")
            counts["organizations"] += 1

        for ip in entities["ips"]:
            G.add_node(ip, type="IP",
                       label=ip, case_id=case_id)
            G.add_edge(ip, source_filename,
                       relationship="FOUND_IN")
            counts["ips"] += 1

        # Every pair of people gets a CO_MENTIONED_WITH edge, so this is
        # quadratic. A document with a few hundred distinct names turns into
        # tens of thousands of graph inserts, and none of them consulted the
        # stop signal - the only check in this function ran every 50 spaCy
        # documents, which for a short file means exactly once, at i=0.
        # Checking per outer row keeps Stop responsive here.
        #
        # The pairwise pass is also capped at CO_MENTION_MAX_PERSONS people per
        # chunk (see the constant): at most C(cap, 2) edges are inserted for one
        # chunk no matter how many names it holds. Both bounds on `j` and `k`
        # use the capped count; capping only `j` would still let a capped person
        # connect to everyone past the cap and the relation would stay linear in
        # the number of names rather than bounded.
        n_persons = min(len(persons_resolved), CO_MENTION_MAX_PERSONS)
        for j in range(n_persons):
            if governor is not None and j % 10 == 0:
                governor.check_and_throttle()
            for k in range(j + 1, n_persons):
                G.add_edge(
                    persons_resolved[j], persons_resolved[k],
                    relationship="CO_MENTIONED_WITH"
                )

    save_graph(G, case_id, cases_dir)
    return counts, all_extracted


def get_graph_data(case_id: str,
                   cases_dir: str) -> dict:
    G = load_graph(case_id, cases_dir)
    nodes = [
        {
            "id": n,
            "label": G.nodes[n].get("label", n),
            "type": G.nodes[n].get(
                "type", "Unknown")
        }
        for n in G.nodes()
    ]
    edges = [
        {
            "source": u,
            "target": v,
            "relationship": G.edges[u, v].get(
                "relationship", "RELATED")
        }
        for u, v in G.edges()
    ]
    return {"nodes": nodes, "edges": edges}


def get_entity_summary(case_id: str,
                       cases_dir: str) -> dict:
    G = load_graph(case_id, cases_dir)
    counts = {
        "Person": 0, "Location": 0,
        "Organization": 0, "IP": 0, "File": 0
    }
    for n in G.nodes():
        t = G.nodes[n].get("type", "Unknown")
        if t in counts:
            counts[t] += 1
    return counts


def get_graph_context(query: str,
                      case_id: str,
                      cases_dir: str) -> str:
    """
    Returns relationship context for entities
    found in the query. Used by RAG engine.
    """
    entities = extract_entities(query)
    all_names = (
        entities["persons"] +
        entities["locations"] +
        entities["organizations"] +
        entities["ips"]
    )
    if not all_names:
        return ""

    G = load_graph(case_id, cases_dir)
    context_lines = []

    for name in all_names:
        for node in G.nodes():
            if (fuzz.ratio(name.lower(),
                           node.lower()) > 80):
                for _, target, data in \
                        G.out_edges(node, data=True):
                    rel = data.get('relationship', 'RELATED')
                    context_lines.append(f"- {node} → [{rel}] → {target}")
                for source, _, data in \
                        G.in_edges(node, data=True):
                    rel = data.get('relationship', 'RELATED')
                    context_lines.append(f"- {source} → [{rel}] → {node}")

    if not context_lines:
        return ""

    unique_lines = list(dict.fromkeys(context_lines))
    return (
        "Graph Context (Known Relationships):\n" +
        "\n".join(unique_lines[:30])
    )
