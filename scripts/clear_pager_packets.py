#!/usr/bin/env python3
"""Remove all emergency pager (ch9 FSK) packet rows from the packets table.

Covers both Inbox and Outbox rows in one go -- both received and sent
pager messages are stored as protocol 'pager' in the packets table (see
src/api/routes/emergency_pager_routes.py; Inbox vs Outbox is distinguished
by source_id, not a separate table), so clearing by protocol wipes both.
One-way-at-a-time broadcast traffic, not mesh nodes, so it never touches
the nodes/telemetry tables -- safe to wipe wholesale, same reasoning as
clear_dapnet_packets.py.

Usage (on the Pi):
    # dry run - shows how many rows would be removed, writes nothing
    python3 clear_pager_packets.py

    # apply
    sudo python3 clear_pager_packets.py --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

_WHERE = "protocol = 'pager'"
_COUNT_SQL = f"SELECT COUNT(*) FROM packets WHERE {_WHERE}"
_DELETE_SQL = f"DELETE FROM packets WHERE {_WHERE}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=DB_PATH)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete the rows (default: dry run only).",
    )
    args = parser.parse_args()

    con = sqlite3.connect(args.db_path)
    try:
        count = con.execute(_COUNT_SQL).fetchone()[0]
        if count == 0:
            print("No pager packet rows found.")
            return 0

        if not args.apply:
            print(
                f"Dry run: {count} pager packet row(s) would be removed. "
                "Re-run with --apply to actually delete."
            )
            return 0

        con.execute(_DELETE_SQL)
        con.commit()
        print(f"Removed {count} pager packet row(s).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
