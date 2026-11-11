"""``ronda``: the command line (Typer)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
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
pair_app = typer.Typer(no_args_is_help=True, help="Connect a remote channel (Telegram).")
unpair_app = typer.Typer(no_args_is_help=True, help="Disconnect a remote channel.")
app.add_typer(pair_app, name="pair")
app.add_typer(unpair_app, name="unpair")
pos_app = typer.Typer(no_args_is_help=True, help="Run a pos (platform adapter) by hand.")
app.add_typer(pos_app, name="pos")

GROUPS = [("Needs you", {"waiting_approval", "waiting_input", "error"}), ("Running", {"running"}),
          ("Done", {"done", "ended"})]


def _api(path: str, timeout: float = 2.0, method: str = "GET", body: dict | None = None) -> dict:
    """Call the hub; HTTP errors with a JSON body come back as dicts with "_status"."""
    from ronda.hub.auth import read_token

    token = read_token(config.token_path())
    if not token:
        raise RuntimeError("no token yet: run `ronda up` first")
    req = urllib.request.Request(
        config.hub_url() + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Ronda-Channel": "cli"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if method == "GET" and e.code in (401, 403):
            raise
        try:
            data = json.loads(e.read())
        except ValueError:
            raise e from None
        return {"_status": e.code, **(data if isinstance(data, dict) else {"detail": data})}


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
    notify: bool = typer.Option(None, "--notify/--no-notify", help="Desktop notifications (default: config.toml, on)."),
    relay: bool = typer.Option(True, "--relay/--no-relay", help="Start the relay when Telegram or webhooks are set up."),
    tmux: bool = typer.Option(True, "--tmux/--no-tmux", help="Watch CLI agents in tmux panes when tmux is installed."),
    openbot: bool = typer.Option(True, "--openbot/--no-openbot", help="Watch OpenBot agents when OpenBot is installed."),
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
    settings = config.settings()
    if notify is not None:
        settings.notify = notify
    hub_app = create_app(port=port, token=token, settings=settings)
    url = f"http://{config.HOST}:{port}/?login={hub_app.state.login_codes.issue()}"
    typer.secho(f"Ronda hub on http://{config.HOST}:{port}", bold=True)
    typer.echo(f"Open the inbox: {url}  (one-time link, 10 minutes; `ronda open` makes a new one)")
    if not web_dist():
        typer.secho("Web UI not built: run `npm ci && npm run build` in web/. The API works meanwhile.", fg="yellow")
    if open_browser:
        webbrowser.open(url)
    typer.echo(f"Approvals wait {settings.approval_wait_s}s, replies {settings.reply_wait_s}s, "
               f"notifications {'on' if settings.notify else 'off'} ({config.config_path()})")
    children = [c for c in (_start_relay(port) if relay else None, _start_tmux(port) if tmux else None,
                            _start_openbot(port) if openbot else None, _start_orca(port)) if c]
    try:
        uvicorn.run(hub_app, host=config.HOST, port=port, log_level="warning")
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()


def _start_tmux(port: int):
    import shutil

    if not shutil.which("tmux"):
        return None
    typer.echo("tmux pos: watching CLI agents in tmux panes (separate process)")
    env = {**os.environ, "RONDA_URL": f"http://{config.HOST}:{port}"}
    return subprocess.Popen([sys.executable, "-m", "ronda.cli", "pos", "tmux"], env=env)


def _start_orca(port: int):
    """Opt-in (`orca_pos = true` in config.toml): the Orca CLI is heavy to poll, and Claude in Orca
    already reports through its hooks."""
    import tomllib

    try:
        with open(config.config_path(), "rb") as f:
            wanted = bool(tomllib.load(f).get("orca_pos", False))
    except (OSError, tomllib.TOMLDecodeError):
        wanted = False
    if not wanted:
        return None
    from ronda.pos.orca.pos import orca_cli

    if not orca_cli():
        typer.secho("orca_pos is on but the orca CLI was not found.", fg="yellow")
        return None
    typer.echo("Orca pos: non-Claude agents in Orca terminals (separate process)")
    env = {**os.environ, "RONDA_URL": f"http://{config.HOST}:{port}"}
    return subprocess.Popen([sys.executable, "-m", "ronda.cli", "pos", "orca"], env=env)


@pos_app.command("orca")
def pos_orca(interval: float = typer.Option(10.0, help="Seconds between polls (the orca CLI is slow).")):
    """Watch codex, opencode, gemini and aider in Orca terminals (opt-in: orca_pos = true)."""
    from ronda.pos.orca.pos import main as orca_main

    orca_main(interval)


def _start_openbot(port: int):
    from ronda.pos.openbot.pos import installed

    if not installed():
        return None
    typer.echo("OpenBot pos: agents with Local scripts on (separate process)")
    env = {**os.environ, "RONDA_URL": f"http://{config.HOST}:{port}"}
    return subprocess.Popen([sys.executable, "-m", "ronda.cli", "pos", "openbot"], env=env)


@pos_app.command("openbot")
def pos_openbot(interval: float = typer.Option(3.0, help="Seconds between polls.")):
    """Watch OpenBot agents that have Local scripts on; answer their approvals and questions (runs with `ronda up`)."""
    from ronda.pos.openbot.pos import main as openbot_main

    openbot_main(interval)


@pos_app.command("tmux")
def pos_tmux(interval: float = typer.Option(2.0, help="Seconds between scans.")):
    """Watch codex, opencode, gemini and aider in tmux panes; answer them with send-keys (runs with `ronda up`)."""
    from ronda.pos.tmux.pos import main as tmux_main

    tmux_main(interval)


def _start_relay(port: int):
    """The relay is a separate process (ADR-0011): the hub itself never talks to the internet."""
    from ronda.relay.runner import configured

    names = configured(config.home())
    if not names:
        return None
    typer.echo(f"Relay: {', '.join(names)} (separate process)")
    env = {**os.environ, "RONDA_URL": f"http://{config.HOST}:{port}"}
    return subprocess.Popen([sys.executable, "-m", "ronda.cli", "relay"], env=env)


@app.command()
def relay(test: bool = typer.Option(False, "--test", help="Send one sample notification to every channel and exit.")):
    """Forward 'needs you' moments to Telegram and webhooks, and take answers back (runs with `ronda up`)."""
    if test:
        import asyncio

        from ronda.relay.runner import send_test

        results = asyncio.run(send_test())
        if not results:
            typer.secho("Nothing to test: run `ronda pair telegram` or add [[webhooks]] to config.toml.", fg="yellow")
            raise typer.Exit(1)
        for name, ok in results:
            typer.secho(f"  {'sent' if ok else 'FAILED'}  {name}", fg="green" if ok else "red")
        raise typer.Exit(0 if all(ok for _, ok in results) else 1)
    from ronda.relay.runner import main as relay_main

    relay_main()


@pair_app.command("telegram")
def pair_telegram():
    """Connect a Telegram bot (make one with @BotFather first). The token is never shown or logged."""
    import asyncio
    import secrets as _secrets

    from ronda.relay.telegram import TelegramApi, TelegramError, pair, save_config

    token = typer.prompt("Bot token from @BotFather", hide_input=True).strip()
    api = TelegramApi(token)
    try:
        me = asyncio.run(api.call("getMe"))
    except TelegramError:
        typer.secho("Telegram did not accept that token.", fg="red")
        raise typer.Exit(1)
    code = f"{_secrets.randbelow(10**6):06d}"
    typer.echo(f"Send this to @{me.get('username')} in Telegram within 5 minutes:")
    typer.secho(f"    /pair {code}", bold=True)
    try:
        chat, name = asyncio.run(pair(api, code))
    except TimeoutError:
        typer.secho("No /pair message arrived. Nothing was saved.", fg="red")
        raise typer.Exit(1)
    path = save_config(config.home(), token, [chat], me.get("username") or "")
    typer.secho(f"Paired with {name}. Saved to {path} (owner only).", fg="green")
    typer.echo("Restart `ronda up` to start the relay.")


@unpair_app.command("telegram")
def unpair_telegram():
    """Forget the Telegram bot and chat."""
    from ronda.relay.telegram import config_path

    path = config_path(config.home())
    if path.exists():
        path.unlink()
        typer.secho(f"Removed {path}. Restart `ronda up` to stop the relay.", fg="green")
    else:
        typer.echo("Telegram is not paired.")


@app.command("open")
def open_inbox(print_only: bool = typer.Option(False, "--print", help="Print the link instead of opening it.")):
    """Open the inbox in a browser with a fresh one-time login link."""
    try:
        res = _api("/v1/login-code", method="POST", body={})
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        typer.secho(f"Hub not reachable at {config.hub_url()} ({e}). Start it with `ronda up`.", fg="red")
        raise typer.Exit(1)
    if "_status" in res:
        typer.secho(f"The hub refused ({res['_status']}).", fg="red")
        raise typer.Exit(1)
    url = config.hub_url() + res["path"]
    typer.echo(url)
    if not print_only:
        webbrowser.open(url)


token_app = typer.Typer(no_args_is_help=True, help="Manage the local hub token.")
app.add_typer(token_app, name="token")


@token_app.command("rotate")
def token_rotate():
    """Replace ~/.ronda/token (if a login link or the token leaked). Restart `ronda up` afterwards."""
    from ronda.hub.auth import rotate_token

    rotate_token(config.token_path())
    typer.secho(f"New token written to {config.token_path()} (owner only).", fg="green")
    typer.echo("Restart `ronda up`; hooks pick up the new token by themselves.")


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


def _span(td) -> str:
    s = int(td.total_seconds())
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s"


@app.command()
def stats(
    since: str = typer.Option("24h", help="Window to look back over: 90m, 24h, 7d."),
    show_lost: bool = typer.Option(False, "--lost", help="List every lost event."),
):
    """Dogfooding numbers: lost events, hook errors, and how long agents waited for you."""
    from ronda.stats import compute, parse_since

    try:
        window = parse_since(since)
    except ValueError as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(2)
    now = datetime.now(timezone.utc)
    st = compute(config.home(), now - window, now)
    typer.secho(f"Last {since}", bold=True)
    lost = len(st.lost)
    color = "green" if lost == 0 else "red"
    typer.secho(f"  events sent by hooks   {st.attempted}", nl=False)
    typer.echo(f"   stored by the hub {st.stored}   ", nl=False)
    typer.secho(f"lost {lost}", fg=color)
    if st.lost_hub_down:
        typer.echo(f"  not delivered while the hub was down: {len(st.lost_hub_down)} (expected: agents fell back to their own prompts)")
    if st.hook_errors:
        typer.secho("  hook errors", fg="yellow")
        for msg, n in st.hook_errors.most_common():
            typer.echo(f"    {n:>5}  {msg}")
    else:
        typer.secho("  hook errors            0", fg="green")
    hosts = ", ".join(f"{h} {n}" for h, n in st.by_host.most_common()) or "none"
    typer.echo(f"  sessions               {st.sessions} ({hosts})")
    typer.echo(f"  waited for approval    {_span(st.waiting['waiting_approval'])}")
    typer.echo(f"  waited for a reply     {_span(st.waiting['waiting_input'])}")
    if st.longest_wait_session:
        typer.echo(f"  longest single wait    {_span(st.longest_wait)} ({st.longest_wait_session})")
    if show_lost and st.lost:
        typer.secho("  lost events", fg="red")
        for x in st.lost:
            typer.echo(f"    {x.ts}  {x.session_id}  {x.label}  {x.event_id}")
    if lost:
        raise typer.Exit(1)


def _find_session(ref: str) -> dict:
    """A session by full id, or by a unique prefix of its id with or without the 'claude:' part."""
    try:
        sessions = _api("/v1/sessions")["sessions"]
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        typer.secho(f"Hub not reachable at {config.hub_url()} ({e}). Start it with `ronda up`.", fg="red")
        raise typer.Exit(1)
    hits = [s for s in sessions if s["session_id"] == ref]
    if not hits:
        hits = [s for s in sessions if s["session_id"].split(":", 1)[-1].startswith(ref) or s["session_id"].startswith(ref)]
    if len(hits) != 1:
        typer.secho(f"{'No' if not hits else 'More than one'} session matches '{ref}'. See `ronda status`.", fg="red")
        raise typer.Exit(2)
    return hits[0]


def _act(ref: str, body: dict) -> None:
    s = _find_session(ref)
    path = f"/v1/sessions/{urllib.parse.quote(s['session_id'], safe='')}/actions"
    res = _api(path, method="POST", body=body, timeout=5)
    if res.get("error") == "confirm_required":
        cmd = (s.get("request") or {}).get("input", "")
        typer.secho(f"Risky command: {cmd}", fg="yellow")
        if not typer.confirm("Approve it anyway?", default=False):
            raise typer.Exit(1)
        res = _api(path, method="POST", body={**body, "confirm": True}, timeout=5)
    if "_status" in res:
        typer.secho(res.get("message") or res.get("detail") or f"Refused ({res['_status']})", fg="red")
        raise typer.Exit(1)
    typer.secho(f"Sent: {body['type']} to {s['session_id']}", fg="green")


@app.command()
def approve(session: str = typer.Argument(..., help="Session id or a unique prefix (see `ronda status`).")):
    """Approve the tool call a session is waiting on."""
    _act(session, {"type": "approve"})


@app.command()
def deny(session: str = typer.Argument(..., help="Session id or a unique prefix.")):
    """Deny the tool call a session is waiting on."""
    _act(session, {"type": "deny"})


@app.command()
def reply(session: str = typer.Argument(..., help="Session id or a unique prefix."),
          text: str = typer.Argument(..., help="What to tell the agent.")):
    """Reply to a session that finished its turn and waits for you."""
    _act(session, {"type": "reply", "text": text})


@app.command()
def snooze(session: str = typer.Argument(..., help="Session id or a unique prefix."),
           minutes: int = typer.Option(60, help="How long, in minutes."),
           forever: bool = typer.Option(False, "--forever", help="Until you unmute it.")):
    """Stop notifications for one session or agent for a while (FR-15). It stays in the inbox."""
    s = _find_session(session)
    path = f"/v1/sessions/{urllib.parse.quote(s['session_id'], safe='')}/snooze"
    res = _api(path, method="POST", body={"minutes": None if forever else minutes})
    if "_status" in res:
        typer.secho(str(res.get("detail") or res), fg="red")
        raise typer.Exit(1)
    typer.secho(f"Snoozed {s['session_id']} until {'you unmute it' if forever else res['snoozed_until'][:16]}", fg="green")


@app.command()
def unsnooze(session: str = typer.Argument(..., help="Session id or a unique prefix.")):
    """Turn notifications back on for a session."""
    s = _find_session(session)
    _api(f"/v1/sessions/{urllib.parse.quote(s['session_id'], safe='')}/snooze", method="DELETE")
    typer.secho(f"Unmuted {s['session_id']}", fg="green")


@app.command()
def audit(limit: int = typer.Option(30, help="How many actions to show.")):
    """Every approve, deny and reply sent through Ronda (FR-24), newest first."""
    try:
        actions = _api(f"/v1/actions?limit={limit}")["actions"]
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        typer.secho(f"Hub not reachable ({e}).", fg="red")
        raise typer.Exit(1)
    if not actions:
        typer.echo("No actions yet.")
    for a in actions:
        text = f"  {a['text'][:60]!r}" if a.get("text") else ""
        typer.echo(f"{a['created_at'][:19]}  {a['type']:<8} {a['outcome']:<10} {a['channel']:<4} {a['actor']}  {a['session_id']}{text}")


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
        r = inst.install(path, exe, config.settings())
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
        check(i.current_shape, "Hooks can approve and reply (M2 shape)",
              f"Hooks in {i.path} are from an older Ronda: run `ronda install claude` again")

    try:
        rules = load_rules()
        check(True, f"{len(rules.get('hosts', []))} host rules from {rules_path()}", "")
    except Exception as e:
        check(False, "", f"Host rules at {rules_path()} do not load: {e}")

    dist = web_dist()
    check(dist is not None, f"Web UI built ({dist})", "Web UI not built: `npm ci && npm run build` in web/", warn=True)

    from ronda.relay.runner import configured, load_webhooks
    from ronda.relay.telegram import config_path as tg_path

    from ronda.pos.openbot.pos import automation_dir, installed as openbot_installed

    if openbot_installed():
        on = (automation_dir() / "url").exists()
        check(on, "OpenBot: Local scripts is on for at least one agent",
              "OpenBot: no agent has Local scripts on, so Ronda cannot see OpenBot agents "
              "(agent settings > Permissions > Local scripts)", warn=True)

    names = configured(config.home())
    _, hook_errors = load_webhooks(config.home())
    check(not hook_errors, "Relay: " + (", ".join(names) if names else "not set up (optional)"),
          "Webhook config problems: " + "; ".join(f"#{e.index + 1} {e.message}" for e in hook_errors))
    if tg_path(config.home()).exists():
        check(token_mode_ok(tg_path(config.home())), "Telegram config readable by you only",
              f"{tg_path(config.home())} is readable by others")

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
