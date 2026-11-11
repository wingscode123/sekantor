# Spike: Claude Code hooks API

Status: **done for M1** (interactive approval flow in a terminal still to capture before M2, see summary.md).

- Date: 2026-11-11
- Claude Code tested: CLI 2.1.319 (`~/.local/bin/claude.exe`), Orca-hosted 2.1.319 (`sdk-ts`),
  Claude desktop app 5.1231.0 bundling CLI 2.1.321, OpenBot bundling CLI 2.1.322
- OS: Windows 11 (Git Bash present, so hooks run under Git Bash by default)
- Sources (read 2026-11-11):
  - https://code.claude.com/docs/en/hooks (reference)
  - https://code.claude.com/docs/en/hooks-guide
  - https://code.claude.com/docs/en/settings
- Raw evidence: [`payloads/`](payloads/) (redacted with `scripts/spike/redact.py`), captured by
  [`scripts/spike/capture_hook.py`](../../scripts/spike/capture_hook.py) registered via
  [`capture-settings.example.json`](capture-settings.example.json) in project-local
  `.claude/settings.local.json` only. The global `~/.claude/settings.json` was not touched.

## TL;DR for Ronda

| Question | Answer | Evidence |
| --- | --- | --- |
| Which events give us the status? | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `Notification`, `Stop`, `StopFailure`, `SessionEnd` | docs + captures |
| Best "waiting for approval" signal | **`PermissionRequest`** (fires when Claude Code is about to ask). `Notification`/`permission_prompt` only fires after ~6 s of waiting. | docs; `payloads/cli-headless/10_PermissionRequest.json` |
| Back to running after a reply | `UserPromptSubmit` (not in the PRD's list of 5 hooks) | `payloads/cli-headless/02_UserPromptSubmit.json` |
| Back to running after approval | `PostToolUse` / `PostToolUseFailure` for the same `tool_use_id`... but `PermissionRequest` has **no** `tool_use_id`; correlate on `prompt_id` + `tool_name` + `tool_input` | captures |
| Turn finished | `Stop` (has `last_assistant_message`) → `waiting_input` | `payloads/cli-headless/05_Stop.json` |
| Turn died on API error | `StopFailure` (`error`: `rate_limit`, `overloaded`, ...) → `error` | docs |
| Session over | `SessionEnd` (`reason`: `clear`, `resume`, `logout`, `prompt_input_exit`, `other`) → `ended` | `payloads/cli-headless/06_SessionEnd.json` |
| How PreToolUse decides (M2) | exit 0 + `hookSpecificOutput.permissionDecision` = `allow` / `deny` / `ask` / `defer` | docs |
| How PermissionRequest decides (M2) | exit 0 + `hookSpecificOutput.decision.behavior` = `allow` / `deny`; exit 2 is **ignored** for this event | docs |
| How Stop continues (M2 reply) | exit 0 + `{"decision": "block", "reason": "<reply text>"}`; check `stop_hook_active`; capped at 8 consecutive continues | docs |
| "No decision" | exit 0 with empty stdout | docs |
| Timeout unit / default | seconds; default **600 s** for command hooks (30 s for `UserPromptSubmit`); SessionEnd has a **1.5 s shared budget** | docs |
| Timed-out hook | cancelled, output discarded, action proceeds (unless `onFailure: "block"`) | docs |
| Do hooks fire in Claude desktop / VS Code? | **Yes**, captured live. Desktop spawns the CLI with `--setting-sources=user,project,local`. | `payloads/claude-desktop/`, `payloads/claude-vscode/` |
| Do user-level hooks fire in OpenBot? | **No.** OpenBot spawns the CLI with `--setting-sources=project,local`. | probe evidence |
| Settings hot reload? | Yes, the file watcher picked up our new `settings.local.json` inside an already-running Orca session. | `payloads/orca/*` |

## Event reference (subset relevant to Ronda)

Common stdin fields on every event: `session_id`, `transcript_path`, `cwd`, `hook_event_name`,
plus (when available) `prompt_id`, `permission_mode`, `effort.level`, `scratchpad_dir`,
`agent_id` / `agent_type` (inside subagents).

| Event | Extra stdin fields (captured or documented) | Can block / decide | Ronda use |
| --- | --- | --- | --- |
| `SessionStart` | `source` (`startup`/`resume`/`clear`/`compact`/`fork`), optional `model`, `session_title` | context only | create session (initial status is a status-engine decision, M1) |
| `UserPromptSubmit` | `prompt`, `prompt_id` | `decision: block` | → `running`; summary = prompt |
| `PreToolUse` | `tool_name`, `tool_input`, `tool_use_id` | `permissionDecision` | → `running`; remember current tool |
| `PermissionRequest` | `tool_name`, `tool_input`, `permission_suggestions` (no `tool_use_id`) | `decision.behavior` | → `waiting_approval`; `request` = tool + input |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, `duration_ms` | `decision: block` | → `running` |
| `PostToolUseFailure` | `error`, `is_interrupt` | none | → `running` |
| `PermissionDenied` | `reason` (auto mode only) | `retry` | → `running` |
| `Notification` | `message`, `title`, `notification_type` | none | `permission_prompt` → `waiting_approval`; `idle_prompt`/`agent_needs_input` → `waiting_input` |
| `Stop` | `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons` | `decision: block` + `reason` | → `waiting_input`; summary = last message |
| `StopFailure` | `error`, `error_details`, `last_assistant_message` | none | → `error` |
| `SubagentStart` / `SubagentStop` | `agent_id`, `agent_type` | | ignore in M1 (do not flip parent status) |
| `SessionEnd` | `reason` | none | → `ended` |

Notes:
- `Notification` `permission_prompt` fires after ~6 s and is skipped entirely if a host or a
  `PermissionRequest` hook answers first. So it cannot be the primary approval signal.
- `Stop` does **not** fire when the user interrupts (Esc). An interrupted session stays
  `running` until the next `UserPromptSubmit`/`Stop`/`Notification`/`SessionEnd`. M1 accepts
  this; `idle_prompt` (~60 s) partly covers it.
- `PermissionRequest` also fires in `-p` (headless) sessions, right before the call is denied
  (captured). There is no `PermissionDenied` there; `PermissionDenied` is auto-mode only.
- In SDK-hosted sessions (Desktop, VS Code, Orca, OpenBot all use
  `--permission-prompt-tool=stdio`), docs: *"the hooks run alongside your host, and whichever
  decides first applies."* Relevant for M2: an approval from Ronda races the host's own dialog.
- `SessionStart` payload had **no `model`** in our captures; the model is only in the transcript
  or the parent process cmdline (`--model=`).

## Output contract (for M2, recorded now)

- Exit 0 + empty stdout = success, no decision. This is what the M1 hook always does.
- Exit 2 = blocking error on events that can block (stderr is the reason). **Never used by Ronda**:
  on PreToolUse it means deny.
- Any other exit code = non-blocking error; first line of stderr may be shown to the user. So the
  M1 hook must swallow all errors and still exit 0.
- JSON is only read if stdout is exactly one JSON object.

PreToolUse decision:
```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "allow|deny|ask|defer", "permissionDecisionReason": "..."}}
```
PermissionRequest decision:
```json
{"hookSpecificOutput": {"hookEventName": "PermissionRequest",
  "decision": {"behavior": "allow|deny", "message": "(deny only)", "interrupt": false}}}
```
Stop continuation (reply):
```json
{"decision": "block", "reason": "<text Claude should act on>"}
```

## Timeouts and failure behaviour

- `timeout` is in **seconds**, per handler. Default 600 s for `command`/`http`/`mcp_tool`,
  30 s on `UserPromptSubmit`. On timeout the hook is cancelled, output discarded, and the action
  proceeds (fail-open for the agent = fail-closed for Ronda: no approval happens).
- `SessionEnd`: all hooks share a **1.5 s** budget (raise with a per-hook `timeout` up to 60 s or
  `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`).
- Matching hooks for one event run in parallel; identical handlers in several settings files run
  once.
- `async: true` (command hooks only) runs the hook in the background; Claude does not wait and
  ignores decisions. In `-p` mode, async hooks still running at teardown are killed.
- `type: "http"` hooks exist: POST the stdin JSON to a URL; connection failure / non-2xx = non-blocking
  error. Header values can interpolate env vars listed in `allowedEnvVars`.

## Settings, shells and Windows

- Files: `~/.claude/settings.json` (user), `.claude/settings.json` (project, committed),
  `.claude/settings.local.json` (project, local), managed policy. Hooks **merge** across levels.
- Hosts can restrict which files load with `--setting-sources` (observed, not documented on the
  hooks page):

  | Host | `CLAUDE_CODE_ENTRYPOINT` | `--setting-sources` | Ronda user-level hook fires? |
  | --- | --- | --- | --- |
  | Terminal CLI (in an Orca terminal) | `cli` (headless `-p` shows `sdk-cli`) | default (all) | yes (captured) |
  | Orca 1.4.255 | `sdk-ts` | `user,project,local` | yes |
  | Claude desktop 5.1231.0 | `claude-desktop` | `user,project,local` | yes (captured) |
  | VS Code extension | `claude-vscode` | not passed (all) | yes (captured) |
  | OpenBot 0.1.0 | `openbot` | `project,local` | **no**, only via the agent dir's `.claude/` |

- Windows: shell-form commands run in Git Bash (PowerShell if Git Bash is missing). Exec form
  (`command` + `args`) runs without a shell and needs a real `.exe`. We used exec form:
  `"command": "${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe"`.
- Without Git Bash, a failing PreToolUse/PermissionRequest hook with `onFailure` unset can
  block the tool call. `ronda-hook` must therefore never exit non-zero.

## Measured hook overhead (Windows, Python 3.11 + psutil)

`timing_ms.total` inside the capture script (excludes interpreter start-up, ~40-60 ms):

| Event | ms |
| --- | --- |
| typical | 150-340 |
| worst (`PermissionRequest`) | 923 |

The capture script walks the full parent chain with psutil, which is slow on Windows. This is
**over the 100 ms budget**; M1 must measure and fix it (options: walk the chain only on
`SessionStart`, `async: true` for observe-only events, lighter stdlib-only hook). See ADR to come.

## Open items

1. Interactive approval in a terminal with `--permission-mode default`: the manual test ran in auto
   mode, so no prompt appeared. Captured so far: `Notification`/`idle_prompt`
   (`"Claude is waiting for your input"`, ~60 s after `Stop`). Needed before M2, not for M1.
2. A plain terminal outside Orca (Windows Terminal) for its fingerprint.
