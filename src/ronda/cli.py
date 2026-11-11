"""``ronda``: the command line (Typer)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import typer

from ronda import __version__, config

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Ronda keeps watch over your coding agents.")
install_app = typer.Typer(no_args_is_help=True, help="Install Ronda's hooks into an agent.")
uninstall_app = typer.Typer(no_args_is_help=True, help="Remove Ronda's hooks from an agent.")
app.add_typer(install_app, name="install")
app.add_typer(uninstall_app, name="uninstall")

GROUPS = [("Needs you", {"waiting_approval", "waiting_input", "error"}), ("Running", {"running"}),
          ("Done", {"done", "ended"})]


def _api(path: str, timeout: float = 2.0) -> dict:
    from ronda.hub.auth import read_token

    token = read_token(config.token_path())
    if not token:
        raise RuntimeError("no token yet: run `ronda up` first")
    req = urllib.request.Request(config.hub_url() + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _ago(iso: str) -> str:
    s = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


@app.command()
def version():
    """Print the version."""
    typer.echo(__version__)


@app.command()
def up(
    port: int = typer.Option(config.DEFAULT_PORT, help="Port on 127.0.0.1."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the inbox in a browser."),
):
    """Start the hub and the web inbox on 127.0.0.1."""
    import uvicorn

    from ronda.hub.app import create_app, web_dist
    from ronda.hub.auth import ensure_token

    os.environ["RONDA_PORT"] = str(port)
    with socket.socket() as s:
        if s.connect_ex((config.HOST, port)) == 0:
            typer.secho(f"Port {port} is already in use. Is Ronda already up? Try `ronda status`.", fg="red")
            raise typer.Exit(1)
    token = ensure_token(config.token_path())
    url = f"http://{config.HOST}:{port}/?token={token}"
    typer.secho(f"Ronda hub on http://{config.HOST}:{port}", bold=True)
    typer.echo(f"Open the inbox: {url}")
    if not web_dist():
        typer.secho("Web UI not built: run `npm ci && npm run build` in web/. The API works meanwhile.", fg="yellow")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(port=port, token=token), host=config.HOST, port=port, log_level="warning")


@app.command()
def status(as_json: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Show sessions, the ones that need you first."""
    try:
        data = _api("/v1/sessions")
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        typer.secho(f"Hub not reachable at {config.hub_url()} ({e}). Start it with `ronda up`.", fg="red")
        raise typer.Exit(1)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    sessions = data["sessions"]
    if not sessions:
        typer.echo("No sessions yet. Agents appear on their first hook event.")
        return
    for title, statuses in GROUPS:
        rows = [s for s in sessions if s["status"] in statuses]
        if not rows:
            continue
        typer.secho(f"{title} ({len(rows)})", bold=True)
        for s in rows:
            host = (s.get("host") or {}).get("app", "?")
            cwd = Path((s.get("workspace") or {}).get("cwd") or "?").name
            branch = (s.get("workspace") or {}).get("branch") or ""
            summary = (s.get("summary") or "").replace("\n", " ")[:70]
            color = {"waiting_approval": "yellow", "waiting_input": "yellow", "error": "red", "running": "green"}.get(s["status"])
            typer.secho(f"  {s['status']:<17}", fg=color, nl=False)
            typer.echo(f"{_ago(s['status_since']):>4}  {s['source']} in {host}  {cwd} {branch}  {summary}")


def _scope(project: bool, global_: bool) -> str:
    if project and global_:
        typer.secho("Pick one of --project or --global.", fg="red")
        raise typer.Exit(2)
    return "global" if global_ else "project"


@install_app.command("claude")
def install_claude(
    project: bool = typer.Option(False, "--project", help="This project only: ./.claude/settings.local.json (default)."),
    global_: bool = typer.Option(False, "--global", help="Every project: ~/.claude/settings.json."),
):
    """Install ronda-hook into Claude Code settings (backs the file up first)."""
    from ronda.pos.claude_code import install as inst

    path = inst.settings_path(_scope(project, global_))
    exe = inst.hook_executable()
    if not exe:
        typer.secho("ronda-hook not found next to this Python or on PATH.", fg="red")
        raise typer.Exit(1)
    try:
        r = inst.install(path, exe)
    except (ValueError, OSError) as e:
        typer.secho(f"Not changed: {path} could not be read ({e}).", fg="red")
        raise typer.Exit(1)
    typer.secho(f"Installed {r.changed} hooks in {r.path}", fg="green")
    if r.backup:
        typer.echo(f"Backup: {r.backup}")
    typer.echo("Running Claude Code sessions pick this up by themselves; new sessions too.")


