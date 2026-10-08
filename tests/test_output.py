import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from web_scraper.output import (
    MAX_SLUG_LENGTH,
    json_path_for,
    new_run_id,
    output_filename,
    slug_for_url,
)

SAO_PAULO = timezone(timedelta(hours=-3))


def test_output_filename_has_slug_utc_timestamp_and_run_id() -> None:
    scraped_at = datetime(2026, 10, 7, 22, 53, 41, tzinfo=UTC)

    name = output_filename("https://stackshare.io/nubank", scraped_at, "3f9a1c2e")

    assert name == "stackshare.io-nubank_20261007T225341Z_3f9a1c2e.md"


def test_output_filename_converts_local_time_to_utc() -> None:
    scraped_at = datetime(2026, 10, 7, 19, 53, 41, tzinfo=SAO_PAULO)

    name = output_filename("https://example.com", scraped_at, "abc")

    assert name == "example.com_20261007T225341Z_abc.md"


def test_same_url_same_second_gets_distinct_names_via_run_id() -> None:
    scraped_at = datetime(2026, 10, 7, 22, 53, 41, tzinfo=UTC)

    first = output_filename("https://example.com", scraped_at, "aaaa1111")
    second = output_filename("https://example.com", scraped_at, "bbbb2222")

    assert first != second


def test_new_run_id_is_short_hex() -> None:
    assert re.fullmatch(r"[0-9a-f]{8}", new_run_id())


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://stackshare.io/nubank", "stackshare.io-nubank"),
        ("https://example.com/", "example.com"),
        ("https://Example.com/A/B?q=1", "example.com-a-b"),
        ("https://example.com/../../etc/passwd", "example.com-..-..-etc-passwd"),
    ],
)
def test_slug_for_url(url: str, expected: str) -> None:
    assert slug_for_url(url) == expected


def test_slug_never_contains_path_separators_and_is_bounded() -> None:
    slug = slug_for_url("https://example.com/" + "a/" * 200)

    assert "/" not in slug
    assert len(slug) <= MAX_SLUG_LENGTH


@pytest.mark.parametrize(
    ("markdown_path", "expected"),
    [
        ("output/a_20261007T225341Z_3f9a1c2e.md", "output/a_20261007T225341Z_3f9a1c2e.json"),
        ("notes/PAGE.MD", "notes/PAGE.json"),
        ("notes/page", "notes/page.json"),
        ("notes/v1.2", "notes/v1.2.json"),
        ("notes/data.json", "notes/data.json.json"),
    ],
)
def test_json_path_sits_next_to_the_markdown_and_never_collides(
    markdown_path: str, expected: str
) -> None:
    assert json_path_for(Path(markdown_path)) == Path(expected)
