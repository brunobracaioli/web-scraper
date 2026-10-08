from datetime import UTC, datetime

from web_scraper.converter import Page, convert, to_markdown

SCRAPED_AT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def make_page(html: str, final_url: str = "https://example.com/blog/post") -> Page:
    return Page(
        source_url="https://example.com/p",
        final_url=final_url,
        html=html.encode(),
        encoding="utf-8",
        scraped_at=SCRAPED_AT,
        run_id="3f9a1c2e",
    )


def test_writes_front_matter_with_json_encoded_values() -> None:
    markdown = to_markdown(
        convert(make_page('<title>A "quoted": title</title><body><p>x</p></body>'))
    )

    assert markdown.startswith("---\n")
    assert 'title: "A \\"quoted\\": title"' in markdown
    assert 'source_url: "https://example.com/p"' in markdown
    assert 'final_url: "https://example.com/blog/post"' in markdown
    assert 'scraped_at: "2026-10-07T12:00:00+00:00"' in markdown
    assert 'run_id: "3f9a1c2e"' in markdown


def test_prefers_main_over_surrounding_layout() -> None:
    html = "<body><nav>Menu</nav><main><p>Real content</p></main><footer>Foot</footer></body>"

    markdown = to_markdown(convert(make_page(html)))

    assert "Real content" in markdown
    assert "Menu" not in markdown
    assert "Foot" not in markdown


def test_falls_back_to_body_when_no_main_or_article() -> None:
    markdown = to_markdown(convert(make_page("<body><div><p>Plain body</p></div></body>")))

    assert "Plain body" in markdown


def test_strips_scripts_styles_and_forms() -> None:
    html = (
        "<main><p>Keep</p><script>alert(1)</script><style>p{}</style>"
        "<form><input name='q'></form></main>"
    )

    markdown = to_markdown(convert(make_page(html)))

    assert "Keep" in markdown
    assert "alert" not in markdown
    assert "p{}" not in markdown


def test_resolves_relative_links_and_images_against_final_url() -> None:
    html = '<main><a href="../about">About</a><img src="/img/logo.png" alt="logo"></main>'

    # Images only survive without cleanup (see test_cleaner.py).
    markdown = to_markdown(convert(make_page(html), clean=False))

    assert "[About](https://example.com/about)" in markdown
    assert "![logo](https://example.com/img/logo.png)" in markdown


def test_unwraps_javascript_links_keeping_text() -> None:
    markdown = to_markdown(
        convert(make_page('<main><a href="javascript:void(0)">Click</a></main>'))
    )

    assert "Click" in markdown
    assert "javascript:" not in markdown


def test_title_falls_back_to_h1_then_url() -> None:
    with_h1 = to_markdown(convert(make_page("<body><h1>Heading One</h1></body>")))
    without_title = to_markdown(convert(make_page("<body><p>x</p></body>")))

    assert "\n# Heading One\n" in with_h1
    assert "\n# https://example.com/blog/post\n" in without_title


def test_collapses_excess_blank_lines() -> None:
    markdown = to_markdown(convert(make_page("<main><p>a</p><br><br><br><br><p>b</p></main>")))

    assert "\n\n\n" not in markdown


def test_inlines_react_streamed_chunks_in_place_of_skeletons() -> None:
    # Shape emitted by React streaming SSR (Next.js App Router), simplified.
    html = (
        "<body><main>"
        '<!--$?--><template id="B:1"></template><div class="animate-pulse">Loading</div><!--/$-->'
        "</main>"
        '<div hidden id="S:1"><h2>Tech Stack</h2><template id="P:2"></template></div>'
        '<script>$RC("B:1","S:1")</script>'
        '<div hidden id="S:2"><ul><li>Clojure</li><li>Datomic</li></ul></div>'
        '<script>$RS("S:2","P:2")</script>'
        "</body>"
    )

    markdown = to_markdown(convert(make_page(html)))

    assert "## Tech Stack" in markdown
    assert "- Clojure\n- Datomic" in markdown
    assert "Loading" not in markdown


def test_keeps_skeleton_when_streamed_chunk_is_missing() -> None:
    html = (
        '<main><!--$?--><template id="B:1"></template><p>Fallback</p><!--/$--></main>'
        '<script>$RC("B:1","S:9")</script>'
    )

    assert "Fallback" in to_markdown(convert(make_page(html)))
