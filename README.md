<p align="center"><img src="brand/social/readme-banner.png" width="1280" alt="Ronda: Your agents work all night. Ronda keeps watch."></p>

# Ronda

One inbox for every AI coding agent on your machine. See who's waiting, approve, and reply from one place.

Ronda watches Claude Code (terminal, VS Code, Claude desktop), Orca, OpenBot and any CLI agent in
tmux, and sorts them by who needs you: waiting for approval, waiting for input, error, running, done.
Everything stays on your machine: the hub binds to `127.0.0.1`, needs a local token, and sends no telemetry.

**Status:** pre-alpha, feature-complete for 1.0 (M0 to M4). Watches Claude Code (terminal, VS Code,
Claude desktop, Orca), OpenBot (Local scripts API), and codex/opencode/gemini/aider in tmux or Orca
terminals. Approve, deny and reply from the inbox, the CLI, or Telegram; phone notifications via ntfy.
Public beta planned for 25 January 2027.

## Try it from source

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 18+ (for the web UI build).

```sh
uv sync
(cd web && npm ci && npm run build)   # builds the inbox into src/ronda/hub/static
uv run ronda up                       # hub on 127.0.0.1:7878, opens the inbox (one-time link; `ronda open` for another)
uv run ronda install claude --project # in the project you want watched (or --global; backs up first)
uv run ronda doctor
```

Start Claude Code in that project and its card appears in the inbox. `uv run ronda status` shows the
same list in the terminal. Approve, deny or reply from the inbox, or with `uv run ronda approve|deny <session>`
and `uv run ronda reply <session> "text"` (the terminal prompt stays usable; whoever answers first wins).
`uv run ronda audit` lists every action. `uv run ronda stats` reports lost events and time spent waiting for you;
`uv run ronda uninstall claude` removes only Ronda's hooks.

## Docs

- [Product requirements](docs/PRD.md)
- [M0 spike summary](docs/spike/summary.md) and [Claude Code hooks findings](docs/spike/claude-hooks.md)
- [Architecture decisions](docs/adr/)
- [Dogfooding M1](docs/dogfooding.md)
- [Approve and reply (M2 spike)](docs/spike/m2-actions.md)
- [Phone notifications, Telegram, webhooks, tmux](docs/channels.md)
- [Writing a pos](docs/writing-a-pos.md) and the [threat model](docs/threat-model.md)
- [Releasing](docs/release.md)
- [Brand](brand/BRAND.md) and [design system](design.md)
- [Landing page](site/index.html) and [inbox design direction](site/inbox.html)

## License

MIT
