<p align="center"><img src="brand/social/readme-banner.png" width="1280" alt="SeKantor: Your agents work all night. SeKantor keeps watch."></p>

# SeKantor

One inbox for every AI coding agent on your machine. See who is waiting for you, from one place.

SeKantor watches Claude Code (terminal, VS Code, Claude desktop), Orca, OpenBot and any CLI agent in
tmux, and sorts them by who needs you: waiting for approval, waiting for input, error, running, done.
Everything stays on your machine: the hub binds to `127.0.0.1`, needs a local token, and sends no telemetry.

**Status:** pre-alpha, feature-complete for 1.0 (M0 to M4). Watches Claude Code (terminal, VS Code,
Claude desktop, Orca), OpenBot (Local scripts API), and codex/opencode/gemini/aider in tmux or Orca
terminals.
SeKantor was called Ronda until 2026-11-16 (ADR-0023); upgrading keeps your token, settings and history.

A pixel office is coming: each agent gets a desk, and you see who is working, who is waiting and who left.
Today SeKantor detects your agents and shows the inbox.
Public beta planned for 25 January 2027.

## Try it from source

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 18+ (for the web UI build).

```sh
uv sync
(cd web && npm ci && npm run build)   # builds the inbox into src/sekantor/hub/static
uv run sekantor up                       # hub on 127.0.0.1:7878, opens the inbox (one-time link; `sekantor open` for another)
uv run sekantor install claude --project # in the project you want watched (or --global; backs up first)
uv run sekantor doctor
```

Start Claude Code in that project and its card appears in the inbox. `uv run sekantor status` shows the
same list in the terminal. SeKantor only watches: you answer an agent in its own app, and the inbox says where.
`uv run sekantor stats` reports lost events and time spent waiting for you;
`uv run sekantor uninstall claude` removes only SeKantor's hooks.

## Docs

- [Product requirements](docs/PRD.md)
- [M0 spike summary](docs/spike/summary.md) and [Claude Code hooks findings](docs/spike/claude-hooks.md)
- [Architecture decisions](docs/adr/)
- [Quiet hours, snooze, tmux](docs/watching.md)
- [Dogfooding M1](docs/dogfooding.md)
- [Approve and reply (M2 spike)](docs/spike/m2-actions.md)
- [Writing a pos](docs/writing-a-pos.md) and the [threat model](docs/threat-model.md)
- [Releasing](docs/release.md)
- [Improvement log](docs/improvement-log.md): the pstack audit, cleanup, CI move and dogfooding (November 2026)
- [Brand](brand/BRAND.md) and [design system](design.md)
- [Landing page](site/index.html) and [inbox design direction](site/inbox.html)

## License

MIT
