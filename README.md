<p align="center"><img src="brand/social/readme-banner.png" width="1280" alt="SeKantor. Your AI agents, in one office."></p>

# SeKantor

SeKantor shows the AI coding agents it detects on your machine as avatars in a 2D pixel-art office, with desks grouped by project. Agents type, read, browse the web, or head to the server rack to run commands and tests. Idle agents grab coffee.

When an agent needs permission or an answer, it walks over to your desk. It also brings a report when a turn finishes. Click **Accept** on its card to acknowledge the report. SeKantor is watch-only. Use `Open in <app>`, when available, to return to the source app and respond there.

The hub binds to `127.0.0.1`, requires a local token, and sends no telemetry. SeKantor supports Claude Code in the terminal, VS Code, Claude desktop, and Orca, plus OpenBot with Local scripts enabled and Codex, OpenCode, Gemini CLI, and Aider in tmux.

## Try it from source

From this checkout, with Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 18+:

```sh
uv sync
cd web
npm ci
npm run build
cd ..
uv run sekantor install claude --project
uv run sekantor up
```

Start Claude Code in the checkout to see its avatar. The hook command backs up your settings and applies to the current project. Use `--global` to connect Claude Code across projects. To connect one other project, run `uv run --project /path/to/sekantor sekantor install claude --project` from that project's directory.

Keep the hub running and use another terminal in the checkout for these commands:

- `uv run sekantor open` opens the office in your browser with a fresh one-time login link. Once signed in, open `http://127.0.0.1:7878/?view=mini` for the compact view.
- `uv run sekantor doctor` checks the setup. `uv run sekantor status` lists sessions in the terminal.
- `uv run sekantor stats` reports lost events, hook errors, and how long agents waited for you over the last 24 hours by default.
- `uv run sekantor uninstall claude` removes SeKantor's project hooks. Pass `--global` if you installed them globally.

## Windows desktop installer

SeKantor is pre-alpha. CircleCI builds an unsigned, per-user Windows x64 installer. See the [desktop installer guide](docs/release.md#desktop-installer-windows) for the artifact and setup steps. Signed installers and macOS and Linux builds are planned.

## Docs

- [Office design](docs/superpowers/specs/2026-11-16-sekantor-design.md) and [landing page](site/index.html)
- [Watching agents](docs/watching.md) and [writing a platform adapter](docs/writing-a-pos.md)
- [Architecture decisions](docs/adr/) and [threat model](docs/threat-model.md)
- [Brand guidelines](brand/BRAND.md)

## License

[MIT](LICENSE)
