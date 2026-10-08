# Spec — URL → Markdown (v1, simple)

Status: implemented (v1.2 — JSON output) · Owner: Bruno Bracaioli · Updated: 2026-10-07

## Objective

CLI that takes a URL, downloads the page, extracts the main content and saves
it as a Markdown file with metadata (front matter), plus a JSON file with the
same content structured by sections (for programs). v1 is a plain HTTP fetch;
anti-bot strategies (headless browser, etc.) are explicitly out of scope and
come in v2.

## Contract (CLI)

```
web-scraper <url> [-o OUTPUT] [--out-dir DIR] [--timeout SECONDS] [--no-clean] [-v]
```

| Arg | Default | Description |
|-----|---------|-------------|
| `url` | — | `http`/`https` URL to scrape (required) |
| `-o, --output` | — | Exact Markdown file path, used as-is (overrides `--out-dir`); the JSON goes next to it. Must not be a directory |
| `--out-dir` | `output/` | Directory for the auto-named files `<slug>_<timestamp>_<run_id>.md` / `.json` |
| `--timeout` | `30` | HTTP timeout in seconds |
| `--no-clean` | off | Skip the cleanup step (keeps images, navigation, buttons, hidden elements) |
| `-v, --verbose` | off | Debug logs on stderr |

- **stdout**: paths of the written files, one per line — the `.md`, then the
  `.json` (only on success, pipe-friendly).
- **stderr**: logs and error messages.
- **Exit codes**: `0` success · `1` fetch/HTTP error or output not writable ·
  `2` invalid usage/URL · `3` blocked by an anti-bot challenge.

### Output format

```markdown
---
title: "<page title>"
source_url: "<url as given>"
final_url: "<url after redirects>"
scraped_at: "<ISO-8601 UTC>"
run_id: "<8 hex chars>"
---

# <page title>

<main content as Markdown>
```

Front matter values are JSON-encoded strings (valid YAML, no escaping bugs).
With cleanup on, the `# <page title>` heading is only added when the content
has no `<h1>` of its own (otherwise the page would have two H1s).

### JSON output

Written next to the Markdown, same name with `.json`: `-o notes/page.md` →
`notes/page.json`; a path without `.md` gets `.json` appended
(`notes/v1.2` → `notes/v1.2.json`), so the two files never collide.

The JSON is built by parsing the Markdown body (CommonMark + GFM tables, via
`markdown-it-py`), not the HTML, so it always carries exactly the text and
links of the `.md` file. It follows the same cleanup (`--no-clean` included).

```json
{
  "schema_version": 1,
  "metadata": {"title": "…", "source_url": "…", "final_url": "…", "scraped_at": "…", "run_id": "…"},
  "blocks": [],
  "sections": [
    {"heading": "Nubank", "level": 1, "blocks": [ … ], "sections": [
      {"heading": "DevOps (7)", "level": 4, "blocks": [
        {"type": "list", "ordered": false, "items": [
          {"text": "GitHub", "links": [{"text": "GitHub", "url": "https://stackshare.io/github"}]}
        ]}
      ], "sections": []}
    ]}
  ]
}
```

- `metadata`: the front matter fields, same values.
- `blocks` at the root: content before the first heading.
- **Sections** nest by heading level: a heading closes the open sections of
  its level or deeper, so `h2 → h4` nests directly and a second `h1` starts a
  new root section. Section = `heading`, `level`, `blocks`, `sections`, plus
  `links` when the heading itself is a link.
- **Blocks** (`type`):
  - `paragraph`: `text`, `links`, `images`;
  - `list`: `ordered`, `items` — each item has `text`, `links`, `images` from
    its first paragraph, and `blocks` for nested lists or further content;
  - `table`: `header` (list of cell texts), `rows` (list of rows), `links`;
  - `code`: `language` (first word of the fence info, or `null`), `text`;
  - `quote`: `blocks`.
  Headings inside a quote or list item become paragraphs; horizontal rules
  and raw HTML are dropped.
