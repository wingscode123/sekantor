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
| `not delivered while the hub was down` | Expected: the agent fell back to its own prompt | any |
| `hook errors` | From `~/.ronda/hook.log` | only "hub unreachable" while the hub was off |
| `waited for approval / a reply` | Waits you answered: total, count, median (PRD success metric) | baseline |
| `left waiting` | Waits nobody answered: the session ended or still waits | context |

`ronda stats` exits 1 when `lost` is above 0. If it is, keep `~/.ronda/sent.log`,
`~/.ronda/hook.log` and `~/.ronda/ronda.db` and open an issue with the `--lost` output.

## Undo

```sh
uv run ronda uninstall claude --global   # removes only Ronda's hooks, backs up first
```
