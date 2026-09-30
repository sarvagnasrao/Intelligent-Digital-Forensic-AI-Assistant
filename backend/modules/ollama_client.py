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

_cap_cache = {"value": None, "at": None, "ok": False}
_CAP_TTL = 300.0
# A capability that could not be read is cached for far less time than one that
# could, so the cache still short-circuits the common case without pinning a
# stale "unreadable" for five minutes after Ollama comes back. See the note in
# model_context_limit().
_CAP_FAIL_TTL = 5.0

# If Ollama served FEWER tokens than this fraction of what we sent, the prompt
# was cut. Deliberately insensitive, and the reason is the bias above: because
# CHARS_PER_TOKEN under-counts characters-per-token, `estimated` over-states the
# true count on prose by up to ~1.9x, so `eval_count < estimated` is normal and
# means nothing. Only losing more than half the prompt is unambiguous, and half
# is the case that matters -- B26 lost 95% of the evidence and it arrived
# looking like a successful answer.
_TRUNCATION_LOSS_RATIO = 0.5


def model_context_limit() -> int | None:
    """
    The longest window the model was TRAINED for, or None if unreadable.

    This is a capability, not a setting, so it is read rather than configured.
    None means "not measured" and is never coerced to 0 -- a 0 limit would clamp
    every request to nothing, which reads as a working number and is not one.
    """
    now = time.monotonic()
    # The cache must short-circuit on a FAILURE too, not only on a success.
    #
    # It used to require value is not None, so an unreadable capability was
    # never cached at all and every single call re-probed /api/show. Measured
    # on one generate_response() call with Ollama unreachable: FOUR requests,
    # three of them /api/show, against a 5-second timeout each. Against a
    # daemon that accepts the connection and then hangs -- which is a real
    # state for Ollama, and the state this box was in -- that is up to 15
    # seconds added to every query before the genuine error can surface.
    #
    # The failure TTL is deliberately short. §16's rule for a failed telemetry
    # session is that failure must not be permanent, so an eGPU plugged in
    # mid-session gets picked up; the same applies here, and 5 s is short
    # enough that a restarted Ollama is noticed almost immediately while still
    # collapsing the burst of probes a single query makes.
    ttl = _CAP_TTL if _cap_cache["ok"] else _CAP_FAIL_TTL
    # `at is None` means "never probed", which must never satisfy the TTL. A
    # 0.0 sentinel would not be safe: time.monotonic() is measured from an
    # arbitrary origin and is small on some platforms, so a fresh process could
    # report "unreadable" for the first seconds of its life purely because the
    # clock had not reached the sentinel.
    if _cap_cache["at"] is not None and (now - _cap_cache["at"]) < ttl:
        return _cap_cache["value"]

    settings = _settings()
    value = None
    try:
        r = requests.post(
            f"{settings.ollama_base_url}/api/show",
            json={"model": settings.ollama_model},
            timeout=5)
        if r.status_code == 200:
            body = r.json() or {}
            # /api/show nests this differently across Ollama builds: some expose
            # llama.context_length, most only model_info.<arch>.context_length.
            # Read both rather than assume one, and report None if neither is
            # there instead of guessing a number we would then budget against.
            nested = ((body.get("llama") or {}).get("context_length"))
            candidates = [nested] if isinstance(nested, int) else []
            for k, v in (body.get("model_info") or {}).items():
                if k.endswith("context_length") and isinstance(v, int):
                    candidates.append(v)
            positives = [c for c in candidates if isinstance(c, int) and c > 0]
            if positives:
                value = max(positives)
    except Exception:
        # Cannot measure. The configured value governs, and requesting a window
        # the model cannot honour is caught by the saturation check at the
        # response rather than by a guess made here.
        pass

    _cap_cache["value"] = value
    _cap_cache["at"] = now
    _cap_cache["ok"] = value is not None
    return value


def requested_context_tokens() -> int:
    """
    The window we ASK Ollama to serve, clamped to what the model can do.

    This is the fix for the setting that was not a setting. ollama_num_ctx used
    to feed only the *reporting* path, so raising it made the app budget as if
    it had room while Ollama kept serving its own 4,096 default and truncated
    the evidence in silence -- B26's exact mechanism, re-armed by the obvious
    "fix". Passing num_ctx on the request is what makes the number a control,
    and clamping to the model's real capability is what stops that control from
    asking for a window that does not exist.
    """
    settings = _settings()
    configured = int(settings.ollama_num_ctx)
    if configured <= 0:
        configured = 4096
    cap = model_context_limit()
    if cap:
        return max(1024, min(configured, cap))
    return max(1024, configured)


