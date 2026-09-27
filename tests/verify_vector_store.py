"""
Guards the vector store's client lifecycle and its optional-dependency contract.

Two defects are covered here, both of which were silent.

1. get_client() cached a single global Qdrant client and ignored the path it
   was handed. Only the first case opened in a process was ever reachable:
   every later case was served that same client, so case B's chunks were
   written into case A's storage folder and case B's collection never
   existed. A search over case B then found nothing and the investigator
   concluded the evidence was clean. Per-case isolation is the entire point of
   a per-case collection name and cannot hold while the client is shared.

2. torch and sentence-transformers were imported at module scope, but
   requirements.txt does not pin them. On any install that follows
   requirements.txt, `import backend.main` raised ImportError - which does not
   degrade embedding, it removes the whole backend: no status endpoint, no
   queue, no cases. The fix makes them lazy, and this asserts the module
   still imports when they are absent.

The embedding backend itself is NOT changed here. It is still local
SentenceTransformers despite the function's name, and switching to an Ollama
embedder is a migration (768-dim vs the 384-dim VECTOR_SIZE) rather than a
bug fix, so it needs its own decision and a re-index.

Run:  PYTHONPATH=. python tests/verify_vector_store.py
"""
import os
import sys
import shutil
import uuid
import tempfile

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


# ---------------------------------------------------------------------------
# Part A — per-case client isolation
# ---------------------------------------------------------------------------

def part_a():
    from backend.modules import vector_store as vs

    print("\n=== A. one client per case, keyed on a normalised path ===")

    base = tempfile.mkdtemp(prefix="idfai_vs_test_")
    a = os.path.join(base, "case-a", "qdrant")
    b = os.path.join(base, "case-b", "qdrant")

    ca = vs.get_client(a)
    cb = vs.get_client(b)
    check("two cases get two different clients", ca is not cb,
          "shared client - case B would be served case A's storage")
    check("the cached client is per-path, not a single global",
          len(vs._clients) >= 2, f"{len(vs._clients)} cached")

    # Callers spell the same directory two ways: cases.py uses os.path.join
    # (backslashes on Windows), while ingestion.py, queries.py, entities.py
    # and evidence.py use f"{cases_dir}/{case_id}/qdrant" (forward slashes).
    # Keyed on the raw string those are two keys for one directory, and the
    # second open dies on Qdrant's exclusive per-directory lock.
    same_a = vs.get_client(a.replace("\\", "/"))
    check("two spellings of one directory resolve to one client",
          same_a is ca, "cache would open the same folder twice")
    check("key normalisation collapses separators and ./ prefixes",
          vs._client_key("./data/cases/x/qdrant")
          == vs._client_key(os.path.join("data", "cases", "x", "qdrant")))

    # Actual data isolation, not just object identity. Deterministic vectors
    # keep this fast and keep the real embedding model out of it.
    real_embed = vs.get_ollama_embeddings
    vs.get_ollama_embeddings = lambda texts: [
        [0.1] * vs.VECTOR_SIZE for _ in texts]
    try:
        case_a_id, case_b_id = str(uuid.uuid4()), str(uuid.uuid4())
        n = vs.store_chunks(
            chunks=["alpha evidence", "beta evidence"],
            source_filename="a.txt", evidence_id="ev-a",
            case_id=case_a_id, qdrant_path=a)

        check("store_chunks reports the chunks it wrote", n == 2, n)

        names_a = [c.name for c in ca.get_collections().collections]
        check("case A's collection exists in case A's storage",
              vs.get_collection_name(case_a_id) in names_a, names_a)
        names_b = [c.name for c in cb.get_collections().collections]
        check("case B's storage does NOT contain case A's collection",
              vs.get_collection_name(case_a_id) not in names_b, names_b)

        # The scenario the bug actually produced: evidence indexed under one
        # case landing in another case's store.
        vs.store_chunks(
            chunks=["gamma evidence"],
            source_filename="b.txt", evidence_id="ev-b",
            case_id=case_b_id, qdrant_path=b)
        names_a = [c.name for c in ca.get_collections().collections]
        names_b = [c.name for c in cb.get_collections().collections]
        check("indexing case B leaves case A untouched",
              vs.get_collection_name(case_b_id) not in names_a, names_a)
        check("case B's collection is in case B's storage",
              vs.get_collection_name(case_b_id) in names_b, names_b)
    finally:
        vs.get_ollama_embeddings = real_embed
        vs.close_client(a)
        vs.close_client(b)

    # Releasing the lock is what makes the directory removable at all. Uses a
    # fresh path, because the block above already closed a and b - calling
    # close_client on those again would correctly return False and prove
    # nothing.
    c_dir = os.path.join(base, "case-c", "qdrant")
    vs.get_client(c_dir)
    check("close_client reports that it released a client",
          vs.close_client(c_dir) is True)
    check("close_client on an already-closed path is a no-op",
          vs.close_client(c_dir) is False)
    try:
        shutil.rmtree(os.path.join(base, "case-c"), ignore_errors=True)
        check("a case directory can be removed after close",
              not os.path.exists(os.path.join(base, "case-c")))
    finally:
        vs.close_all_clients()
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part B — a stop is a stop, not an indexing failure
# ---------------------------------------------------------------------------

