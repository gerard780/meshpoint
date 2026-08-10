"""Native Reticulum/LXMF messaging -- meshpoint's own LXMF delivery
destination, verified against reticulum-meshchat's approach.

Attaches to the local ``rnsd`` shared instance as a client (never opens
the RNode/TCP interfaces itself) -- see ``config.ReticulumConfig``'s
docstring for why that ordering matters and why this whole service is
opt-in. The one architectural fact worth restating here: ``RNS.Reticulum()``
auto-detects a local shared instance and attaches to it if one is
already running; if not, it falls back to reading ``~/.reticulum/config``
and bringing up whatever interfaces are configured there itself, which
is the exact scenario this service must never trigger by starting
before rnsd. Confirmed live on the deployment Pi (rnsd running, a
throwaway client script attached and exchanged a real LXMF message with
meshchat.py) before this was written -- see
memory/project_m1_meshpoint.md for that verification.

Message history reuses the existing ``messages`` table
(protocol='reticulum'); only the peer roster (built from announces) is
a new table, since Reticulum has nothing like Meshtastic/MeshCore's
NodeInfo packet to enrich ``nodes`` from.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import RNS
    import LXMF
except ImportError:  # not installed -- e.g. Mac dev environment
    RNS = None
    LXMF = None

from src.api.websocket_manager import WebSocketManager
from src.storage.message_repository import MessageRepository
from src.storage.reticulum_peer_repository import ReticulumPeerRepository

_ANNOUNCE_ASPECTS = ("lxmf.delivery", "lxmf.propagation", "nomadnetwork.node")


class _AnnounceHandler:
    """Bridges RNS.Transport's announce callback (fired on RNS's own
    thread, one instance per aspect since aspect_filter is per-handler,
    not passed into the callback -- same shape as reticulum-meshchat's
    own AnnounceHandler) into LxmfService._on_announce."""

    def __init__(self, aspect_filter: str, on_announce):
        self.aspect_filter = aspect_filter
        self._on_announce = on_announce

    def received_announce(
        self, destination_hash, announced_identity, app_data,
        announce_packet_hash=None,
    ) -> None:
        self._on_announce(self.aspect_filter, destination_hash, app_data)


class LxmfService:
    """One LXMF delivery destination for meshpoint itself, backed by a
    persisted Identity. start()/stop() follow the same shape as every
    other companion service wired in server.py's lifespan."""

    def __init__(
        self,
        display_name: str,
        identity_path: str,
        lxmf_storage_dir: str,
        message_repo: MessageRepository,
        peer_repo: ReticulumPeerRepository,
        ws_manager: WebSocketManager,
    ):
        self._display_name = display_name
        self._identity_path = Path(identity_path)
        self._lxmf_storage_dir = lxmf_storage_dir
        self._message_repo = message_repo
        self._peer_repo = peer_repo
        self._ws_manager = ws_manager
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._router = None
        self._source = None
        self._identity = None

    @property
    def available(self) -> bool:
        """False when rns/lxmf aren't installed -- lets server.py log a
        clear reason instead of crashing startup when a user enables
        this before running `pip install -r requirements.txt`."""
        return RNS is not None and LXMF is not None

    @property
    def own_address(self) -> Optional[str]:
        return RNS.prettyhexrep(self._source.hash) if self._source else None

    async def start(self) -> None:
        if not self.available:
            logger.warning(
                "reticulum.enabled is true but rns/lxmf are not installed -- "
                "run `pip install -r requirements.txt` on the Pi. Skipping "
                "Reticulum companion startup."
            )
            return

        self._loop = asyncio.get_running_loop()

        # RNS.Reticulum() blocks briefly while it probes for a local
        # shared instance -- off the event loop so it can't stall
        # startup of everything else.
        reticulum = await self._loop.run_in_executor(None, RNS.Reticulum)
        logger.info(
            "Reticulum instance ready (config dir: %s)", reticulum.configdir
        )

        self._identity_path.parent.mkdir(parents=True, exist_ok=True)
        if self._identity_path.exists():
            self._identity = RNS.Identity.from_file(str(self._identity_path))
            logger.info("Reticulum: loaded identity from %s", self._identity_path)
        else:
            self._identity = RNS.Identity()
            self._identity.to_file(str(self._identity_path))
            logger.info(
                "Reticulum: generated new identity at %s", self._identity_path
            )

        self._router = LXMF.LXMRouter(storagepath=self._lxmf_storage_dir)
        self._source = self._router.register_delivery_identity(
            self._identity, display_name=self._display_name,
        )
        self._router.register_delivery_callback(self._on_lxmf_message)

        for aspect in _ANNOUNCE_ASPECTS:
            RNS.Transport.register_announce_handler(
                _AnnounceHandler(aspect, self._on_announce)
            )

        self._source.announce()
        logger.info(
            "Reticulum LXMF service started -- address %s", self.own_address
        )

    async def stop(self) -> None:
        # Neither RNS nor LXMF expose a clean per-client detach -- process
        # exit is how meshchat.py itself relies on state being flushed too.
        self._router = None
        self._source = None

    def _on_announce(
        self, aspect: str, destination_hash: bytes, app_data: Optional[bytes],
    ) -> None:
        display_name = ""
        if app_data:
            try:
                display_name = LXMF.display_name_from_app_data(app_data) or ""
            except Exception:
                display_name = ""
        dest_hex = RNS.hexrep(destination_hash, delimit=False)
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_announce(dest_hex, display_name, aspect), self._loop,
            )

    async def _handle_announce(
        self, destination_hash: str, display_name: str, aspect: str,
    ) -> None:
        await self._peer_repo.record_announce(destination_hash, display_name, aspect)
        await self._ws_manager.broadcast(
            "reticulum_peer",
            {
                "destination_hash": destination_hash,
                "display_name": display_name,
                "aspect": aspect,
            },
        )

    def _on_lxmf_message(self, message) -> None:
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_inbound_message(message), self._loop,
            )

    async def _handle_inbound_message(self, message) -> None:
        source_hex = RNS.hexrep(message.source_hash, delimit=False)
        text = (
            message.content.decode("utf-8", errors="replace")
            if message.content else ""
        )
        packet_id = message.hash.hex() if getattr(message, "hash", None) else ""
        peers = await self._peer_repo.list_peers()
        name = next(
            (p.display_name for p in peers if p.destination_hash == source_hex), "",
        )
        row_id, is_duplicate = await self._message_repo.save_received(
            text=text, node_id=source_hex, node_name=name,
            protocol="reticulum", packet_id=packet_id,
        )
        if is_duplicate:
            return
        await self._ws_manager.broadcast(
            "reticulum_message",
            {
                "id": row_id, "direction": "received", "text": text,
                "node_id": source_hex, "node_name": name,
            },
        )

    async def send_message(self, destination_hash_hex: str, text: str) -> int:
        """Sends a direct LXMF message. Raises ValueError if the
        destination hasn't announced yet (its public key is unknown --
        the same real constraint reticulum-meshchat's own UI has)."""
        if not self.available or self._router is None or self._source is None:
            raise RuntimeError("Reticulum service is not running")

        dest_hash = bytes.fromhex(destination_hash_hex)
        identity = RNS.Identity.recall(dest_hash)
        if identity is None:
            raise ValueError(
                "Unknown destination -- no announce received from this peer yet"
            )

        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE,
            "lxmf", "delivery",
        )
        lxm = LXMF.LXMessage(
            destination, self._source, text, desired_method=LXMF.LXMessage.DIRECT,
        )
        self._router.handle_outbound(lxm)

        peers = await self._peer_repo.list_peers()
        name = next(
            (p.display_name for p in peers
             if p.destination_hash == destination_hash_hex), "",
        )
        row_id = await self._message_repo.save_sent(
            text=text, node_id=destination_hash_hex, node_name=name,
            protocol="reticulum",
        )
        return row_id

    async def list_peers(self):
        return await self._peer_repo.list_peers()
