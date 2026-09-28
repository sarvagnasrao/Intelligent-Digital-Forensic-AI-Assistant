import time
import requests
from backend.dependencies import get_settings


def _settings():
    return get_settings()


def is_ollama_running() -> bool:
    try:
        r = requests.get(
            f"{_settings().ollama_base_url}/api/tags",
            timeout=3
        )
        return r.status_code == 200
    except Exception:
        return False


def is_model_available() -> bool:
    return ollama_diagnostic()["model_ready"]


# ---------------------------------------------------------------------------
# Context window
# ---------------------------------------------------------------------------
#
# There are two different "context lengths" and conflating them is how the
# whole prompt ends up silently discarded:
#
#   /api/show  -> llama.context_length = 131072   the length the model was
#                                                    TRAINED at
#   /api/ps    -> context_length     = 4096      the length Ollama is
#                                                    SERVING it with
#
# Only the second one bounds a prompt. Budgeting against the first means
# building an 80,000-token prompt for a 4,096-token model, which Ollama
# accepts, truncates without telling the caller, and answers from the last
# 4,096 tokens — the tail of the question, with the evidence gone.
#
# Ollama 0.17 has no /api/tokenize endpoint, so an exact token count for a
# text longer than the window is not obtainable without generating. The
# prompt is therefore budgeted from a measured characters-per-token ratio and
# the result is *verified* against Ollama's own prompt_eval_count, which
# arrives with the response.

CHARS_PER_TOKEN = 2.4
# Measured on this project's own data with llama3.2:3b, and the direction
# matters more than the number:
#
#   SYSTEM_PROMPT prose              2,116 chars ->   468 tok (4.52 c/tok)
#   dense forensic log/dump text   212,815 chars -> 80,311 tok (2.65 c/tok)
#   assembled 7-excerpt prompt       8,472 chars ->  3,345 tok (2.53 c/tok)
#
# The estimate is chars / CHARS_PER_TOKEN, so it over-estimates the token
# count only when CHARS_PER_TOKEN is *below* the real ratio. Over-estimating
# costs a little unused window. Under-estimating overflows, and an overflow
# is silent -- Ollama truncates without telling the caller and returns a
# confident answer built from the tail of the prompt. So the constant is set
# below the densest measurement (2.53), never above, and the asymmetry is
# deliberate: waste some window rather than lose the evidence.
#
# A single ratio is crude -- prose tokenises at nearly twice the density of
# the log/dump text this system actually indexes -- so a prose-heavy query
# will not use the full window. That is the safe direction to be crude in.
# The unsafe direction is caught at run time by prompt_eval_count below.

_ctx_cache = {"value": None, "at": 0.0}
_CTX_TTL = 30.0


def effective_context_tokens() -> int:
    """
    The context window the model is being served with, not the one it was
    trained for.

    Read from /api/ps, which only lists a model once it is loaded. Cached for
    CTX_TTL so a burst of queries does not add a probe to every one, and
    falling back to the configured ollama_num_ctx when the model is not
    currently resident -- in which case there is nothing to measure and the
    configured value is the honest answer.
    """
    now = time.monotonic()
    if _ctx_cache["value"] and (now - _ctx_cache["at"]) < _CTX_TTL:
        return _ctx_cache["value"]

    settings = _settings()
    configured = int(settings.ollama_num_ctx)
    value = configured

    try:
        r = requests.get(
            f"{settings.ollama_base_url}/api/ps", timeout=3)
        if r.status_code == 200:
            wanted = settings.ollama_model.split(":")[0]
            for m in r.json().get("models", []):
                name = (m.get("name") or m.get("model") or "")
                if name.split(":")[0] == wanted:
                    live = m.get("context_length")
                    if isinstance(live, int) and live > 0:
                        value = live
                    break
    except Exception:
        # Cannot measure. The configured value stands, and the prompt
        # verifier below is what stops a wrong guess from going unnoticed.
        pass

    _ctx_cache["value"] = value
    _ctx_cache["at"] = now
    return value


