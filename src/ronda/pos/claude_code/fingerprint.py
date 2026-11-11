"""Host fingerprint (FR-08/FR-09): which app is this agent running in?

``classify`` is pure. ``collect`` gathers signals for the current hook process: the inherited env
always, the parent chain and the agent exe only when ``deep`` (SessionStart), because psutil is slow
on Windows (ADR-0003).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

CHAIN_DEPTH = 8


def rules_path() -> Path:
    override = os.environ.get("RONDA_HOSTS")
    if override:
        return Path(override)
    user = Path(os.environ.get("RONDA_HOME") or Path.home() / ".ronda") / "hosts.yaml"
    if user.is_file():
        return user
    return Path(__file__).resolve().parents[2] / "hosts.yaml"


def load_rules(path: Path | None = None) -> dict:
    import yaml  # lazy: only paid when a hook classifies

    with open(path or rules_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _env_get(env: dict[str, str], name: str) -> str | None:
    if name in env:
        return env[name]
    up = name.upper()
    for k, v in env.items():
        if k.upper() == up:
            return v
    return None


def _match(sig: dict, env: dict[str, str], chain: list[str], exe: str | None, cwd: str | None, cmdline: str | None) -> bool:
    if "env" in sig:
        v = _env_get(env, sig["env"])
        if not v:
            return False
        if "equals" in sig:
            return v.lower() == str(sig["equals"]).lower()
        if "matches" in sig:
            return re.search(sig["matches"], v, re.I) is not None
        return True
    if "parent" in sig:
        return any(re.search(sig["parent"], n or "", re.I) for n in chain[:CHAIN_DEPTH])
    if "exe" in sig:
        return bool(exe) and re.search(sig["exe"], exe.replace("\\", "/"), re.I) is not None
    if "cwd" in sig:
        return bool(cwd) and re.search(sig["cwd"], cwd.replace("\\", "/"), re.I) is not None
    if "cmdline" in sig:
        return bool(cmdline) and re.search(sig["cmdline"], cmdline, re.I) is not None
    return False


def _score(signals: list[dict], *args) -> tuple[float, list[str]]:
    p, via = 1.0, []
    for s in signals:
        if _match(s, *args):
            p *= 1 - float(s["weight"])
            via.append(s["id"])
    return round(1 - p, 3), via


def classify(rules: dict, env: dict[str, str], chain: list[str] | None = None, exe: str | None = None,
             cwd: str | None = None, cmdline: str | None = None) -> dict[str, Any] | None:
    """Return ``{"app", "confidence", "via"}`` or None when there is no evidence at all."""
    chain = chain or []
    args = (env, chain, exe, cwd, cmdline)
    best: tuple[str, float, list[str]] | None = None
    for host in rules.get("hosts", []):
        conf, via = _score(host.get("signals", []), *args)
        if via and (best is None or conf > best[1]):
            best = (host["id"], conf, via)
    if best and best[1] >= float(rules.get("min_confidence", 0.5)):
        return {"app": best[0], "confidence": best[1], "via": best[2]}
    term = (rules.get("fallback") or {}).get("terminal")
    if term and chain:
        conf, via = _score(term.get("signals", []), *args)
        if via:
            return {"app": "terminal", "confidence": conf, "via": via}
    return None


def collect(env: dict[str, str], cwd: str | None, agent_pid: int | None, deep: bool) -> tuple[list[str], str | None, str | None]:
    """(parent chain names, agent exe, agent cmdline) for the hook process. Empty unless ``deep``."""
    if not deep:
        return [], None, None
    try:
        import psutil
    except ImportError:
        return [], None, None
    chain: list[str] = []
    exe = cmdline = None
    try:
        p = psutil.Process()
        for parent in p.parents()[:CHAIN_DEPTH + 2]:
            try:
                chain.append(parent.name())
            except psutil.Error:
                chain.append("")
        if agent_pid:
            agent = psutil.Process(agent_pid)
            try:
                exe = agent.exe()
                cmdline = " ".join(agent.cmdline()[:20])
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    return chain, exe, cmdline
