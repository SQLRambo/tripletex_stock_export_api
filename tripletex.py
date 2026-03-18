"""
Tripletex API functions for fetching products and inventory.
"""

import csv
import io
from datetime import date, datetime, timedelta
import requests

BASE_URL = "https://tripletex.no/v2"


def create_session(consumer_token, employee_token):
    resp = requests.put(
        f"{BASE_URL}/token/session/:create",
        params={
            "consumerToken": consumer_token,
            "employeeToken": employee_token,
            "expirationDate": (date.today() + timedelta(days=1)).isoformat(),
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


def _auth(session_token):
    return ("0", session_token)


def _get_all_pages(session_token, path, params=None):
    params = dict(params or {})
    params.setdefault("count", 1000)
    params["from"] = 0
    results = []
    while True:
        resp = requests.get(f"{BASE_URL}{path}", params=params, auth=_auth(session_token))
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
    products, _ = _get_all_pages(
        session_token,
        "/product",
        {"fields": "id,number,name,costExcludingVatCurrency", "isSupplierProduct": "false"},
    )
    return {p["id"]: p for p in products}


def get_inventory_by_location(session_token):
    """Returns (location_map, has_locations).
    location_map: {product_id: [(wh_number, wh_name, loc_number, loc_name, qty), ...]}
    """
    resp = requests.get(
        f"{BASE_URL}/product/inventoryLocation",
        params={"count": 1, "from": 0, "fields": "id"},
        auth=_auth(session_token),
    )
    resp.raise_for_status()
    if resp.json().get("fullResultSize", 0) == 0:
        return {}, False

    locations, _ = _get_all_pages(
        session_token,
        "/product/inventoryLocation",
        {"fields": "product(id),inventory(number,name),inventoryLocation(number,name),stockOfGoods"},
    )
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
    inventories, _ = _get_all_pages(
        session_token,
        "/inventory/inventories",
        {"dateFrom": today, "dateTo": today, "fields": "product(id),stock"},
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


def _sort_key(product):
    num = str(product.get("number") or "").strip().replace(" ", "")
    try:
        return (0, float(num), "")
    except ValueError:
        return (1, 0.0, num.lower())


def _format_number(val):
    if isinstance(val, float):
        return str(val).replace(".", ",")
    return val


def build_rows(products, qty_map, has_locations):
    """Returns (headers, rows) sorted by product number."""
    if has_locations:
        headers = [
            "Nummer", "Navn", "Kostpris (ekskl. mva)",
            "Lager nr", "Lager navn", "Lokasjon nr", "Lokasjon navn", "Antall på lager",
        ]
    else:
        headers = ["Nummer", "Navn", "Kostpris (ekskl. mva)", "Lager", "Antall på lager"]

    rows = []
    for product in sorted(products.values(), key=_sort_key):
        product_id = product["id"]
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

    return headers, rows


def generate_csv_bytes(headers, rows):
    """Returns CSV content as UTF-8 bytes with BOM (for Excel compatibility)."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(headers)
    writer.writerows([[_format_number(cell) for cell in row] for row in rows])
    return output.getvalue().encode("utf-8-sig")


def fetch_report(session_token):
    """
    Fetches products and inventory, returns (headers, rows).
    Raises requests.HTTPError on API errors.
    """
    products = get_products(session_token)
    qty_map, has_locations = get_inventory_by_location(session_token)
    if not has_locations:
        qty_map = get_inventory_by_warehouse(session_token)
    headers, rows = build_rows(products, qty_map, has_locations)
    return headers, rows


def fetch_date_report(session_token, report_date):
    """
    Fetches stock qty and value per warehouse for a specific date.
    report_date: ISO date string (YYYY-MM-DD).
    Returns (headers, rows).
    """
    products = get_products(session_token)

    inventories, _ = _get_all_pages(
        session_token,
        "/inventory/inventories",
        {"dateFrom": report_date, "dateTo": report_date, "fields": "product(id),stock"},
    )

    # Build {product_id: [(warehouse_name, qty, value), ...]}
    warehouse_map = {}
    for inv in inventories:
        product_id = inv.get("product", {}).get("id")
        if product_id is None:
            continue
        product = products.get(product_id, {})
        cost = product.get("costExcludingVatCurrency") or 0
        for entry in inv.get("stock") or []:
            qty = entry.get("closingStock") or 0
            if qty != 0:
                warehouse_name = entry.get("inventory", "")
                value = float(qty) * float(cost) if cost else 0
                warehouse_map.setdefault(product_id, []).append((warehouse_name, qty, value))

    headers = [
        "Nummer", "Navn", "Kostpris (ekskl. mva)",
        "Lager", "Antall på lager", "Lagerverdi (ekskl. mva)",
    ]
    rows = []
    for product in sorted(products.values(), key=_sort_key):
        product_id = product["id"]
        cost = product.get("costExcludingVatCurrency", "")
        number = product.get("number", "")
        name = product.get("name", "")
        warehouses = warehouse_map.get(product_id, [])
        for warehouse_name, qty, value in warehouses:
            rows.append([number, name, cost, warehouse_name, qty, value])

    return headers, rows


def csv_filename(prefix="lagerantall"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.csv"
