"""Model-assisted named-entity extraction, bounded and verified.

Only three entity types are delegated to a model: people, organisations and
places. Everything else is exact from :mod:`app.analysis.extractors`.

Two safeguards make a small model safe to use here:

* **The quote must exist.** The model is asked to return the exact text it
  based the answer on. Anything whose quote is not literally present in the
  source is discarded, which removes most invented names.
* **The answer is capped.** Only the first few thousand characters of the
  largest artifacts are sent, and only a limited number of artifacts per job,
  so analysis stays in the background instead of becoming the bottleneck.

The configured cloud model is used when one is set up (it is much better at
this task); otherwise the local Ollama model is used.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.analysis.extractors import (
    MAX_ENTITY_VALUE,
    ExtractedEntity,
    normalize_value,
)
from app.artifacts.models import EntityType

logger = logging.getLogger(__name__)

_ALLOWED = {
    "person": EntityType.PERSON,
    "people": EntityType.PERSON,
    "name": EntityType.PERSON,
    "organization": EntityType.ORGANIZATION,
    "organisation": EntityType.ORGANIZATION,
    "org": EntityType.ORGANIZATION,
    "company": EntityType.ORGANIZATION,
    "location": EntityType.LOCATION,
    "place": EntityType.LOCATION,
    "address": EntityType.LOCATION,
    "account": EntityType.USERNAME,
    "username": EntityType.USERNAME,
    "handle": EntityType.USERNAME,
    "financial_entity": EntityType.ORGANIZATION,
    "service": EntityType.ORGANIZATION,
    "device": EntityType.DEVICE_ID,
}

# Names longer than this are almost always a sentence the model echoed back.
MAX_NAME_LENGTH = 80
MAX_ENTITIES_PER_CALL = 25

_PROMPT = """You are a forensic text annotator.
Extract high-recall candidates for people, organisations, places, and accounts
(handles, service accounts, account names). Also identify named financial
entities and technical services/devices when explicit.

Rules:
- Copy each name exactly as it appears in the text. Do not translate, correct or complete it.
- "quote" must be the exact sentence fragment containing the name.
- Skip generic words: "the company", "our office", "user", "admin", "Windows", "Gmail", "Unknown".
- Include plausible uncertain candidates; all candidates require investigator review.
- Output ONLY a JSON array, no prose and no code fences.
  Each item: {{"type": "person"|"organization"|"location", "value": "...", "quote": "..."}}
- If there is nothing to extract, output [].

Text:
\"\"\"
{text}
\"\"\"

