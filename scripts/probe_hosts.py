"""M0 spike: dump host fingerprints of running AI coding agent processes.

Finds claude, codex, opencode, gemini and aider processes (native binaries and
node/python wrappers) and prints, for each one, its parent process chain,
selected environment variables, cwd and command line as JSON.

    uv run python scripts/probe_hosts.py -o probe.json
    uv run python scripts/probe_hosts.py --all-env -o probe.json   # also list every env var name

Prefer -o over shell redirection: Windows PowerShell 5.1 writes `>` output as UTF-16.

Read-only: it never signals, writes to, or attaches to any process.
Secrets are redacted: any env var whose name looks like a key/token/secret.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone

import psutil

AGENTS = ("claude", "codex", "opencode", "gemini", "aider")

ENV_KEYS_EXACT = {
    "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "TERM", "TMUX", "TMUX_PANE", "STY",
    "WT_SESSION", "WT_PROFILE_ID", "VSCODE_PID", "VSCODE_CWD", "VSCODE_IPC_HOOK_CLI",
    "VSCODE_GIT_IPC_HANDLE", "VSCODE_INJECTION", "CURSOR_TRACE_ID", "ZED_TERM",
    "__CFBundleIdentifier", "ITERM_SESSION_ID", "KITTY_WINDOW_ID", "WEZTERM_PANE",
    "ALACRITTY_WINDOW_ID", "GHOSTTY_RESOURCES_DIR", "SSH_CONNECTION", "SESSIONNAME",
    "SHELL", "COMSPEC", "MSYSTEM", "WSL_DISTRO_NAME", "PWD",
}
ENV_KEY_PARTS = ("ORCA", "OPENBOT", "CLAUDE", "ANTHROPIC", "CODEX", "GEMINI", "AIDER", "OPENCODE")
SECRET_RE = re.compile(r"KEY|TOKEN|SECRET|PASSW|AUTH|CREDENTIAL|COOKIE|SPAWN", re.I)
MAX_CHAIN = 20


def redact_env(env: dict[str, str], all_env: bool) -> dict[str, str]:
    out = {}
    for k, v in env.items():
        ku = k.upper()
        selected = k in ENV_KEYS_EXACT or ku in ENV_KEYS_EXACT or any(p in ku for p in ENV_KEY_PARTS)
        if not selected and not all_env:
            continue
        if SECRET_RE.search(k):
            out[k] = "<redacted>"
        elif selected:
            out[k] = v
        else:
            out[k] = "<value omitted>"
    return dict(sorted(out.items()))


def safe(proc: psutil.Process, attr: str, errors: list[str]):
    try:
        return getattr(proc, attr)()
    except (psutil.AccessDenied, psutil.ZombieProcess) as e:
        errors.append(f"{attr}: {type(e).__name__}")
    except psutil.NoSuchProcess:
        errors.append(f"{attr}: NoSuchProcess")
    except OSError as e:
        errors.append(f"{attr}: OSError {e.errno}")
    return None


def agent_match(name: str | None, cmdline: list[str] | None) -> str | None:
    """Return the agent name if this process looks like an agent, else None."""
    n = (name or "").lower()
    base = re.sub(r"\.(exe|cmd|bat|ps1)$", "", n)
    if base in AGENTS:
        return base
    if base in ("node", "bun", "deno", "python", "python3", "pythonw") or base.startswith("python3."):
        for arg in (cmdline or [])[1:4]:
            a = arg.replace("\\", "/").lower()
            for agent in AGENTS:
                # e.g. .../node_modules/@anthropic-ai/claude-code/cli.js, .../bin/codex, -m aider
                if re.search(rf"(^|/|@[\w-]+/){agent}([-\w]*)?(/|\.js|\.mjs|\.py|$)", a) or a == agent:
                    return agent
    return None


def describe(proc: psutil.Process, all_env: bool, with_env: bool) -> dict:
    errors: list[str] = []
    item = {"pid": proc.pid}
    item["name"] = safe(proc, "name", errors)
    item["exe"] = safe(proc, "exe", errors)
    item["cmdline"] = safe(proc, "cmdline", errors)
    item["cwd"] = safe(proc, "cwd", errors)
    ct = safe(proc, "create_time", errors)
    item["started"] = datetime.fromtimestamp(ct, timezone.utc).isoformat() if ct else None
    if with_env:
        env = safe(proc, "environ", errors)
        item["env"] = redact_env(env, all_env) if env is not None else None
    if errors:
        item["errors"] = errors
    return item


def chain_of(proc: psutil.Process, all_env: bool) -> list[dict]:
    chain = []
    seen = {proc.pid}
    try:
        parent = proc.parent()
    except psutil.Error:
        parent = None
    while parent is not None and len(chain) < MAX_CHAIN and parent.pid not in seen:
        seen.add(parent.pid)
        chain.append(describe(parent, all_env, with_env=False))
        try:
            parent = parent.parent()
        except psutil.Error:
            break
    return chain


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all-env", action="store_true", help="also list every env var name (values omitted)")
    ap.add_argument("-o", "--output", help="write JSON to this file (UTF-8) instead of stdout")
    args = ap.parse_args()

    me = os.getpid()
    found = []
    for proc in psutil.process_iter(["pid", "name"]):
        if proc.pid == me:
            continue
        try:
            cmd = proc.cmdline()
        except psutil.Error:
            cmd = None
        agent = agent_match(proc.info.get("name"), cmd)
        if not agent:
            continue
        # Electron/Chromium helper processes (e.g. Claude desktop's GPU/renderer
        # children, also named claude.exe) are not agents.
        if cmd and any(a.startswith("--type=") for a in cmd[1:]):
            continue
        item = describe(proc, args.all_env, with_env=True)
        item["agent"] = agent
        item["parent_chain"] = chain_of(proc, args.all_env)
        found.append(item)

    # Drop agent processes whose parent is also a matched agent of the same kind
    # (e.g. claude.cmd -> node cli.js). Keep them, but mark as nested.
    pids = {f["pid"]: f["agent"] for f in found}
    for f in found:
        parent_pid = f["parent_chain"][0]["pid"] if f["parent_chain"] else None
        f["nested_in_agent"] = parent_pid in pids

    out = {
        "probe_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "python": sys.version.split()[0],
                     "psutil": psutil.__version__},
        "agent_count": len(found),
        "agents": found,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {len(found)} agent process(es) to {args.output}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
