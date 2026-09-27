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


def generate_response(prompt: str,
                      system_prompt: str = "",
                      model: str = None
                      ) -> str:
    """
    Returns the model's text.

    Ollama reports its own failures as JSON — {"error": "model ... not found"}
    with a 404 — and this used to read only .get("response", ""), which threw
    that message away and returned an empty string. An empty string then became
    "The AI did not generate a response. Please try rephrasing your question."
    in rag_engine, which is not just useless advice but actively misleading:
    no rewording of the question can install a model.

    So the status code is checked, the error field is surfaced, and the caller
    is told what to do about it.
    """
    settings = _settings()
    if model is None:
        model = settings.ollama_model
    url = f"{settings.ollama_base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 1024
        }
    }

    try:
        r = requests.post(url, json=payload, timeout=120)
    except Exception as e:
        return (f"⚠️ Cannot reach Ollama at "
                f"{settings.ollama_base_url} ({type(e).__name__}). "
                f"Start it with `ollama serve`, then ask again. "
                f"Nothing was searched — your question was not answered.")

    # Ollama answers 4xx/5xx with {"error": "..."} rather than a prose
    # message, so this is the only place the real cause is visible.
    try:
        body = r.json()
    except Exception:
        return (f"⚠️ Ollama returned HTTP {r.status_code} with a "
                f"non-JSON body. The model could not be reached.")

    if r.status_code != 200 or body.get("error"):
        detail = (body.get("error")
                  or f"HTTP {r.status_code}").strip()
        low = detail.lower()
        if "not found" in low:
            return (f"⚠️ The model '{model}' is not installed on this "
                    f"machine, so there is nothing to answer with. "
                    f"Fix it with: ollama pull {model} — then ask again. "
                    f"Your question was not searched.")
        return (f"⚠️ Ollama could not generate a response "
                f"({detail}). Your question was not answered.")

    text = body.get("response")
    if text is None:
        return (f"⚠️ Ollama returned no 'response' field "
                f"(HTTP {r.status_code}).")
    return text
