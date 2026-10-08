# Spec — Session checkpoint hook (Claude Code)

Status: implemented (v3 — Stop) · Owner: Bruno Bracaioli · Updated: 2026-10-07

## Objective

Keep one notes file per Claude Code session with what matters (goal,
decisions, state, next steps), so the essentials survive `/compact` and can be
re-read later. Hooks remind Claude to write the checkpoint (during the turn
and before it ends), hold auto-compact back until it is written, put the notes
back into the context after compaction, and append an automatic record when
the session ends.

## Contract

| Item | Value |
|------|-------|
| Script | `.claude/hooks/session_checkpoint.py` (stdlib only, Python ≥ 3.11 as `python3`) |
| Config | `.claude/settings.json` → `PostToolUse` (all tools), `Stop`, `PreCompact` (manual + auto), `SessionStart` (matcher `compact`), `SessionEnd` |
| Notes file | `docs/NOTES/NOTES.<session_id>.md` (under `$CLAUDE_PROJECT_DIR`) |
| State | `.claude/state/session-checkpoint/<session_id>` — JSON counters (gitignored) |
| Interval | `SESSION_CHECKPOINT_EVERY` env var, default `25` tool calls |
| Input | Hook payload JSON on stdin (`session_id`, `hook_event_name`, `tool_name`, `tool_input`, `stop_hook_active`, `permission_mode`, `trigger`, `source`, `transcript_path`, `reason`) |
| Exit codes | `0` handled (with or without output) · `1` invalid payload or I/O error (non-blocking) |

State per session:

| Field | Meaning |
|-------|---------|
| `since_reminder` | Tool calls since the last reminder or checkpoint (drives the periodic reminder) |
| `since_checkpoint` | Tool calls since the notes were last written (staleness) |
| `compact_deferrals` | Auto-compactions deferred since the last checkpoint/compaction |
| `urgent` | A deferred auto-compact is waiting: remind on the next tool call or turn end |

## Behavior

### PostToolUse

1. Tool calls made inside a subagent (payload has `agent_id`) are ignored: the
   main session owns the notes.
2. A `Write`/`Edit`/`MultiEdit` on the session's notes file **is** the
   checkpoint: the whole state resets, no output.
3. Any other tool call increments `since_checkpoint`.
4. If `urgent` is set, the hook prints the **urgent** reminder
   (`hookSpecificOutput.additionalContext`: auto-compact is waiting, update the
   notes before anything else) and clears `urgent`.
5. Otherwise it increments `since_reminder`; on reaching the interval it prints
   the periodic reminder and resets `since_reminder`, so an ignored reminder is
   repeated only after another full interval.
6. Both reminders name the absolute notes path and the expected sections:
   goal, decisions (and why), state, next steps / open questions, gotchas,
   key files — a short current snapshot, not a log, with no secrets or PII,
   leaving the `## Session log` section untouched.

### Stop

Fires when the main agent finishes its turn (not for subagents). Catches the
moments PostToolUse can't: a turn that ends with text only, and the natural
pause after a task — a better time to checkpoint than mid-task.