@uninstall_app.command("claude")
def uninstall_claude(
    project: bool = typer.Option(False, "--project", help="./.claude/settings.local.json (default)."),
    global_: bool = typer.Option(False, "--global", help="~/.claude/settings.json."),
):
    """Remove Ronda's hooks from Claude Code settings; other hooks stay."""
    from ronda.pos.claude_code import install as inst

    path = inst.settings_path(_scope(project, global_))
    try:
        r = inst.uninstall(path)
    except (ValueError, OSError) as e:
        typer.secho(f"Not changed: {path} could not be read ({e}).", fg="red")
        raise typer.Exit(1)
    if not r.changed:
        typer.echo(f"No Ronda hooks in {path}.")
        return
    typer.secho(f"Removed {r.changed} hooks from {r.path}", fg="green")
    typer.echo(f"Backup: {r.backup}")


@app.command()
def doctor():
    """Check that everything is in place."""
    from ronda.hub.app import web_dist
    from ronda.hub.auth import read_token, token_mode_ok
    from ronda.pos.claude_code import install as inst
    from ronda.pos.claude_code.fingerprint import load_rules, rules_path

    failures = 0

    def check(ok: bool, good: str, bad: str, warn: bool = False):
        nonlocal failures
        if ok:
            typer.secho("  ok    ", fg="green", nl=False)
            typer.echo(good)
        elif warn:
            typer.secho("  warn  ", fg="yellow", nl=False)
            typer.echo(bad)
        else:
            failures += 1
            typer.secho("  fail  ", fg="red", nl=False)
            typer.echo(bad)

    typer.secho(f"Ronda {__version__} doctor", bold=True)
    check(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Python 3.11 or later is required")

    tp = config.token_path()
    check(read_token(tp) is not None and token_mode_ok(tp), f"Token at {tp} (owner only)",
          f"Token missing or readable by others at {tp}: run `ronda up` once")

    try:
        h = _api("/v1/health", timeout=1.5)
        check(h.get("ok") is True, f"Hub answers at {config.hub_url()} with the token", "Hub answered but not ok")
    except urllib.error.HTTPError as e:
        check(False, "", f"Hub refused the token (HTTP {e.code}): the token file and the running hub differ")
    except (urllib.error.URLError, OSError, RuntimeError):
        check(False, "", f"Hub not reachable at {config.hub_url()}: run `ronda up`")

    exe = inst.hook_executable()
    check(exe is not None, f"ronda-hook at {exe}", "ronda-hook not found")
    found = [i for i in (inst.inspect(inst.settings_path("project")), inst.inspect(inst.settings_path("global")))
             if i.events]
    check(bool(found), "Claude Code hooks installed in " + ", ".join(str(i.path) for i in found),
          "Claude Code hooks not installed: run `ronda install claude --project` (or --global)")
    for i in found:
        check(i.complete, f"All {len(inst.EVENTS)} hook events registered in {i.path.name}",
              f"Some hook events missing in {i.path}: run `ronda install claude` again")
        check(i.commands_exist, "Hook command exists", f"Hook command missing: {', '.join(i.commands)}")

    try:
        rules = load_rules()
        check(True, f"{len(rules.get('hosts', []))} host rules from {rules_path()}", "")
    except Exception as e:
        check(False, "", f"Host rules at {rules_path()} do not load: {e}")

    dist = web_dist()
    check(dist is not None, f"Web UI built ({dist})", "Web UI not built: `npm ci && npm run build` in web/", warn=True)

    if exe:
        sample = json.dumps({"hook_event_name": "Notification", "session_id": "ronda-doctor",
                             "notification_type": "doctor", "message": "doctor"}).encode()
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:  # no token there: measures the hook without posting
            env = {**os.environ, "RONDA_HOME": tmp}
            t = time.perf_counter()
            p = subprocess.run([str(exe)], input=sample, capture_output=True, env=env, timeout=10)
            ms = (time.perf_counter() - t) * 1000
        check(p.returncode == 0 and not p.stdout, f"ronda-hook returns no decision ({ms:.0f} ms, runs async)",
              f"ronda-hook printed output or exited {p.returncode}")

    log = config.hook_log_path()
    recent = []
    if log.exists():
        cutoff = time.time() - 600
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]:
            try:
                if time.mktime(time.strptime(line[:19], "%Y-%m-%dT%H:%M:%S")) >= cutoff and "doctor" not in line:
                    recent.append(line)
            except ValueError:
                continue
    check(not recent, "No hook errors in the last 10 minutes",
          f"{len(recent)} hook errors in the last 10 minutes, see {log}", warn=True)

    if failures:
        typer.secho(f"{failures} problem(s).", fg="red", bold=True)
        raise typer.Exit(1)
    typer.secho("All good.", fg="green", bold=True)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
