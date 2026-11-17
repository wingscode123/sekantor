# SeKantor: a pixel office for your AI agents (design)

- Date: 2026-11-16
- Status: Draft for owner approval (owner answered the builder check on 2026-11-16)
- Replaces: the Ronda inbox direction (docs/PRD.md). Ronda's detection and status engine are kept.

## 1. Why

Ronda shows every AI coding agent on the machine as an inbox you can answer from. After weeks of
dogfooding, the owner found that waiting for an agent in its own app is fine: an inbox alone is not
compelling. Meanwhile "virtual offices" where people watch their AI agents work are popular.

SeKantor ("sekantor", Indonesian for *sharing an office, officemates*) turns the same data into a 2D
pixel-art office. Every agent running on the machine is detected and gets a desk and an avatar. You
watch them work. When one needs you, it walks over to your desk. You answer in the agent's own app,
one click away. You can restyle the office and the avatars by typing a prompt, carried out by your
own AI agent through ACP (Agent Client Protocol), so it runs on your own AI subscription.

## 2. Who it is for

- Developers who run several coding agents at once (Claude Code in a terminal, Claude desktop,
  VS Code, Orca, OpenBot, CLI agents in tmux).
- Vibecoders building projects with AI, who often have no Python, uv or Node installed and do not
  live in a terminal.

Single user, single machine. No teammates, accounts or sync.

## 3. Goals, non-goals, anti-goals

Goals
1. Install with a normal installer and see your agents in the office within 2 minutes, without a terminal.
2. Show at a glance who is working on what, who needs you, and who is stuck.
3. Make watching pleasant enough that the owner keeps the mini window open by choice (success: a
   week of daily use).
4. Restyle the office and avatars by prompt; a tidy result in under 1 minute.

Non-goals (MVP)
- Answering, approving or replying from SeKantor. Replies happen in the source app ("Open in Orca").
- Relay to phones (ntfy, Telegram, webhooks) and the audit log.
- Teams, multiple machines, cloud anything.
- Running agents for coding work from SeKantor (a later phase may, see section 9).
- Installing Node, an ACP adapter or an agent for the user (restyling needs one already set up).
- A Python/PyPI/uv install path: the desktop app is the only product.
- Signed installers and macOS/Linux builds in the MVP (they come before the public release).

Anti-goals (a failure even if it works)
- It slows the machine: noticeable CPU or RAM use while only being watched.
- Any agent data leaves the machine. SeKantor itself makes no outbound network calls; prompt-based
  restyling goes through the user's agent, which the user already trusts with the network.
- It approves anything on an agent's behalf. (It cannot: no approve path in the MVP.)
- It copies the look, characters or assets of an existing game.

## 4. Constraints carried over

- Local-first; the hub binds to 127.0.0.1 only; a token is required on every local request.
- Hooks must never break or noticeably slow an agent: fail closed (silently) and stay fast.
- Windows, macOS and Linux.
- Small Conventional Commits, tests first for the status engine, an ADR per non-trivial decision.

## 5. Approaches considered

