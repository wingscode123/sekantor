"""M0 spike: redact captured payloads / probe output before committing them.

    python scripts/spike/redact.py IN.json OUT.json

- replaces the home directory and username with ~ / <user>
- masks e-mail addresses
- masks env vars that identify the account (account/org UUID, e-mail, OAuth, tokens)
- drops long JSON blobs passed via --settings / --allowedTools (kept as "<omitted N chars>")
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
from pathlib import Path

HOME = str(Path.home())
USER = getpass.getuser()
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# any spelling of a user profile dir, e.g. the 8.3 short name C:\Users\ABCDEF~1
USERS_DIR_RE = re.compile(r"(Users[\\/]+)(?!<user>)[^\\/\"']+", re.I)
SENSITIVE_ENV = re.compile(r"ACCOUNT|ORGANIZATION|EMAIL|OAUTH|TOKEN|SECRET|KEY|AUTH|PAIRING|RATE_LIMIT|SUBSCRIPTION", re.I)
LONG_FLAGS = ("--settings", "--allowedTools", "--disallowedTools", "--mcp-config", "--append-system-prompt", "--system-prompt")


def scrub_str(s: str) -> str:
    variants = {HOME, HOME.replace("\\", "/"), HOME.replace("\\", "\\\\"),
                "/c" + HOME[2:].replace("\\", "/") if len(HOME) > 2 and HOME[1] == ":" else HOME}
    for v in sorted(variants, key=len, reverse=True):
        s = s.replace(v, "~")
    s = USERS_DIR_RE.sub(lambda m: m.group(1) + "<user>", s)
    s = EMAIL_RE.sub("<email>", s)
    if USER and len(USER) > 2:
        s = s.replace(USER, "<user>")
    return s


def scrub_cmdline(cmd: list) -> list:
    out, skip = [], False
    for i, a in enumerate(cmd):
        if skip:
            skip = False
            out.append(f"<omitted {len(a)} chars>" if len(a) > 80 else scrub_str(a))
            continue
        if isinstance(a, str):
            key = a.split("=", 1)[0]
            if key in LONG_FLAGS:
                if "=" in a:
                    val = a.split("=", 1)[1]
                    out.append(f"{key}=<omitted {len(val)} chars>" if len(val) > 80 else scrub_str(a))
                else:
                    out.append(a)
                    skip = True
                continue
            out.append(scrub_str(a))
        else:
            out.append(a)
    return out


def scrub(obj, parent_key: str = ""):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if parent_key == "env" and SENSITIVE_ENV.search(k) and isinstance(v, str) and v:
                out[k] = "<redacted>"
            elif k == "cmdline" and isinstance(v, list):
                out[k] = scrub_cmdline(v)
            else:
                out[k] = scrub(v, k)
        return out
    if isinstance(obj, list):
        if parent_key == "argv":
            return scrub_cmdline(obj)
        return [scrub(v, parent_key) for v in obj]
    if isinstance(obj, str):
        return scrub_str(obj)
    return obj


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text(json.dumps(scrub(data), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
