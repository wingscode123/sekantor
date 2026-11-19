"""``sekantor``: the command line (Typer)."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer

from sekantor import __version__, config
from sekantor.selfexe import self_command

app = typer.Typer(add_completion=False, no_args_is_help=True, help="SeKantor keeps watch over your coding agents.")
install_app = typer.Typer(no_args_is_help=True, help="Install SeKantor's hooks into an agent.")
uninstall_app = typer.Typer(no_args_is_help=True, help="Remove SeKantor's hooks from an agent.")
app.add_typer(install_app, name="install")
app.add_typer(uninstall_app, name="uninstall")
pos_app = typer.Typer(no_args_is_help=True, help="Run a pos (platform adapter) by hand.")
app.add_typer(pos_app, name="pos")

GROUPS = [("Needs you", {"waiting_approval", "waiting_input", "error"}), ("Running", {"running"}),
          ("Reports pending", {"report_pending"}), ("Reports accepted", {"report_accepted"}),
          ("Done", {"done", "ended"})]


def _api(path: str, timeout: float = 2.0, method: str = "GET", body: dict | None = None) -> dict:
    """Call the hub; HTTP errors with a JSON body come back as dicts with "_status"."""
    from sekantor.hub.auth import read_token

    token = read_token(config.token_path())
    if not token:
        raise RuntimeError("no token yet: run `sekantor up` first")
    req = urllib.request.Request(
        config.hub_url() + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-SeKantor-Channel": "cli"})
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


def _hub(path: str, **kw) -> dict:
    """_api for commands: a hub that is down, refuses the token or does not answer ends the command with one line."""
    try:
        return _api(path, **kw)
    except urllib.error.HTTPError as e:
        why = "refused the token" if e.code in (401, 403) else "answered with an error"
        typer.secho(f"The hub {why} (HTTP {e.code}). Run `sekantor doctor`.", fg="red")
    except (urllib.error.URLError, RuntimeError) as e:  # could not connect or send, or no token
        typer.secho(f"Hub not reachable at {config.hub_url()} ({e}). Start it with `sekantor up`.", fg="red")
    except OSError as e:  # sent, but the answer did not come: it may have been done
        typer.secho(f"The hub did not answer in time ({e}). Check `sekantor status` before you try again.", fg="red")
    raise typer.Exit(1)


def _session_path(s: dict, suffix: str) -> str:
    return f"/v1/sessions/{urllib.parse.quote(s['session_id'], safe='')}/{suffix}"


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


def _keep_in_ram() -> None:
    """ADR-0020, unless `keep_in_ram = false` (the default for the frozen app) in config.toml."""
    from sekantor import resident

    if not config.settings().keep_in_ram:
        return
    why_not = resident.keep_resident()
    if why_not and sys.platform == "win32":
        logging.getLogger("sekantor.hub").warning("could not keep the hub in RAM: %s", why_not)


@app.command()
def up(
    port: int = typer.Option(config.DEFAULT_PORT, help="Port on 127.0.0.1."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the inbox in a browser."),
    notify: bool = typer.Option(None, "--notify/--no-notify", help="Desktop notifications (default: config.toml, on)."),
    tmux: bool = typer.Option(True, "--tmux/--no-tmux", help="Watch CLI agents in tmux panes when tmux is installed."),
    openbot: bool = typer.Option(True, "--openbot/--no-openbot", help="Watch OpenBot agents when OpenBot is installed."),
    log_file: Path = typer.Option(None, "--log-file", help="Write output here instead of the console (used by `sekantor service`)."),
):
    """Start the hub and the web inbox on 127.0.0.1."""
    import uvicorn

    from sekantor.hub.app import create_app, web_dist
    from sekantor.hub.auth import ensure_token

    global _CHILD_OUT
    _migrate()  # first run after the rename: copy ~/.ronda over (ADR-0023)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log(log_file)
        _CHILD_OUT = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = _CHILD_OUT
        typer.echo(f"--- {datetime.now().isoformat(timespec='seconds')} sekantor up")
    from sekantor import logs

    logs.setup("hub")
    _keep_in_ram()

    os.environ["SEKANTOR_PORT"] = str(port)
    with socket.socket() as s:
        if s.connect_ex((config.HOST, port)) == 0:
            typer.secho(f"Port {port} is already in use. Is SeKantor already up? Try `sekantor status`.", fg="red")
            raise typer.Exit(1)
    token = ensure_token(config.token_path())
    settings, problems = config.load()
    for p in problems:
        typer.secho(f"config.toml: {p}", fg="yellow")
    if notify is not None:
        settings.notify = notify
    hub_app = create_app(port=port, token=token, settings=settings)
    url = f"http://{config.HOST}:{port}/?login={hub_app.state.login_codes.issue()}"
    typer.secho(f"SeKantor hub on http://{config.HOST}:{port}", bold=True)
    typer.echo(f"Open the inbox: {url}  (one-time link, 10 minutes; `sekantor open` makes a new one)")
    if not web_dist():
        typer.secho("Web UI not built: run `npm ci && npm run build` in web/. The API works meanwhile.", fg="yellow")
    if open_browser:
        webbrowser.open(url)
    typer.echo(f"Notifications {'on' if settings.notify else 'off'} ({config.config_path()})")
    children = [c for c in (_start_tmux(port) if tmux else None,
                            _start_openbot(port) if openbot else None, _start_orca(port)) if c]
    try:
        server = uvicorn.Server(uvicorn.Config(hub_app, host=config.HOST, port=port, log_level="warning"))

        def watch_stop():  # POST /v1/shutdown sets the flag; uvicorn then drains and returns
            while not server.should_exit:
                if hub_app.state.should_exit:
                    server.should_exit = True
                time.sleep(0.2)

        threading.Thread(target=watch_stop, daemon=True, name="stop-watch").start()
        server.run()
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()


def _start_tmux(port: int):
    import shutil

    if not shutil.which("tmux"):
        return None
    typer.echo("tmux pos: watching CLI agents in tmux panes (separate process)")
    return _spawn(self_command("pos", "tmux"), port)


def _start_orca(port: int):
    """Opt-in (`orca_pos = true` in config.toml): the Orca CLI is heavy to poll, and Claude in Orca
    already reports through its hooks."""
    if not config.settings().orca_pos:
        return None
    from sekantor.pos.orca.pos import orca_cli

    if not orca_cli():
        typer.secho("orca_pos is on but the orca CLI was not found.", fg="yellow")
        return None
    typer.echo("Orca pos: non-Claude agents in Orca terminals (separate process)")
    return _spawn(self_command("pos", "orca"), port)


@pos_app.command("orca")
def pos_orca(interval: float = typer.Option(10.0, help="Seconds between polls (the orca CLI is slow).")):
    """Watch codex, opencode, gemini and aider in Orca terminals (opt-in: orca_pos = true)."""
    from sekantor.pos.orca.pos import main as orca_main

    orca_main(interval)


def _start_openbot(port: int):
    from sekantor.pos.openbot.pos import installed

    if not installed():
        return None
    typer.echo("OpenBot pos: agents with Local scripts on (separate process)")
    return _spawn(self_command("pos", "openbot"), port)


@pos_app.command("openbot")
def pos_openbot(interval: float = typer.Option(3.0, help="Seconds between polls.")):
    """Watch OpenBot agents that have Local scripts on; report their status (runs with `sekantor up`)."""
    from sekantor.pos.openbot.pos import main as openbot_main

    openbot_main(interval)


@pos_app.command("tmux")
def pos_tmux(interval: float = typer.Option(2.0, help="Seconds between scans.")):
    """Watch codex, opencode, gemini and aider in tmux panes; report their status (runs with `sekantor up`)."""
    from sekantor.pos.tmux.pos import main as tmux_main

    tmux_main(interval)


_CHILD_OUT = None  # where child processes write when the hub runs as a service
LOG_MAX_BYTES = 5_000_000


def _migrate() -> None:
    """Copy a Ronda-era home over once, and say so."""
    note = config.migrate_note()
    if note:
        typer.echo(note)


def _rotate_log(path: Path, max_bytes: int = LOG_MAX_BYTES) -> None:
    """Move a large log to <name>.1 (replacing the old one) so the service log never grows without bound."""
    try:
        if path.stat().st_size > max_bytes:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:  # missing, or still open in another process: keep appending
        pass


def _spawn(args: list[str], port: int):
    from sekantor.lifeline import parent_env

    env = {**os.environ, "SEKANTOR_URL": f"http://{config.HOST}:{port}", **parent_env()}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    if _CHILD_OUT is not None:
        return subprocess.Popen(args, env=env, stdout=_CHILD_OUT, stderr=subprocess.STDOUT, **flags)
    return subprocess.Popen(args, env=env, **flags)


@app.command("open")
def open_inbox(print_only: bool = typer.Option(False, "--print", help="Print the link instead of opening it.")):
    """Open the inbox in a browser with a fresh one-time login link."""
    res = _hub("/v1/login-code", method="POST", body={})
    if "_status" in res:
        typer.secho(f"The hub refused ({res['_status']}).", fg="red")
        raise typer.Exit(1)
    url = config.hub_url() + res["path"]
    typer.echo(url)
    if not print_only:
        webbrowser.open(url)


@app.command()
def stop(wait: bool = typer.Option(False, "--wait", help="Return only once the hub has exited (up to 20 s); the uninstaller uses this.")):
    """Stop the running hub (its watchers end with it)."""
    try:
        res = _api("/v1/shutdown", timeout=10, method="POST", body={})
    except urllib.error.HTTPError as e:
        _stop_refused(e.code)
    except RuntimeError:  # no token file: no hub was ever started here
        _wait_gone(wait)
        typer.echo("No hub running.")
        return
    except OSError as e:  # URLError is an OSError
        reason = e.reason if isinstance(e, urllib.error.URLError) else e
        if not isinstance(reason, ConnectionRefusedError):
            if wait and _wait_gone(wait):  # a busy hub may have got the request and be draining
                typer.echo("SeKantor hub stopped.")
                return
            typer.secho("The hub did not answer; it may still be stopping.", fg="yellow")
            raise typer.Exit(1)
        _wait_gone(wait)
        typer.echo("No hub running.")
        return
    if "_status" in res:
        _stop_refused(res["_status"])
    if wait and not _wait_gone(wait):
        typer.secho("The hub is still running after 20 s.", fg="yellow")
        raise typer.Exit(1)
    typer.echo("SeKantor hub stopped.")


def _bundle_processes() -> list:
    """Other processes running an exe from this frozen folder (the hub and its watchers): they lock its
    files, so the uninstaller must wait for them. Empty when running from source."""
    from sekantor.selfexe import frozen

    if not frozen():
        return []
    import psutil

    folder = os.path.normcase(str(Path(sys.executable).parent))
    found = []
    for p in psutil.process_iter(["exe"]):
        exe = p.info.get("exe")
        if p.pid != os.getpid() and exe and os.path.normcase(str(Path(exe).parent)) == folder:
            found.append(p)
    return found


def _wait_gone(wait: bool, wait_s: float = 20.0) -> bool:
    """With --wait: block until the port is free and no process from this folder is left."""
    if not wait:
        return True
    from sekantor import service

    return service.wait_free(lambda: service.port_busy(config.HOST, config.port()) or bool(_bundle_processes()),
                             wait_s=wait_s)


def _stop_refused(code: int):
    why = "refused the token" if code in (401, 403) else "answered with an error"
    typer.secho(f"The hub {why} (HTTP {code}). Run `sekantor doctor`.", fg="red")
    raise typer.Exit(1)


service_app = typer.Typer(no_args_is_help=True, help="Start the hub automatically at login.")
app.add_typer(service_app, name="service")


@service_app.command("install")
def service_install(start: bool = typer.Option(True, "--start/--no-start", help="Also start it now.")):
    """Run the hub at every login (Task Scheduler / launchd / systemd user), with no window."""
    _install_service(start)


def _install_service(start: bool) -> str:
    """Install the login service. Returns "started" (the new hub runs), "restart_needed" (another
    hub still holds the port; the service takes over at next login) or "not_started"."""
    from sekantor import selfexe, service

    p = service.plan(config.home())
    _migrate()
    hub_busy = lambda: service.port_busy(config.HOST, config.port())  # noqa: E731
    # The installed app replacing a source install: its task may still run the old hub. End our own
    # task first, so the port frees up for the new one (a hub started by hand stays and keeps the port).
    takeover = bool(start and p.start and p.stop and selfexe.frozen() and hub_busy())
    if takeover:
        service.run(p.stop, check=False)
    # the old Ronda service, so it does not start a second hub
    cleaned = service.run(p.cleanup, check=False)
    old_hub_ended = bool(p.stop) and bool(cleaned) and cleaned[0].returncode == 0
    for old in p.cleanup_files:
        old.unlink(missing_ok=True)
    result = "not_started"
    try:
        for path, content in p.files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            (path.write_bytes if isinstance(content, bytes) else path.write_text)(content)
        was_busy = hub_busy()
        service.run(p.install)
        if start and not p.start:
            # launchd / systemd: the install command starts the service itself
            result = "restart_needed" if was_busy else "started"
        elif start:
            busy = hub_busy
            # schtasks /End returns before the old hub has exited: give it time to let go of the port
            if old_hub_ended or takeover:
                service.wait_free(busy)
            if busy():
                typer.secho("A hub is already running; the service takes over at the next login.", fg="yellow")
                result = "restart_needed"
            else:
                service.run(p.start)
                result = "started"
    except (RuntimeError, OSError) as e:
        typer.secho(f"Could not install the service: {e}", fg="red")
        raise typer.Exit(1)
    typer.secho("The hub now starts at login (no window). Output: " + str(config.home() / "hub.log"), fg="green")
    typer.echo("Open the inbox with `sekantor open`. Remove with `sekantor service uninstall`.")
    return result


@service_app.command("uninstall")
def service_uninstall():
    """Stop starting the hub at login."""
    from sekantor import service

    p = service.plan(config.home())
    service.run(p.uninstall, check=False)
    for path in p.remove:
        if path.exists():
            path.unlink()
    typer.secho("Removed. The hub no longer starts at login.", fg="green")


@service_app.command("restart")
def service_restart():
    """Restart the hub that runs as a service, e.g. after updating SeKantor."""
    from sekantor import service

    p = service.plan(config.home())
    if not service.installed(p):
        typer.secho("The service is not installed: `sekantor service install`.", fg="yellow")
        raise typer.Exit(1)
    try:
        ok = service.restart(p, busy=lambda: service.port_busy(config.HOST, config.port()))
    except (RuntimeError, OSError) as e:
        typer.secho(f"Could not restart the hub: {e}", fg="red")
        raise typer.Exit(1)
    if not ok:
        typer.secho(f"The old hub still holds port {config.port()} after 20 s. Stop it (Task Manager: "
                    "pythonw.exe running sekantor) and run this again.", fg="red")
        raise typer.Exit(1)
    typer.secho("Restarted.", fg="green")


@service_app.command("status")
def service_status():
    """Is the hub set to start at login?"""
    from sekantor import service

    ok = service.installed(service.plan(config.home()))
    typer.secho("Starts at login: yes" if ok else "Starts at login: no (sekantor service install)",
                fg="green" if ok else "yellow")
    raise typer.Exit(0 if ok else 1)


token_app = typer.Typer(no_args_is_help=True, help="Manage the local hub token.")
app.add_typer(token_app, name="token")


@token_app.command("rotate")
def token_rotate():
    """Replace ~/.sekantor/token (if a login link or the token leaked). Restart `sekantor up` afterwards."""
    from sekantor.hub.auth import rotate_token

    rotate_token(config.token_path())
    typer.secho(f"New token written to {config.token_path()} (owner only).", fg="green")
    typer.echo("Restart `sekantor up`; hooks pick up the new token by themselves.")


@app.command()
def status(as_json: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Show sessions, the ones that need you first."""
    data = _hub("/v1/sessions")
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    if not data["sessions"]:
        typer.echo("No sessions yet. Agents appear on their first hook event.")
        return
    sessions = [s for s in data["sessions"] if s.get("report_to") != "lead"]
    if not sessions:
        typer.echo("No sessions in your inbox.")
        return
    def group_status(s):
        if s["status"] == "reported":
            return "report_pending" if s.get("report_pending") else "report_accepted"
        if s["status"] == "waiting_input" and s.get("needs_you") is False:
            return "done"
        return s["status"]

    for title, statuses in GROUPS:
        rows = [s for s in sessions if group_status(s) in statuses]
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
    from sekantor.stats import compute, parse_since

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
        typer.echo(f"  not delivered, the hub was down or too slow: {len(st.lost_hub_down)} (agents fell back to their own prompts)")
    if st.hook_errors:
        typer.secho("  hook errors", fg="yellow")
        for msg, n in st.hook_errors.most_common():
            typer.echo(f"    {n:>5}  {msg}")
    else:
        typer.secho("  hook errors            0", fg="green")
    hosts = ", ".join(f"{h} {n}" for h, n in st.by_host.most_common()) or "none"
    typer.echo(f"  sessions               {st.sessions} ({hosts})")
    for status, label in (("waiting_approval", "approval"), ("waiting_input", "a reply")):
        n, med = len(st.answers[status]), st.median(status)
        extra = f"   ({n} answered, median {_span(med)})" if n else ""
        typer.echo(f"  waited for {label:<12}{_span(st.waiting[status])}{extra}")
    typer.echo(f"  left waiting           {_span(st.left_waiting)}   (ended or still open with no answer)")
    typer.echo("  Since this version, finished turns are reports and are excluded from wait totals.")
    if st.longest_wait_session:
        typer.echo(f"  longest answered wait  {_span(st.longest_wait)} ({st.longest_wait_session})")
    if show_lost and st.lost:
        typer.secho("  lost events", fg="red")
        for x in st.lost:
            typer.echo(f"    {x.ts}  {x.session_id}  {x.label}  {x.event_id}")
    if lost:
        raise typer.Exit(1)


