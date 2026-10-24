"""Load ``feeds.yaml`` and fetch the latest entries with feedparser.

Each feed is wrapped in try/except so one broken source never kills the run.
We keep the newest ``PER_FEED_LIMIT`` entries, drop anything older than
``RECENT_WINDOW_HOURS``, and drop anything already in the ``History`` store.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import yaml

from .history import History

log = logging.getLogger(__name__)

PER_FEED_LIMIT = 5
RECENT_WINDOW_HOURS = 48
SUMMARY_MAX_CHARS = 800


@dataclass
class FeedSource:
    category: str
    name: str
    url: str


@dataclass
class Article:
    id: str
    category: str
    source: str
    title: str
    link: str
    summary: str
    published: datetime


def load_feeds(path: Path = Path("feeds.yaml")) -> list[FeedSource]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    sources: list[FeedSource] = []
    for item in raw:
        sources.append(
            FeedSource(
                category=item["category"].strip(),
                name=item["name"].strip(),
                url=item["url"].strip(),
            )
        )
    return sources


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_summary(raw: str) -> str:
    if not raw:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[: SUMMARY_MAX_CHARS - 1].rstrip() + "\u2026"
    return text


def _entry_published(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        tm = getattr(entry, attr, None) or (
            entry.get(attr) if hasattr(entry, "get") else None
        )
        if tm:
            try:
                return datetime(*tm[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _fetch_one(source: FeedSource) -> list[Article]:
    parsed = feedparser.parse(source.url)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        exc = getattr(parsed, "bozo_exception", None)
        log.warning("Feed parse error for %s (%s): %s", source.name, source.url, exc)
        return []

    articles: list[Article] = []
    for entry in parsed.entries[:PER_FEED_LIMIT]:
        link = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not link or not title:
            continue
        published = _entry_published(entry) or datetime.now(timezone.utc)
        summary = _clean_summary(entry.get("summary") or entry.get("description") or "")
        articles.append(
            Article(
                id=entry.get("id") or link,
                category=source.category,
                source=source.name,
                title=title,
                link=link,
                summary=summary,
                published=published,
            )
        )
    return articles


def fetch_all(
    sources: Iterable[FeedSource],
    history: History,
    *,
    window_hours: int = RECENT_WINDOW_HOURS,
    now: datetime | None = None,
) -> list[Article]:
    """Fetch every source, dropping stale or already-seen articles."""

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=window_hours)
    results: list[Article] = []
    for source in sources:
        try:
            entries = _fetch_one(source)
        except Exception:  # noqa: BLE001 -- one broken source must not kill the run
            log.exception("Failed to fetch %s", source.name)
            continue
        for art in entries:
            if art.published < cutoff:
                continue
            if history.contains(art.link):
                continue
            results.append(art)
    return results
