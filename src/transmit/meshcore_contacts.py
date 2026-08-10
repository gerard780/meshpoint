"""Parse MeshCore companion contact-list command results.

``meshcore.commands.get_contacts()`` returns ``None`` on its own
timeout, an ERROR ``Event`` when the companion rejects, or a
CONTACTS ``Event`` whose ``payload`` shape varies by firmware.
This module owns that defensive parse so MeshCoreTxClient stays thin.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MeshcoreContactParser:
    """Normalize and extract contact rows from a get_contacts result."""

    @staticmethod
    def normalize_payload(payload: Any) -> list[dict]:
        """Accept both dict-keyed-by-pubkey and list formats.

        Defensively filters values to dicts only. Some firmware
        revisions return mixed int/string values alongside contact
        dicts; non-dicts are dropped so shape drift cannot crash
        callers.
        """
        if isinstance(payload, dict):
            return [v for v in payload.values() if isinstance(v, dict)]
        if isinstance(payload, list):
            return [e for e in payload if isinstance(e, dict)]
        return []

    @classmethod
    def from_command_result(cls, result: Any) -> list[dict]:
        """Turn a library get_contacts return value into contact rows.

        ``None`` (library timeout) and ERROR events become ``[]`` with
        a warning. Valid payloads become ``{index, name, public_key,
        last_seen}`` rows.
        """
        if result is None:
            logger.warning(
                "get_contacts: companion returned no event "
                "(busy or timed out)"
            )
            return []

        if cls._is_error_event(result):
            detail = cls._error_detail(result)
            logger.warning(
                "get_contacts: companion error%s",
                f" ({detail})" if detail else "",
            )
            return []

        entries = cls.normalize_payload(getattr(result, "payload", None))
        return cls._entries_to_contacts(entries)

    @staticmethod
    def _is_error_event(result: Any) -> bool:
        try:
            from meshcore import EventType
        except Exception:
            return False
        event_type = getattr(result, "type", None)
        return event_type == EventType.ERROR

    @staticmethod
    def _error_detail(result: Any) -> str:
        payload = getattr(result, "payload", None)
        if not isinstance(payload, dict):
            return ""
        return str(
            payload.get("reason") or payload.get("error") or payload
        )

    @staticmethod
    def _entries_to_contacts(entries: list[dict]) -> list[dict]:
        contacts: list[dict] = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            try:
                name = entry.get("adv_name") or entry.get("name") or ""
                pk = entry.get("public_key", "")
                if name and pk:
                    contacts.append({
                        "index": i,
                        "name": name,
                        "public_key": pk,
                        "last_seen": entry.get("lastmod", 0),
                    })
            except Exception:
                logger.debug(
                    "get_contacts: skipping malformed entry at index %d",
                    i,
                    exc_info=True,
                )
        return contacts
