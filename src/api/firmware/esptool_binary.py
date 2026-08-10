"""Resolve the esptool binary for flash subprocesses."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


class EspToolBinaryResolver:
    """Prefer venv-local esptool next to ``sys.executable``, else PATH."""

    def resolve(self) -> str:
        sibling = Path(sys.executable).resolve().parent / "esptool"
        if sibling.is_file():
            return str(sibling)
        sibling_win = Path(sys.executable).resolve().parent / "esptool.exe"
        if sibling_win.is_file():
            return str(sibling_win)
        found = shutil.which("esptool")
        if found:
            return found
        return "esptool"
