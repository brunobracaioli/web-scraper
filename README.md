# web-scraper

Scrape a web page and save it as Markdown (with front matter) plus a JSON
file with the same content structured by sections.

Spec: [`docs/specs/url-to-markdown.md`](docs/specs/url-to-markdown.md).

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (manages
  Python 3.12 and the dependencies)
- Bash 4.4+ (Linux, WSL, or macOS with Homebrew bash)
- Optional: `shellcheck` (`sudo apt install shellcheck`) so `check` also lints
  `scrape.sh`

## Quick start

```bash
./scrape.sh setup                          # once: checks uv, installs deps
./scrape.sh https://stackshare.io/nubank   # -> output/stackshare.io-nubank_<timestamp>_<id>.md + .json
```

## Usage — `scrape.sh`

`scrape.sh` is the single entry point. It works from any directory; under the
hood it calls `uv run web-scraper ...`.

| Command | What it does |
|---------|--------------|
| `./scrape.sh <url> [options]` | Shortcut for `scrape <url> [options]` |
| `./scrape.sh scrape <url> [options]` | Scrape one page into the output directory |
| `./scrape.sh batch <file> [options]` | Scrape every URL listed in `<file>` |
| `./scrape.sh setup` | Check `uv` and install dependencies (`uv sync`) |
| `./scrape.sh check` | Format check, lint, type check, `shellcheck` (if installed) and tests |
| `./scrape.sh help` | Show usage (also the default with no arguments) |

### Options (forwarded to the CLI)

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output FILE` | — | Exact Markdown file, no timestamp/id added; the `.json` goes next to it (`scrape` only; rejected in `batch`) |
| `--out-dir DIR` | `<project>/output` | Directory for auto-named files `<slug>_<timestamp>_<id>.md` / `.json` |
| `--timeout SECONDS` | `30` | HTTP timeout |
| `--no-clean` | off | Skip the cleanup: keep images, navigation, buttons and hidden elements |
| `-v, --verbose` | off | Debug logs |

Full list: `./scrape.sh scrape --help`.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OUT_DIR` | `<project>/output` | Output directory, independent of where you run the script. An explicit `--out-dir` wins. |
| `BATCH_DELAY` | `2` | Seconds to wait between URLs in `batch` (decimals allowed) |

### Examples

```bash
./scrape.sh https://stackshare.io/nubank
./scrape.sh scrape https://example.com -o notes/example.md
./scrape.sh scrape https://example.com --out-dir pages --timeout 15 -v
OUT_DIR=~/scraped ./scrape.sh https://en.wikipedia.org/wiki/Nubank
BATCH_DELAY=5 ./scrape.sh batch urls.example.txt --timeout 15
```

## Batch mode

The URL file has one URL per line (see [`urls.example.txt`](urls.example.txt)):

```text
# Lines starting with # are comments; blank lines are ignored.
https://stackshare.io/nubank
https://example.com    anything after the URL is ignored
```

- Only the first word of each line is used, so trailing notes are fine.
- Files saved on Windows (CRLF line endings) work, and the last line doesn't
  need a trailing newline.
- URLs are scraped **one at a time**, with `BATCH_DELAY` seconds between them.
- `-o/--output` is rejected (every URL would overwrite the same file); use
  `--out-dir`.
- At the end, a summary goes to stderr:

  ```text
  batch: 5 total, 3 ok, 0 blocked, 2 failed
    failed:  ftp://invalid
    failed:  https://example.com/does-not-exist-404
  ```

- Exit code is `0` only if **every** URL succeeded, otherwise `1`.

## Output

Each page becomes two files with the same name: a Markdown file (prose, with
front matter) and a JSON file (the same content, structured).

### Markdown

```markdown
---
title: "Nubank Tech Stack - StackShare"
source_url: "https://stackshare.io/nubank"
final_url: "https://stackshare.io/nubank"
scraped_at: "2026-10-07T22:56:08.603801+00:00"
run_id: "325cac05"
---

# Nubank

...main content...
```

The `# heading` is the page's own `<h1>`; when the page has none, the title is
used instead.

### JSON

The same text and links as the `.md`, as a tree of sections (one per heading,
nested by level) holding typed blocks — `paragraph`, `list`, `table`, `code`,
`quote` — with plain text and their links:

```json
{
  "schema_version": 1,
  "metadata": {"title": "Nubank Tech Stack - StackShare", "source_url": "…", "final_url": "…", "scraped_at": "…", "run_id": "65ab5454"},
  "blocks": [],
  "sections": [
    {"heading": "Nubank", "level": 1, "blocks": [
      {"type": "paragraph", "text": "nubank.com.br", "links": [{"text": "nubank.com.br", "url": "https://nubank.com.br"}]},
      {"type": "paragraph", "text": "32 tools"}
    ], "sections": [
      {"heading": "Tech Stack", "level": 2, "blocks": ["…"], "sections": [
        {"heading": "DevOps (7)", "level": 4, "blocks": [
          {"type": "list", "ordered": false, "items": [
            {"text": "GitHub", "links": [{"text": "GitHub", "url": "https://stackshare.io/github"}]}
          ]}
        ], "sections": []}
      ]}
    ]}
  ]
}
```

