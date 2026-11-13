# Dogfooding M1

M1's exit criterion (PRD, Milestones): **one full working day without a lost event.**
Ronda measures this itself, from local files only.

## Set up (once)

```sh
uv run ronda install claude --global   # every project; backs up ~/.claude/settings.json first
uv run ronda service install           # the hub starts at login, no window (output: ~/.ronda/hub.log)
uv run ronda open                      # the inbox in your browser
uv run ronda doctor                    # should end with "All good."
```

Hooks in `~/.claude/settings.json` reach Claude Code in a terminal, VS Code, Claude desktop and
Orca. They do not reach OpenBot agents (OpenBot loads only project and local settings, see
`docs/spike/summary.md`).

## Updating Ronda

Stop the hub before `git pull` and `uv sync`: `uv sync` replaces `ronda-hook.exe`, which running hooks
may hold open, and a failed replace leaves no hook at all. Stop it with `schtasks /End /TN "Ronda hub"`
(Windows), `launchctl bootout gui/$(id -u)/dev.ronda.hub` (macOS) or `systemctl --user stop ronda`
(Linux), wait until nothing listens on port 7878, update, then:

```sh
uv run ronda install claude --global    # only when the release notes say the hooks changed
uv run ronda service restart            # waits until the old hub has let go of the port
uv run ronda doctor
```

## During the day

Work as usual. Glance at the inbox when you switch tasks. Note anything that looks wrong:
a card in the wrong group, a status that does not move, a host labelled wrongly.

## At the end of the day

```sh
uv run ronda stats --since 10h          # or however long the day was
uv run ronda stats --since 10h --lost   # list each lost event, if any
```

| Line | Meaning | Target |
| --- | --- | --- |
| `lost` | A hook sent the event while the hub was up, and the hub never stored it | **0** |
| `not delivered, the hub was down or too slow` | The agent fell back to its own prompt | 0 while the hub runs |
| `hook errors` | From `~/.ronda/hook.log` | only "hub unreachable" while the hub was off |
| `~/.ronda/hub.log` | "event loop was blocked", "store lock", "sent N s ago" lines: the hub was slow | none |
| `waited for approval / a reply` | Waits you answered: total, count, median (PRD success metric) | baseline |
| `left waiting` | Waits nobody answered: the session ended or still waits | context |

`ronda stats` exits 1 when `lost` is above 0. If it is, keep `~/.ronda/sent.log`,
`~/.ronda/hook.log` and `~/.ronda/ronda.db` and open an issue with the `--lost` output.

## Undo

```sh
uv run ronda uninstall claude --global   # removes only Ronda's hooks, backs up first
```