def effective_context_tokens() -> int:
    """
    The context window the model is being served with, not the one it was
    trained for.

    Two sources, in order of authority:

    1. /api/ps, which only lists a model once it is loaded. This is a genuine
       measurement, so it wins when it exists.
    2. otherwise, the window we requested -- which is the honest answer, because
       we now send num_ctx on every request and Ollama honours it (verified:
       a 4,096-clamped request returned prompt_eval_count 10,044 once
       num_ctx: 16384 was asked for).

    The caveat, stated rather than implied: this Ollama build's /api/ps carries
    no context_length at all -- its details are families/family/format/
    parameter_size/parent_model/quantization_level -- so path 1 never fires
    here and the requested value always governs. That is why the request, not
    the probe, is the load-bearing half. If a future build does report it, the
    measurement takes over automatically and nothing else changes.
    """
    now = time.monotonic()
    if _ctx_cache["value"] and (now - _ctx_cache["at"]) < _CTX_TTL:
        return _ctx_cache["value"]

    settings = _settings()
    value = requested_context_tokens()

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
        # Cannot measure. The requested value stands, and the saturation and
        # truncation checks at the response are what stop a wrong guess from
        # going unnoticed.
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
        # The context window is the single biggest lever on answer quality and
        # nothing reported it, so a 4,096-token model and a 16,384-token one
        # looked identical from the outside. Both are reported because they are
        # different facts and only the second one bounds a prompt: the model is
        # *trained* for one length and *served* with another, and conflating
        # them is what made B26's overflow inevitable.
        #
        # `model_context_tokens` is None when /api/show cannot be read. That is
        # a capability that could not be measured, not a model with no context.
        "model_context_tokens": model_context_limit(),
        "requested_context_tokens": requested_context_tokens(),
        "effective_context_tokens": effective_context_tokens(),
        "prompt_budget_tokens": prompt_budget_tokens(),
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
            "num_predict": settings.ollama_num_predict,
            # Without this, Ollama applies its own default (4,096 for this
            # model) and the app has no way to widen it -- the prompt is
            # accepted, silently truncated, and answered from its tail. Sending
            # it is what makes ollama_num_ctx a control rather than a number
            # that only ever appears in the budget arithmetic.
            "num_ctx": requested_context_tokens(),
            # Fixed so the same evidence and the same question give the same
            # answer. temperature 0.1 still samples, and an investigator
            # re-running a query to check an answer they are about to quote in a
            # report must not get a different one. See dependencies.py.
            "seed": settings.ollama_seed,
            # top_p, top_k and repeat_penalty are deliberately NOT set. Ollama
            # already defaults them to 0.9 / 40 / 1.1, so sending them would
            # change nothing while implying they had been considered here.
            # They were considered: temperature is already near-greedy, which
            # is right for a factual claim and is the setting that grounds
            # answers in the retrieved text rather than in the model's priors.
            # The one real risk at low temperature is repetition on repetitive
            # evidence -- a prompt full of log lines is full of repeated
            # timestamps and IPs -- and repeat_penalty at its 1.1 default is
            # what already guards it.
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

    # Second, independent guard. Saturation asks "did we fill the window we
    # asked for"; this asks "did Ollama read most of what we sent". They fail
    # differently, and the case they cover is the one that produced B26: a
    # window smaller than we believe we have, so the prompt is cut while
    # eval_count stays comfortably below `limit` and saturation stays False.
    estimated = prompt_stats.get("estimated_tokens")
    lost_most = (
        isinstance(estimated, int) and isinstance(eval_count, int)
        and estimated > 0
        and eval_count < estimated * _TRUNCATION_LOSS_RATIO)
    prompt_stats["evidence_lost"] = lost_most
    prompt_stats["requested_context_tokens"] = requested_context_tokens()

    return {
        "text": text,
        "prompt_eval_count": eval_count,
        "eval_tokens": body.get("eval_count"),
        "error": None,
        # A prompt that filled the window to the last token is a prompt
        # Ollama truncated. It is not a slow answer, it is a different
        # answer, and it arrives looking exactly like a successful one.
        "saturated": prompt_stats["overflowed"] or lost_most,
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
