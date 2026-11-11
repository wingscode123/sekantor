# Spike: approve and reply from outside the terminal (M2)

Date: 2026-11-11 · Claude Code 2.1.322, interactive, `--permission-mode default`, Windows 11,
driven through an Orca terminal (`orca terminal send/read`). Test hooks in a throw-away folder
(project `.claude/settings.local.json`), timestamps from the hooks themselves.

## 1. A waiting PermissionRequest hook does not block the terminal prompt

PermissionRequest hook (sync) sleeps 20 s with no decision.

| t | event |
| --- | --- |
| +6.8 s | UserPromptSubmit |
| +14.1 s | PermissionRequest hook starts; the permission menu is already on screen |
| +20.2 s | Notification `permission_prompt` (fires while the hook still runs) |
| +34.1 s | hook ends, no decision; the menu stays until the person answers |

## 2. A hook decision answers the menu

Hook waits for a file, then prints
`{"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}`.

| t | event |
| --- | --- |
| +14.9 s | PermissionRequest hook starts, menu on screen |
| +22.8 s | hook returns `allow` |
| +30.6 s | PostToolUse: the command ran with no input in the terminal |

## 3. Answering in the terminal first wins

| t | event |
| --- | --- |
| +16.7 s | PermissionRequest hook starts and waits |
| +26.9 s | "1" (Yes) typed in the terminal |
| +32.1 s | PostToolUse: the command ran |
| +52.8 s | the hook returns `deny`: ignored, the file was already written |

"Whichever decides first applies" (docs) holds for the terminal too. The waiting hook keeps
running until it returns; Ronda must cancel it when the session moves on.

## 4. Reply through an async Stop hook with asyncRewake

Stop hook: `"async": true, "asyncRewake": true`; waits for a file, then writes the text to
stderr and exits 2. The turn ends normally and the terminal is free in the meantime.

| t | event |
| --- | --- |
| +168.5 s | Stop hook starts (turn over, prompt free) |
| +180.1 s | reply written; hook exits 2 |
| +182.6 s | UserPromptSubmit fires; screen shows "Stop hook feedback"; Claude runs the requested command |
| +192.9 s | next Stop, `stop_hook_active: true` |

Claude described it as "The stop hook asked me to run ...": the reply arrives as hook feedback,
not as a typed user message, and Claude acted on it.

## Consequences for M2

- Approve/deny: a **synchronous** PermissionRequest hook that long-polls the hub. Waiting is safe
  because the terminal (or host) prompt stays usable; the first answer wins.
- Reply: an **async + asyncRewake** Stop hook that long-polls the hub. It never blocks the agent.
- The hub must release waiting hooks when the session moves on (PostToolUse, PermissionDenied,
  UserPromptSubmit, Stop, SessionEnd), so stale hooks exit and the UI hides stale buttons.
- One idle waiting process per session (Python, roughly 15-30 MB each) is the cost of reply.

## M2 end-to-end check (built Ronda, same setup)

Interactive Claude Code in an Orca terminal, `ronda install claude --project` (new hook shape),
hub from `ronda up`, actions from the CLI (`ronda approve/deny/reply`). 2026-11-11.

| Step | Result |
| --- | --- |
| Agent asks to run `echo from-ronda > approved.txt` | card in "Needs you" with Approve and Deny; host Orca, branch shown |
| It was answered outside Ronda first (terminal/Orca) | Ronda refused the late approve ("not waiting"); nothing ran twice |
| `ronda reply` with a new instruction | agent woke ("Stop hook feedback") and asked to run it |
| `ronda approve` | command ran, `replied.txt` written; audit: reply and approve `delivered` |
| `ronda deny` on `echo nope > denied.txt` | terminal: "Denied by the user from Ronda."; no file |
| `ronda approve` on `rm -rf ./junk` | asked for a second confirmation; "n" sent nothing; deny afterwards; folder kept |

## M4: reply in an Orca chat (Agent SDK host)

2026-11-11. Orca 1.4.255 chat session (`CLAUDE_CODE_ENTRYPOINT=sdk-ts`, model haiku), test hooks in
project settings: Stop `async` + `asyncRewake` waiting for a file; UserPromptSubmit logged.

| t | event |
| --- | --- |
| +0 s | prompt "Reply with exactly READY"; agent answers READY; Stop hook starts waiting |
| +3 s | reply written; hook exits 2 |
| +5.6 s | UserPromptSubmit in the same session; transcript shows "Stop hook feedback" with the text |
| +8.7 s | agent answers WOKE; Stop again with `stop_hook_active: true` |

Reply is therefore enabled for `sdk-ts` as well as `cli` (`reply_entrypoints` in config.toml).
Claude desktop (`claude-desktop`) and VS Code (`claude-vscode`) are still to be tried by hand.
