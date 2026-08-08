#!/usr/bin/env python3
"""One-time cleanup: merge "!"-prefixed node_id rows that got forked before
server.py's prefix-normalization fix existed (_touch_node_from_packet and
_upsert_node both used to write Packet.source_id / a heartbeat's node_id
verbatim -- some of which carry a leading "!" that Node.node_id never
does for the same physical node).

The live fix stops NEW splits from happening; it does nothing for splits
that already exist in the database. This merges those in, once.

Safe to re-run: once there are no more "!"-prefixed rows left, it's a
no-op. Only ever touches the nodes table -- packets are left as-is (their
source_id/destination_id already get normalized at read-time by both the
server's API responses and the dashboard's own lookups, so there's
nothing there that actually needs fixing).

Usage:
    python3 merge_duplicate_nodes.py [--db local_meshradar.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from server import _connect  # noqa: E402


def _pick(a, b):
    """Prefer a's value, falling back to b's, treating '' as missing too."""
    if a not in (None, ""):
        return a
    return b


def merge_duplicates(db_path: str, dry_run: bool = False) -> int:
    conn = _connect(db_path)
    prefixed_rows = conn.execute(
        "SELECT * FROM nodes WHERE node_id LIKE '!%'"
    ).fetchall()

    merged = 0
    for row in prefixed_rows:
        p = dict(row)
        device_id = p["device_id"]
        real_id = p["node_id"][1:]

        target_row = conn.execute(
            "SELECT * FROM nodes WHERE device_id = ? AND node_id = ?",
            (device_id, real_id),
        ).fetchone()

        if dry_run:
            action = "merge into existing row" if target_row else "rename in place (no target)"
            print(f"  ({device_id}, {p['node_id']!r}) -> ({device_id}, {real_id!r})  [{action}]")
            merged += 1
            continue

        if target_row is None:
            conn.execute(
                "UPDATE nodes SET node_id = ? WHERE device_id = ? AND node_id = ?",
                (real_id, device_id, p["node_id"]),
            )
            merged += 1
            continue

        t = dict(target_row)
        long_name = _pick(p["long_name"], t["long_name"])
        short_name = _pick(p["short_name"], t["short_name"])
        display_name = long_name or short_name or _pick(t["display_name"], p["display_name"]) or real_id
        last_heard = max(p["last_heard"] or "", t["last_heard"] or "") or None
        # Whichever row's last_heard is more recent has the fresher signal.
        newer = p if (p["last_heard"] or "") >= (t["last_heard"] or "") else t

        conn.execute(
            """
            UPDATE nodes SET
                long_name = ?, short_name = ?, display_name = ?,
                hardware_model = ?, firmware_version = ?, role = ?, public_key = ?,
                latitude = ?, longitude = ?, altitude = ?, has_position = ?,
                last_heard = ?, packet_count = ?,
                latest_signal_json = ?, latest_telemetry_json = ?
            WHERE device_id = ? AND node_id = ?
            """,
            (
                long_name, short_name, display_name,
                _pick(p["hardware_model"], t["hardware_model"]),
                _pick(p["firmware_version"], t["firmware_version"]),
                _pick(p["role"], t["role"]),
                _pick(p["public_key"], t["public_key"]),
                p["latitude"] if p["latitude"] is not None else t["latitude"],
                p["longitude"] if p["longitude"] is not None else t["longitude"],
                p["altitude"] if p["altitude"] is not None else t["altitude"],
                p["has_position"] or t["has_position"],
                last_heard,
                (p["packet_count"] or 0) + (t["packet_count"] or 0),
                newer["latest_signal_json"],
                _pick(p["latest_telemetry_json"], t["latest_telemetry_json"]),
                device_id, real_id,
            ),
        )
        conn.execute(
            "DELETE FROM nodes WHERE device_id = ? AND node_id = ?",
            (device_id, p["node_id"]),
        )
        merged += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(Path(__file__).parent / "local_meshradar.db"))
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    if args.dry_run:
        print("Dry run:")
    count = merge_duplicates(args.db, dry_run=args.dry_run)
    verb = "Would merge" if args.dry_run else "Merged"
    print(f"{verb} {count} '!'-prefixed duplicate node row(s).")


if __name__ == "__main__":
    main()