- **Inline content** becomes plain `text`: link text, image alt, Markdown
  escapes undone (`AWS\_Lambda` → `AWS_Lambda`), soft line break → space,
  hard break → `\n`, emphasis/code markers removed. `links` = `[{text, url}]`
  and `images` = `[{alt, url}]` in reading order (images only survive with
  `--no-clean`).
- `links`, `images` and an item's `blocks` are **omitted when empty**;
  `blocks` and `sections` of the root and of each section are always present.
- `schema_version` is bumped on incompatible changes to this shape.

## Behavior

1. Validate URL: scheme `http`/`https` and a host; otherwise exit `2`.
2. GET with redirects, browser-like headers, timeout, retries only on
   connection errors (GET is idempotent).
3. Abort if body exceeds 10 MB (streamed, never fully buffered beyond limit).
4. Detect anti-bot challenge pages (Vercel Checkpoint, Cloudflare) **before**
   checking the status code → exit `3` with the provider name.
5. Non-2xx → exit `1`. Non-HTML content type → exit `1`.
6. React streaming SSR (Next.js App Router): replay the `$RC`/`$RS` calls
   statically — move each hidden `<div id="S:n">` chunk into its
   `<template id="B:n"|"P:n">` slot, dropping the loading skeleton up to the
   matching `<!--/$-->`. Unmatched calls leave the skeleton untouched.
7. Content extraction: prefer `<main>`, then `<article>`, then `<body>`;
   drop `script`, `style`, `noscript`, `svg`, `iframe`, `template`, `form`.
8. Relative `href`/`src` resolved to absolute against the final URL;
   `javascript:` links unwrapped (text kept).
9. Title: `<title>` → first `<h1>` → final URL.
10. Cleanup (default; see below), skipped with `--no-clean`.
11. Collapse 3+ blank lines into one.
12. Each run gets a `run_id` (8 random hex chars), logged on start together
    with the URL (so blocked/failed attempts are traceable too), written to
    the front matter and to the auto-generated file name.
