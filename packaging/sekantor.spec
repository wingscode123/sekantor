# PyInstaller spec: one folder (dist/sekantor/) with two exes sharing one runtime.
#   sekantor.exe       console   the CLI (setup, doctor, stop, service, install/uninstall ...)
#   sekantor-hub.exe   windowed  `up`, started by the app and the login task without a console window
# The Claude Code hook is the native forwarder (hook/, ADR-0026): CI builds it with cargo and copies
# sekantor-hook.exe into this folder after PyInstaller, before `tauri build`.
# Build from the repo root after `npm run build` in web/:
#   uv run pyinstaller packaging/sekantor.spec --distpath dist --workpath build/pyi
# The Tauri bundle copies dist/sekantor/ into the installer (desktop/src-tauri/tauri.conf.json).
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
PKG = ROOT / "src" / "sekantor"

if not (PKG / "hub" / "static" / "index.html").is_file():
    raise SystemExit("web UI not built: run `npm ci && npm run build` in web/ first")

# Read at runtime next to the modules (Path(__file__).parent / ...), so keep the package layout.
datas = [
    (str(PKG / "hosts.yaml"), "sekantor"),
    (str(PKG / "pos" / "tmux" / "agents.yaml"), "sekantor/pos/tmux"),
    (str(PKG / "hub" / "static"), "sekantor/hub/static"),
]
# uvicorn picks its loop, protocol, websockets and lifespan modules by name at runtime.
hiddenimports = collect_submodules("sekantor") + collect_submodules("uvicorn") + collect_submodules("websockets")


def analysis(entry):
    return Analysis([str(ROOT / "packaging" / entry)], pathex=[str(ROOT / "src")], datas=datas,
                    hiddenimports=hiddenimports, excludes=["tkinter", "pytest"], noarchive=False)


def exe(a, name, console):
    return EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name=name, console=console,
               upx=False, debug=False, strip=False)


cli = analysis("entry_cli.py")
hub = analysis("entry_hub.py")

COLLECT(
    exe(cli, "sekantor", True), cli.binaries, cli.datas,
    exe(hub, "sekantor-hub", False), hub.binaries, hub.datas,
    name="sekantor", upx=False, strip=False,
)
