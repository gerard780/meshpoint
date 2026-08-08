#!/usr/bin/env python3
"""One-off backfill: import a real Meshpoint's own concentrator.db history
into this local_meshradar server's database.

Meshpoint's own SQLite schema (src/storage/database.py) and this tool's
schema (server.py's init_db) were both derived independently from the same
Packet/Node/Telemetry shapes, so the column mapping here is close to
1:1 -- the only fields the real DB never stores at all are coding_rate and
signal_quality_percent (left NULL below, not a data-loss bug) and
hop_count/has_position/display_name (all trivially derivable).

This only ever reads the source database -- nothing here modifies your
real Meshpoint install. Runs anywhere with just Python's stdlib (no
Meshpoint dependencies, same as server.py itself), so there's no need to
have the main Meshpoint app installed on whichever machine runs this.

Usage:
    python3 import_concentrator_db.py \\
        --source /path/to/concentrator.db \\
        --device-id <the real Meshpoint's own device_id from local.yaml> \\
        [--target local_meshradar.db] [--dry-run]

Re-running this against the same target WILL duplicate packet rows --
there's no natural unique key to de-dupe against (packet_id/timestamp
pairs from real mesh traffic aren't guaranteed unique over long capture
windows). Use --dry-run first, and don't run it twice against the same
target unless you mean to.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from server import init_db, _upsert_node  # noqa: E402


def _open_source(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _open_target(path: str) -> sqlite3.Connection:
    init_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_signal(source_conn: sqlite3.Connection, node_id: str) -> dict | None:
    row = source_conn.execute(
        "SELECT rssi, snr, frequency_mhz, spreading_factor, bandwidth_khz, timestamp "
        "FROM packets WHERE source_id = ? AND rssi IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _latest_telemetry(source_conn: sqlite3.Connection, node_id: str) -> dict | None:
    row = source_conn.execute(
        "SELECT battery_level, voltage, temperature, humidity, barometric_pressure, "
        "channel_utilization, air_util_tx, uptime_seconds, timestamp "
        "FROM telemetry WHERE node_id = ? ORDER BY timestamp DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def import_nodes(
    source_conn: sqlite3.Connection, target_conn: sqlite3.Connection, device_id: str,
) -> int:
    rows = source_conn.execute("SELECT * FROM nodes").fetchall()
    for row in rows:
        node = dict(row)
        node_id = node["node_id"]
        node_for_upsert = {
            **node,
            "display_name": node.get("long_name") or node.get("short_name") or node_id,
            "has_position": node.get("latitude") is not None and node.get("longitude") is not None,
            "latest_signal": _latest_signal(source_conn, node_id),
            "latest_telemetry": _latest_telemetry(source_conn, node_id),
        }
        _upsert_node(target_conn, device_id, node_for_upsert, node.get("last_heard") or "")
    target_conn.commit()
    return len(rows)


def _insert_packet_batch(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO packets (
            device_id, packet_id, source_id, destination_id, protocol,
            packet_type, hop_limit, hop_start, hop_count, channel_hash,
            want_ack, via_mqtt, relay_node, decoded_payload_json,
            decrypted, capture_source, timestamp,
            rssi, snr, frequency_mhz, spreading_factor, bandwidth_khz,
            coding_rate, signal_quality_percent, received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )


def import_packets(
    source_conn: sqlite3.Connection, target_conn: sqlite3.Connection, device_id: str,
    batch_size: int = 2000,
) -> int:
    cursor = source_conn.execute("SELECT * FROM packets ORDER BY timestamp ASC")
    total = 0
    batch: list[tuple] = []
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            p = dict(row)
            hop_start = p.get("hop_start") or 0
            hop_limit = p.get("hop_limit") or 0
            hop_count = (hop_start - hop_limit) if hop_start > 0 else 0
            # received_at is backdated to the packet's own real timestamp,
            # not import time -- keeps the historical feed in true
            # chronological order instead of bunching everything "now".
            batch.append((
                device_id, p.get("packet_id"), p.get("source_id"), p.get("destination_id"),
                p.get("protocol"), p.get("packet_type"), hop_limit, hop_start, hop_count,
                p.get("channel_hash"), p.get("want_ack"), p.get("via_mqtt"), p.get("relay_node"),
                p.get("decoded_payload"), p.get("decrypted"), p.get("capture_source"),
                p.get("timestamp"), p.get("rssi"), p.get("snr"), p.get("frequency_mhz"),
                p.get("spreading_factor"), p.get("bandwidth_khz"), None, None,
                p.get("timestamp"),
            ))
        _insert_packet_batch(target_conn, batch)
        total += len(batch)
        print(f"  ...{total} packets imported", end="\r", flush=True)
        batch = []
    target_conn.commit()
    print()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="path to the real Meshpoint's concentrator.db")
    parser.add_argument("--target", default=str(Path(__file__).parent / "local_meshradar.db"))
    parser.add_argument(
        "--device-id", required=True,
        help="the real Meshpoint's device_id (config/local.yaml -> device: device_id), "
             "so backfilled history attaches to the same device already live in local_meshradar",
    )
    parser.add_argument("--dry-run", action="store_true", help="report counts only, write nothing")
    parser.add_argument(
        "--nodes-only", action="store_true",
        help="re-import node identities only, skip packets -- safe to re-run repeatedly "
             "(node upserts are idempotent; packet re-import is not, see the caveat above)",
    )
    args = parser.parse_args()

    if not Path(args.source).exists():
        print(f"Source database not found: {args.source}")
        sys.exit(1)

    source_conn = _open_source(args.source)

    if args.dry_run:
        node_count = source_conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        packet_count = source_conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        print(f"Dry run -- would import {node_count} nodes and {packet_count} packets "
              f"into {args.target} under device_id={args.device_id}. Nothing written.")
        return

    target_conn = _open_target(args.target)
    start = time.monotonic()

    print(f"Importing nodes from {args.source} ...")
    node_count = import_nodes(source_conn, target_conn, args.device_id)
    print(f"  {node_count} nodes imported")

    if args.nodes_only:
        print("--nodes-only set, skipping packets.")
    else:
        print(f"Importing packets from {args.source} ...")
        packet_count = import_packets(source_conn, target_conn, args.device_id)
        print(f"  {packet_count} packets imported")

    elapsed = time.monotonic() - start
    print(f"Done in {elapsed:.1f}s. Restart local_meshradar's server (or just refresh "
          f"the dashboard) to see the backfilled history.")

    source_conn.close()
    target_conn.close()


if __name__ == "__main__":
    main()
