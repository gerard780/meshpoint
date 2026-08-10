"""NDJSON subprocess streaming for esptool flash endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional


class EspToolNdjsonStreamer:
    """Encode NDJSON events and stream a subprocess stdout/stderr as NDJSON."""

    def ndjson(self, payload: dict) -> bytes:
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    async def stream_subprocess(self, cmd: list[str]) -> AsyncIterator[bytes]:
        yield self.ndjson({"type": "started", "cmd": cmd})
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as exc:
            yield self.ndjson({
                "type": "result",
                "result": {"returncode": -1, "success": False, "error": str(exc)},
            })
            return

        queue: asyncio.Queue = asyncio.Queue()

        async def pump(stream: Optional[asyncio.StreamReader], name: str) -> None:
            if stream is not None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    await queue.put({
                        "type": "line",
                        "stream": name,
                        "text": line.decode("utf-8", errors="replace").rstrip("\n"),
                    })
            await queue.put(None)

        stdout_task = asyncio.create_task(pump(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(pump(process.stderr, "stderr"))

        pending = 2
        while pending:
            item = await queue.get()
            if item is None:
                pending -= 1
                continue
            yield self.ndjson(item)

        await stdout_task
        await stderr_task
        returncode = await process.wait()
        yield self.ndjson({
            "type": "result",
            "result": {"returncode": returncode, "success": returncode == 0},
        })
