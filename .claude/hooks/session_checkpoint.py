#!/usr/bin/env python3
"""Claude Code hook: per-session notes in docs/NOTES/ that survive /compact.

PostToolUse: every N tool calls, remind Claude to update the session's notes file;
writing that file is the checkpoint and resets the count.
Stop: before the turn ends, ask for a checkpoint that is pending or overdue.
PreCompact: defer auto-compact while the notes are stale (PostToolUse then reminds
urgently) and log the compaction once it proceeds.
SessionStart (compact): put the notes back into Claude's context.
SessionEnd: Claude can no longer act, so the hook appends an automatic record itself.

Spec: docs/specs/session-checkpoint-hook.md. Stdlib only; payload JSON on stdin.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NOTES_DIR = Path("docs/NOTES")
STATE_DIR = Path(".claude/state/session-checkpoint")
CHECKPOINT_EVERY_ENV = "SESSION_CHECKPOINT_EVERY"
DEFAULT_CHECKPOINT_EVERY = 25
# The urgent reminder rides on the next tool result, so the request carrying it
# must still go out uncompacted: one deferral is not enough.
MAX_COMPACT_DEFERRALS = 2
MAX_RESTORED_CHARS = 9_000  # Claude Code caps additionalContext at 10,000 chars
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
NOTES_EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})
FILE_EDIT_TOOLS = NOTES_EDIT_TOOLS | {"NotebookEdit"}
FILE_PATH_KEYS = ("file_path", "notebook_path")
SESSION_LOG_HEADING = "## Session log"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

NOTES_GUIDE = f"""\
Keep it a short current snapshot, not a log:
- Goal: what the user asked for (their words when it matters) and constraints
- Decisions: what was decided and why
- State: done and verified / in progress / not started
- Next steps and questions waiting on the user
- Gotchas: errors hit and how they were fixed
- Key files
No secrets, tokens or PII. Leave the "{SESSION_LOG_HEADING}" section (appended by \
the hooks) as it is."""

REMINDER = (
    "Session checkpoint due (behind by {count} tool call(s)). Create or update {notes} "
    "so the essentials survive /compact, then carry on with the task. " + NOTES_GUIDE
)
URGENT_REMINDER = (
    "Auto-compact is waiting for your notes: it was deferred so you can checkpoint "
    "first. Before anything else, create or update {notes} (behind by {count} tool "
    "call(s)). " + NOTES_GUIDE
)
STOP_REMINDER = (
    "Before you finish: your session notes are behind by {count} tool call(s). Create or "
    "update {notes} so the essentials survive /compact, then end the turn without "
    "repeating your last answer. " + NOTES_GUIDE
)
RESTORED_NOTES = (
    "Session notes you saved before the conversation was compacted ({notes}). They are "
    "your own checkpoint: rely on them and keep updating the file.{stale}\n\n{content}"
)
STALE_NOTES = (
    " They were behind by {count} tool call(s) at compaction: bring them up to date "
    "from the compaction summary at your next checkpoint."
)


class PayloadError(ValueError):
    """The hook payload is not what Claude Code sends."""


@dataclass(frozen=True, slots=True)
class Session:
    root: Path
    session_id: str

    @property
    def notes(self) -> Path:
        return (self.root / NOTES_DIR / f"NOTES.{self.session_id}.md").resolve()

    @property
    def state_file(self) -> Path:
        return self.root / STATE_DIR / self.session_id


@dataclass(slots=True)
class CheckpointState:
    """Per-session counters persisted between hook runs."""

    since_reminder: int = 0
    since_checkpoint: int = 0
    compact_deferrals: int = 0
    urgent: bool = False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise PayloadError("payload is not a JSON object")
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or Path.cwd())
        session = Session(root, _session_id(payload))
        handler = HANDLERS.get(str(payload.get("hook_event_name")))
        output = handler(payload, session) if handler else None
        if output:
            print(output)
    except (ValueError, OSError) as exc:
        print(f"session-checkpoint: {exc}", file=sys.stderr)
        return 1
    return 0


def handle_post_tool_use(payload: dict[str, Any], session: Session) -> str | None:
    """Count the tool call; return a reminder when a checkpoint is due."""
    if "agent_id" in payload:  # subagent tool call: the main session owns the notes
        return None
    if payload.get("tool_name") in NOTES_EDIT_TOOLS and _target(payload) == session.notes:
        _save_state(session, CheckpointState())
        return None

    state = _load_state(session)
    state.since_checkpoint += 1
    if state.urgent:
        template = URGENT_REMINDER
        state.urgent = False
    else:
        state.since_reminder += 1
        if state.since_reminder < _checkpoint_every():
            _save_state(session, state)
            return None
        template = REMINDER
    state.since_reminder = 0
    _save_state(session, state)
    reminder = template.format(count=state.since_checkpoint, notes=session.notes)
    return _context_output("PostToolUse", reminder)


def handle_stop(payload: dict[str, Any], session: Session) -> str | None:
    """Before the turn ends, ask for a checkpoint that is pending or overdue."""
    # Already continuing because of a Stop hook, or unable to write files: let it end.
    if payload.get("stop_hook_active") or payload.get("permission_mode") == "plan":
        return None
    state = _load_state(session)
    if state.urgent:
        template = URGENT_REMINDER
    elif state.since_checkpoint >= _checkpoint_every():
        template = STOP_REMINDER
    else:
        return None
    state.urgent = False
    state.since_reminder = 0
    _save_state(session, state)
    reminder = template.format(count=state.since_checkpoint, notes=session.notes)
    return _context_output("Stop", reminder)


def handle_pre_compact(payload: dict[str, Any], session: Session) -> str | None:
    """Defer auto-compact while the notes are stale; log the compaction otherwise."""
    state = _load_state(session)
    trigger = str(payload.get("trigger", "unknown"))
    if (
        trigger == "auto"
        and state.since_checkpoint > 0
        and state.compact_deferrals < MAX_COMPACT_DEFERRALS
    ):
        state.compact_deferrals += 1
        state.urgent = True
        _save_state(session, state)
        reason = (
            f"session-checkpoint: auto-compact deferred ({state.compact_deferrals}/"
            f"{MAX_COMPACT_DEFERRALS}) so Claude can update {session.notes} first"
        )
        return json.dumps({"decision": "block", "reason": reason})

    state.compact_deferrals = 0
    state.urgent = False
    _save_state(session, state)
    if session.notes.exists():
        behind = state.since_checkpoint
        suffix = f"; notes behind by {behind} tool call(s)" if behind else ""
        _append_log(session, [f"- {_now()} — compacted ({trigger}){suffix}"])
    return None


def handle_session_start(payload: dict[str, Any], session: Session) -> str | None:
    """After compaction, put the notes back into Claude's context."""
    if payload.get("source") != "compact" or not session.notes.exists():
        return None
    content = session.notes.read_text(encoding="utf-8").strip()
    if len(content) > MAX_RESTORED_CHARS:
        content = f"{content[:MAX_RESTORED_CHARS]}\n\n[truncated: read {session.notes}]"
    behind = _load_state(session).since_checkpoint
    stale = STALE_NOTES.format(count=behind) if behind else ""
    context = RESTORED_NOTES.format(notes=session.notes, stale=stale, content=content)
    return _context_output("SessionStart", context)


