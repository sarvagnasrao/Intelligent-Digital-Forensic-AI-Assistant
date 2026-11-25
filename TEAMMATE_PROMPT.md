# Prompt to paste into Claude Code (on the teammate's laptop)

Before pasting: unzip `eval_kit.zip` so that the folder `eval_kit\` sits directly inside the root of your
Intelligent-Digital-Forensic-AI-Assistant checkout (the folder that contains `backend\` and `frontend\`).
Open Claude Code in that project root, then paste everything below the line.

---

Run the evaluation in `eval_kit` (a folder at the root of this repo, next to `backend\`). Follow these steps exactly.

**Rules**
- Do NOT edit `build_corpus.py`, `run_eval.py`, `score_claims.py`, `queries.json`, or anything under `backend\`. If something fails, fix only the environment (missing packages, the spaCy model, the embedding model download, environment variables).
- Do not interpret, round or summarise the numbers. Print them exactly as they appear in the results file.

**Steps**
1. Confirm the repo is on the `main` branch (or whichever branch has `backend\modules\rag_engine.py`, `vector_store.py`, `text_parser.py`, `ingestion_modes.py` and `backend\dependencies.py`). Run `git log -1 --format="%h %ci %s"` and include the output in the report.
2. Stop the backend (uvicorn/FastAPI) and the Vite dev server if they are running. They share `data/forensic.db` and the Qdrant lock.
3. Use the Python environment the backend normally runs in (the one where the project already works). Record its path and `python --version`. Make sure these are importable, and install only what is missing:
   - everything in the root `requirements.txt`
   - `torch` and `sentence-transformers`. The model `all-MiniLM-L6-v2` must load: `python -c "from sentence_transformers import SentenceTransformer as S; print(S('all-MiniLM-L6-v2', device='cpu').max_seq_length)"` should print 256.
   - spaCy model `en_core_web_sm` for spaCy 3.7. If `python -m spacy download en_core_web_sm` gives a 404, install the wheel directly: `pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl`
4. The backend's `Settings` requires `APP_NAME` and `APP_VERSION`. `run_eval.py` runs from `eval_kit\`, so a `.env` in the repo root is NOT picked up. Set them as environment variables in the same shell (values from `.env.example`):
   `APP_NAME=Intelligent Digital Forensic AI Assistant`, `APP_VERSION=1.0.0`, plus `PYTHONUTF8=1`.
   Do not set `OLLAMA_NUM_CTX` or other OLLAMA_* overrides. Use the code defaults (num_ctx 16384, model llama3.2:3b, seed 42) and report them.
5. Make sure Ollama is running and `llama3.2:3b` is pulled (`curl http://127.0.0.1:11434/api/tags`). Warm the model once with the same context the backend requests, and report how long it took:
   `curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"llama3.2:3b\",\"prompt\":\"Say ok\",\"stream\":false,\"keep_alive\":\"2h\",\"options\":{\"num_ctx\":16384,\"num_predict\":5}}"`
6. From inside `eval_kit\` run:
   - `python build_corpus.py` (expected: `case A files: 36 case B files: 4 answerable: 30 unanswerable: 8 cross-case: 5`)
   - `python run_eval.py --repo .. --embedder real --llm --out results_full`
   Run the second one in the background with stdout/stderr redirected to `run_full.log`. It makes 38 LLM calls.
7. **Watch for the known timeout problem.** `backend\modules\ollama_client.py` waits at most 180 s for each `/api/generate` call (`requests.post(..., timeout=180)`, non-streaming). On a CPU-only laptop a 16384-token prompt takes longer than that. When it times out, the client does NOT raise. It returns an answer text that starts with "⚠️ Cannot reach Ollama ... (ReadTimeout)", and `run_eval.py` then records `error: null` with `seconds` ≈ 180. Those LLM results are invalid even though the run "succeeds".
   - After the first LLM query, check the Ollama server log (or the `[GIN]` lines if you started `ollama serve` yourself). A `POST /api/generate` taking about `3m0s` and returning 500 means it is timing out. If so, stop the run and report back rather than letting it run for hours.
   - When the run finishes, count the `full_pipeline` entries whose `answer` starts with "⚠️" or whose `seconds` >= 179, and report that count. It must be 0 for the LLM results to be valid.
8. Do not fill in the claim-judging sheet; that is done by hand later.

**Report (print exactly, no rounding, no interpretation)** from `eval_kit\results_full\results_real.json`:
- `embedder_mode`, `embedder`, `llm_model`, `machine` (CPU/GPU/RAM), `chunk_size`, `chunk_overlap`, `retrieval_top_k_production`, `case_A`, `case_B`
- For each retriever `dense`, `hybrid_rrf`, `exact_term`: `retrieval.<name>.all` → recall@1, @3, @5, @10, @14 (hits/of as stored) and `mrr`. Also give the `identifier` and `semantic` breakdowns and `retrieval_strict_gold_only.<name>`.
- `retrieval_latency_ms_median_of_queries`
- Median end-to-end latency: `statistics.median` of `seconds` over all `full_pipeline` entries. Also give it separately for `set == "answerable"` and `set == "unanswerable"`. Print the raw float.
- Cross-case leakage: `cross_case.total_chunks_from_other_case`, plus `markers_found_in_own_case` and `case_A_id_against_case_B_directory`
- Abstention:
  - every row of `abstention_retrieval_level` (id, exact_term_hits, gate_fires_on_exact_term_hits, gate_fires_on_whole_case)
  - for the 8 `full_pipeline` entries with `set == "unanswerable"`: id, `refused`, `model_not_consulted`, `grounding`, `seconds`, `error`
  - the same fields for the answerable set, so false abstentions are visible
- The count of timed-out LLM answers from step 7.
- Any environment fixes you had to make.

Finally, zip `eval_kit\results_full\` together with `eval_kit\run_full.log` as `results_full.zip` so it can be sent back.