def prompt_budget_tokens() -> int:
    """
    Tokens available to the prompt.

    Ollama's n_ctx is shared between prompt and completion, so num_predict
    comes off the top before the evidence gets any of it.
    """
    settings = _settings()
    n_ctx = effective_context_tokens()
    # The margin absorbs the part of the estimate that cannot be known
    # without a real tokenizer: the join characters, the elision markers
    # whose digit count varies, and the error left in CHARS_PER_TOKEN.
    room = n_ctx - int(settings.ollama_num_predict) - 256
    return max(256, room)


def ollama_diagnostic() -> dict:
    """
    Structured, honest view of the Ollama side of the system.

    This exists because "Ollama is running" and "the AI can answer" are two
    different facts, and the app used to conflate them. Ollama answers
    /api/tags with 200 and an EMPTY model list on a machine that has never
    pulled a model, so a green "running" light sat next to an assistant that
    could not say a word.

    Every field that could not be measured is None with a reason attached,
    never a fabricated 0 or False.
    """
    settings = _settings()
    base = settings.ollama_base_url
    configured = settings.ollama_model

    out = {
        "base_url": base,
        "configured_model": configured,
        "running": None,
        "model_ready": None,
        "installed_models": None,
        "reason": None,
    }

    try:
        r = requests.get(f"{base}/api/tags", timeout=3)
    except Exception as e:
        # Not an error state we can describe better than this.
        out["reason"] = f"Cannot reach Ollama at {base} ({type(e).__name__})."
        return out

    if r.status_code != 200:
        out["running"] = False
        out["reason"] = f"Ollama answered HTTP {r.status_code} on /api/tags."
        return out

    out["running"] = True
    try:
        models = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:
        out["reason"] = f"Ollama is up but /api/tags was unreadable ({e})."
        return out

    out["installed_models"] = models

    # Ollama reports "llama3.2:3b" in the tag list once pulled, and a bare
    # "llama3.2" when a single quantisation is present. Accept either, and
    # accept a ":latest" suffix, so a correctly-installed model is never
    # reported as missing.
    def _matches(name: str) -> bool:
        n = name.split(":")[0]
        c = configured.split(":")[0]
        return n == c

    out["model_ready"] = any(_matches(m) for m in models)

    if not models:
        out["reason"] = (
            "Ollama is running but has no models installed. "
            f"Pull one with: ollama pull {configured}"
        )
    elif not out["model_ready"]:
        out["reason"] = (
            f"Ollama is running but '{configured}' is not installed. "
            f"Installed: {', '.join(models) or 'none'}. "
            f"Fix with: ollama pull {configured}"
        )
    return out


