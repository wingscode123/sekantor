"""Paths and defaults. Everything lives in ~/.sekantor unless SEKANTOR_HOME says otherwise."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sekantor.projects import KINDS, Kind

HOST = "127.0.0.1"  # never configurable: the hub binds to loopback only
DEFAULT_PORT = 7878


def home() -> Path:
    return Path(os.environ.get("SEKANTOR_HOME") or Path.home() / ".sekantor")


def migrate_home(old: Path, new: Path, errors: list[str] | None = None) -> bool:
    """Copy a Ronda-era home into the SeKantor one (ADR-0023).

    Skipped when ``old`` is missing or ``new`` already has both its token and its database.
    Otherwise each item (token with mode 600, config.toml, hosts.cache.json, the database via sqlite
    backup, safe while an old hub writes) is copied only when ``new`` lacks it, so a folder that
    something else created first (a cache file, say) still migrates and nothing is overwritten.
    Never touches ``old``. A failed item is appended to ``errors`` and the rest carry on.
    True when anything was copied.
    """
    import shutil
    import sqlite3

    if not old.is_dir() or ((new / "token").exists() and (new / "sekantor.db").exists()):
        return False
    errors = errors if errors is not None else []
    copied = False
    for name in ("token", "config.toml", "hosts.cache.json"):
        if (old / name).is_file() and not (new / name).exists():
            try:
                new.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old / name, new / name)
                if name == "token":
                    os.chmod(new / name, 0o600)
                copied = True
            except OSError as e:
                errors.append(f"{name}: {e}")
    if (old / "ronda.db").is_file() and not (new / "sekantor.db").exists():
        tmp = new / "sekantor.db.part"
        try:
            new.mkdir(parents=True, exist_ok=True)
            src = sqlite3.connect(f"file:{(old / 'ronda.db').as_posix()}?mode=ro", uri=True)
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            os.replace(tmp, new / "sekantor.db")
            copied = True
        except (OSError, sqlite3.Error) as e:
            errors.append(f"sekantor.db: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return copied


def migrate_legacy_home(errors: list[str] | None = None) -> bool:
    """migrate_home from ~/.ronda, unless SEKANTOR_HOME points somewhere else on purpose."""
    if os.environ.get("SEKANTOR_HOME"):
        return False
    return migrate_home(Path.home() / ".ronda", home(), errors)


def migrate_note() -> str:
    """Run the legacy migration; a one-line note for the user when it did something or failed."""
    errors: list[str] = []
    copied = migrate_legacy_home(errors)
    if not copied and not errors:
        return ""
    line = "Copied ~/.ronda to ~/.sekantor"
    return line + (f" (not copied: {'; '.join(errors)})" if errors else "")


def token_path() -> Path:
    return home() / "token"


def hook_log_path() -> Path:
    return home() / "hook.log"


def port() -> int:
    try:
        return int(os.environ.get("SEKANTOR_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def hub_url() -> str:
    return os.environ.get("SEKANTOR_URL") or f"http://{HOST}:{port()}"


# --- settings: ~/.sekantor/config.toml (all optional) ----------------------------

# Folders whose Claude Code runs are not agent sessions: OpenBot's own helper runs start in its
# program folder (28 of 37 "OpenBot" sessions in the first dogfooding run).
DEFAULT_IGNORE_CWD = [r"/Programs/OpenBot(/|$)", r"/OpenBot\.app/", r"^/opt/OpenBot(/|$)"]


class Settings:
    def __init__(self, notify: bool = True, quiet_hours: str | None = None, ignore_cwd: list[str] | None = None,
                 orca_pos: bool = False, keep_in_ram: bool | None = None, projects: dict[str, Kind] | None = None,
                 remind_after_minutes: int = 10):
        self.notify = bool(notify)
        self.quiet_hours = parse_quiet_hours(quiet_hours)  # FR-33: (start, end) minutes, or None
        self.ignore_cwd = list(ignore_cwd) if ignore_cwd is not None else list(DEFAULT_IGNORE_CWD)
        self.orca_pos = bool(orca_pos)  # opt-in: the orca CLI is heavy to poll
        if keep_in_ram is not None and not isinstance(keep_in_ram, bool):
            raise TypeError("keep_in_ram must be true or false")
        # ADR-0020 is for the Python hub; a frozen install has the Rust forwarder and no slow hook to protect.
        self.keep_in_ram = (not getattr(sys, "frozen", False)) if keep_in_ram is None else keep_in_ram

        if projects is not None and (not isinstance(projects, dict) or any(
            not isinstance(kind, str) or kind not in KINDS for kind in projects.values()
        )):
            raise ValueError("projects must map project names to kinds")
        self.projects = dict(projects or {})
        if isinstance(remind_after_minutes, bool) or not isinstance(remind_after_minutes, int) or remind_after_minutes < 0:
            raise ValueError("remind_after_minutes must be 0 or more")
        self.remind_after_minutes = remind_after_minutes  # A4: 0 = off

    def ignored(self, cwd: str | None) -> bool:
        import re

        if not cwd:
            return False
        path = cwd.replace("\\", "/")
        for p in self.ignore_cwd:
            try:
                if re.search(p, path, re.I):
                    return True
            except re.error:
                continue
        return False

    def quiet(self, now=None) -> bool:
        return in_quiet_hours(self.quiet_hours, now)


def parse_quiet_hours(spec: str | None) -> tuple[int, int] | None:
    """'22:00-07:00' -> (1320, 420) in minutes after midnight, local time. Bad or empty -> None."""
    import re

    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", spec or "")
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59 or (h1, m1) == (h2, m2):
        return None
    return h1 * 60 + m1, h2 * 60 + m2


def in_quiet_hours(window: tuple[int, int] | None, now=None) -> bool:
    if not window:
        return False
    from datetime import datetime

    t = (now or datetime.now()).astimezone()
    minute = t.hour * 60 + t.minute
    start, end = window
    return start <= minute < end if start < end else (minute >= start or minute < end)


def config_path(base: Path | None = None) -> Path:
    return (base or home()) / "config.toml"


def read_toml(base: Path | None = None) -> dict:
    """config.toml as a dict; a missing or broken file reads as empty."""
    import tomllib

    try:
        with open(config_path(base), "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


# config.toml key -> Settings argument
SETTING_KEYS = {"notify": "notify", "quiet_hours": "quiet_hours", "ignore_cwd": "ignore_cwd", "orca_pos": "orca_pos",
                "keep_in_ram": "keep_in_ram", "projects": "projects",
                "remind_after_minutes": "remind_after_minutes"}
# Keys of the answering era (ADR-0021): an old config.toml still has them, and that is not a problem.
OLD_KEYS = {"approval_wait", "reply_wait", "risky_commands", "reply_entrypoints"}


REMOVED_KEYS = {"webhooks", "telegram"}


def load(base: Path | None = None) -> tuple[Settings, list[str]]:
    """The settings from config.toml and what is wrong with it. A bad value keeps its default, the rest still apply."""
    import tomllib

    try:
        with open(config_path(base), "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return Settings(), []
    except (OSError, tomllib.TOMLDecodeError) as e:
        return Settings(), [f"{config_path(base)} is not read, defaults apply: {e}"]
    good, problems = {}, []
    for key, value in data.items():
        if key in REMOVED_KEYS or key in OLD_KEYS:
            continue  # removed features (relay, answering); an old config.toml may still have these
        if key not in SETTING_KEYS:
            problems.append(f"unknown setting {key!r}")
            continue
        if key == "projects" and isinstance(value, dict):
            valid = {}
            for name, kind in value.items():
                if isinstance(kind, str) and kind in KINDS:
                    valid[name] = kind
                else:
                    problems.append(f"projects[{name!r}] = {kind!r} is not valid, detection applies")
            good["projects"] = valid
            continue
        try:
            Settings(**{SETTING_KEYS[key]: value})
            good[SETTING_KEYS[key]] = value
        except (TypeError, ValueError):
            problems.append(f"{key} = {value!r} is not valid, the default applies")
    return Settings(**good), problems


def settings(base: Path | None = None) -> Settings:
    """Read config.toml. A missing file gives the defaults; see load() for what was wrong with it."""
    return load(base)[0]