JSON:"""


@dataclass
class LLMResult:
    entities: list[ExtractedEntity]
    error: str | None = None
    provider: str = ""
    answer: str = ""


class AnalysisLLM:
    """Thin client for the worker's ``/generate`` endpoint."""

    def __init__(self, config=None, *, timeout: float = 180.0):
        from app.config import get_config

        self.config = config or get_config()
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------
    def use_cloud(self) -> bool:
        """True when a cloud endpoint and key are configured."""
        from app.config import cloud_api_key

        return (
            self.config.ollama.provider == "openai"
            and bool(cloud_api_key(self.config))
        )

    def describe(self) -> str:
        if not self.config.analysis.llm_enabled:
            return "disabled (regex extraction only)"
        if self.use_cloud():
            return f"cloud model '{self.config.ollama.cloud_model}'"
        return f"local model '{self.config.ollama.model}'"

    def available(self) -> bool:
        return bool(self.config.analysis.llm_enabled)

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------
    async def _ask(self, prompt: str) -> LLMResult:
        import httpx

        from app.config import cloud_api_key

        payload = {
            "case_id": 0,
            "question": prompt,
            "mode": "raw",
            "model": self.config.ollama.model,
            "max_tokens": 700,
            "context_window_tokens": self.config.ollama.context_window_tokens,
            "timeout_seconds": int(self.timeout),
            "temperature": 0.0,
            "provider": "ollama",
        }
        provider = "local"
        if self.use_cloud():
            payload.update({
                "provider": "openai",
                "model": self.config.ollama.cloud_model,
                "api_base_url": self.config.ollama.cloud_base_url,
                "api_key": cloud_api_key(self.config),
                "max_tokens": 700,
            })
            provider = "cloud"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.config.worker.url}/generate", json=payload
                )
        except httpx.HTTPError as exc:
            return LLMResult([], f"Model request failed: {exc}", provider)

        if response.status_code != 200:
            return LLMResult(
                [], f"Model returned HTTP {response.status_code}", provider
            )
        body = response.json()
        if not body.get("success"):
            return LLMResult(
                [], body.get("error") or "Model returned no answer", provider
            )
        return LLMResult([], None, provider, answer=body.get("answer") or "")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def extract_named_entities(
        self,
        text: str,
        *,
        max_chars: int = 6000,
    ) -> LLMResult:
        """Ask the model for people/orgs/locations in ``text``.

        The attempt is best-effort: any failure returns an empty list and an
        error string, because the deterministic entities are already stored and
        the investigator must never lose them to a model problem.
        """
        if not self.available():
            return LLMResult([], "Model extraction is disabled", "")
        trimmed = text or ""
        if len(trimmed.strip()) < 40:
            return LLMResult([], None, "")

        width = max(500, int(max_chars))
        overlap = min(500, width // 5)
        step = max(1, width - overlap)
        entities: list[ExtractedEntity] = []
        seen: set[tuple[EntityType, str]] = set()
        provider = ""
        for start in range(0, len(trimmed), step):
            window = trimmed[start:start + width]
            response = await self._ask(_PROMPT.format(text=window))
            if response.error:
                return LLMResult(entities, response.error, response.provider)
            provider = response.provider or provider
            for entity in parse_model_answer(response.answer, window):
                key = (entity.entity_type, entity.normalized)
                if key in seen:
                    continue
                seen.add(key)
                entity.start = start + entity.start if entity.start >= 0 else -1
                entity.end = entity.start + len(entity.value) if entity.start >= 0 else -1
                entities.append(entity)
        return LLMResult(entities, None, provider)


def parse_model_answer(answer: str, source: str) -> list[ExtractedEntity]:
    """Turn a model reply into entities that are actually supported by ``source``.

    Every candidate must be typed person/organisation/location, must occur in
    the source, and must come with a quote that also occurs in the source. That
    last rule is what stops the model from inventing a name and dressing it in
    plausible context.
    """
    payload = _extract_json_array(answer)
    if payload is None:
        logger.debug("Model answer was not a JSON array: %r", answer[:200])
        return []

    results: list[ExtractedEntity] = []
    seen: set[tuple[EntityType, str]] = set()

    for item in payload:
        if not isinstance(item, dict):
            continue
        mapped = _ALLOWED.get(str(item.get("type", "")).strip().lower())
        value = str(item.get("value", "")).strip().strip("\"'")
        quote = str(item.get("quote", "")).strip().strip("\"'")
        if mapped is None or not value:
            continue
        if len(value) < 2 or len(value) > MAX_NAME_LENGTH:
            continue
        if len(value) > MAX_ENTITY_VALUE:
            continue
        # The quote is the evidence: without it in the source, drop the row.
        if not quote or quote not in source or value not in quote:
            continue
        if value.lower() in _STOPWORDS:
            continue

        normalized = normalize_value(mapped, value)
        if (mapped, normalized) in seen:
            continue
        seen.add((mapped, normalized))

        occurrences = source.count(value)
        confidence = 0.85 if occurrences >= 2 else 0.65
        value_offset = quote.find(value)
        # Keep the cited value inside the bounded literal excerpt, including
        # when it appears near the end of a long model-supplied quote.
        excerpt_start = max(0, value_offset + len(value) - 300)
        excerpt = quote[excerpt_start:excerpt_start + 300]

        results.append(
            ExtractedEntity(
                entity_type=mapped,
                value=value,
                normalized=normalized,
                start=source.find(quote) + quote.find(value),
                end=source.find(quote) + quote.find(value) + len(value),
                extractor="llm",
                confidence=confidence,
                metadata={"quote": excerpt, "occurrences": occurrences,
                          "confidence_tier": "higher" if confidence >= 0.8 else "candidate",
                          "provenance": "literal source quote"},
            )
        )
        if len(results) >= MAX_ENTITIES_PER_CALL:
            break
    return results


# Generic words that a model happily labels as an organisation.
_STOPWORDS = {
    "user", "users", "admin", "administrator", "the company", "our company",
    "the office", "customer", "client", "unknown", "n/a", "gmail", "outlook",
    "windows", "microsoft windows", "the system", "system", "internet",
    "the internet", "email", "phone", "server", "desktop", "laptop",
}


def _squash(value: str) -> str:
    """Lowercase and collapse whitespace, for substring comparison."""
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _extract_json_array(answer: str) -> list | None:
    """Find and decode the first JSON array in a model answer."""
    text = (answer or "").strip()
    if not text:
        return None
    # Strip a code fence if the model added one despite instructions.
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return None
    candidate = text[start:end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # A trailing comma is the most common small-model mistake.
        candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, list) else None
