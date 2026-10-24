"""Gemini-powered relevance filter + 'why it matters' generator.

We batch one call per category so we stay well inside the free tier rate limits
and only send the minimum per-article metadata Gemini needs to reason.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Iterable

import google.generativeai as genai

from .feeds import Article

log = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.5-flash-lite"
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0

TOPICS = (
    "healthcare payments technology",
    "consumer payments technology and solutions",
    "product management practices",
    "AI adoption in product management design and development",
)

_PROMPT_TEMPLATE = """You curate a newsletter for a product manager focused on:
- healthcare payments technology
- consumer payments technology and solutions
- product management practices
- AI adoption in product management design and development

For EACH article below, return strict JSON with:
  id (string, copy the input id exactly)
  relevant (boolean)
  why_it_matters (1-2 sentences explaining the impact for a PM in the topics above; empty string when relevant is false)

Drop marketing fluff, job listings, vendor press releases with no substance, and items unrelated to the four topics above.

Articles:
{json_articles}

Respond with a JSON array only, no prose, no markdown fences.
"""


@dataclass
class Curated:
    article: Article
    why_it_matters: str


def _configured_model() -> genai.GenerativeModel | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY not set; skipping AI curation.")
        return None
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(MODEL_NAME)


def _articles_payload(articles: list[Article]) -> str:
    return json.dumps(
        [
            {
                "id": art.id,
                "title": art.title,
                "source": art.source,
                "summary": art.summary,
            }
            for art in articles
        ],
        ensure_ascii=False,
    )


def _parse_response(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Gemini response was not valid JSON: %s", text[:500])
        return []
    if not isinstance(data, list):
        log.warning("Gemini response was not a JSON array: %s", text[:500])
        return []
    return data


def _call_model(model: genai.GenerativeModel, prompt: str) -> str | None:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                },
            )
            return getattr(response, "text", None)
        except Exception as exc:  # noqa: BLE001 -- any SDK error should retry
            last_exc = exc
            wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            log.warning(
                "Gemini call failed (attempt %s/%s): %s; sleeping %.1fs",
                attempt,
                MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)
    log.error("Gemini call giving up after %s attempts: %s", MAX_RETRIES, last_exc)
    return None


def _curate_category(
    model: genai.GenerativeModel, articles: list[Article]
) -> list[Curated]:
    if not articles:
        return []
    prompt = _PROMPT_TEMPLATE.format(json_articles=_articles_payload(articles))
    raw = _call_model(model, prompt)
    if raw is None:
        return [Curated(article=a, why_it_matters="") for a in articles]

    results = _parse_response(raw)
    verdicts = {item.get("id"): item for item in results if isinstance(item, dict)}

    curated: list[Curated] = []
    for art in articles:
        verdict = verdicts.get(art.id)
        if verdict is None:
            curated.append(Curated(article=art, why_it_matters=""))
            continue
        if not verdict.get("relevant", False):
            continue
        why = (verdict.get("why_it_matters") or "").strip()
        curated.append(Curated(article=art, why_it_matters=why))
    return curated


def curate(articles: Iterable[Article]) -> list[Curated]:
    """Filter articles via Gemini and attach a 'why it matters' line.

    If Gemini is unavailable (no key, repeated failures), all articles survive
    without a ``why_it_matters`` so the digest still ships.
    """

    by_category: dict[str, list[Article]] = {}
    for art in articles:
        by_category.setdefault(art.category, []).append(art)

    model = _configured_model()
    if model is None:
        return [Curated(article=a, why_it_matters="") for a in articles]

    curated_all: list[Curated] = []
    for category, items in by_category.items():
        log.info("Curating %s (%d articles)", category, len(items))
        curated_all.extend(_curate_category(model, items))
    return curated_all
