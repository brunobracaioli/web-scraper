# Session d5124ca0 — scraper cleanup (v1.1) + JSON output (v1.2) + -o dir fix

## Goal
1. (v1.1, done) "ajuste o script de scraping para 'limpar' esses dados antes de
   salvar": remove HTML leftovers (images, breadcrumb, tabs, buttons, duplicated
   counts, glued text, duplicated title/H1) from the Markdown output.
2. (v1.2, done) "além de salvar o arquivo .md em prosa, quero que salve
   também um arquivo json para ter uma versão estruturada".
3. (done) "corrija o bug do -o com pasta".
4. (in progress) "consegue criar um repo publico desse nosso projeto no github?"
   — user chose: name `web-scraper`, MIT license, hide email (commits use the
   GitHub noreply address via *local* git config; email removed from
   pyproject `authors`). `.claude/settings.local.json` gitignored.
   Pre-publish scan: no secrets (grep; gitleaks not installed).

## Decisions
- Cleanup is **on by default**, generic (no per-site code), in
  `src/web_scraper/cleaner.py`; `--no-clean` keeps the exact v1 output.
- Responsive duplicates: keep the variant visible at the widest breakpoint
  (Tailwind `hidden`/`sm:hidden`, Bootstrap `d-none`/`d-md-none`).
  `opacity-0`/`invisible` NOT treated as hidden (StackShare % live in tooltips).
- Buttons dropped unless their text has a digit (keeps "5 upvotes").
- Image-only link → text link (aria-label/title/alt); dropped when its parent
  already has a text link to the same href (avatar next to name).
- Removed element leaves a space only when between two siblings.
- Synthesized `# title` only when the content has no `<h1>`.
- JSON (user picked **generic by sections**, not StackShare-specific): always
  written next to the .md (same stem, `.json`); built by parsing the rendered
  Markdown body with `markdown-it-py` (new dep, 4.2.0) so text/links never
  diverge from the .md and markdownify escapes are undone. Schema v1: root
  `blocks` + `sections` tree by heading level; blocks paragraph/list/table/
  code/quote; `links`/`images`/item `blocks` omitted when empty.
- `converter.convert(page, clean) -> Conversion(metadata, body)`;
  `to_markdown(conversion)` and `structure.to_json(conversion)` render it (HTML
  parsed once). stdout now prints 2 paths (.md then .json).
- `-o FILE` names the .md; JSON = `.md`→`.json`, else `.json` appended
  (`v1.2` → `v1.2.json`, never collides). `write_markdown` → `write_text`.

## State
- Done + verified: cleanup (v1.1) and JSON output (v1.2): code, spec
  (section "JSON output"), README, `scrape.sh` help; `./scrape.sh check` green
  (84 tests).
- Real run `output/stackshare.io-nubank_20261007T235356Z_65ab5454.{md,json}`:
  .md body identical to the previous cleaned run, JSON layers 17/6/7/2, team 7,
  47 link URLs identical to the .md. JSON ~18.8 KB (indent=2) vs 3 KB .md.
- `--no-clean -o <path without .md>` → `<path>.json`; raw .md body identical
  to v1, raw JSON has the 43 images.
- Fixed (user asked): `-o` pointing at a directory (or whose `.json` sibling
  is one) → exit 2 before fetching; other write OSErrors → exit 1
  (`EXIT_WRITE_ERROR`), one-line error, no traceback. Regression tests in
  `tests/test_cli.py` (84 passed).

## Gotchas
- `bs4` doesn't re-export `NavigableString`/`PageElement` for mypy → import
  from `bs4.element`.
- RUF001 on literal en/em dashes in regex → use `\u2013`-style escapes.
- mypy rejects `{**inline_text}` into a TypedDict with an extra NotRequired key
  ("not explicitly found in any ** item") → build `{**lead, "blocks": [...]}`
  and `del` the key when empty.

## Key files
`src/web_scraper/cleaner.py`, `src/web_scraper/structure.py`,
`src/web_scraper/converter.py`, `src/web_scraper/output.py`,
`src/web_scraper/cli.py`, `tests/test_cleaner.py`, `tests/test_structure.py`,
`tests/test_cli.py`, `docs/specs/url-to-markdown.md`
