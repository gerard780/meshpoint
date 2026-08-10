"""Resolve the esptool binary for flash subprocesses."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


class EspToolBinaryResolver:
    """Prefer venv-local esptool next to ``sys.executable``, else PATH.

    Do not ``Path.resolve()`` the interpreter first: on Linux a venv
    ``python`` is often a symlink into ``/usr/bin``, which would make
    sibling lookup miss ``venv/bin/esptool``.
    """

    _CANDIDATES = ("esptool", "esptool.py", "esptool.exe")

    def resolve(self) -> str:
        bin_dir = Path(sys.executable).parent
        for name in self._CANDIDATES:
            sibling = bin_dir / name
            if sibling.is_file():
                return str(sibling)
        found = shutil.which("esptool") or shutil.which("esptool.py")
        if found:
            return found
        return "esptool"
