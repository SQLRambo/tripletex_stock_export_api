#!/usr/bin/env python3
"""
Tripletex Product Inventory — CLI
Fetches cost price and qty in stock for all products.
"""

import argparse
import sys
import requests

from tripletex import (
    create_session, delete_session, fetch_report,
    generate_csv_bytes,
)


def print_table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def main():
    parser = argparse.ArgumentParser(
        description="Fetch cost price and stock quantity for all Tripletex products."
    )
    parser.add_argument("--consumer-key", help="Tripletex consumer token")
    parser.add_argument("--user-key", help="Tripletex employee/user token")
    parser.add_argument("--session-token", help="Tripletex session token (skips authentication)")
    parser.add_argument(
        "--output",
        choices=["table", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--csv-file",
        default="lagerantall.csv",
        help="Base CSV output filename (default: lagerantall.csv)",
    )
    args = parser.parse_args()

    if args.session_token:
        session_token = args.session_token
        owns_session = False
    elif args.consumer_key and args.user_key:
        print("Authenticating...", flush=True)
        try:
            session_token = create_session(args.consumer_key, args.user_key)
        except requests.HTTPError as e:
            print(f"Authentication failed: {e}", file=sys.stderr)
            sys.exit(1)
        owns_session = True
    else:
        print("Error: provide either --session-token or both --consumer-key and --user-key.", file=sys.stderr)
        sys.exit(1)

    try:
        print("Fetching products...", flush=True)
        print("Fetching inventory...", flush=True)
        headers, rows = fetch_report(session_token)
        print(f"\n{len(rows)} products found.\n")

        if args.output == "csv":
            base, ext = args.csv_file.rsplit(".", 1) if "." in args.csv_file else (args.csv_file, "csv")
            filename = f"{base}_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
            with open(filename, "wb") as f:
                f.write(generate_csv_bytes(headers, rows))
            print(f"Saved to {filename}")
        else:
            print_table(rows, headers)

    finally:
        if owns_session:
            delete_session(session_token)


if __name__ == "__main__":
    main()