def generate_response_detailed(prompt: str,
                               system_prompt: str = "",
                               model: str = None
                               ) -> dict:
    """
    Same as generate_response, but also reports what Ollama actually did --
    specifically prompt_eval_count, which is the only ground truth available
    for whether the prompt overflowed the context window.

    Returns {text, prompt_eval_count, eval_tokens, error, saturated}.
    """
    settings = _settings()
    if model is None:
        model = settings.ollama_model
    url = f"{settings.ollama_base_url}/api/generate"

    # Backstop for callers that assemble their own prompt.
    #
    # run_rag_query budgets its prompt properly, but four other features
    # (case summary, contradiction analysis, entity profile and its retry)
    # build a prompt by hand and were sending 8-12 x 30,000-character chunks
    # -- up to 360,000 characters -- at the same 4,096-token window. They
    # overflowed exactly as silently.
    #
    # The check lives here, at the transport, rather than in five call sites,
    # because this is the one boundary that cannot be bypassed: a caller that
    # forgets to budget cannot overflow the window, and a caller fixed later
    # cannot regress the others.
    #
    # Head AND tail are kept. Cutting the end would delete the task
    # instruction and the question -- these prompts put the request last --
    # so a naive truncation would answer a different question than the one
    # asked, which is worse than the overflow it is preventing. The cut is
    # marked, so the model can see that context is missing.
    prompt_stats = {"estimated_tokens": int(
        len(prompt) / CHARS_PER_TOKEN), "clamped": False}
    budget = prompt_budget_tokens()
    if prompt_stats["estimated_tokens"] > budget:
        ceiling = int(budget * CHARS_PER_TOKEN)
        marker_room = 220
        head_room = int(ceiling * 0.55)
        tail_room = ceiling - head_room - marker_room
        if tail_room < 0:
            # Pathological budget: keep the head and the instruction only.
            head_room = max(0, ceiling - marker_room)
            tail_room = 0
        dropped = max(0, len(prompt) - head_room - tail_room)
        kept_head = prompt[:head_room].rstrip()
        kept_tail = (prompt[len(prompt) - tail_room:].lstrip()
                     if tail_room > 0 else "")
        prompt = (
            f"{kept_head}\n\n"
            f"[… {dropped:,} characters of context omitted: this prompt "
            f"did not fit the model's "
            f"{effective_context_tokens():,}-token window. The material "
            f"above and below is only part of what was assembled. …]\n\n"
            f"{kept_tail}"
        )
        prompt_stats = {
            "estimated_tokens": int(len(prompt) / CHARS_PER_TOKEN),
            "clamped": True,
            "chars_clamped": dropped,
        }

    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": settings.ollama_num_predict
        }
    }

    def _fault(message):
        return {
            "text": message,
            "prompt_eval_count": None,
            "eval_tokens": None,
            "error": message,
            "saturated": False,
            "prompt_stats": prompt_stats,
        }

    try:
        r = requests.post(url, json=payload, timeout=180)
    except Exception as e:
        return _fault(
            f"⚠️ Cannot reach Ollama at "
            f"{settings.ollama_base_url} ({type(e).__name__}). "
            f"Start it with `ollama serve`, then ask again. "
            f"Nothing was searched — your question was not answered.")

    try:
        body = r.json()
    except Exception:
        return _fault(
            f"⚠️ Ollama returned HTTP {r.status_code} with a "
            f"non-JSON body. The model could not be reached.")

    if r.status_code != 200 or body.get("error"):
        detail = (body.get("error")
                  or f"HTTP {r.status_code}").strip()
        low = detail.lower()
        if "not found" in low:
            return _fault(
                f"⚠️ The model '{model}' is not installed on this "
                f"machine, so there is nothing to answer with. "
                f"Fix it with: ollama pull {model} — then ask again. "
                f"Your question was not searched.")
        return _fault(
            f"⚠️ Ollama could not generate a response "
            f"({detail}). Your question was not answered.")

    text = body.get("response")
    if text is None:
        return _fault(
            f"⚠️ Ollama returned no 'response' field "
            f"(HTTP {r.status_code}).")

    eval_count = body.get("prompt_eval_count")
    limit = effective_context_tokens()
    prompt_stats["prompt_eval_count"] = eval_count
    prompt_stats["context_tokens"] = limit
    prompt_stats["overflowed"] = (
        isinstance(eval_count, int) and eval_count >= limit - 2)
    return {
        "text": text,
        "prompt_eval_count": eval_count,
        "eval_tokens": body.get("eval_count"),
        "error": None,
        # A prompt that filled the window to the last token is a prompt
        # Ollama truncated. It is not a slow answer, it is a different
        # answer, and it arrives looking exactly like a successful one.
        "saturated": prompt_stats["overflowed"],
        "prompt_stats": prompt_stats,
    }


def generate_response(prompt: str,
                      system_prompt: str = "",
                      model: str = None
                      ) -> str:
    """
    Returns the model's text.
    """
    return generate_response_detailed(
        prompt, system_prompt, model)["text"]