def handle_session_end(payload: dict[str, Any], session: Session) -> str | None:
    """Append an end-of-session entry (time, reason, edited files) to the notes."""
    transcript = payload.get("transcript_path")
    edited = [
        path
        for path in (edited_files(Path(transcript)) if transcript else [])
        if path.resolve() != session.notes
    ]
    session.state_file.unlink(missing_ok=True)
    if not session.notes.exists() and not edited:
        return None

    lines = [f"- {_now()} — session ended ({payload.get('reason', 'unknown')})"]
    if edited:
        lines.append("  - files edited:")
        lines.extend(f"    - `{_display_path(path, session.root)}`" for path in edited)
    _append_log(session, lines)
    return None


HANDLERS: dict[str, Callable[[dict[str, Any], Session], str | None]] = {
    "PostToolUse": handle_post_tool_use,
    "Stop": handle_stop,
    "PreCompact": handle_pre_compact,
    "SessionStart": handle_session_start,
    "SessionEnd": handle_session_end,
}


def edited_files(transcript: Path) -> list[Path]:
    """Files changed by successful file-edit tool calls, in first-edit order."""
    requested: dict[str, Path] = {}
    failed: set[str] = set()
    for entry in _transcript_entries(transcript):
        for block in _content_blocks(entry):
            if block.get("type") == "tool_use" and block.get("name") in FILE_EDIT_TOOLS:
                path = _file_path(block.get("input"))
                if path is not None:
                    requested[str(block.get("id"))] = path
            elif block.get("type") == "tool_result" and block.get("is_error"):
                failed.add(str(block.get("tool_use_id")))

    edited: dict[Path, None] = {}
    for tool_use_id, path in requested.items():
        if tool_use_id not in failed:
            edited.setdefault(path, None)
    return list(edited)


