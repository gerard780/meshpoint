#!/usr/bin/env python3
"""Remove all LoRaWAN packet rows from the packets table.

Covers every LoRaWAN packet_type in one go (Join-Request, Join-Accept,
Data Up, Rejoin-Request) -- they all share protocol 'lorawan' in the
packets table (see src/decode/lorawan_decoder.py). The LoRaWAN page's
Devices list is derived live from this table (DISTINCT-style aggregation
in src/api/routes/lorawan_routes.py, no separate devices table), so
clearing it also resets that view -- nothing orphaned elsewhere, same
reasoning as clear_pager_packets.py/clear_dapnet_packets.py.

Usage (on the Pi):
    # dry run - shows how many rows would be removed, writes nothing
    python3 clear_lorawan_packets.py

    # apply
    sudo python3 clear_lorawan_packets.py --apply
"""

import argparse
import sqlite3
import sys

DB_PATH = "/opt/meshpoint/data/concentrator.db"

_WHERE = "protocol = 'lorawan'"
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
            print("No LoRaWAN packet rows found.")
            return 0

        if not args.apply:
            print(
                f"Dry run: {count} LoRaWAN packet row(s) would be removed. "
                "Re-run with --apply to actually delete."
            )
            return 0

        con.execute(_DELETE_SQL)
        con.commit()
        print(f"Removed {count} LoRaWAN packet row(s).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