13. The rendered Markdown is parsed into the JSON document (see "JSON
    output"); the HTML is parsed only once for both files.

### Cleanup

Goal: Markdown with the page's information and none of its chrome, so it is
cheap to read and to feed to an LLM. Rules are generic (no per-site code) and
applied to the extracted content before rendering, in this order:

1. **Hidden content** dropped: `hidden` attribute, `aria-hidden="true"`,
   inline `display: none`, and utility classes that hide the element at the
   widest breakpoint (Tailwind `hidden`/`md:hidden`, Bootstrap
   `d-none`/`d-md-none`; a later `sm:flex`/`d-sm-block` shows it again).
   Responsive sites render mobile and desktop variants of the same text; the
   desktop one is kept. `opacity-0`/`invisible` are **not** treated as hidden
   (hover tooltips often carry data).
2. **Chrome** dropped: `<nav>` and `role="navigation"` (breadcrumbs, tabs,
   menus). Buttons (`<button>`, `role="button"`) are dropped unless their text
   has a digit — then only the text is kept (counters like "5 upvotes").
3. **Images** (`img`, `svg`, `picture`) removed:
   - a link whose only content is an image becomes a text link labelled by
     the link's `aria-label`/`title` or the image `alt` (logo grids keep their
     names); with no label it is dropped;
   - that image link is dropped instead when its parent element already has a
     text link to the same URL (avatar next to the author's name);
   - any other image is dropped.
4. **Count badges**: a heading followed by an inline element whose text is
   just a count (`17`, `1.2k`, `99+`) gets it folded in: `## Tools (17)`.
5. **Link groups**: a `<div>` whose children are only links (2+) becomes a
   bulleted list.
6. **Word boundaries**: an element removed from between two siblings leaves a
   space (`View all<svg/>32` → "View all 32"), and a space is added
   between adjacent inline elements (`<span>32</span><span>tools</span>` →
   "32 tools"; flex/gap layouts separate them only visually). Not applied
   around `sub`/`sup` or between text and an element (`H<sub>2</sub>O`).
7. Link `title` equal to the link text is dropped (`[Scala](url "Scala")`).
8. **Title**: consecutive repeated segments removed
   (`Nubank - StackShare | StackShare` → `Nubank - StackShare`).

Not removed: ordinary links such as "View all" (they point to fuller pages,
and recognising them would need per-language phrase lists).

## Edge cases

- Redirects: `final_url` records where we ended up; links resolve against it.
- Charset: taken from `Content-Type` when present; otherwise BeautifulSoup
  sniffs `<meta charset>`/bytes.
- Page without `<main>`/`<article>`: falls back to `<body>`.
- Filename: `<slug>_<YYYYMMDDTHHMMSSZ>_<run_id>.md`. Slug = host + path,
  `[a-z0-9.-]` only, max 120 chars — no path traversal possible from the URL.
  Timestamp is UTC (same instant as `scraped_at`) so names sort
  chronologically; `run_id` keeps names unique even for the same URL in the
  same second. Repeated runs never overwrite earlier files. The JSON shares
  the Markdown's name with `.json`.
- `-o` naming an existing directory (or whose `.json` sibling is one) → exit
  `2` **before** any request, nothing written. Any other write failure
  (`--out-dir` is a file, no permission, disk full) → exit `1` with a one-line
  error, no traceback.

## Acceptance criteria

- [x] `web-scraper https://example.com` writes
      `output/example.com_<timestamp>_<run_id>.md` with front matter and content.
- [x] Running the same URL twice produces two distinct files; `-o` keeps the
      exact name given.
- [x] `web-scraper https://stackshare.io/nubank` writes the full stack (32 tools
      by layer) — content streamed by React is inlined, not the skeleton.
- [x] When the server answers with the Vercel challenge (intermittent on
      StackShare), exits `3` and writes **no** file.
- [x] `web-scraper ftp://x` exits `2`.
- [x] Scripts/styles never appear in the output; relative links become absolute.
- [x] Unit tests cover converter (incl. React streaming), fetcher (mock
      transport) and filename slug.
- [x] Cleanup on `https://stackshare.io/nubank`: no image Markdown, no
      breadcrumb/tabs/Follow/Copy link, every tool and team member still
      present as a text link, stats read "32 tools", one H1, title
      without the repeated "| StackShare".
- [x] `--no-clean` reproduces the v1 output (images kept).
- [x] Every run also writes `<same name>.json`; stdout lists both paths.
- [x] On `https://stackshare.io/nubank` the JSON is valid, has the four layer
      sections under "Tech Stack" with 17/6/7/2 list items and the team
      section with 7, and its set of link URLs equals the `.md`'s.
- [x] `--no-clean` JSON carries the images (`images`); cleaned JSON has none.
- [x] `-o notes/page.md` → `notes/page.json`; `-o notes/v1.2` → `notes/v1.2.json`.
- [x] `-o <existing dir>` exits `2` without fetching; an unwritable output
      exits `1` without a traceback.

## Orchestrator script (`scrape.sh`)

Single entry point wrapping the CLI; works from any directory.

| Command | Behavior |
|---------|----------|
| `./scrape.sh <url> [opts]` / `scrape <url> [opts]` | Runs the CLI; options forwarded; CLI exit code preserved |
| `batch <file> [opts]` | Sequential scrape of each URL in `<file>`, `BATCH_DELAY` s between requests |
| `setup` | Checks `uv`, runs `uv sync` |
| `check` | `ruff format --check`, `ruff check`, `mypy`, `shellcheck` (if installed), `pytest` |
| `help` (default) | Usage |

- Output dir: `OUT_DIR` env, default `<project>/output` (not relative to cwd).
  A `--out-dir` given by the user overrides it.
- Batch file: one URL per line (first whitespace-separated token), blank lines
  and `#` lines ignored, CRLF tolerated, last line may lack `\n`.
- Batch rejects `-o/--output` (all URLs would overwrite one file) → exit `2`.
- Batch summary on stderr (stdout stays = written paths): totals plus each
  blocked/failed URL. Exit `0` only if every URL succeeded, else `1`.
- Usage errors (unknown command, missing arg/file, bad `BATCH_DELAY`, file
  without URLs) → exit `2`.

## Out of scope (v2+)

Headless browser rendering (JS-heavy pages and JS challenges), header/TLS
fingerprint realism, proxy rotation, parallel batch with per-host rate
limiting, robots.txt policy.
