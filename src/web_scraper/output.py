"""Output file naming and writing (Markdown and its JSON sibling)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

MAX_SLUG_LENGTH = 120
NON_SLUG_CHARS = re.compile(r"[^a-z0-9.]+")
RUN_ID_LENGTH = 8
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
MARKDOWN_SUFFIX = ".md"
JSON_SUFFIX = ".json"


def new_run_id() -> str:
    """Short random id telling scrape attempts apart (file name, front matter, logs)."""
    return uuid.uuid4().hex[:RUN_ID_LENGTH]


def output_filename(url: str, scraped_at: datetime, run_id: str) -> str:
    """`<slug>_<UTC timestamp>_<run id>.md`: unique per attempt, sorts chronologically."""
    timestamp = scraped_at.astimezone(UTC).strftime(TIMESTAMP_FORMAT)
    return f"{slug_for_url(url)}_{timestamp}_{run_id}{MARKDOWN_SUFFIX}"


def slug_for_url(url: str) -> str:
    """Filesystem-safe name from host + path (no separators, so no traversal)."""
    parts = urlsplit(url)
    raw = f"{parts.hostname or ''}-{parts.path}".lower()
    slug = NON_SLUG_CHARS.sub("-", raw).strip("-.")[:MAX_SLUG_LENGTH].rstrip("-.")
    return slug or "page"


def json_path_for(markdown_path: Path) -> Path:
    """The JSON goes next to the Markdown: `page.md` → `page.json`, `page` → `page.json`."""
    if markdown_path.suffix.lower() == MARKDOWN_SUFFIX:
        return markdown_path.with_suffix(JSON_SUFFIX)
    # with_suffix would eat part of the name ("v1.2" → "v1.json") and could collide.
    return markdown_path.with_name(markdown_path.name + JSON_SUFFIX)


def write_text(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
