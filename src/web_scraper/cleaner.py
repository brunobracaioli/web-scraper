"""Cleanup of extracted content: drops page chrome, images and hidden duplicates.

Generic rules (no per-site code), applied before rendering Markdown. See the
"Cleanup" section of docs/specs/url-to-markdown.md.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Tag
from bs4.element import NavigableString, PageElement

GRAPHIC_TAGS = ("img", "svg", "picture")
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
BUTTON_ROLE = "button"
NAVIGATION_ROLE = "navigation"
# Not rendered by the browser, so they never separate the words around them.
INVISIBLE_TAGS = frozenset({"script", "style", "template", "noscript"})
NON_TEXT_PARENTS = frozenset(GRAPHIC_TAGS) | INVISIBLE_TAGS
# sub/sup are left out on purpose: "H<sub>2</sub>O" must not become "H 2 O".
INLINE_TAGS = frozenset(
    {
        "a", "abbr", "b", "bdi", "cite", "code", "data", "dfn", "em", "i", "kbd",
        "label", "mark", "q", "s", "samp", "small", "span", "strong", "time", "u", "var",
    }
)  # fmt: skip
MIN_LINK_GROUP_SIZE = 2
DIGIT = re.compile(r"\d")
COUNT = re.compile(r"\d[\d.,]*\s?[kKmMbB]?\+?")
DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.IGNORECASE)
# " | ", " - ", en/em dash, middle dot and bullet, each surrounded by spaces.
TITLE_SEPARATOR = re.compile(r"(\s+[|\-\u2013\u2014\u00b7\u2022]\s+)")

# Display utilities per breakpoint, narrowest first, as (class prefix, "hide" utility):
# Tailwind `hidden` / `md:hidden` / `md:flex`, Bootstrap `d-none` / `d-md-none` / `d-md-flex`.
BREAKPOINTS = (
    (("", "hidden"), ("d-", "none")),
    (("sm:", "hidden"), ("d-sm-", "none")),
    (("md:", "hidden"), ("d-md-", "none")),
    (("lg:", "hidden"), ("d-lg-", "none")),
    (("xl:", "hidden"), ("d-xl-", "none")),
    (("2xl:", "hidden"), ("d-xxl-", "none")),
)
DISPLAY_UTILITIES = frozenset(
    {
        "block", "inline", "inline-block", "flex", "inline-flex", "grid", "inline-grid",
        "table", "table-row", "table-cell", "contents", "flow-root", "list-item",
    }
)  # fmt: skip


def clean_title(title: str) -> str:
    """Drop consecutive repeated segments: "A - Site | Site" → "A - Site"."""
    parts = TITLE_SEPARATOR.split(title)
    kept = [parts[0]]
    for separator, segment in zip(parts[1::2], parts[2::2], strict=True):
        if segment.casefold() != kept[-1].casefold():
            kept += [separator, segment]
    return "".join(kept)


def clean_content(soup: BeautifulSoup, root: Tag | BeautifulSoup) -> None:
    """Strip chrome and images from `root` in place, keeping its information."""
    _drop_hidden(root)
    _drop_chrome(root)
    _replace_graphics(root)
    _fold_heading_counts(root)
    _link_groups_to_lists(soup, root)
    _space_adjacent_inlines(root)
    _drop_redundant_link_titles(root)


def _drop_hidden(root: Tag | BeautifulSoup) -> None:
    for tag in root.find_all(_is_hidden):
        _remove(tag)


def _is_hidden(tag: Tag) -> bool:
    if tag.has_attr("hidden") or _attr(tag, "aria-hidden").lower() == "true":
        return True
    if DISPLAY_NONE.search(_attr(tag, "style")):
        return True
    return _hidden_at_widest_breakpoint(tag.get_attribute_list("class"))


def _hidden_at_widest_breakpoint(classes: list[str]) -> bool:
    """Replay display utilities from narrowest to widest breakpoint (desktop wins)."""
    hidden = False
    for utilities in BREAKPOINTS:
        for name in classes:
            for prefix, hide in utilities:
                if not name.startswith(prefix):
                    continue
                utility = name.removeprefix(prefix)
                if utility == hide:
                    hidden = True
                elif utility in DISPLAY_UTILITIES:
                    hidden = False
    return hidden


def _drop_chrome(root: Tag | BeautifulSoup) -> None:
    for tag in root.find_all(_is_navigation):
        _remove(tag)
    for button in root.find_all(_is_button):
        if DIGIT.search(button.get_text()):
            button.unwrap()  # counters such as "5 upvotes" carry data
        else:
            _remove(button)


def _is_navigation(tag: Tag) -> bool:
    return tag.name == "nav" or _attr(tag, "role") == NAVIGATION_ROLE


def _is_button(tag: Tag) -> bool:
    return tag.name == "button" or _attr(tag, "role") == BUTTON_ROLE


def _replace_graphics(root: Tag | BeautifulSoup) -> None:
    for link in root.find_all("a", href=True):
        if _visible_text(link) or link.find(GRAPHIC_TAGS) is None:
            continue
        label = _graphic_label(link)
        if not label or _parent_links_with_text(link):
            _remove(link)
            continue
        link.clear()
        link.append(label)
    for graphic in root.find_all(GRAPHIC_TAGS):
        _remove(graphic)


def _graphic_label(link: Tag) -> str:
    for label in (_attr(link, "aria-label"), _attr(link, "title")):
        if label:
            return label
    for image in link.find_all("img"):
        alt = _attr(image, "alt")
        if alt:
            return alt
    return ""


def _parent_links_with_text(link: Tag) -> bool:
    """True when a sibling subtree already links to the same URL with text."""
    if link.parent is None:
        return False
    return any(
        other is not link and _visible_text(other)
        for other in link.parent.find_all("a", href=_attr(link, "href"))
    )


def _fold_heading_counts(root: Tag | BeautifulSoup) -> None:
    for heading in root.find_all(HEADING_TAGS):
        badge = _next_significant_sibling(heading)
        if not isinstance(badge, Tag) or badge.name not in INLINE_TAGS:
            continue
        count = badge.get_text(strip=True)
        if COUNT.fullmatch(count):
            heading.append(f" ({count})")
            badge.decompose()


def _next_significant_sibling(tag: Tag) -> PageElement | None:
    for sibling in tag.next_siblings:
        if not _is_transparent(sibling):
            return sibling
    return None


def _link_groups_to_lists(soup: BeautifulSoup, root: Tag | BeautifulSoup) -> None:
    for container in root.find_all("div"):
        children = [child for child in container.children if not _is_transparent(child)]
        if len(children) < MIN_LINK_GROUP_SIZE:
            continue
        if not all(isinstance(child, Tag) and child.name == "a" for child in children):
            continue
        group = soup.new_tag("ul")
        for link in children:
            item = soup.new_tag("li")
            item.append(link.extract())
            group.append(item)
        container.append(group)


def _space_adjacent_inlines(root: Tag | BeautifulSoup) -> None:
    for parent in [root, *root.find_all(True)]:
        previous: Tag | None = None
        for node in list(parent.children):
            if _is_invisible(node) or (isinstance(node, NavigableString) and not node):
                continue
            if not isinstance(node, Tag) or node.name not in INLINE_TAGS:
                previous = None
                continue
            if previous is not None and _touches(previous, node):
                node.insert_before(" ")
            previous = node


def _touches(left: Tag, right: Tag) -> bool:
    """Both have text and nothing (not even a space) sits between them."""
    left_text, right_text = left.get_text(), right.get_text()
    if not left_text.strip() or not right_text.strip():
        return False
    return not left_text[-1].isspace() and not right_text[0].isspace()


def _drop_redundant_link_titles(root: Tag | BeautifulSoup) -> None:
    for link in root.find_all("a", title=True):
        if _attr(link, "title").casefold() == link.get_text(strip=True).casefold():
            del link["title"]


def _remove(tag: Tag) -> None:
    """Detach `tag`; between two siblings it leaves a space so their words don't merge."""
    if tag.parent is None:
        return
    if tag.previous_sibling is not None and tag.next_sibling is not None:
        tag.replace_with(" ")
    else:
        tag.extract()  # a space at the edge would surface as "[ text](url)" or " text"


def _is_invisible(node: PageElement) -> bool:
    return isinstance(node, Comment) or (isinstance(node, Tag) and node.name in INVISIBLE_TAGS)


def _is_transparent(node: PageElement) -> bool:
    """Contributes no visible text: comments, whitespace, empty or invisible tags."""
    if _is_invisible(node):
        return True
    if isinstance(node, Tag):
        return not _visible_text(node)
    return not str(node).strip()


def _visible_text(tag: Tag) -> str:
    """Text a reader sees, ignoring comments and text inside graphics (svg <title>)."""
    return "".join(
        text
        for text in tag.find_all(string=True)
        if not isinstance(text, Comment)
        and not any(parent.name in NON_TEXT_PARENTS for parent in text.parents)
    ).strip()


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name)
    return value.strip() if isinstance(value, str) else ""
