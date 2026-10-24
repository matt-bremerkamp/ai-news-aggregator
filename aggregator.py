"""Entry point for the daily news aggregator.

Usage:
  python aggregator.py            # full run: fetch, curate, email, archive, commit-ready
  python aggregator.py --dry-run  # fetch + curate + print Markdown; no email, no writes

Designed for GitHub Actions: the workflow runs this script, then commits
``digests/`` and ``history.json`` back to the repo.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from aggregator.ai import curate
from aggregator.email_send import EmailConfigError, send
from aggregator.feeds import fetch_all, load_feeds
from aggregator.history import History
from aggregator.render import render

log = logging.getLogger("aggregator")

DIGESTS_DIR = Path("digests")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily news aggregator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and curate, then print the Markdown digest. Do not email, archive, or update history.",
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="Run end to end but skip the SMTP step (useful when secrets are unset).",
    )
    return parser.parse_args(argv)


def _write_archive(markdown: str, digest_date: date) -> Path:
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGESTS_DIR / f"{digest_date.isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    log.info("Wrote archive %s", path)
    return path


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = _parse_args(argv)

    now = datetime.now(timezone.utc)
    log.info("Run starting at %s (UTC)", now.isoformat())

    sources = load_feeds()
    history = History.load()

    fresh = fetch_all(sources, history, now=now)
    log.info("Fetched %d candidate articles after dedup + freshness filter", len(fresh))

    curated = curate(fresh)
    log.info("Curated down to %d articles after relevance filter", len(curated))

    rendered = render(curated, digest_date=now.date())

    if args.dry_run:
        print(rendered.markdown)
        log.info("Dry run complete; skipping email, archive, and history update.")
        return 0

    if rendered.total_items == 0:
        log.warning("No items survived curation today; skipping email but still updating history.")
    elif not args.skip_email:
        try:
            send(rendered)
        except EmailConfigError as exc:
            log.error("Email config error: %s", exc)
            return 2
        except Exception:  # noqa: BLE001 -- log and keep archive on any SMTP failure
            log.exception("Email send failed; archive will still be written.")

    _write_archive(rendered.markdown, rendered.digest_date)

    history.add([c.article.link for c in curated])
    history.add([a.link for a in fresh])
    history.prune()
    history.save()
    log.info("History saved with %d entries.", len(history.seen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
