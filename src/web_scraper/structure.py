"""Markdown → JSON: sections by heading, typed blocks with plain text and links.

Built from the rendered Markdown body (not from the HTML), so the JSON carries
exactly the text and links of the .md file. See "JSON output" in
docs/specs/url-to-markdown.md.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Literal, NotRequired, TypedDict

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from web_scraper.converter import Conversion

SCHEMA_VERSION = 1
MARKDOWN = MarkdownIt("commonmark").enable("table")


class Link(TypedDict):
    text: str
    url: str


class Image(TypedDict):
    alt: str
    url: str


class InlineText(TypedDict):
    """Plain text of inline Markdown; `links`/`images` are omitted when empty."""

    text: str
    links: NotRequired[list[Link]]
    images: NotRequired[list[Image]]


class Paragraph(InlineText):
    type: Literal["paragraph"]


class ListItem(InlineText):
    blocks: NotRequired[list[Block]]  # nested lists and any further paragraphs


class ListBlock(TypedDict):
    type: Literal["list"]
    ordered: bool
    items: list[ListItem]


class Table(TypedDict):
    type: Literal["table"]
    header: list[str]
    rows: list[list[str]]
    links: NotRequired[list[Link]]


class Code(TypedDict):
    type: Literal["code"]
    language: str | None
    text: str


class Quote(TypedDict):
    type: Literal["quote"]
    blocks: list[Block]


type Block = Paragraph | ListBlock | Table | Code | Quote


class Section(TypedDict):
    heading: str
    level: int
    blocks: list[Block]
    sections: list[Section]
    links: NotRequired[list[Link]]  # when the heading itself is a link


class Document(TypedDict):
    schema_version: int
    metadata: dict[str, str]
    blocks: list[Block]  # content before the first heading
    sections: list[Section]


def to_json(conversion: Conversion) -> str:
    blocks, sections = _outline(conversion.body)
    document: Document = {
        "schema_version": SCHEMA_VERSION,
        "metadata": dict(conversion.metadata),
        "blocks": blocks,
        "sections": sections,
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _outline(markdown: str) -> tuple[list[Block], list[Section]]:
    """Nest sections by heading level: a heading closes the open ones at its level or deeper."""
    blocks: list[Block] = []
    sections: list[Section] = []
    open_sections: list[Section] = []
    for node in SyntaxTreeNode(MARKDOWN.parse(markdown)).children:
        if node.type == "heading":
            section = _section(node)
            while open_sections and open_sections[-1]["level"] >= section["level"]:
                open_sections.pop()
            (open_sections[-1]["sections"] if open_sections else sections).append(section)
            open_sections.append(section)
        else:
            (open_sections[-1]["blocks"] if open_sections else blocks).extend(_blocks([node]))
    return blocks, sections


def _section(heading: SyntaxTreeNode) -> Section:
    inline = _inline(heading)
    level = int(heading.tag.removeprefix("h"))
    section: Section = {"heading": inline["text"], "level": level, "blocks": [], "sections": []}
    if "links" in inline:
        section["links"] = inline["links"]
    return section


def _blocks(nodes: Iterable[SyntaxTreeNode]) -> list[Block]:
    blocks: list[Block] = []
    for node in nodes:
        match node.type:
            # Headings only get here nested in a quote or list item.
            case "paragraph" | "heading":
                blocks.append({"type": "paragraph", **_inline(node)})
            case "bullet_list" | "ordered_list":
                items = [_list_item(item) for item in node.children]
                blocks.append(
                    {"type": "list", "ordered": node.type == "ordered_list", "items": items}
                )
            case "table":
                blocks.append(_table(node))
            case "fence" | "code_block":
                language = node.info.split()[0] if node.info.split() else None
                blocks.append(
                    {"type": "code", "language": language, "text": node.content.rstrip("\n")}
                )
            case "blockquote":
                blocks.append({"type": "quote", "blocks": _blocks(node.children)})
            # hr and raw HTML carry no text worth keeping.
    return blocks


def _list_item(node: SyntaxTreeNode) -> ListItem:
    children = node.children
    lead: InlineText = {"text": ""}
    if children and children[0].type == "paragraph":
        lead, children = _inline(children[0]), children[1:]
    item: ListItem = {**lead, "blocks": _blocks(children)}
    if not item["blocks"]:
        del item["blocks"]
    return item


def _table(node: SyntaxTreeNode) -> Table:
    rows: list[list[str]] = []
    links: list[Link] = []
    for part in node.children:  # thead, tbody
        for row in part.children:
            cells = [_inline(cell) for cell in row.children]
            rows.append([cell["text"] for cell in cells])
            links += [link for cell in cells for link in cell.get("links", [])]
    # GFM tables always have a header row.
    table: Table = {"type": "table", "header": rows[0] if rows else [], "rows": rows[1:]}
    if links:
        table["links"] = links
    return table


def _inline(node: SyntaxTreeNode) -> InlineText:
    links: list[Link] = []
    images: list[Image] = []
    inline: InlineText = {"text": _plain_text(node, links, images).strip()}
    if links:
        inline["links"] = links
    if images:
        inline["images"] = images
    return inline


def _plain_text(node: SyntaxTreeNode, links: list[Link], images: list[Image]) -> str:
    """Text a reader sees (link text, image alt), collecting links and images on the way."""
    match node.type:
        case "text" | "code_inline":
            return node.content
        case "softbreak":
            return " "
        case "hardbreak":
            return "\n"
        case "html_inline":
            return ""
    text = "".join(_plain_text(child, links, images) for child in node.children)
    if node.type == "link":
        links.append({"text": text.strip(), "url": _attr(node, "href")})
    elif node.type == "image":
        images.append({"alt": text.strip(), "url": _attr(node, "src")})
    return text


def _attr(node: SyntaxTreeNode, name: str) -> str:
    value = node.attrGet(name)
    return "" if value is None else str(value)
