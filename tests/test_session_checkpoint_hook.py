"""Runs `.claude/hooks/session_checkpoint.py` as Claude Code does: JSON on stdin."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "session_checkpoint.py"
SESSION_ID = "6a6c6a99-01d2-4111-a2fc-d10a33aba294"
EVERY = 3


def run_hook(project: Path, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(project),
        "SESSION_CHECKPOINT_EVERY": str(EVERY),
    }
    return subprocess.run(  # noqa: S603 — fixed interpreter and script
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def notes_file(project: Path) -> Path:
    return project / "docs" / "NOTES" / f"NOTES.{SESSION_ID}.md"


def tool_call(tool_name: str = "Read", **tool_input: str) -> dict[str, Any]:
    return {
        "session_id": SESSION_ID,
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def pre_compact(trigger: str = "auto") -> dict[str, Any]:
    return {"session_id": SESSION_ID, "hook_event_name": "PreCompact", "trigger": trigger}


def stop(*, stop_hook_active: bool = False, permission_mode: str = "default") -> dict[str, Any]:
    return {
        "session_id": SESSION_ID,
        "hook_event_name": "Stop",
        "stop_hook_active": stop_hook_active,
        "permission_mode": permission_mode,
    }


def session_start(source: str = "compact") -> dict[str, Any]:
    return {"session_id": SESSION_ID, "hook_event_name": "SessionStart", "source": source}


def write_notes(project: Path, text: str) -> Path:
    notes = notes_file(project)
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(text, encoding="utf-8")
    return notes


def session_end(transcript: Path, reason: str = "prompt_input_exit") -> dict[str, Any]:
    return {
        "session_id": SESSION_ID,
        "hook_event_name": "SessionEnd",
        "transcript_path": str(transcript),
        "reason": reason,
    }


def write_transcript(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
    return path


def tool_use(tool_use_id: str, name: str, file_path: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": name,
                    "input": {"file_path": file_path},
                }
            ]
        },
    }


def tool_result(tool_use_id: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "is_error": is_error}]
        },
    }


def test_reminds_exactly_every_n_tool_calls(tmp_path: Path) -> None:
    outputs = [run_hook(tmp_path, tool_call()).stdout for _ in range(EVERY * 2)]

    assert [bool(out) for out in outputs] == [False, False, True, False, False, True]
    reminder = json.loads(outputs[EVERY - 1])["hookSpecificOutput"]
    assert reminder["hookEventName"] == "PostToolUse"
    assert str(notes_file(tmp_path)) in reminder["additionalContext"]


def test_writing_the_notes_file_resets_the_count(tmp_path: Path) -> None:
    for _ in range(EVERY - 1):
        run_hook(tmp_path, tool_call())

    checkpoint = run_hook(tmp_path, tool_call("Write", file_path=str(notes_file(tmp_path))))
    after = [run_hook(tmp_path, tool_call()).stdout for _ in range(EVERY)]

    assert checkpoint.stdout == ""
    assert [bool(out) for out in after] == [False, False, True]


def test_subagent_tool_calls_are_ignored(tmp_path: Path) -> None:
    payload = {**tool_call(), "agent_id": "agent-abc123"}

    outputs = [run_hook(tmp_path, payload).stdout for _ in range(EVERY * 2)]

    assert outputs == [""] * (EVERY * 2)


def test_invalid_session_id_is_rejected_without_writing(tmp_path: Path) -> None:
    payload = {**tool_call(), "session_id": "../../escape"}

    result = run_hook(tmp_path, payload)

    assert result.returncode == 1
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []


def test_session_end_appends_log_with_successfully_edited_files(tmp_path: Path) -> None:
    notes = notes_file(tmp_path)
    notes.parent.mkdir(parents=True)
    notes.write_text("# Session notes\n\nGoal: scrape pages.\n", encoding="utf-8")
    transcript = write_transcript(
        tmp_path / "transcript.jsonl",
        [
            tool_use("t1", "Edit", str(tmp_path / "src" / "app.py")),
            tool_result("t1"),
            tool_use("t2", "Write", str(tmp_path / "denied.py")),
            tool_result("t2", is_error=True),
            tool_use("t3", "Write", str(notes)),
            tool_result("t3"),
        ],
    )

    result = run_hook(tmp_path, session_end(transcript))

    text = notes.read_text(encoding="utf-8")
    assert result.returncode == 0
    assert text.startswith("# Session notes\n\nGoal: scrape pages.\n")
    assert "## Session log" in text
    assert "session ended (prompt_input_exit)" in text
    assert "src/app.py" in text
    assert "denied.py" not in text
    assert f"NOTES.{SESSION_ID}.md" not in text


def test_session_end_without_notes_or_edits_creates_nothing(tmp_path: Path) -> None:
    transcript = write_transcript(tmp_path / "transcript.jsonl", [])

    result = run_hook(tmp_path, session_end(transcript))

    assert result.returncode == 0
    assert not notes_file(tmp_path).exists()


def test_auto_compact_is_deferred_twice_while_notes_are_stale(tmp_path: Path) -> None:
    run_hook(tmp_path, tool_call())

    outputs = [run_hook(tmp_path, pre_compact()).stdout for _ in range(3)]

    assert [json.loads(out)["decision"] for out in outputs[:2]] == ["block", "block"]
    assert outputs[2] == ""


def test_deferred_compact_makes_the_next_tool_call_remind_urgently(tmp_path: Path) -> None:
    run_hook(tmp_path, tool_call())
    run_hook(tmp_path, pre_compact())

    urgent = run_hook(tmp_path, tool_call()).stdout
    following = run_hook(tmp_path, tool_call()).stdout

    context = json.loads(urgent)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("Auto-compact is waiting")
    assert str(notes_file(tmp_path)) in context
    assert following == ""


def test_auto_compact_proceeds_when_notes_are_up_to_date(tmp_path: Path) -> None:
    run_hook(tmp_path, tool_call())
    run_hook(tmp_path, tool_call("Edit", file_path=str(notes_file(tmp_path))))

    assert run_hook(tmp_path, pre_compact()).stdout == ""


def test_manual_compact_is_never_deferred(tmp_path: Path) -> None:
    run_hook(tmp_path, tool_call())

    assert run_hook(tmp_path, pre_compact("manual")).stdout == ""


def test_allowed_compaction_is_logged_in_existing_notes(tmp_path: Path) -> None:
    notes = write_notes(tmp_path, "# Session notes\n")
    run_hook(tmp_path, tool_call())

    run_hook(tmp_path, pre_compact("manual"))

    text = notes.read_text(encoding="utf-8")
    assert text.startswith("# Session notes\n\n## Session log\n\n- ")
    assert "compacted (manual); notes behind by 1 tool call(s)" in text


def test_notes_are_restored_into_context_after_compaction(tmp_path: Path) -> None:
    write_notes(tmp_path, "# Session notes\n\nGoal: scrape pages.\n")
    run_hook(tmp_path, tool_call())

    result = run_hook(tmp_path, session_start())

    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert "Goal: scrape pages." in output["additionalContext"]
    assert "behind by 1 tool call(s)" in output["additionalContext"]


def test_nothing_is_restored_without_notes_or_outside_compaction(tmp_path: Path) -> None:
    without_notes = run_hook(tmp_path, session_start())
    write_notes(tmp_path, "# Session notes\n")
    on_startup = run_hook(tmp_path, session_start("startup"))

    assert without_notes.stdout == ""
    assert on_startup.stdout == ""


def test_stop_is_silent_while_notes_are_less_than_an_interval_behind(tmp_path: Path) -> None:
    for _ in range(EVERY - 1):
        run_hook(tmp_path, tool_call())

    assert run_hook(tmp_path, stop()).stdout == ""


def test_stop_asks_for_a_checkpoint_when_a_full_interval_behind(tmp_path: Path) -> None:
    for _ in range(EVERY):
        run_hook(tmp_path, tool_call())

    result = run_hook(tmp_path, stop())

    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "Stop"
    assert output["additionalContext"].startswith("Before you finish")
    assert str(notes_file(tmp_path)) in output["additionalContext"]


def test_stop_delivers_a_pending_urgent_reminder_once(tmp_path: Path) -> None:
    run_hook(tmp_path, tool_call())
    run_hook(tmp_path, pre_compact())

    at_stop = run_hook(tmp_path, stop()).stdout
    next_call = run_hook(tmp_path, tool_call()).stdout

    context = json.loads(at_stop)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("Auto-compact is waiting")
    assert next_call == ""


def test_stop_never_continues_twice_in_a_row_or_in_plan_mode(tmp_path: Path) -> None:
    for _ in range(EVERY):
        run_hook(tmp_path, tool_call())

    already_continuing = run_hook(tmp_path, stop(stop_hook_active=True))
    planning = run_hook(tmp_path, stop(permission_mode="plan"))

    assert already_continuing.stdout == ""
    assert planning.stdout == ""
