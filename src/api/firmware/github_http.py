"""Synchronous GitHub HTTP helpers for firmware download routes.

Blocking I/O only: callers must wrap in ``run_in_executor``.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path


class GithubHttpClient:
    """Minimal GitHub API / asset downloader (urllib, no extra deps)."""

    def __init__(self, json_timeout_s: float = 15.0, download_timeout_s: float = 180.0):
        self._json_timeout_s = json_timeout_s
        self._download_timeout_s = download_timeout_s

    def fetch_json_sync(self, url: str) -> object:
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=self._json_timeout_s) as resp:
            return json.loads(resp.read().decode())

    def download_to_sync(self, url: str, dest: Path) -> None:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=self._download_timeout_s) as resp, open(
            dest, "wb",
        ) as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
