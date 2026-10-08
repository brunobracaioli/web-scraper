"""HTML → Markdown: main-content extraction, cleanup, link absolutization, front matter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, Tag
from markdownify import markdownify

from web_scraper.cleaner import clean_content, clean_title

NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "template", "form")
CONTENT_SELECTORS = ("main", "article", "body")
URL_ATTRIBUTES = {"a": "href", "img": "src"}
EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
# React streaming SSR runtime calls: $RC("B:n","S:n") fills a Suspense boundary,
# $RS("S:n","P:n") fills a placeholder. The browser runs them; we replay them.
REACT_STREAM_CALL = re.compile(r'\$R([CS])\("([^"]+)","([^"]+)"\)')
SUSPENSE_START_MARKERS = frozenset({"$", "$?", "$!"})
SUSPENSE_END_MARKER = "/$"


@dataclass(frozen=True, slots=True)
class Page:
    source_url: str
    final_url: str
    html: bytes
    encoding: str | None
    scraped_at: datetime
    run_id: str


@dataclass(frozen=True, slots=True)
class Conversion:
    """A converted page, rendered by `to_markdown` and `structure.to_json`."""

    metadata: Mapping[str, str]
    body: str  # Markdown without front matter


def convert(page: Page, *, clean: bool = True) -> Conversion:
    soup = BeautifulSoup(page.html, "html.parser", from_encoding=page.encoding)
    title = _extract_title(soup) or page.final_url
    _inline_react_streamed_chunks(soup)
    content = _select_content(soup)
    if clean:
        title = clean_title(title)
        # Before _strip_noise: svg icons must leave a space, not glue words together.
        clean_content(soup, content)
    _strip_noise(content)
    _absolutize_urls(content, page.final_url)

    body = markdownify(str(content), heading_style="ATX", bullets="-")
    body = EXCESS_BLANK_LINES.sub("\n\n", body).strip()
    # A cleaned page keeps its own <h1>; a second, synthesized one would be noise.
    heading = "" if clean and content.find("h1") else f"# {title}\n\n"

    return Conversion(metadata=_metadata(page, title), body=f"{heading}{body}")


def to_markdown(conversion: Conversion) -> str:
    return f"{_front_matter(conversion.metadata)}\n{conversion.body}\n"


def _extract_title(soup: BeautifulSoup) -> str | None:
    for tag in (soup.title, soup.find("h1")):
        if isinstance(tag, Tag):
            text = " ".join(tag.get_text().split())
            if text:
                return text
    return None


def _inline_react_streamed_chunks(soup: BeautifulSoup) -> None:
    """Move streamed chunks (hidden `S:n` divs) into place, replacing skeletons."""
    for script in soup.find_all("script"):
        for kind, first_id, second_id in REACT_STREAM_CALL.findall(script.get_text()):
            is_boundary = kind == "C"
            target_id, segment_id = (first_id, second_id) if is_boundary else (second_id, first_id)
            target = soup.find("template", id=target_id)
            segment = soup.find(id=segment_id)
            if not isinstance(target, Tag) or not isinstance(segment, Tag):
                continue
            if is_boundary:
                _remove_suspense_fallback(target)
            target.insert_before(*list(segment.contents))
            target.decompose()
            segment.decompose()


def _remove_suspense_fallback(template: Tag) -> None:
    """Drop the loading fallback between the boundary template and its `<!--/$-->`."""
    depth = 0
    node = template.next_sibling
    while node is not None:
        following = node.next_sibling
        if isinstance(node, Comment):
            if node == SUSPENSE_END_MARKER:
                if depth == 0:
                    return
                depth -= 1
            elif node in SUSPENSE_START_MARKERS:
                depth += 1
        node.extract()
        node = following


def _select_content(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    for selector in CONTENT_SELECTORS:
        tag = soup.find(selector)
        if isinstance(tag, Tag):
            return tag
    return soup


def _strip_noise(root: Tag | BeautifulSoup) -> None:
    for tag in root.find_all(NOISE_TAGS):
        tag.decompose()


def _absolutize_urls(root: Tag | BeautifulSoup, base_url: str) -> None:
    for tag_name, attribute in URL_ATTRIBUTES.items():
        for tag in root.find_all(tag_name):
            value = tag.get(attribute)
            if not isinstance(value, str):
                continue
            if value.strip().lower().startswith("javascript:"):
                tag.unwrap()
                continue
            tag[attribute] = urljoin(base_url, value)


def _metadata(page: Page, title: str) -> dict[str, str]:
    return {
        "title": title,
        "source_url": page.source_url,
        "final_url": page.final_url,
        "scraped_at": page.scraped_at.isoformat(),
        "run_id": page.run_id,
    }


def _front_matter(metadata: Mapping[str, str]) -> str:
    # JSON strings are valid YAML scalars, so this is safe to emit as-is.
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()]
    return "---\n" + "\n".join(lines) + "\n---\n"
