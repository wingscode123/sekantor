# M0 spike summary

Date: 2026-11-11 · Machine: Windows 11, Claude Code CLI 2.1.319, Orca 1.4.255,
Claude desktop 5.1231.0 (CLI 2.1.321), VS Code extension (CLI 2.1.322), OpenBot 0.1.0 (CLI 2.1.322).

Details: [claude-hooks.md](claude-hooks.md) · Evidence: [payloads/](payloads/), [evidence/](evidence/)
· Rules: [hosts.yaml](../../hosts.yaml) · Decisions: [ADRs](../adr/)

## Answers to the PRD open questions

| # | Question | Answer | Confidence | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Which OpenBot, and does it have a local API to inject messages? | **nightly-labs/openbot** 0.67.1 (uninstall registry `URLInfoAbout`, `resources/app-update.yml` owner `nightly-labs`). Agents run the Claude Code CLI over SDK stdio (`CLAUDE_AGENT_SDK_CLIENT_APP=openbot/0.1.0`), one process per agent in `~/OpenBot/Agents/agent-<uuid>`. **Yes, a local API exists:** the bundled `resources/cli/openbot-cli.mjs` uses the "Local scripts API" (per-agent opt-in; URL and token in `%APPDATA%/OpenBot/automation`): `GET /v1/agents`, `POST /v1/agents/{id}/messages`, delivery status incl. "the agent waits for a person". The token files were not read. | high | install metadata, CLI source header |
| 1b | Do Ronda's hooks reach OpenBot sessions? | **Not via `~/.claude/settings.json`.** OpenBot passes `--setting-sources=project,local`, so only `.claude/settings*.json` inside each agent dir load. | high | probe cmdline |
| 2 | Do hooks in `~/.claude/settings.json` fire for Claude Code desktop? | **Yes.** Desktop spawns the CLI with `--setting-sources=user,project,local`; we captured SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStop, SessionEnd from a desktop session (project-level settings; user-level loads by the same flag). Also true for the VS Code extension. | high (project-level observed, user-level inferred from flag + docs) | `payloads/claude-desktop/`, `payloads/claude-vscode/` |
| 3 | Does the Orca CLI expose agent status and input? | **Partly.** `orca terminal list/read/send/wait --for tui-idle` gives read + input for agents running in Orca *terminals*. Orca *chat* sessions (SDK) are not exposed beyond `orca search`. Orca already gets status by installing its **own Claude Code hooks** (`~/.orca/agent-hooks/orca-agent-hook.exe` on 16 events, env `ORCA_AGENT_HOOK_PORT`, transport `raw-json-v1`). Ronda's hooks see Orca sessions anyway, so the Orca pos is only needed for non-Claude agents in Orca. | medium (CLI `--help` only, commands not exercised) | `orca --help`, user settings (read-only) |
| 4 | Main OS for dogfooding? | **Windows** (owner confirmed). No tmux/WSL on the machine; Linux/macOS covered by portable code + tests. | n/a | kickoff |
| 5 | Core language? | **Python** (ADR-0001). | n/a | kickoff |
| 6 | macOS: can we read other processes' env? | **Not tested** (no Mac). Mitigation found: the hook process inherits the agent's env (documented and observed), so Claude Code fingerprinting never needs to read another process's env. Only the tmux/process pos (M3) would depend on it. | n/a | `payloads/*/SessionStart` `env` |

## Other findings that change the plan

1. **Use `PermissionRequest` for `waiting_approval`, not `PreToolUse`** (ADR-0002, proposed). It fires
   only when a prompt would appear, also in headless and SDK hosts. `Notification/permission_prompt`
   lags ~6 s.
2. **More hooks than the PRD lists** are needed: `UserPromptSubmit`, `PermissionRequest`,
   `PostToolUse(Failure)`, `StopFailure` (ADR-0002, proposed).
3. **Hook latency**: Python + psutil = 150-900 ms (up to 3 s under load) on Windows. M1 hook is
   stdlib-only, fingerprints once per session, and is registered `async: true` except SessionEnd
   (ADR-0003, proposed).
4. **`CLAUDE_PID`** is present in the hook env: cheap agent PID for FR-07 liveness. Claude desktop
   restarts the CLI on resume (new PID, same `session_id`), so the latest PID wins.
5. **`CLAUDE_CODE_ENTRYPOINT`** identifies the host in one env var: `cli`, `sdk-cli` (headless `-p`),
   `sdk-ts` (Orca chat), `claude-desktop`, `claude-vscode`, `openbot`.
6. **`SubagentStop` fires after `Stop`** for an internal helper (`agent_type: ""`, last message looks
   like a suggested next prompt). Must not change session status.
7. **cwd casing differs** (`d:\Ronda` from VS Code vs `D:\Ronda`): normalise before grouping/display.
8. **Orca's hooks coexist** in the global settings; `ronda install` must append, back up, and
   uninstall only its own entries (ADR-0004).
9. **Settings hot-reload works**: a running Orca session picked up our new `settings.local.json`.
10. The **Claude desktop Electron main process is also named `claude.exe`**. The probe skips
    Chromium helpers (`--type=`), but the main process still shows as `unknown`; the process pos must
    ignore it (exe under `AnthropicClaude/app-*`).

## Still open

- Interactive approval flow in a terminal with `--permission-mode default` (A ran in auto mode, so
  no prompt appeared): `PermissionRequest` → `Notification/permission_prompt` → `PostToolUse`
  ordering. Not blocking M1 (headless capture shows `PermissionRequest`), needed before M2.
- Plain terminal (Windows Terminal) fingerprint: the "terminal" test ran inside an Orca terminal.
- macOS/Linux probes for the unverified `hosts.yaml` rules.
