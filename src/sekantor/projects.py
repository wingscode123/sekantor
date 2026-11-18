"""Bounded, local project classification for the office."""

from __future__ import annotations

import json
import os
import re
import stat
import time
import tomllib
from collections import OrderedDict
from itertools import islice
from pathlib import Path
from threading import Lock
from typing import Literal, get_args

Kind = Literal["web", "backend", "data", "mobile", "game", "infra", "docs", "other"]
KINDS = frozenset(get_args(Kind))
CACHE_SECONDS = 600
MAX_CACHE_ENTRIES = 1024
MAX_BYTES = 64 * 1024
MAX_ENTRIES = 256
PRIORITY = ("mobile", "game", "web", "backend", "data", "infra")
JS = {
    "web": {"react", "vue", "svelte", "next", "vite"},
    "mobile": {"react-native", "expo"},
    "backend": {"express", "fastify", "nest", "@nestjs/core", "@nestjs/common"},
    "game": {"phaser"},
}
PYTHON = {
    "backend": {"fastapi", "django", "flask"},
    "data": {"pandas", "numpy", "torch", "sklearn", "scikit-learn", "jupyter", "jupyterlab"},
    "game": {"pygame"},
}
RUST = {"game": {"bevy"}, "backend": {"axum", "actix", "actix-web"}}
CODE_SUFFIXES = set(
    ".py .js .jsx .ts .tsx .mjs .cjs .vue .svelte .rs .go .java .kt .swift .dart .cs "
    ".rb .php .c .h .cpp .sh .ps1 .ipynb .html .css .sql .scala .lua .zig .ex .exs".split()
)
IGNORED_DIRS = {"node_modules", "vendor", "dist", "build", "__pycache__", "target"}
_cache: OrderedDict[Path, tuple[float, str, Kind, tuple[str, ...]]] = OrderedDict()
_lock = Lock()


def _mode(path: Path) -> int:
    try:
        info = path.lstat()
        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return 0
        return info.st_mode
    except (OSError, ValueError):
        return 0


def _is_file(folder: Path, marker: str) -> bool:
    path = folder
    *parents, filename = Path(marker).parts
    for part in parents:
        path /= part
        if not stat.S_ISDIR(_mode(path)):
            return False
    return stat.S_ISREG(_mode(path / filename))


def _read(path: Path) -> str:
    if not stat.S_ISREG(_mode(path)):
        return ""
    try:
        with path.open("rb") as file:
            data = file.read(MAX_BYTES + 1)
        return data.decode("utf-8-sig") if len(data) <= MAX_BYTES else ""
    except (OSError, UnicodeError):
        return ""


def _table(value) -> dict:
    return value if isinstance(value, dict) else {}


def _manifest(folder: Path, name: str, parse) -> dict:
    try:
        raw = _read(folder / name)
        return _table(parse(raw)) if raw else {}
    except (ValueError, RecursionError):
        return {}


def _dependencies(table: dict, sections: tuple[str, ...]) -> set[str]:
    return {key.lower() for section in sections for key in _table(table.get(section))}


def _python_names(lines) -> set[str]:
    if not isinstance(lines, (list, tuple)):
        return set()
    names = set()
    for line in lines:
        if isinstance(line, str) and (match := re.match(r"\s*([\w.-]+)", line)):
            names.add(match[1].lower().replace("_", "-"))
    return names


def _entries(folder: Path) -> tuple[list[Path], bool]:
    if not stat.S_ISDIR(_mode(folder)):
        return [], False
    try:
        with os.scandir(folder) as entries:
            paths = [Path(e.path) for e in islice(entries, MAX_ENTRIES + 1)]
        return paths[:MAX_ENTRIES], len(paths) <= MAX_ENTRIES
    except OSError:
        return [], False


