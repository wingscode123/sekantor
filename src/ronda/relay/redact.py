"""Mask secrets before any text leaves the machine (ADR-0012)."""

from __future__ import annotations

import re

MASK = "<redacted>"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # well-known key formats
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}"), MASK),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), MASK),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), MASK),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), MASK),
    # bearer / basic auth headers
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    # credentials inside URLs: scheme://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):[^@\s/]+@"), r"\1:" + MASK + "@"),
    # --password=x, --token x, --api-key x, -pSECRET is too ambiguous to catch
    (re.compile(r"(?i)(--(?:password|passwd|pass|token|secret|api[-_]?key|access[-_]?key)(?:=|\s+))(\S+)"), r"\1" + MASK),
    # NAME_WITH_SECRET_WORD=value / : value (env assignments, config lines)
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIALS?)"
                r"[A-Z0-9_]*)(\s*[=:]\s*)(['\"]?)(?!\$)[^\s'\";]+\3"), r"\1\2" + MASK),
]


def redact(text: str | None, limit: int | None = None) -> str | None:
    """Return ``text`` with secrets masked, cut to ``limit`` characters."""
    if text is None:
        return None
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    if limit is not None and len(out) > limit:
        out = out[: limit - 1] + "…"
    return out