It is built from the Markdown (not the HTML), so it never disagrees with the
`.md`; it is generic (no per-site fields) and follows `--no-clean` too (then it
also lists `images`). Full schema in the spec, section "JSON output". Example:
all tools of one layer with `jq`:

```bash
jq -r '.. | objects | select(.heading? == "DevOps (7)") | .blocks[].items[].text' output/<file>.json
```

### Cleanup (default)

Before saving, the content is cleaned so only the page's information is left
(rules in the spec, section "Cleanup"). On StackShare/Nubank the file goes
from ~9.6 KB to ~3 KB with no data lost:

- **Images removed.** Logo grids and avatars become text links
  (`- [Scala](https://stackshare.io/scala)`); an avatar next to the person's
  name is dropped; decorative images go away.
- **Page chrome removed:** breadcrumbs, tabs and menus (`<nav>`), action
  buttons (Follow, Copy link). Buttons showing a number ("5 upvotes") keep
  their text.
- **Responsive duplicates removed:** sites render a mobile and a desktop
  version of the same text (`5 upvotes` + `5`); only the desktop one is kept.
  Hidden elements (`hidden`, `aria-hidden`, `display: none`) are dropped too.
- **Glued words fixed:** "32tools" → "32 tools", "Decidedon" → "Decided on".
- **Tidier structure:** count badges fold into headings (`#### DevOps (7)`),
  groups of links become bulleted lists, repeated title segments are removed
  (`Nubank Tech Stack - StackShare | StackShare` → `Nubank Tech Stack - StackShare`).

Use `--no-clean` to get the raw conversion (e.g. articles where the images
matter).

### File names — new files per attempt

Every run writes **new** files; earlier attempts are never overwritten:

```text
stackshare.io-nubank_20261007T225607Z_21550ae2.md
stackshare.io-nubank_20261007T225607Z_21550ae2.json
stackshare.io-nubank_20261007T225608Z_325cac05.md
stackshare.io-nubank_20261007T225608Z_325cac05.json
└──── slug ────────┘ └─ timestamp ──┘ └run id┘
```

- **slug** — host + path of the final URL (only `[a-z0-9.-]`, max 120 chars).
- **timestamp** — when the page was scraped, in **UTC** (`Z`; Brasília is
  UTC−3). Same instant as `scraped_at` in the front matter, so `ls` lists
  attempts in chronological order.
- **run id** — 8 random hex chars, unique per run. It is also written to the
  front matter (`run_id`) and logged when the run starts
  (`run 325cac05: fetching ...`), so you can trace attempts that were blocked
  or failed and saved no file.

With `-o FILE` the exact name you gave is used for the Markdown (no
timestamp/id), and the JSON goes next to it: `-o notes/page.md` →
`notes/page.json` (a name without `.md` gets `.json` appended). `-o` must be
a file path: pointing it at a directory is rejected (exit `2`) before the page
is fetched — use `--out-dir` for that.

### stdout vs. stderr

Only the paths of the written files go to **stdout** — two lines per page,
the `.md` then the `.json`; logs, errors and the batch summary go to
**stderr**. That makes the output easy to pipe:

