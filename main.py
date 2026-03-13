#!/usr/bin/env python3
"""
Tripletex Product Inventory
Fetches cost price and qty in stock for all products.
"""

import argparse
import csv
import sys
from datetime import date, datetime
import requests

BASE_URL = "https://tripletex.no/v2"


def create_session(consumer_token, employee_token):
    resp = requests.put(
        f"{BASE_URL}/token/session/:create",
        params={
            "consumerToken": consumer_token,
            "employeeToken": employee_token,
            "expirationDate": date.today().isoformat(),
        },
    )
    resp.raise_for_status()
    return resp.json()["value"]["token"]


def delete_session(session_token):
    try:
        requests.delete(
            f"{BASE_URL}/token/session/:deleteByToken",
            params={"token": session_token},
        )
    except Exception:
        pass


def auth(session_token):
    return ("0", session_token)


def get_all_pages(session_token, path, params=None):
    params = dict(params or {})
    params.setdefault("count", 1000)
    params["from"] = 0
    results = []
    while True:
        resp = requests.get(f"{BASE_URL}{path}", params=params, auth=auth(session_token))
        resp.raise_for_status()
        data = resp.json()
        values = data.get("values") or []
        results.extend(values)
        total = data.get("fullResultSize", 0)
        params["from"] += len(values)
        if not values or params["from"] >= total:
            break
    return results, data.get("fullResultSize", len(results))


def get_products(session_token):
    products, _ = get_all_pages(
        session_token,
        "/product",
        {"fields": "id,number,name,costExcludingVatCurrency", "isSupplierProduct": "false"},
    )
    return {p["id"]: p for p in products}


def get_inventory_by_location(session_token):
    """Returns (qty_map, found) where qty_map is {product_id: total_qty}."""
    resp = requests.get(
        f"{BASE_URL}/product/inventoryLocation",
        params={"count": 1, "from": 0, "fields": "id"},
        auth=auth(session_token),
    )
    resp.raise_for_status()
    full_size = resp.json().get("fullResultSize", 0)

    if full_size == 0:
        return {}, False

    locations, _ = get_all_pages(
        session_token,
        "/product/inventoryLocation",
        {"fields": "product(id),inventory(number,name),inventoryLocation(number,name),stockOfGoods"},
    )
    # {product_id: [(warehouse_number, warehouse_name, location_number, location_name, qty), ...]}
    location_map = {}
    for loc in locations:
        product_id = loc.get("product", {}).get("id")
        qty = loc.get("stockOfGoods") or 0
        if product_id is not None and qty != 0:
            inventory = loc.get("inventory") or {}
            inv_location = loc.get("inventoryLocation") or {}
            location_map.setdefault(product_id, []).append((
                inventory.get("number", ""),
                inventory.get("name", ""),
                inv_location.get("number", ""),
                inv_location.get("name", ""),
                qty,
            ))
    return location_map, True


def get_inventory_by_warehouse(session_token):
    """Returns {product_id: [(warehouse_name, qty), ...]} with only non-zero quantities."""
    today = date.today().isoformat()
    inventories, _ = get_all_pages(
        session_token,
        "/inventory/inventories",
        {
            "dateFrom": today,
            "dateTo": today,
            "fields": "product(id),stock",
        },
    )
    warehouse_map = {}
    for inv in inventories:
        product_id = inv.get("product", {}).get("id")
        if product_id is None:
            continue
        for stock_entry in inv.get("stock") or []:
            qty = stock_entry.get("closingStock") or 0
            if qty != 0:
                warehouse_name = stock_entry.get("inventory", "")
                warehouse_map.setdefault(product_id, []).append((warehouse_name, qty))
    return warehouse_map


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


def _format_csv_value(val):
    if isinstance(val, float):
        return str(val).replace(".", ",")
    return val


def write_csv(rows, headers, filename):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)
        writer.writerows([[_format_csv_value(cell) for cell in row] for row in rows])
    print(f"Saved to {filename}")


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
        help="CSV output filename (default: lagerantall.csv)",
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
        products = get_products(session_token)

        print("Fetching inventory by location...", flush=True)
        qty_map, has_locations = get_inventory_by_location(session_token)

        if not has_locations:
            print("Locations not enabled — fetching inventory by warehouse...", flush=True)
            qty_map = get_inventory_by_warehouse(session_token)

        if has_locations:
            headers = [
                "Nummer", "Navn", "Kostpris (ekskl. mva)",
                "Lager nr", "Lager navn", "Lokasjon nr", "Lokasjon navn", "Antall på lager",
            ]
        else:
            headers = ["Nummer", "Navn", "Kostpris (ekskl. mva)", "Lager", "Antall på lager"]

        def sort_key(item):
            num = str(item[1].get("number") or "").strip().replace(" ", "")
            try:
                return (0, float(num), "")
            except ValueError:
                return (1, 0.0, num.lower())

        rows = []
        for product_id, product in sorted(products.items(), key=sort_key):
            cost = product.get("costExcludingVatCurrency", "")
            cost_str = cost if cost is not None else ""
            number = product.get("number", "")
            name = product.get("name", "")

            if has_locations:
                entries = qty_map.get(product_id, [])
                if entries:
                    for wh_number, wh_name, loc_number, loc_name, qty in entries:
                        rows.append([number, name, cost_str, wh_number, wh_name, loc_number, loc_name, qty])
                else:
                    rows.append([number, name, cost_str, "", "", "", "", 0])
            else:
                warehouses = qty_map.get(product_id, [])
                if warehouses:
                    for warehouse_name, qty in warehouses:
                        rows.append([number, name, cost_str, warehouse_name, qty])
                else:
                    rows.append([number, name, cost_str, "", 0])

        print(f"\n{len(rows)} products found.\n")

        if args.output == "csv":
            base, ext = args.csv_file.rsplit(".", 1) if "." in args.csv_file else (args.csv_file, "csv")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{base}_{timestamp}.{ext}"
            write_csv(rows, headers, filename)
        else:
            print_table(rows, headers)

    finally:
        if owns_session:
            delete_session(session_token)


if __name__ == "__main__":
    main()
