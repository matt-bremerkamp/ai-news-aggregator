"""Render curated articles into Markdown + HTML using Jinja2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .ai import Curated

TEMPLATE_DIR = Path("templates")
CATEGORY_ORDER = (
    "Healthcare Payments",
    "Consumer Payments",
    "Product Management & AI",
)


@dataclass
class CategoryGroup:
    name: str
    items: list[Curated]


def _group_by_category(items: Iterable[Curated]) -> list[CategoryGroup]:
    buckets: dict[str, list[Curated]] = {}
    for item in items:
        buckets.setdefault(item.article.category, []).append(item)
    for category_items in buckets.values():
        category_items.sort(key=lambda c: c.article.published, reverse=True)

    ordered: list[CategoryGroup] = []
    for name in CATEGORY_ORDER:
        if name in buckets:
            ordered.append(CategoryGroup(name=name, items=buckets.pop(name)))
    for name, items_ in buckets.items():
        ordered.append(CategoryGroup(name=name, items=items_))
    return ordered


def _env(autoescape: bool) -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(enabled_extensions=("html",)) if autoescape else False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


@dataclass
class Rendered:
    markdown: str
    html: str
    plain_text: str
    total_items: int
    digest_date: date


def render(curated: list[Curated], *, digest_date: date | None = None) -> Rendered:
    digest_date = digest_date or date.today()
    categories = _group_by_category(curated)
    context = {
        "date": digest_date.strftime("%A, %B %d, %Y"),
        "categories": categories,
        "total_items": sum(len(c.items) for c in categories),
    }

    md_env = _env(autoescape=False)
    html_env = _env(autoescape=True)
    markdown = md_env.get_template("digest.md.j2").render(**context)
    html = html_env.get_template("digest.html.j2").render(**context)

    return Rendered(
        markdown=markdown,
        html=html,
        plain_text=markdown,
        total_items=context["total_items"],
        digest_date=digest_date,
    )