def part_b():
    from backend.modules import vector_store as vs

    print("\n=== B. a stop request is not reported as an index failure ===")

    base = tempfile.mkdtemp(prefix="idfai_vs_stop_")
    path = os.path.join(base, "qdrant")

    # StopIteration is a subclass of Exception, so a generic handler around
    # the embed loop would swallow an operator's stop and report it as a
    # failed index - the job would go red instead of Stopped.
    def _stopped():
        return True

    try:
        vs.store_chunks(
            chunks=["a", "b", "c"],
            source_filename="doc.txt", evidence_id="ev-1",
            case_id=str(uuid.uuid4()), qdrant_path=path,
            stop_check=_stopped)
        check("a requested stop raises StopIteration", False,
              "returned normally - the stop was ignored")
    except StopIteration:
        check("a requested stop raises StopIteration", True)
    except vs.VectorStoreError as e:
        check("a requested stop raises StopIteration", False,
              f"reported as an indexing failure: {e}")
    except Exception as e:
        check("a requested stop raises StopIteration", False,
              f"{type(e).__name__}: {e}")

    # An empty batch is the one case that legitimately stores nothing. It must
    # stay distinguishable from a failure (B10).
    try:
        n = vs.store_chunks(
            chunks=[], source_filename="empty.txt", evidence_id="ev-2",
            case_id=str(uuid.uuid4()), qdrant_path=path)
        check("an empty batch returns 0, not an error", n == 0, n)
    except Exception as e:
        check("an empty batch returns 0, not an error", False,
              f"{type(e).__name__}: {e}")
    finally:
        vs.close_all_clients()
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part C — the backend imports without the optional ML dependencies
# ---------------------------------------------------------------------------

def part_c():
    import importlib.abc

    print("\n=== C. backend imports without torch / sentence-transformers ===")

    blocked = {"torch", "sentence_transformers"}

    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in blocked:
                raise ImportError(
                    f"{fullname} is not installed (simulated clean install)")
            return None

    # A subprocess would be cleaner, but this keeps the check self-contained
    # and it is the import itself that has to survive.
    saved_path = list(sys.meta_path)
    saved_mods = {m: sys.modules.pop(m) for m in list(sys.modules)
                  if m.split(".")[0] in blocked}
    sys.meta_path.insert(0, Blocker())
    try:
        import backend.main          # noqa: F401
        import backend.ingestion      # noqa: F401
        check("backend.main imports with both ML packages unavailable", True)
        check("ingestion imports with both ML packages unavailable", True)
    except Exception as e:
        check("backend.main imports with both ML packages unavailable", False,
              f"{type(e).__name__}: {e}")
    finally:
        sys.meta_path[:] = saved_path
        sys.modules.update(saved_mods)

    # And the failure, when it does come, has to be actionable rather than a
    # bare ImportError from somewhere deep in the call stack.
    from backend.modules import vector_store as vs
    real = vs.get_ollama_embeddings
    vs.get_ollama_embeddings = None
    try:
        vs._embed_model = None
        vs._embed_tried = False
        saved = {k: v for k, v in vars(vs).items()
                 if k in ("_embed_model", "_embed_tried")}
        vs.get_ollama_embeddings = real
        # Simulate the absent backend by pointing the lazy import at nothing.
        import builtins
        real_import = builtins.__import__

        def _no_torch(name, *a, **kw):
            if name.split(".")[0] in blocked:
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *a, **kw)

        builtins.__import__ = _no_torch
        try:
            vs._embed_model = None
            vs._embed_tried = False
            vs.get_ollama_embeddings(["hello"])
            check("a missing embedding backend raises a clear error", False,
                  "returned normally")
        except RuntimeError as e:
            check("a missing embedding backend raises a clear error",
                  "sentence-transformers" in str(e), str(e)[:90])
        except Exception as e:
            check("a missing embedding backend raises a clear error", False,
                  f"{type(e).__name__}: {e}")
        finally:
            builtins.__import__ = real_import
            for k, v in saved.items():
                setattr(vs, k, v)
    finally:
        vs.get_ollama_embeddings = real


def main():
    for fn in (part_a, part_b, part_c):
        try:
            fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")

    print(f"\n{'=' * 60}")
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"    FAILED: {f}")
    print(f"{'=' * 60}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
