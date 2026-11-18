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

from sekantor import config

CHAIN_DEPTH = 8


def rules_path() -> Path:
    override = os.environ.get("SEKANTOR_HOSTS")
    if override:
        return Path(override)
    user = config.home() / "hosts.yaml"
    if user.is_file():
        return user
    return Path(__file__).resolve().parents[2] / "hosts.yaml"


def load_rules(path: Path | None = None) -> dict:
    """The rules, from a JSON cache next to the token when it is fresh (yaml is a slow import)."""
    import json

    src = Path(path or rules_path())
    cache = config.home() / "hosts.cache.json"
    key = f"{src.resolve()}|{src.stat().st_mtime_ns}"
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            return cached["rules"]
    except (OSError, ValueError):
        pass
    import yaml

    with open(src, encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.name + f".{os.getpid()}")
        tmp.write_text(json.dumps({"key": key, "rules": rules}), encoding="utf-8")
        os.replace(tmp, cache)
    except OSError:
        pass
    return rules


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


def env_names(rules: dict) -> set[str]:
    """Env names for host classification and session identity."""
    groups = [h.get("signals", []) for h in rules.get("hosts", [])]
    groups.append(((rules.get("fallback") or {}).get("terminal") or {}).get("signals", []))
    return {s["env"] for signals in groups for s in signals if "env" in s} | set(rules.get("forward_env", []))


def collect(agent_pid: int | None, deep: bool, from_agent: bool = False) -> tuple[list[str], str | None, str | None]:
    """(parent chain names, agent exe, agent cmdline) for the hook process. Empty unless ``deep``.

    ``from_agent``: the hub runs this for a hook it did not spawn, so the chain is the agent's own
    (the agent first, then its parents) and nothing is known without ``agent_pid``.
    """
    if not deep:
        return [], None, None
    try:
        import psutil
    except ImportError:
        return [], None, None
    chain: list[str] = []
    exe = cmdline = None
    try:
        if from_agent:
            if not agent_pid:
                return [], None, None
            p = psutil.Process(agent_pid)
            walk = [p, *p.parents()]
        else:
            walk = psutil.Process().parents()
        for parent in walk[:CHAIN_DEPTH + 2]:
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
