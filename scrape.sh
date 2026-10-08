#!/usr/bin/env bash
# Orchestrator for the web-scraper CLI: setup, single and batch scraping, checks.
# Run `./scrape.sh help` for usage. Works from any directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/output}"
BATCH_DELAY="${BATCH_DELAY:-2}"

# Exit codes of the Python CLI (docs/specs/url-to-markdown.md).
readonly EXIT_OK=0
readonly EXIT_USAGE=2
readonly EXIT_BLOCKED=3

usage() {
  cat <<EOF
Usage: ./scrape.sh <command> [args]

Commands:
  <url> [options]          Shortcut for "scrape <url> [options]"
  scrape <url> [options]   Scrape one page into the output directory (.md + .json)
  batch <file> [options]   Scrape every URL listed in <file> (one per line, # = comment)
  setup                    Check uv and install dependencies
  check                    Format check, lint, type check and tests
  help                     Show this help

Options for scrape/batch are forwarded to the CLI:
  --out-dir DIR   --timeout SECONDS   --no-clean   -v, --verbose
  -o, --output FILE (scrape only; the .json goes next to it)
  Full list: ./scrape.sh scrape --help

Environment:
  OUT_DIR       Output directory      (default: <project>/output)
  BATCH_DELAY   Seconds between URLs  (default: 2)

Examples:
  ./scrape.sh https://stackshare.io/nubank
  ./scrape.sh scrape https://example.com -o notes/example.md
  BATCH_DELAY=5 ./scrape.sh batch urls.txt --timeout 15
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit "$EXIT_USAGE"
}

require_uv() {
  command -v uv >/dev/null 2>&1 \
    || die "uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
}

# --out-dir goes first so a user-supplied --out-dir (later on the line) wins.
run_scraper() {
  uv run --project "$ROOT" web-scraper --out-dir "$OUT_DIR" "$@"
}

cmd_scrape() {
  (($# >= 1)) || die "missing URL. Usage: ./scrape.sh scrape <url> [options]"
  run_scraper "$@"
}

cmd_batch() {
  (($# >= 1)) || die "missing URL file. Usage: ./scrape.sh batch <file> [options]"
  local file="$1"
  shift
  [[ -f $file && -r $file ]] || die "cannot read URL file: $file"
  [[ $BATCH_DELAY =~ ^[0-9]+([.][0-9]+)?$ ]] || die "BATCH_DELAY must be a number of seconds"

  local arg
  for arg in "$@"; do
    case "$arg" in
      -o | --output | --output=*)
        die "-o/--output would make every URL overwrite the same file; use --out-dir"
        ;;
    esac
  done

  local -a blocked=() failed=()
  local total=0 ok=0 url rc
  # Read from fd 3 so the CLI can't swallow the rest of the file from stdin.
  while read -r url _ <&3 || [[ -n ${url:-} ]]; do
    url="${url%$'\r'}" # tolerate CRLF files (Windows editors)
    if [[ -z $url || $url == \#* ]]; then
      continue
    fi
    if ((total > 0)); then
      sleep "$BATCH_DELAY"
    fi
    total=$((total + 1))

    rc=0
    run_scraper "$url" "$@" </dev/null || rc=$?
    case "$rc" in
      "$EXIT_OK") ok=$((ok + 1)) ;;
      "$EXIT_BLOCKED") blocked+=("$url") ;;
      *) failed+=("$url") ;;
    esac
  done 3<"$file"

  ((total > 0)) || die "no URLs found in $file"

  printf '\nbatch: %d total, %d ok, %d blocked, %d failed\n' \
    "$total" "$ok" "${#blocked[@]}" "${#failed[@]}" >&2
  for url in "${blocked[@]}"; do printf '  blocked: %s\n' "$url" >&2; done
  for url in "${failed[@]}"; do printf '  failed:  %s\n' "$url" >&2; done

  if ((ok < total)); then
    exit 1
  fi
}

cmd_setup() {
  uv --version
  uv sync --project "$ROOT"
  printf 'ready. try: ./scrape.sh https://example.com\n'
}

cmd_check() (
  cd "$ROOT"
  uv run ruff format --check src tests .claude/hooks
  uv run ruff check src tests .claude/hooks
  uv run mypy src tests .claude/hooks
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck scrape.sh
  else
    printf 'shellcheck not installed, skipping scrape.sh lint\n' >&2
  fi
  uv run pytest "$@"
)

main() {
  local command="${1:-help}"
  if (($# > 0)); then
    shift
  fi

  case "$command" in
    help | -h | --help)
      usage
      return
      ;;
  esac

  require_uv
  case "$command" in
    http://* | https://*) cmd_scrape "$command" "$@" ;;
    scrape) cmd_scrape "$@" ;;
    batch) cmd_batch "$@" ;;
    setup) cmd_setup ;;
    check) cmd_check "$@" ;;
    *)
      usage >&2
      die "unknown command: $command (URLs must start with http:// or https://)"
      ;;
  esac
}

main "$@"