```bash
./scrape.sh batch urls.txt | xargs wc -l                 # line count of each file
./scrape.sh https://example.com 2>/dev/null              # just the two paths
./scrape.sh https://example.com 2>/dev/null | grep 'json$' | xargs jq .metadata
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (batch: every URL succeeded) |
| `1` | Fetch/HTTP error, non-HTML content, body > 10 MB, output can't be written (batch: at least one URL failed or was blocked) |
| `2` | Usage error: invalid URL, unknown command, missing argument/file, invalid `BATCH_DELAY`, URL file with no URLs, `-o` in batch, `-o` pointing at a directory |
| `3` | Blocked by an anti-bot challenge (Vercel Security Checkpoint, Cloudflare) |

`scrape` returns the CLI's exit code unchanged.

## How it works

1. `src/web_scraper/fetcher.py` — `httpx` GET with redirects, timeout, a 10 MB
   cap and retries on connection errors. Detects anti-bot challenge pages
   **before** looking at the status code, so a challenge is never saved as if
   it were the content.
2. `src/web_scraper/converter.py` — inlines content streamed by React (see
   below), picks `<main>` → `<article>` → `<body>`, strips `script`, `style`,
   `form` and the like, turns relative links into absolute ones, and renders
   Markdown with `markdownify`.
3. `src/web_scraper/cleaner.py` — the cleanup step (see "Cleanup" above),
   called by the converter unless `--no-clean`.
4. `src/web_scraper/structure.py` — parses the rendered Markdown with
   `markdown-it-py` into the JSON document (sections and typed blocks).
5. `src/web_scraper/output.py` — builds a safe file name from the URL (no path
   traversal), pairs the `.json` with the `.md`, and writes UTF-8.
6. `src/web_scraper/cli.py` — argument parsing, logging, exit codes.

### Next.js / React streaming pages

Sites built with the Next.js App Router (like StackShare) send the HTML
first with only **loading skeletons**; the real content arrives in hidden
`<div id="S:n">` blocks at the end of the page, and the browser's JavaScript
(`$RC`/`$RS` calls) moves them into place. Without handling this, StackShare
produced a 242-byte file with only the title.

The converter replays those moves statically (no JavaScript is executed),
so the full content comes through — for StackShare/Nubank, all 32 tools by
layer, the engineering decisions and the team. This applies to any Next.js
site, not just StackShare.

## Known limitations

- **Anti-bot is intermittent.** StackShare sometimes answers with the Vercel
  Security Checkpoint (HTTP 429, a JavaScript challenge) and sometimes with
  the real page. When challenged, the scraper exits `3` and writes nothing;
  a plain HTTP client can't solve the challenge. Retrying later sometimes
  works.
- **Pages that build their content entirely in JavaScript** (client-side
  rendering without streamed HTML) come out empty or partial — needs a
  headless browser (roadmap).
- **Cleanup is heuristic.** It removes what is generically recognisable as
  chrome; site-specific duplication can remain (on StackShare the four layer
  names appear once in the chart legend and again with their percentages).
  Ordinary links such as "View all" are kept.
- **Images are dropped by default**; use `--no-clean` when they carry content.
- Respect each site's terms of use before scraping at scale — anti-bot
  checkpoints exist precisely to restrict automation.

## Development

```bash
./scrape.sh check     # ruff format --check, ruff check, mypy --strict, shellcheck, pytest
```

Layout:

```text
scrape.sh                    # orchestrator (entry point)
urls.example.txt             # sample batch file
src/web_scraper/             # fetcher, converter, cleaner, structure, output, cli
tests/                       # pytest (converter, cleaner, structure, cli, fetcher/mock transport, output, hook)
docs/specs/                  # url-to-markdown.md, session-checkpoint-hook.md
docs/NOTES/                  # per-session Claude Code notes (see below)
.claude/settings.json        # Claude Code hooks
.claude/hooks/               # session_checkpoint.py
output/                      # generated files (gitignored)
```

### Session notes hook (Claude Code)

Project hooks keep one notes file per Claude Code session,
`docs/NOTES/NOTES.<session_id>.md`, so the essentials survive `/compact`
(spec: [`docs/specs/session-checkpoint-hook.md`](docs/specs/session-checkpoint-hook.md)).

| Event | What happens |
|-------|--------------|
| `PostToolUse` | Every 25 tool calls, Claude gets a reminder to update the notes (goal, decisions, state, next steps, gotchas, key files). Writing the notes file resets the count. |
| `Stop` | When Claude is about to end its turn, it is asked to update the notes first if a checkpoint is urgent (auto-compact waiting) or the notes are a full interval behind. Never twice in a row (`stop_hook_active`), never in plan mode, never for chat-only turns. |
| `PreCompact` | **Auto**-compact with stale notes (tool calls since the last checkpoint) is deferred up to 2 times, and the next tool call (or the end of the turn) brings Claude an urgent reminder to checkpoint first. Manual `/compact` is never deferred. When compaction proceeds, `- <UTC time> — compacted (<trigger>)` is appended to the notes. |
| `SessionStart` (`compact`) | Right after compaction, the notes are put back into Claude's context (up to 9,000 chars), flagged when they were behind. |
| `SessionEnd` | Claude can no longer act, so the hook appends `- <UTC time> — session ended (<reason>)` and the files edited in the session (from the transcript) under `## Session log`. Sessions with no notes and no edits create no file. |

- Configured in `.claude/settings.json`; the script is stdlib-only and runs
  with `python3` (≥ 3.11).
- Change the interval with `SESSION_CHECKPOINT_EVERY=<n>` in the environment
  that launches `claude`.
- Before a manual `/compact`, ask Claude for a checkpoint if the notes may be
  behind — only auto-compact is deferred.
- Deferring an auto-compact that Claude Code triggered to recover from a
  context-limit error fails that request; the 2-deferral cap bounds it.
- The counters live in `.claude/state/` (gitignored). The notes are meant to be
  versioned: they must never contain secrets or PII.

## Roadmap

1. Headless browser (Playwright) as a fallback, only when the plain fetch is
   challenged (exit `3`) or the page depends on JavaScript.
2. More realistic headers/fingerprint, backoff and retries on challenges.
3. Parallel batch with per-host rate limiting.

## License

[MIT](LICENSE)
