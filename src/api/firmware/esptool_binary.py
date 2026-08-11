"""Resolve the esptool binary for flash subprocesses."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

# esptool 4.x uses underscore subcommands (``write_flash``). The hyphen
# form (``write-flash``) is esptool 5+ only and silently fails on 4.7.x
# with an unrecognized-command exit — which is what RC users hit when
# the UI looked "done" but the board stayed on the old companion build.
WRITE_FLASH_SUBCOMMAND = "write_flash"


class EspToolBinaryResolver:
    """Prefer venv-local esptool next to ``sys.executable``, else PATH.

    Do not ``Path.resolve()`` the interpreter first: on Linux a venv
    ``python`` is often a symlink into ``/usr/bin``, which would make
    sibling lookup miss ``venv/bin/esptool``.

    When no console script is present but the package is installed,
    fall back to ``python -m esptool`` so flash still works after a
    plain ``pip install esptool`` without a wrapper on PATH.
    """

    _CANDIDATES = ("esptool", "esptool.py", "esptool.exe")

    def resolve_path(self) -> Optional[str]:
        """Absolute path to an esptool executable, or None."""
        bin_dir = Path(sys.executable).parent
        for name in self._CANDIDATES:
            sibling = bin_dir / name
            if sibling.is_file():
                return str(sibling)
        return shutil.which("esptool") or shutil.which("esptool.py")

    def resolve_argv(self) -> list[str]:
        """Argv prefix for ``asyncio.create_subprocess_exec``."""
        path = self.resolve_path()
        if path:
            return [path]
        return [sys.executable, "-m", "esptool"]

    def resolve(self) -> str:
        """Legacy single-token path (tests / display). Prefer ``resolve_argv``."""
        path = self.resolve_path()
        if path:
            return path
        return "esptool"

    def missing_install_hint(self) -> Optional[str]:
        """Human-readable fix if neither binary nor module is available."""
        if self.resolve_path() is not None:
            return None
        try:
            import esptool  # noqa: F401
        except ImportError:
            return (
                "esptool is not installed in the Meshpoint venv. "
                "Run: sudo /opt/meshpoint/venv/bin/pip install "
                "'esptool>=4.7.0,<5' && sudo systemctl restart meshpoint"
            )
        return None