@app.command()
def digest(
    since: str = typer.Option("today", help="Window start: today, 8h, 90m, 2d or a time like 2026-11-19T08:00."),
    as_json: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """The daily standup: what the agents did, who waited for you, and who is waiting now."""
    from sekantor.hub.digest import parse_range

    try:
        start = parse_range(since)
    except ValueError as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(2)
    data = _hub("/v1/digest?since=" + urllib.parse.quote(start.isoformat(), safe=""), timeout=15.0)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    t = data["totals"]
    typer.secho(f"Standup since {start.strftime('%Y-%m-%d %H:%M')}", bold=True)
    typer.echo(f"  {t['agents']} agents, {t['turns']} turns finished, asked you {t['asked']}x, "
               f"waited {_span(timedelta(seconds=t['wait_s']))} (longest {_span(timedelta(seconds=t['longest_wait_s']))}), "
               f"{t['errors']} errors, waiting now {t['waiting_now']}")
    for r in data["sessions"]:
        who = r["agent"] or "agent"
        where = (r["project"] or {}).get("name") or "?"
        tools = " ".join(f"{k} {n}" for k, n in sorted(r["tools"].items())) or "no tool use"
        flag = typer.style("WAITING ", fg="yellow", bold=True) if r["waiting"] else ("ERROR   " if r["status"] == "error" else "        ")
        typer.echo(f"{flag}{where}  {who}  {r['session_id']}  {r['status']}  "
                   f"{r['turns']} turns, asked {r['asked']}x ({_span(timedelta(seconds=r['wait_s']))}), {tools}")
        if r["summary"]:
            typer.echo(f"        {r['summary'].splitlines()[0][:100]}")


def _find_session(ref: str) -> dict:
    """A session by full id, or by a unique prefix of its id with or without the 'claude:' part."""
    sessions = _hub("/v1/sessions")["sessions"]
    hits = [s for s in sessions if s["session_id"] == ref]
    if not hits:
        hits = [s for s in sessions if s["session_id"].split(":", 1)[-1].startswith(ref) or s["session_id"].startswith(ref)]
    if len(hits) != 1:
        typer.secho(f"{'No' if not hits else 'More than one'} session matches '{ref}'. See `sekantor status`.", fg="red")
        raise typer.Exit(2)
    return hits[0]


@app.command()
def snooze(session: str = typer.Argument(..., help="Session id or a unique prefix."),
           minutes: int = typer.Option(60, help="How long, in minutes."),
           forever: bool = typer.Option(False, "--forever", help="Until you unmute it.")):
    """Stop notifications for one session or agent for a while (FR-15). It stays in the inbox."""
    s = _find_session(session)
    res = _hub(_session_path(s, "snooze"), method="POST", body={"minutes": None if forever else minutes})
    if "_status" in res:
        typer.secho(str(res.get("detail") or res), fg="red")
        raise typer.Exit(1)
    typer.secho(f"Snoozed {s['session_id']} until {'you unmute it' if forever else res['snoozed_until'][:16]}", fg="green")


@app.command()
def unsnooze(session: str = typer.Argument(..., help="Session id or a unique prefix.")):
    """Turn notifications back on for a session."""
    s = _find_session(session)
    res = _hub(_session_path(s, "snooze"), method="DELETE")
    if "_status" in res:
        typer.secho(str(res.get("detail") or res), fg="red")
        raise typer.Exit(1)
    typer.secho(f"Unmuted {s['session_id']}", fg="green")


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
    """Install sekantor-hook into Claude Code settings (backs the file up first)."""
    from sekantor.pos.claude_code import install as inst

    _migrate()
    path = inst.settings_path(_scope(project, global_))
    exe = inst.hook_executable()
    if not exe:
        typer.secho("sekantor-hook not found next to this Python or on PATH.", fg="red")
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
    """Remove SeKantor's hooks from Claude Code settings; other hooks stay."""
    from sekantor.pos.claude_code import install as inst

    path = inst.settings_path(_scope(project, global_))
    try:
        r = inst.uninstall(path)
    except (ValueError, OSError) as e:
        typer.secho(f"Not changed: {path} could not be read ({e}).", fg="red")
        raise typer.Exit(1)
    if not r.changed:
        typer.echo(f"No SeKantor hooks in {path}.")
        return
    typer.secho(f"Removed {r.changed} hooks from {r.path}", fg="green")
    typer.echo(f"Backup: {r.backup}")


def _detect_integrations() -> dict:
    """Which agent hosts this machine has: shared by `doctor` and `setup`."""
    import shutil

    from sekantor.pos.openbot.pos import automation_dir, installed as openbot_installed
    from sekantor.pos.orca.pos import orca_cli

    openbot = "absent"
    if openbot_installed():
        openbot = "on" if (automation_dir() / "url").exists() else "off"
    return {"openbot": openbot, "orca": bool(orca_cli()), "tmux": bool(shutil.which("tmux"))}


def _hooks_state(exe) -> str:
    """missing: none of ours in the global settings; outdated: old shape, incomplete, or not this install's hook."""
    from sekantor.pos.claude_code import install as inst

    found = inst.inspect(inst.settings_path("global"))
    if not found.events:
        return "missing"
    ours = exe.as_posix().lower() if exe else None
    same_path = all(c.replace("\\", "/").lower() == ours for c in found.commands)
    return "ok" if found.complete and found.current_shape() and same_path else "outdated"


def _setup_report() -> dict:
    from sekantor import service
    from sekantor.pos.claude_code import install as inst

    exe = inst.hook_executable()
    return {"hooks": _hooks_state(exe), "hook_path": str(exe) if exe else None,
            "service": service.installed(service.plan(config.home())),
            "service_current": service.current(service.plan(config.home())), **_detect_integrations()}


@app.command()
def setup(
    as_json: bool = typer.Option(False, "--json", help="Print what is set up and what is not, as JSON (the default)."),
    apply: bool = typer.Option(False, "--apply", help="Install the hooks (global) and the login service, then print the same JSON."),
):
    """First-run check for the desktop app: report the state, or fix it with --apply."""
    if apply:
        import contextlib
        import io

        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                install_claude(project=False, global_=True)
                hub = _install_service(start=True)
        except typer.Exit as e:
            typer.echo(out.getvalue().strip(), err=True)
            raise typer.Exit(e.exit_code or 1)
    report = _setup_report()
    if apply:
        report["hub"] = hub
    typer.echo(json.dumps(report))


@app.command()
def doctor():
    """Check that everything is in place."""
    _migrate()
    from sekantor.hub.app import web_dist
    from sekantor.hub.auth import read_token, token_mode_ok
    from sekantor.pos.claude_code import install as inst
    from sekantor.pos.claude_code.fingerprint import load_rules, rules_path

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

    typer.secho(f"SeKantor {__version__} doctor", bold=True)

    tp = config.token_path()
    check(read_token(tp) is not None and token_mode_ok(tp), f"Token at {tp} (owner only)",
          f"Token missing or readable by others at {tp}: run `sekantor up` once")

    try:
        h = _api("/v1/health", timeout=1.5)
        check(h.get("ok") is True, f"Hub answers at {config.hub_url()} with the token", "Hub answered but not ok")
    except urllib.error.HTTPError as e:
        check(False, "", f"Hub refused the token (HTTP {e.code}): the token file and the running hub differ")
    except (OSError, RuntimeError):
        check(False, "", f"Hub not reachable at {config.hub_url()}: run `sekantor up`")

    exe = inst.hook_executable()
    check(exe is not None, f"sekantor-hook at {exe}", "sekantor-hook not found")
    found = [i for i in (inst.inspect(inst.settings_path("project")), inst.inspect(inst.settings_path("global")))
             if i.events]
    check(bool(found), "Claude Code hooks installed in " + ", ".join(str(i.path) for i in found),
          "Claude Code hooks not installed: run `sekantor install claude --project` (or --global)")
    for i in found:
        check(i.complete, f"All {len(inst.EVENTS)} hook events registered in {i.path.name}",
              f"Some hook events missing in {i.path}: run `sekantor install claude` again")
        check(i.commands_exist, "Hook command exists", f"Hook command missing: {', '.join(i.commands)}")
        check(i.current_shape(), "Hooks are up to date (all asynchronous)",
              f"Hooks in {i.path} are from an older SeKantor: run `sekantor install claude` again")

    try:
        rules = load_rules()
        check(True, f"{len(rules.get('hosts', []))} host rules from {rules_path()}", "")
    except Exception as e:
        check(False, "", f"Host rules at {rules_path()} do not load: {e}")

    dist = web_dist()
    check(dist is not None, f"Web UI built ({dist})", "Web UI not built: `npm ci && npm run build` in web/", warn=True)

    openbot = _detect_integrations()["openbot"]
    if openbot != "absent":
        check(openbot == "on", "OpenBot: Local scripts is on for at least one agent",
              "OpenBot: no agent has Local scripts on, so SeKantor cannot see OpenBot agents "
              "(agent settings > Permissions > Local scripts)", warn=True)

    from sekantor import service as _service

    check(_service.installed(_service.plan(config.home())), "Hub starts at login (sekantor service)",
          "Hub does not start at login: `sekantor service install` keeps it on", warn=True)

    _, config_problems = config.load()
    check(not config_problems, f"Settings in {config.config_path()}",
          "config.toml: " + "; ".join(config_problems))

    if exe:
        sample = json.dumps({"hook_event_name": "Notification", "session_id": "sekantor-doctor",
                             "notification_type": "doctor", "message": "doctor"}).encode()
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:  # no token there: measures the hook without posting
            env = {**os.environ, "SEKANTOR_HOME": tmp}
            t = time.perf_counter()
            p = subprocess.run([str(exe)], input=sample, capture_output=True, env=env, timeout=10)
            ms = (time.perf_counter() - t) * 1000
        check(p.returncode == 0 and not p.stdout, f"sekantor-hook returns no decision ({ms:.0f} ms, runs async)",
              f"sekantor-hook printed output or exited {p.returncode}")

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
