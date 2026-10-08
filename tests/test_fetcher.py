from collections.abc import Callable

import httpx
import pytest

from web_scraper import fetcher as fetcher_module
from web_scraper.fetcher import (
    BotChallengeError,
    FetchError,
    HttpxFetcher,
    InvalidUrlError,
    validate_url,
)

HTML = "text/html; charset=utf-8"


def fetcher_for(handler: Callable[[httpx.Request], httpx.Response]) -> HttpxFetcher:
    return HttpxFetcher(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("url", ["ftp://example.com", "example.com", "https://", "file:///etc"])
def test_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        validate_url(url)


def test_returns_html_body_and_final_url_after_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.com/new"})
        return httpx.Response(200, headers={"content-type": HTML}, text="<p>ok</p>")

    result = fetcher_for(handler).fetch("https://example.com/old")

    assert result.final_url == "https://example.com/new"
    assert result.content == b"<p>ok</p>"
    assert result.encoding == "utf-8"


def test_detects_vercel_challenge_by_header() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, headers={"content-type": HTML, "x-vercel-mitigated": "challenge"}, text="..."
        )

    with pytest.raises(BotChallengeError) as exc_info:
        fetcher_for(handler).fetch("https://stackshare.io/nubank")

    assert exc_info.value.provider == "Vercel"
    assert exc_info.value.status_code == 429


def test_detects_cloudflare_challenge_by_body() -> None:
    body = "<html><head><title>Just a moment...</title></head><body>cloudflare</body></html>"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"content-type": HTML}, text=body)

    with pytest.raises(BotChallengeError) as exc_info:
        fetcher_for(handler).fetch("https://example.com")

    assert exc_info.value.provider == "Cloudflare"


def test_page_mentioning_checkpoint_in_text_is_not_a_challenge() -> None:
    body = "<title>Blog</title><p>How the Vercel Security Checkpoint works</p>"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": HTML}, text=body)

    assert fetcher_for(handler).fetch("https://example.com").status_code == 200


def test_raises_on_http_error_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"content-type": HTML}, text="not found")

    with pytest.raises(FetchError, match="HTTP 404"):
        fetcher_for(handler).fetch("https://example.com/missing")


def test_rejects_non_html_content() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    with pytest.raises(FetchError, match="unsupported content type"):
        fetcher_for(handler).fetch("https://example.com/file.pdf")


def test_aborts_when_body_exceeds_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher_module, "MAX_BODY_BYTES", 10)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": HTML}, content=b"x" * 11)

    with pytest.raises(FetchError, match="larger than"):
        fetcher_for(handler).fetch("https://example.com")


def test_wraps_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(FetchError, match="request failed"):
        fetcher_for(handler).fetch("https://example.com")
