"""Persistent dedup store for already-processed article URLs.

The file on disk is ``history.json`` in the repo root. Each entry records the
sha1 of the article URL plus the ISO timestamp it was first seen, so we can
prune old entries and keep the file compact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_PATH = Path("history.json")
PRUNE_AFTER_DAYS = 30


def url_hash(url: str) -> str:
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()


@dataclass
class History:
    seen: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "History":
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return cls()
        entries = raw.get("entries", [])
        seen = {e["hash"]: e["seen_at"] for e in entries if "hash" in e and "seen_at" in e}
        return cls(seen=seen)

    def contains(self, url: str) -> bool:
        return url_hash(url) in self.seen

    def add(self, urls: Iterable[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for url in urls:
            h = url_hash(url)
            self.seen.setdefault(h, now)

    def prune(self, max_age_days: int = PRUNE_AFTER_DAYS) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        kept: dict[str, str] = {}
        for h, ts in self.seen.items():
            try:
                seen_at = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if seen_at.tzinfo is None:
                seen_at = seen_at.replace(tzinfo=timezone.utc)
            if seen_at >= cutoff:
                kept[h] = ts
        self.seen = kept

    def save(self, path: Path = DEFAULT_PATH) -> None:
        entries = [{"hash": h, "seen_at": ts} for h, ts in sorted(self.seen.items())]
        path.write_text(
            json.dumps({"entries": entries}, indent=2) + "\n",
            encoding="utf-8",
        )
