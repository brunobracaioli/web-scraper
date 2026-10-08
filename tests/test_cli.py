import json
from pathlib import Path

import httpx
import pytest

from web_scraper import cli
from web_scraper.fetcher import HttpxFetcher

PAGE = b"<title>Example</title><main><h1>Example</h1><p><a href='/a'>A</a></p></main>"


def fake_fetcher(timeout_seconds: float) -> HttpxFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=PAGE)

    return HttpxFetcher(timeout_seconds, transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "HttpxFetcher", fake_fetcher)


def test_writes_markdown_and_json_side_by_side(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main(["https://example.com/page", "--out-dir", str(tmp_path)])

    markdown_path, json_path = map(Path, capsys.readouterr().out.splitlines())
    assert exit_code == cli.EXIT_OK
    assert markdown_path.parent == tmp_path
    assert markdown_path.suffix == ".md"
    assert json_path == markdown_path.with_suffix(".json")
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document["metadata"]["run_id"] in markdown_path.name
    assert document["sections"][0]["blocks"] == [
        {"type": "paragraph", "text": "A", "links": [{"text": "A", "url": "https://example.com/a"}]}
    ]


def test_output_option_names_the_markdown_and_json_goes_next_to_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    markdown_path = tmp_path / "notes" / "page.md"
    json_path = tmp_path / "notes" / "page.json"

    exit_code = cli.main(["https://example.com/page", "-o", str(markdown_path)])

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out.splitlines() == [str(markdown_path), str(json_path)]
    assert markdown_path.read_text(encoding="utf-8").startswith("---\n")
    assert json.loads(json_path.read_text(encoding="utf-8"))["metadata"]["title"] == "Example"


def must_not_fetch(timeout_seconds: float) -> HttpxFetcher:
    raise AssertionError("an invalid -o must be rejected before any request")


@pytest.mark.parametrize(
    ("existing_dir", "output"),
    [
        ("out", "out"),  # -o names a directory
        ("out/page.json", "out/page.md"),  # the .json sibling would be a directory
    ],
)
def test_output_that_is_a_directory_is_rejected_before_fetching(
    existing_dir: str,
    output: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(cli, "HttpxFetcher", must_not_fetch)
    (tmp_path / existing_dir).mkdir(parents=True)

    exit_code = cli.main(["https://example.com/page", "-o", str(tmp_path / output)])

    assert exit_code == cli.EXIT_USAGE
    assert capsys.readouterr().out == ""
    assert "is a directory" in caplog.text
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_unwritable_output_fails_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")

    exit_code = cli.main(["https://example.com/page", "--out-dir", str(not_a_dir)])

    assert exit_code == cli.EXIT_WRITE_ERROR
    assert capsys.readouterr().out == ""
    assert "cannot write" in caplog.text