def _append_log(session: Session, lines: list[str]) -> None:
    notes = session.notes
    existing = (
        notes.read_text(encoding="utf-8") if notes.exists() else f"# Session {session.session_id}\n"
    )
    if SESSION_LOG_HEADING not in existing:
        existing = f"{existing.rstrip()}\n\n{SESSION_LOG_HEADING}\n\n"
    elif not existing.endswith("\n"):
        existing += "\n"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")


def _context_output(event: str, context: str) -> str:
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    )


def _session_id(payload: dict[str, Any]) -> str:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise PayloadError(f"invalid session_id: {session_id!r}")
    return session_id


def _target(payload: dict[str, Any]) -> Path | None:
    path = _file_path(payload.get("tool_input"))
    return path.resolve() if path is not None else None


def _file_path(tool_input: object) -> Path | None:
    if not isinstance(tool_input, dict):
        return None
    for key in FILE_PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return Path(value)
    return None


def _transcript_entries(transcript: Path) -> Iterator[dict[str, Any]]:
    try:
        with transcript.open(encoding="utf-8") as lines:
            for line in lines:
                try:
                    entry = json.loads(line)
                except ValueError:  # partially written or corrupt line
                    continue
                if isinstance(entry, dict):
                    yield entry
    except FileNotFoundError:
        return


def _content_blocks(entry: dict[str, Any]) -> Iterator[dict[str, Any]]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        yield from (block for block in content if isinstance(block, dict))


def _display_path(path: Path, root: Path) -> str:
    for base, prefix in ((root.resolve(), ""), (Path.home(), "~/")):
        if path.is_relative_to(base):
            return f"{prefix}{path.relative_to(base)}"
    return str(path)


def _now() -> str:
    return datetime.now(UTC).strftime(TIMESTAMP_FORMAT)


def _checkpoint_every() -> int:
    try:
        every = int(os.environ.get(CHECKPOINT_EVERY_ENV, DEFAULT_CHECKPOINT_EVERY))
    except ValueError:
        return DEFAULT_CHECKPOINT_EVERY
    return every if every >= 1 else DEFAULT_CHECKPOINT_EVERY


def _load_state(session: Session) -> CheckpointState:
    """Missing, corrupt or old-format (plain integer) state means a fresh start."""
    try:
        raw = json.loads(session.state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CheckpointState()
    if not isinstance(raw, dict):
        return CheckpointState()
    return CheckpointState(
        since_reminder=_count(raw.get("since_reminder")),
        since_checkpoint=_count(raw.get("since_checkpoint")),
        compact_deferrals=_count(raw.get("compact_deferrals")),
        urgent=raw.get("urgent") is True,
    )


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _save_state(session: Session, state: CheckpointState) -> None:
    """Atomic write: parallel tool calls may lose an increment, never corrupt the file."""
    path = session.state_file
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(asdict(state)), encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    sys.exit(main())