### 5.1 Where it runs (owner chose: desktop app)
| Option | Trade-off |
| --- | --- |
| Browser tab (today's web UI) | Fastest, but tabs get lost and install still needs Python/uv: wrong for vibecoders |
| **Desktop app with an installer, full window + always-on-top mini mode** (chosen) | One extra phase to package; double-click install, can float over other windows |
| Mini widget only | Too small to explore or restyle the office |

### 5.2 How restyling works (owner chose: A first, then C)
| Option | Trade-off |
| --- | --- |
| **A. Asset kit**: the agent picks and arranges pieces from a bundled pixel-art kit and writes a theme file | Always tidy, fast, cheap; limited to what the kit has |
| B. The agent draws every sprite as pixel matrices | Unlimited but uneven quality, slow, costly, animation frames hard to keep consistent |
| **C. Kit plus small drawn items**: A, and the agent may draw new small items (32x32, office palette) when the kit lacks them; avatar bodies and animations always come from the kit | Freedom where it is cheap, polish where it matters |

### 5.3 How the desktop app is built (builder's call, recorded here)
| Option | Trade-off |
| --- | --- |
| **Tauri shell + today's Python hub as a bundled sidecar** (chosen) | Reuses tested detection/status code; adds packaging work (frozen Python, ~30-50 MB, possible antivirus false positives on Windows) |
| Rewrite the hub in Rust inside Tauri | Smallest app, one language for the shell; rewrites ~2,000 lines of tested code before anything new is visible |
| Electron | Easiest web integration; 100+ MB and heavier at idle, against the anti-goal |

The sidecar can be replaced by a Rust hub later without changing the UI, because the UI talks to the
hub only over its local HTTP/WebSocket API.

**The hub outlives the window** (builder's call): hooks post events whether or not the office is
open, so the hub runs in the background from login (today's `ronda service`, renamed) and the
desktop app attaches to it (port and token from `~/.sekantor`). Closing the window does not stop the
hub; quitting from the tray icon does. If no hub runs when the app opens, the app starts it. An
existing `ronda service` is replaced on first run.

## 6. What the user sees

### 6.1 The office
One open-plan floor seen from above, in 2D pixel art:

```
┌──────────────────────────────────────────────────────────┐
│ [door]     ┌─ ronda ─────────┐  ┌─ agent-platform ─┐ [☕]│
│            │ 🧑‍💻 🧑‍💻          │  │ 🧑‍💻               │ pantry
│            └─────────────────┘  └──────────────────┘    │
│  [server rack ▮▮]   ┌─ openbot agents ───────────────┐   │
│                     │ 🧑 🧑 🧑 🧑 🧑 🧑 🧑 🧑 🧑          │   │
│                     └────────────────────────────────┘   │
│                                   [ YOUR DESK  🙋 ! ]     │
└──────────────────────────────────────────────────────────┘
```

- Desks are grouped in clusters by project (the agent's working folder / git repo). The floor grows
  as agents appear; empty desks are cleared after a while.
- Fixed places: the door (arrive/leave), pantry (idle), server rack (running commands), and **your
  desk**, where avatars come when they need you.
- Each desk has a name plate: agent name, app (Orca, Claude desktop, VS Code, terminal, OpenBot,
  tmux) and project/branch.
- Clicking an avatar opens a card: what it is doing now, its last few steps (today's timeline), and
  **Open in <app>** (today's FR-14 opener).

### 6.2 Activity to animation
| The agent is | In the office |
| --- | --- |
| reading files (Read, Grep, Glob) | leafing through papers at its desk |
| editing code (Edit, Write) | typing fast |
| running commands or tests (Bash) | walks to the server rack, lights blink |
| searching the web (WebSearch, WebFetch) | peering at the screen with a magnifier |
| other tools (MCP, subagents, ...) | generic "working" animation |
| needs permission or an answer | walks to your desk, "!" balloon over its head; desktop notification |
| error | smoke from its monitor, scratches its head |
| done, waiting for a new task | goes to the pantry for coffee |
| session ended | leaves through the door |

Detected agents without tool detail (OpenBot, Orca terminals, tmux) use status only: working, needs
you, error, idle, gone.

### 6.3 Avatar identity
An avatar belongs to an *agent identity*, not a session: (app, project) for Claude Code sessions, the
agent's own name for OpenBot. A new Claude Code session in the same project brings back the same
avatar, so the office has recurring colleagues instead of a new hire per session. Sessions running at
the same time in the same project each get an avatar: the identity is (app, project, seat), where the
seat is the lowest free one, so the second concurrent session becomes a recurring colleague at the
next desk. (Builder's call; the owner may change it.)

### 6.4 Two windows
- **Full window**: explore the office, click avatars, restyle.
- **Mini mode**: a small always-on-top window in a corner showing your desk and whoever is walking to
  it, plus a count of busy agents. Click to open the full window.

Idle cost: animations at a low frame rate (for example 10-12 fps), rendering paused when the window is
hidden or minimised.

## 7. Restyling by prompt (ACP)

1. The user types a prompt in the "Restyle" panel and picks an installed ACP agent (Claude Code via
   its ACP adapter, Gemini CLI, Codex, ...). SeKantor lists the ones it finds. **Owner decision:
   restyling is for users who already have an ACP agent set up.** Without one, the panel shows a short
   guide to setting one up, and the office keeps working with the built-in themes. SeKantor never
   downloads or installs a runtime or agent itself.
2. SeKantor starts the agent as an ACP client over stdio, in a scratch folder, with a system message
   that describes the theme format and the kit catalogue (asset ids, what each looks like in words,
   palettes, character parts).
3. The agent answers with a theme file (JSON). Containment, best effort per agent (builder's call):
   the agent starts in an empty scratch folder with no user files; SeKantor advertises no file or
   terminal capability, denies every permission request, and turns off the agent's own tools where the
   agent offers a setting for it (for example Claude Code's allowed/disallowed tools). Agents run some
   read-only tools without asking; the scratch folder keeps them away from project files, and the
   system message asks for text only. This is not an OS sandbox; the docs say so.
4. SeKantor validates the theme against its schema (unknown asset ids, out-of-bounds layout and
   oversized custom sprites are rejected with a message the agent can fix in one retry), renders a
   **preview**, and offers **Apply / Try again / Cancel**. Applied themes are kept, so the previous
   one can be restored.
5. Phase C adds `custom_sprites`: small pixel matrices (max 32x32, palette indexes only), drawn by the
   agent for items the kit lacks.

Themes are data only: no code from an agent is ever executed by SeKantor.

Theme file, outline (the builder defines the exact schema and versions it):
- `version`, `name`, `palette`
- `floor`: tile ids, size, walls, windows
- `zones`: positions of door, pantry, server rack, your desk, desk clusters
- `decor`: placed kit items (id, x, y, variant)
- `characters`: a default look plus rules matching an agent identity (app, project, agent name) to
  kit parts (body, skin, hair, outfit, accessory, palette swaps)
- `custom_sprites` (phase C)

## 8. What is reused, changed and dropped

Reused from Ronda
- Detection: Claude Code hooks (with host fingerprinting: terminal, Claude desktop, VS Code, Orca,
  OpenBot), the OpenBot, Orca and tmux pos processes.
- Hub: event intake, SQLite store, status engine and sweep, WebSocket stream, timeline, the opener
  (Open in <app>), native notifications, `service` (start at login), lifeline, stats for dogfooding.
- The inbox web UI stays until the office replaces it in S2, so the owner can keep dogfooding
  throughout (builder's call).

Changed
- **Activity**: events gain a structured activity (tool name and a category: read, edit, run, web,
  other) instead of only a text summary. This changes the public event schema: a new optional field
  with an ADR, or schema v2.
- **Hooks**: with no approve or reply path, every hook can be asynchronous, so a slow hub can never
  delay an agent. The hook binary must ship inside the desktop app instead of a Python venv. It may
  become a small native forwarder that posts the raw payload and the hub does the translating
  (builder's call; keep the "fail silently, never block" rule either way).
- **Setup**: first run offers "Connect Claude Code" (installs the global hooks, with backup, as
  `ronda install claude --global` does today) and detects OpenBot/Orca/tmux.
- **Names**: package, commands, folders (`~/.ronda` to `~/.sekantor` with a one-time migration),
  repository (`wingscode123/ronda` renamed to `wingscode123/sekantor`).

Dropped (kept in git history)
- Approve/deny/reply from the UI and the hooks' waiting for answers (PermissionRequest wait, Stop
  asyncRewake), the actions API and audit log, the relay (ntfy, Telegram, webhooks); the inbox web UI
  once S2 lands; the PyPI/uv install path and its CLI as a product (a CLI may remain inside the app
  for support, e.g. `sekantor doctor`).

## 9. Phases

| Phase | Delivers | Done when |
| --- | --- | --- |
| S0 Rename | Repo, package and paths renamed to sekantor; dropped features removed (inbox UI kept); hooks all async | Tests pass; owner's hooks work after reinstall |
| S1 Desktop shell | Tauri app with the hub as a background sidecar, an unsigned **Windows** installer, first-run setup, start at login, tray icon | A clean Windows machine goes from installer to "agents detected" without a terminal (past the SmartScreen warning) |
| S2 Office | Office renderer, desks by project, activity animations, name plates, avatar card with Open in, mini mode, notifications; inbox UI removed | Owner keeps it open a full working day; idle CPU stays low |
| S3 Restyle (A) | ACP client, Restyle panel, theme schema and validation, preview/apply/undo, starter kit | A prompt gives a tidy, valid office in under a minute with Claude Code and one other ACP agent |
| S4 Restyle (C) | Agent-drawn small items | Drawn items pass validation and look at home in the kit's style |
| Release | Signed Windows installer, macOS (signed, notarized) and Linux builds, commissioned asset kit | Before going public |
| Later | Launch agents from the office through ACP (full control, replies inside SeKantor) | Not planned yet |

The asset kit is made in parallel with S0-S2 and is needed by S2.

## 10. Open decisions (owner)

1. **Asset kit**: decided: a CC0 (or commercial-use) pack with *layered* characters (body, hair,
   outfit, accessory as separate sprite sheets with walk/type/read/idle frames) for the MVP; a
   commissioned kit before the public release. Still open: which pack. If no suitable layered pack
   exists, characters fall back to whole pre-drawn sprites with palette swaps, and the theme's
   `characters` rules pick a sprite and palette instead of parts. Must not resemble a specific
   existing game.
2. **Domain**: `sekantor.com` is taken; `.app`, `.dev`, `.id` had no DNS record on 2026-11-16 and may be free.
3. **Release CI**: installers need a Windows builder now and macOS later (GitHub Actions minutes or CircleCI).
4. **Code signing**: decided: unsigned Windows builds for the MVP (the owner is the user); signing
   (Windows certificate, Apple notarization) before the public release. Which certificate is open.

## 11. Left to the builder

Rendering library, the exact theme schema, the event schema change (optional field vs v2), the hook
forwarder's language, how the Python hub is frozen, desk-cluster layout algorithm, animation timings,
how ACP agents are discovered, and how dropped code is removed (in S0, in small commits).
