"""Command-line entry point: `web-scraper <url>`."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from web_scraper.converter import Page, convert, to_markdown
from web_scraper.fetcher import (
    DEFAULT_TIMEOUT_SECONDS,
    BotChallengeError,
    FetchError,
    HttpxFetcher,
    InvalidUrlError,
)
from web_scraper.output import json_path_for, new_run_id, output_filename, write_text
from web_scraper.structure import to_json

EXIT_OK = 0
EXIT_FETCH_ERROR = 1
EXIT_WRITE_ERROR = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 3
DEFAULT_OUT_DIR = Path("output")

logger = logging.getLogger("web_scraper")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="web-scraper", description="Scrape a web page and save it as Markdown and JSON."
    )
    parser.add_argument("url", help="http(s) URL to scrape")
    parser.add_argument(
        "-o", "--output", type=Path, help="exact Markdown file path (the .json goes next to it)"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="directory for auto-named output"
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout (seconds)"
    )
    parser.add_argument(
        "--no-clean",
        dest="clean",
        action="store_false",
        help="keep images, navigation, buttons and hidden elements (raw conversion)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # Checked before fetching: a bad -o shouldn't cost a request (or an anti-bot hit).
    if args.output is not None:
        for target in (args.output, json_path_for(args.output)):
            if target.is_dir():
                logger.error("%s is a directory: -o takes a file path (or use --out-dir)", target)
                return EXIT_USAGE

    run_id = new_run_id()
    try:
        with HttpxFetcher(timeout_seconds=args.timeout) as fetcher:
            logger.info("run %s: fetching %s", run_id, args.url)
            result = fetcher.fetch(args.url)
    except InvalidUrlError as exc:
        logger.error("%s", exc)
        return EXIT_USAGE
    except BotChallengeError as exc:
        logger.error("%s — a headless browser is needed for this site (v2)", exc)
        return EXIT_BLOCKED
    except FetchError as exc:
        logger.error("%s", exc)
        return EXIT_FETCH_ERROR

    scraped_at = datetime.now(UTC)
    page = Page(
        source_url=args.url,
        final_url=result.final_url,
        html=result.content,
        encoding=result.encoding,
        scraped_at=scraped_at,
        run_id=run_id,
    )
    conversion = convert(page, clean=args.clean)
    path = args.output or args.out_dir / output_filename(result.final_url, scraped_at, run_id)
    json_path = json_path_for(path)
    try:
        write_text(to_markdown(conversion), path)
        write_text(to_json(conversion), json_path)
    except OSError as exc:  # unwritable dir, --out-dir is a file, disk full...
        logger.error("cannot write output: %s", exc)
        return EXIT_WRITE_ERROR
    logger.info("saved %s and %s (%d bytes of HTML)", path, json_path, len(result.content))
    print(path)
    print(json_path)
    return EXIT_OK
