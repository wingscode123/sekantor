import json
from datetime import datetime, timezone

import pytest

from sekantor import config, projects
from sekantor.hub.api import session_json
from sekantor.hub.status import SessionState
from sekantor.schema import Host, Status, Workspace


@pytest.mark.parametrize(("files", "kind"), [
    ({"package.json": '{"devDependencies":{"vite":"*"}}'}, "web"),
    ({"package.json": '{"dependencies":{"@nestjs/core":"*"}}'}, "backend"),
    ({"pyproject.toml": '[project]\ndependencies = ["FastAPI>=1"]'}, "backend"),
    ({"Cargo.toml": '[dependencies]\nactix-web = "4"'}, "backend"),
    ({"requirements.txt": "pandas>=2\n"}, "data"),
    ({"package.json": '{"dependencies":{"expo":"*", "react":"*"}}'}, "mobile"),
    ({"pubspec.yaml": "name: sample"}, "mobile"),
    ({"android/app/src/main/AndroidManifest.xml": "<manifest />"}, "mobile"),
    ({"ios/Sample.xcodeproj/project.pbxproj": ""}, "mobile"),
    ({"package.json": '{"dependencies":{"phaser":"*"}}'}, "game"),
    ({"package.json": '{"keywords":["game"],"dependencies":{"three":"*"}}'}, "game"),
    ({"requirements.txt": "pygame\n"}, "game"),
    ({"Cargo.toml": '[dependencies]\nbevy = "0.15"'}, "game"),
    ({"Dockerfile": "FROM scratch"}, "infra"),
    ({"ops.tf": ""}, "infra"),
    ({"helm/Chart.yaml": ""}, "infra"),
    ({"README.md": "", "docs/guide.md": ""}, "docs"),
    ({"README.md": "", "src/code.py": ""}, "other"),
    ({"package.json": '{"name":"three game", "dependencies":{"other":"*"}}'}, "other"),
    ({"package.json": '{"dependencies":{"three":"*"}}'}, "other"),
    ({"package.json": "{"}, "other"),
])
def test_detect_kinds(tmp_path, files, kind):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    project = projects.detect(tmp_path)
    assert project["name"] == tmp_path.name
    assert project["kind"] == kind
    assert bool(project["signals"]) == (kind != "other")


@pytest.mark.parametrize("worktree", [False, True])
def test_git_root_name_and_manifest_fallback(tmp_path, worktree):
    if worktree:
        (tmp_path / ".git").write_text("gitdir: /unused", encoding="utf-8")
    else:
        (tmp_path / ".git").mkdir()
    (tmp_path / "Cargo.toml").write_text('[dependencies]\naxum = "0.8"', encoding="utf-8")
    folder = tmp_path / "src"
    folder.mkdir()
    assert projects.detect(folder) == {
        "name": tmp_path.name, "kind": "backend", "signals": ["Cargo.toml: axum"],
    }


def test_reads_are_capped(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"react":"*"}}' + " " * projects.MAX_BYTES, encoding="utf-8"
    )
    assert projects.detect(tmp_path)["kind"] == "other"


def test_detection_is_cached_per_folder(tmp_path, monkeypatch):
    now = 100.0
    monkeypatch.setattr(projects.time, "monotonic", lambda: now)
    folder = tmp_path / "first"
    folder.mkdir()
    initial = projects.detect(folder)
    initial["signals"].append("caller mutation")
    manifest = {"dependencies": {"react": "*"}}
    (folder / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    now += 599
    assert projects.detect(folder)["signals"] == []
    assert projects.detect(tmp_path)["kind"] == "web"
    now += 1
    assert projects.detect(folder)["kind"] == "web"


def test_session_project_override_and_openbot(tmp_path):
    folder = tmp_path / "workspace"
    folder.mkdir()
    (folder / "package.json").write_text('{"dependencies":{"vue":"*"}}', encoding="utf-8")
    (tmp_path / "config.toml").write_text('[projects]\n"workspace" = "docs"\nbad = "unknown"', encoding="utf-8")
    settings, problems = config.load(tmp_path)
    assert len(problems) == 1
    now = datetime.now(timezone.utc)
    state = SessionState(session_id="example", source="claude-code", status=Status.running,
                         status_since=now, status_ts=now, started_at=now, last_event_at=now)
    assert session_json(state, settings)["project"] is None
    state.workspace = Workspace(cwd=str(folder))
    assert session_json(state)["project"]["kind"] == "web"
    assert session_json(state, settings)["project"] == {
        "name": "workspace", "kind": "docs", "signals": ["config.toml: projects"],
    }
    assert session_json(state)["project"]["kind"] == "web"
    openbot = {"name": "OpenBot agents", "kind": "other", "signals": []}
    state.host = Host(app="openbot", confidence=1.0)
    assert session_json(state, settings)["project"] == openbot
    state.host = None
    state.source = "openbot"
    assert session_json(state, settings)["project"] == openbot
