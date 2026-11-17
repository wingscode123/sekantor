"""PyInstaller entry for sekantor-hub.exe (windowed): `sekantor up` with no console window.

A windowed PyInstaller exe has no stdout or stderr (both None). Click, logging and uvicorn's formatter
(which calls sys.stderr.isatty()) expect streams, so point them at the null device; `up --log-file`
replaces them with the log when the service starts the hub.
"""

import os
import sys

for name in ("stdout", "stderr"):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))

from sekantor.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
