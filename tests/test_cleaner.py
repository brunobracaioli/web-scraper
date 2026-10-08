from datetime import UTC, datetime

import pytest

from web_scraper.cleaner import clean_title
from web_scraper.converter import Page, convert, to_markdown

SCRAPED_AT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def make_page(html: str) -> Page:
    return Page(
        source_url="https://example.com/p",
        final_url="https://example.com/p",
        html=html.encode(),
        encoding="utf-8",
        scraped_at=SCRAPED_AT,
        run_id="3f9a1c2e",
    )


def body_lines(markdown: str) -> list[str]:
    return [line for line in markdown.split("---\n", 2)[2].splitlines() if line]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Nubank Tech Stack - StackShare | StackShare", "Nubank Tech Stack - StackShare"),
        ("Site — Site", "Site"),
        ("A | B", "A | B"),
        ("A - B - A", "A - B - A"),
        ("Home", "Home"),
    ],
)
def test_clean_title_drops_consecutive_repeated_segments(title: str, expected: str) -> None:
    assert clean_title(title) == expected


def test_drops_standalone_images() -> None:
    markdown = to_markdown(
        convert(make_page('<main><img src="/logo.png" alt="Logo"><p>Text</p></main>'))
    )

    assert "![" not in markdown
    assert "Logo" not in markdown
    assert "Text" in markdown


def test_image_only_links_become_a_list_of_text_links() -> None:
    html = (
        "<main><div>"
        '<a href="/scala" title="Scala"><img src="/s.png" alt="Scala logo"></a>'
        '<a href="/kafka"><img src="/k.png" alt="Kafka"></a>'
        "</div></main>"
    )

    markdown = to_markdown(convert(make_page(html)))

    assert "- [Scala](https://example.com/scala)\n- [Kafka](https://example.com/kafka)" in markdown
    assert "![" not in markdown


def test_drops_image_link_when_parent_already_links_with_text() -> None:
    html = (
        '<main><div><a href="/u/ana"><img src="/ana.png" alt="Ana"></a>'
        '<div><a href="/u/ana">Ana</a><p>CTO</p></div></div></main>'
    )

    markdown = to_markdown(convert(make_page(html)))

    assert markdown.count("[Ana](https://example.com/u/ana)") == 1


def test_drops_image_link_without_label() -> None:
    markdown = to_markdown(
        convert(make_page('<main><p>See <a href="/x"><img src="/x.png"></a></p></main>'))
    )

    assert "https://example.com/x" not in markdown


def test_drops_navigation_and_action_buttons_but_keeps_counters() -> None:
    html = (
        '<main><nav aria-label="Breadcrumb"><a href="/">Home</a></nav><h1>Title</h1>'
        '<div role="navigation"><a href="/tab">Tab</a></div>'
        "<button><span>+</span>Follow</button><button><span>5 upvotes</span></button></main>"
    )

    markdown = to_markdown(convert(make_page(html)))

    assert "Home" not in markdown
    assert "Tab" not in markdown
    assert "Follow" not in markdown
    assert "5 upvotes" in body_lines(markdown)


def test_keeps_only_the_desktop_variant_of_responsive_duplicates() -> None:
    html = (
        '<main><p><span class="hidden sm:inline">5 upvotes</span><span class="sm:hidden">5</span>'
        '</p><p class="d-none d-md-block">Desktop</p><p class="d-md-none">Mobile</p></main>'
    )

    lines = body_lines(to_markdown(convert(make_page(html))))

    assert lines[-2:] == ["5 upvotes", "Desktop"]


def test_drops_hidden_elements_but_keeps_hover_tooltips() -> None:
    html = (
        '<main><div hidden>Secret</div><span aria-hidden="true">Icon</span>'
        '<p style="color: red; display: none">Gone</p>'
        '<div class="opacity-0 group-hover:opacity-100">17 tools (53%)</div></main>'
    )

    markdown = to_markdown(convert(make_page(html)))

    assert "Secret" not in markdown
    assert "Icon" not in markdown
    assert "Gone" not in markdown
    assert "17 tools (53%)" in markdown


def test_separates_words_glued_by_layout_only() -> None:
    html = (
        "<main><div><span>32</span><span>tools</span></div>"
        "<div><span>Decided</span><span>on</span><a href='/f'>Flutter</a></div>"
        "<p>H<sub>2</sub>O</p>"
        "<p><a href='/all'>View all<svg><path d='M0'/></svg>32</a></p>"
        "<p><a href='/c'><svg><path d='M0'/></svg>Comments</a></p></main>"
    )

    lines = body_lines(to_markdown(convert(make_page(html))))

    assert lines[-5:] == [
        "32 tools",
        "Decided on [Flutter](https://example.com/f)",
        "H2O",
        "[View all 32](https://example.com/all)",
        "[Comments](https://example.com/c)",
    ]


def test_folds_count_badges_into_headings() -> None:
    html = (
        "<main><div><h4>Utilities</h4><span>6</span></div>"
        "<div><h3>Team</h3><div></div><span>1.2k</span></div>"
        "<div><h2>Year</h2><p>2024</p></div></main>"
    )

    markdown = to_markdown(convert(make_page(html)))

    assert "#### Utilities (6)" in markdown
    assert "### Team (1.2k)" in markdown
    assert "## Year\n\n2024" in markdown


def test_keeps_page_h1_instead_of_adding_title_heading() -> None:
    html = "<title>Page | Site | Site</title><main><h1>Real heading</h1></main>"

    markdown = to_markdown(convert(make_page(html)))

    assert 'title: "Page | Site"' in markdown
    assert body_lines(markdown) == ["# Real heading"]


def test_adds_title_heading_when_page_has_no_h1() -> None:
    markdown = to_markdown(
        convert(make_page("<title>Page | Site | Site</title><main><p>x</p></main>"))
    )

    assert body_lines(markdown) == ["# Page | Site", "x"]


def test_no_clean_keeps_raw_conversion() -> None:
    html = (
        "<title>Page | Site | Site</title><main><h1>Real</h1><nav><a href='/'>Home</a></nav>"
        "<img src='/logo.png' alt='Logo'><button>Follow</button></main>"
    )

    markdown = to_markdown(convert(make_page(html), clean=False))

    assert 'title: "Page | Site | Site"' in markdown
    assert "# Page | Site | Site" in markdown
    assert "![Logo](https://example.com/logo.png)" in markdown
    assert "Home" in markdown
    assert "Follow" in markdown
