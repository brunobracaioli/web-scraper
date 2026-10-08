import json
import re
from datetime import UTC, datetime
from typing import Any

from web_scraper.converter import Conversion, Page, convert, to_markdown
from web_scraper.structure import SCHEMA_VERSION, to_json

SCRAPED_AT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
METADATA = {"title": "T", "source_url": "https://example.com/p", "run_id": "3f9a1c2e"}
MARKDOWN_LINK_URL = re.compile(r"\]\(([^)\s]+)")


def make_page(html: str) -> Page:
    return Page(
        source_url="https://example.com/p",
        final_url="https://example.com/p",
        html=html.encode(),
        encoding="utf-8",
        scraped_at=SCRAPED_AT,
        run_id="3f9a1c2e",
    )


def document_for(body: str) -> Any:
    return json.loads(to_json(Conversion(metadata=METADATA, body=body)))


def outline(sections: list[Any]) -> list[Any]:
    return [(section["heading"], outline(section["sections"])) for section in sections]


def link_urls(node: Any) -> list[str]:
    if isinstance(node, list):
        return [url for item in node for url in link_urls(item)]
    if not isinstance(node, dict):
        return []
    own = [link["url"] for link in node.get("links", [])]
    return own + [url for key, value in node.items() if key != "links" for url in link_urls(value)]


def test_nests_sections_by_heading_level() -> None:
    body = "Intro\n\n# A\n\na text\n\n## B\n\n#### D\n\nd text\n\n## C\n\n# E\n"

    document = document_for(body)

    assert document["blocks"] == [{"type": "paragraph", "text": "Intro"}]
    assert outline(document["sections"]) == [("A", [("B", [("D", [])]), ("C", [])]), ("E", [])]
    section_a = document["sections"][0]
    assert section_a["level"] == 1
    assert section_a["blocks"] == [{"type": "paragraph", "text": "a text"}]
    assert section_a["sections"][0]["sections"][0]["blocks"] == [
        {"type": "paragraph", "text": "d text"}
    ]


def test_paragraphs_have_plain_text_and_links_only_when_present() -> None:
    body = (
        "Decided on [Flutter](https://x.io/f) [React Native](https://x.io/rn) over AWS\\_Lambda\n\n"
        "No links here\n"
    )

    blocks = document_for(body)["blocks"]

    assert blocks == [
        {
            "type": "paragraph",
            "text": "Decided on Flutter React Native over AWS_Lambda",
            "links": [
                {"text": "Flutter", "url": "https://x.io/f"},
                {"text": "React Native", "url": "https://x.io/rn"},
            ],
        },
        {"type": "paragraph", "text": "No links here"},
    ]


def test_inline_formatting_is_flattened_to_text() -> None:
    blocks = document_for("**bold** and `code`  \nnext line\nsame line\n")["blocks"]

    assert blocks == [{"type": "paragraph", "text": "bold and code\nnext line same line"}]


def test_lists_keep_item_links_and_nesting() -> None:
    body = (
        "- [Scala](https://x.io/scala)\n- [Kafka](https://x.io/kafka)\n\n"
        "1. one\n   - nested\n2. two\n"
    )

    blocks = document_for(body)["blocks"]

    assert blocks == [
        {
            "type": "list",
            "ordered": False,
            "items": [
                {"text": "Scala", "links": [{"text": "Scala", "url": "https://x.io/scala"}]},
                {"text": "Kafka", "links": [{"text": "Kafka", "url": "https://x.io/kafka"}]},
            ],
        },
        {
            "type": "list",
            "ordered": True,
            "items": [
                {
                    "text": "one",
                    "blocks": [{"type": "list", "ordered": False, "items": [{"text": "nested"}]}],
                },
                {"text": "two"},
            ],
        },
    ]


def test_tables_code_and_quotes_become_typed_blocks() -> None:
    body = (
        "| Tool | Layer |\n|---|---|\n| [Scala](https://x.io/scala) | Data |\n\n"
        "```python\nprint(1)\n```\n\n    indented\n\n> quoted **text**\n\n---\n"
    )

    blocks = document_for(body)["blocks"]

    assert blocks == [
        {
            "type": "table",
            "header": ["Tool", "Layer"],
            "rows": [["Scala", "Data"]],
            "links": [{"text": "Scala", "url": "https://x.io/scala"}],
        },
        {"type": "code", "language": "python", "text": "print(1)"},
        {"type": "code", "language": None, "text": "indented"},
        {"type": "quote", "blocks": [{"type": "paragraph", "text": "quoted text"}]},
    ]


def test_linked_heading_keeps_its_link() -> None:
    sections = document_for("## [Post title](https://x.io/post)\n")["sections"]

    assert sections == [
        {
            "heading": "Post title",
            "level": 2,
            "blocks": [],
            "sections": [],
            "links": [{"text": "Post title", "url": "https://x.io/post"}],
        }
    ]


def test_metadata_matches_front_matter() -> None:
    conversion = convert(make_page("<title>Page</title><main><h1>Page</h1></main>"))

    document = json.loads(to_json(conversion))
    markdown = to_markdown(conversion)

    assert document["schema_version"] == SCHEMA_VERSION == 1
    assert document["metadata"] == dict(conversion.metadata)
    for key, value in document["metadata"].items():
        assert f"{key}: {json.dumps(value)}" in markdown


def test_images_only_appear_without_cleanup() -> None:
    page = make_page('<main><h1>Logos</h1><p><img src="/logo.png" alt="Logo"></p></main>')

    cleaned = to_json(convert(page))
    raw = json.loads(to_json(convert(page, clean=False)))

    assert '"images"' not in cleaned
    # Raw conversion: synthesized "# Logos" title, then the page's own h1 as a sibling.
    assert raw["sections"][-1]["blocks"] == [
        {
            "type": "paragraph",
            "text": "Logo",
            "images": [{"alt": "Logo", "url": "https://example.com/logo.png"}],
        }
    ]


def test_json_carries_the_same_links_as_the_markdown() -> None:
    html = (
        "<title>Co</title><main><h1>Co</h1><p>Site: <a href='https://co.example'>co</a></p>"
        "<div><h4>DevOps</h4><span>2</span></div>"
        "<div><a href='/github' title='GitHub'><img src='/g.png'></a>"
        "<a href='/sentry'><img src='/s.png' alt='Sentry'></a></div>"
        "<table><tr><th>Name</th></tr><tr><td><a href='/ana'>Ana</a></td></tr></table>"
        "<blockquote><p>See <a href='/post'>post</a></p></blockquote></main>"
    )
    conversion = convert(make_page(html))

    document = json.loads(to_json(conversion))

    assert sorted(link_urls(document)) == sorted(MARKDOWN_LINK_URL.findall(conversion.body))
    devops = document["sections"][0]["sections"][0]
    assert devops["heading"] == "DevOps (2)"
    assert [item["text"] for item in devops["blocks"][0]["items"]] == ["GitHub", "Sentry"]