def _classify(folder: Path) -> tuple[Kind, tuple[str, ...]]:
    signals: dict[Kind, list[str]] = {}

    def add(kind: Kind, signal: str) -> None:
        signals.setdefault(kind, []).append(signal)

    def match(filename: str, names: set[str], rules: dict) -> None:
        for kind, deps in rules.items():
            for dep in sorted(names & deps):
                add(kind, f"{filename}: {dep}")

    package = _manifest(folder, "package.json", json.loads)
    js = _dependencies(package, ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"))
    match("package.json", js, JS)
    keywords = package.get("keywords")
    game_words = " ".join(
        value for value in (folder.name, package.get("name"), package.get("description"),
                            *(keywords if isinstance(keywords, list) else [])) if isinstance(value, str)
    )
    if "three" in js and re.search(r"\b(game|games|gaming|arcade|gameplay)\b", game_words, re.I):
        add("game", "package.json: three")

    python = _manifest(folder, "pyproject.toml", tomllib.loads)
    project = _table(python.get("project"))
    names = _python_names(project.get("dependencies"))
    for groups in (_table(project.get("optional-dependencies")), _table(python.get("dependency-groups"))):
        for group in groups.values():
            names.update(_python_names(group))
    poetry = _table(_table(python.get("tool")).get("poetry"))
    names.update(_dependencies(poetry, ("dependencies", "dev-dependencies")))
    for group in _table(poetry.get("group")).values():
        names.update(_dependencies(_table(group), ("dependencies",)))
    match("pyproject.toml", names, PYTHON)
    match("requirements.txt", _python_names(_read(folder / "requirements.txt").splitlines()), PYTHON)

    cargo = _manifest(folder, "Cargo.toml", tomllib.loads)
    sections = ("dependencies", "dev-dependencies", "build-dependencies")
    rust = _dependencies(cargo, sections) | _dependencies(_table(cargo.get("workspace")), sections)
    for target in _table(cargo.get("target")).values():
        rust.update(_dependencies(_table(target), sections))
    match("Cargo.toml", rust, RUST)

    for marker in ("pubspec.yaml", "AndroidManifest.xml", "app/src/main/AndroidManifest.xml",
                   "android/app/src/main/AndroidManifest.xml"):
        if _is_file(folder, marker):
            add("mobile", marker)

    entries, complete = _entries(folder)
    ios_entries, _ = _entries(folder / "ios")
    for entry in sorted(entries + ios_entries):
        name = entry.name.lower()
        if entry.suffix.lower() == ".xcodeproj" and stat.S_ISDIR(_mode(entry)):
            add("mobile", entry.relative_to(folder).as_posix())
        if entry.parent != folder:
            continue
        if name in {"dockerfile", "ansible.cfg"} or entry.suffix.lower() == ".tf":
            if stat.S_ISREG(_mode(entry)):
                add("infra", entry.name)
        if name in {"terraform", "k8s", "helm", "ansible"} and stat.S_ISDIR(_mode(entry)):
            add("infra", entry.name)
    for kind in PRIORITY:
        if kind in signals:
            return kind, tuple(signals[kind])
    if complete and _mostly_markdown(entries):
        return "docs", ("Markdown files",)
    return "other", ()


def _mostly_markdown(entries: list[Path]) -> bool:
    markdown = files = 0
    paths = list(entries)
    for path in paths:
        if path.name.startswith(".") or path.name.lower() in IGNORED_DIRS:
            continue
        mode = _mode(path)
        if stat.S_ISDIR(mode):
            children, complete = _entries(path)
            if not complete or len(paths) + len(children) > MAX_ENTRIES:
                return False
            paths.extend(children)
        elif stat.S_ISREG(mode):
            suffix = path.suffix.lower()
            if suffix in CODE_SUFFIXES or path.name in {"package.json", "pyproject.toml", "Cargo.toml", "requirements.txt"}:
                return False
            files += 1
            markdown += suffix == ".md"
    return markdown > files / 2


def _inspect(folder: Path) -> tuple[str, Kind, tuple[str, ...]]:
    # A worktree or submodule has a .git file, while a regular clone has a directory.
    for parent in (folder, *folder.parents):
        mode = _mode(parent / ".git")
        if stat.S_ISDIR(mode) or stat.S_ISREG(mode):
            root = parent
            break
    else:
        root = folder

    kind, signals = _classify(folder)
    if kind in {"docs", "other"} and root != folder:
        root_kind, root_signals = _classify(root)
        if root_kind != "other":
            kind, signals = root_kind, root_signals
    return root.name or str(root), kind, signals


def detect(cwd: str | Path) -> dict:
    """Return a fresh JSON object using a ten-minute cache per normalized folder."""
    original = Path(cwd)
    if not original.is_absolute():
        return {"name": original.name or str(original), "kind": "other", "signals": []}
    folder = Path(os.path.abspath(original))
    # Reject UNC/device paths before any filesystem calls.
    if folder.drive.startswith(("\\\\", "//")):
        return {"name": folder.name or str(folder), "kind": "other", "signals": []}

    with _lock:
        now = time.monotonic()
        cached = _cache.get(folder)
        if cached is None or now >= cached[0]:
            # Avoid following symlinked directories, including intermediate components.
            if all(stat.S_ISDIR(_mode(part)) for part in (*reversed(folder.parents), folder)):
                name, kind, signals = _inspect(folder)
            else:
                name, kind, signals = folder.name or str(folder), "other", ()
            _cache[folder] = time.monotonic() + CACHE_SECONDS, name, kind, signals
        else:
            _, name, kind, signals = cached
        _cache.move_to_end(folder)
        if len(_cache) > MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)
    return {"name": name, "kind": kind, "signals": list(signals)}
