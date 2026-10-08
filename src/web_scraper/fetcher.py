"""HTTP fetching: URL validation, size limit and anti-bot challenge detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

ALLOWED_SCHEMES = frozenset({"http", "https"})
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
MAX_BODY_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
CONNECT_RETRIES = 2
CHALLENGE_SNIFF_BYTES = 4096

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
}


class FetchError(Exception):
    """Page could not be fetched (network, HTTP status, content type, size)."""


class InvalidUrlError(FetchError):
    """URL is not an absolute http(s) URL."""


class BotChallengeError(FetchError):
    """Server answered with an anti-bot challenge instead of the page."""

    def __init__(self, provider: str, status_code: int) -> None:
        super().__init__(f"blocked by {provider} anti-bot challenge (HTTP {status_code})")
        self.provider = provider
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class FetchResult:
    final_url: str
    status_code: int
    content: bytes
    encoding: str | None


class Fetcher(Protocol):
    """Seam for swapping the HTTP fetcher for a headless browser later."""

    def fetch(self, url: str) -> FetchResult: ...


def validate_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
        raise InvalidUrlError(f"expected an absolute http(s) URL, got: {url!r}")
    return parts.geturl()


def detect_challenge(headers: httpx.Headers, body_head: bytes) -> str | None:
    """Return the anti-bot provider name if the response is a challenge page."""
    if headers.get("x-vercel-mitigated") == "challenge":
        return "Vercel"
    if headers.get("cf-mitigated") == "challenge":
        return "Cloudflare"
    head = body_head.lower()
    if b"<title>vercel security checkpoint</title>" in head:
        return "Vercel"
    if b"<title>just a moment...</title>" in head and b"cloudflare" in head:
        return "Cloudflare"
    return None


class HttpxFetcher:
    def __init__(
        self,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            transport=transport or httpx.HTTPTransport(retries=CONNECT_RETRIES),
        )

    def __enter__(self) -> HttpxFetcher:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._client.close()

    def fetch(self, url: str) -> FetchResult:
        url = validate_url(url)
        try:
            with self._client.stream("GET", url) as response:
                content = _read_limited(response)
        except httpx.HTTPError as exc:
            raise FetchError(f"request failed: {exc}") from exc

        provider = detect_challenge(response.headers, content[:CHALLENGE_SNIFF_BYTES])
        if provider:
            raise BotChallengeError(provider, response.status_code)
        if not response.is_success:
            raise FetchError(f"HTTP {response.status_code} for {response.url}")

        media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type not in HTML_CONTENT_TYPES:
            raise FetchError(f"unsupported content type: {media_type or 'unknown'}")

        return FetchResult(
            final_url=str(response.url),
            status_code=response.status_code,
            content=content,
            encoding=response.charset_encoding,
        )


def _read_limited(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise FetchError(f"response larger than {MAX_BODY_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