1. `stop_hook_active` true (Claude is already continuing because of a Stop
   hook) or `permission_mode: plan` (Claude can't write the notes) → no output,
   so the hook never keeps a turn going twice in a row.
2. `urgent` set → urgent reminder.
3. Notes behind by at least a full interval (`since_checkpoint ≥
   SESSION_CHECKPOINT_EVERY`) → end-of-turn reminder: update the notes, then
   finish without repeating the last answer.
4. Otherwise (including chat-only turns, which don't move the counters) → no
   output.
5. Output is `hookSpecificOutput.additionalContext` (Claude Code continues the
   turn and labels it "Stop hook feedback", not an error). On output, `urgent`
   is cleared and `since_reminder` reset — the reminder was delivered.

### PreCompact

PreCompact can block compaction but cannot talk to Claude, so it defers and
lets PostToolUse deliver the message.

1. `trigger: auto`, notes stale (`since_checkpoint > 0`) and fewer than **2**
   deferrals so far → prints `{"decision": "block", "reason": ...}`, increments
   `compact_deferrals`, sets `urgent`. Two deferrals, because the urgent
   reminder rides on the next tool result: the request carrying it must still
   go out uncompacted for Claude to act on it.
2. Anything else (manual `/compact`, notes up to date, deferral budget spent)
   → compaction proceeds: `compact_deferrals` and `urgent` reset, and if the
   notes file exists the hook appends
   `- <UTC timestamp> — compacted (<trigger>)` (plus how many tool calls the
   notes were behind) under `## Session log`.

### SessionStart (matcher `compact`)

1. If the notes file exists, prints it as
   `hookSpecificOutput.additionalContext`, introduced as Claude's own
   checkpoint from before compaction (capped at 9,000 characters, with a
   pointer to the file when truncated; Claude Code caps context at 10,000).
2. If the notes were behind at compaction (`since_checkpoint > 0`), asks Claude
   to bring them up to date from the compaction summary at its next checkpoint.
3. No notes file, or any other `source` → no output.

### SessionEnd

1. Reads the transcript and collects the files successfully changed by
   `Write`/`Edit`/`MultiEdit`/`NotebookEdit` in the main session (failed calls
   and the notes file itself excluded; paths relative to the project, or
   `~/...`).
2. Appends `- <UTC timestamp> — session ended (<reason>)`, followed by the
   edited files, under `## Session log` (created if missing).
3. If no notes file exists **and** nothing was edited, writes nothing (no empty
   files for sessions that only chatted).
4. Removes the session's state file.
5. Timeout 10 s (SessionEnd's default budget is 1.5 s).

## Edge cases

- `session_id` must match `[A-Za-z0-9_-]{1,128}`; anything else (e.g. `../x`)
  exits 1 without touching the filesystem — the id becomes a file name.
- Corrupt, missing or old-format (plain integer) state file → fresh state.
  State writes are atomic (temp file + rename); parallel tool calls may lose
  an increment, never corrupt the file.
- Invalid `SESSION_CHECKPOINT_EVERY` (non-numeric, < 1) → default.
- Unreadable or partially written transcript lines are skipped.
- `/compact` keeps the session id, so the same notes file continues after it;
  `/clear` starts a new session and a new file.
- Deferral is bounded (2 per compaction), so a session that never writes notes
  still compacts. If Claude ends its turn without a tool call after a
  deferral, the Stop hook delivers the urgent reminder.
- A stale session that keeps ignoring reminders gets at most one Stop
  continuation per turn (`stop_hook_active` guard).
- Auto-compact triggered to **recover** from a context-limit error (rather
  than proactively) fails the current request when deferred (Claude Code
  behavior); the bound limits this to the 2 deferrals.

## Acceptance criteria

- [ ] No output before the interval; reminder with the notes path exactly at
      the interval; silence again until the next interval.
- [ ] Writing the notes file resets the count.
- [ ] Subagent tool calls neither count nor remind.
- [ ] Invalid session id → exit 1, nothing written.
- [ ] Stop is silent while the notes are less than an interval behind.
- [ ] Stop asks for a checkpoint when the notes are a full interval behind.
- [ ] Stop delivers a pending urgent reminder, which the next tool call doesn't repeat.
- [ ] Stop is silent when `stop_hook_active` is true or in plan mode.
- [ ] Auto-compact with stale notes is blocked twice, then allowed.
- [ ] After a deferral, the next tool call gets the urgent reminder.
- [ ] Auto-compact with up-to-date notes, and manual `/compact`, are never blocked.
- [ ] An allowed compaction is logged in an existing notes file.
- [ ] SessionStart `compact` injects the notes; nothing without notes or for
      other sources.
- [ ] SessionEnd appends the log entry with reason and successfully edited
      files, keeping the existing notes content.
- [ ] SessionEnd with no notes and no edits creates nothing.

## Out of scope

- Summarizing the transcript automatically (would need an LLM call); the
  `PostCompact` summary could be archived later if useful.
- Edits made inside subagents (they live in separate transcripts).
