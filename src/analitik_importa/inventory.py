"""One stock table across own warehouse, Ozon, Wildberries and goods in transit from China.

Key = seller article (Ozon offer_id = WB vendorCode = own SKU).
Physical stock = own warehouse + Ozon FBO + WB warehouses + WB "в пути к клиенту".
Ozon FBS stock is what you *declared* from your own warehouse, so it is not added on top;
it stands in for the own warehouse only while that SKU has no moves in the local book.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from analitik_importa.config import Settings
from analitik_importa.storage import Book

STATUS_URGENT = "Срочно заказать"
STATUS_ORDER = "Пора заказать"
STATUS_OK = "В норме"
STATUS_EXCESS = "Избыток"
STATUS_NO_SALES = "Нет продаж"
STATUS_EMPTY = "Нет в наличии"

STATUS_COLOR = {
    STATUS_URGENT: "#dc2626",
    STATUS_ORDER: "#f59e0b",
    STATUS_OK: "#10b981",
    STATUS_EXCESS: "#6366f1",
    STATUS_NO_SALES: "#94a3b8",
    STATUS_EMPTY: "#64748b",
}


@dataclass
class MpSnapshot:
    fetched_at: datetime = field(default_factory=datetime.now)
    window_days: int = 30
    names: dict[str, str] = field(default_factory=dict)
    images: dict[str, str] = field(default_factory=dict)
    ozon_price: dict[str, float] = field(default_factory=dict)
    wb_price: dict[str, float] = field(default_factory=dict)
    ozon_stock: dict[str, dict[str, int]] = field(default_factory=dict)
    wb_stock: dict[str, dict[str, int]] = field(default_factory=dict)
    wb_warehouses: list[dict[str, Any]] = field(default_factory=list)
    ozon_sales: dict[str, dict[str, float]] = field(default_factory=dict)
    wb_sales: dict[str, dict[str, float]] = field(default_factory=dict)
    connected: dict[str, bool] = field(default_factory=lambda: {"ozon": False, "wb": False})
    errors: list[str] = field(default_factory=list)


def collect_ozon(snap: MpSnapshot, s: Settings) -> None:
    if not (s.ozon_client_id and s.ozon_api_key):
        return
    from analitik_importa.clients.ozon_seller import OzonSellerClient

    try:
        client = OzonSellerClient(s)
        offer_ids = [p["offer_id"] for p in client.list_products() if p.get("offer_id")]
        details = client.product_details(offer_ids) if offer_ids else []
        sku_to_offer: dict[str, str] = {}
        for d in details:
            offer = d["offer_id"]
            snap.names.setdefault(offer, d.get("name") or "")
            if d.get("image"):
                snap.images.setdefault(offer, d["image"])
            if d.get("price"):
                snap.ozon_price[offer] = d["price"]
            if d.get("sku"):
                sku_to_offer[str(d["sku"])] = offer
        snap.ozon_stock = client.stocks_by_offer()
        today = date.today()
        by_sku = client.sales_by_sku(today - timedelta(days=snap.window_days), today)
        for ozon_sku, m in by_sku.items():
            offer = sku_to_offer.get(ozon_sku)
            if offer:
                snap.ozon_sales[offer] = m
        snap.connected["ozon"] = True
    except RuntimeError as exc:
        snap.errors.append(f"Ozon: {exc}")


def collect_wb(snap: MpSnapshot, s: Settings) -> None:
    if not s.wb_api_token:
        return
    from analitik_importa.clients.wb_seller import WbSellerClient

    try:
        client = WbSellerClient(s)
        cards = client.cards()
        nm_to_sku = {c["nm_id"]: c["sku"] for c in cards}
        for c in cards:
            snap.names.setdefault(c["sku"], c["name"])
            if c.get("image"):
                snap.images.setdefault(c["sku"], c["image"])
        try:
            for nm, p in client.prices().items():
                if nm in nm_to_sku and p.get("discounted"):
                    snap.wb_price[nm_to_sku[nm]] = p["discounted"]
        except RuntimeError as exc:
            snap.errors.append(f"WB цены: {exc}")
        rows = client.stocks()
        snap.wb_warehouses = rows
        for r in rows:
            agg = snap.wb_stock.setdefault(r["sku"], {"qty": 0, "to_client": 0, "from_client": 0})
            agg["qty"] += r["qty"]
            agg["to_client"] += r["to_client"]
            agg["from_client"] += r["from_client"]
        for sale in client.sales(snap.window_days):
            agg = snap.wb_sales.setdefault(sale["sku"], {"units": 0.0, "revenue": 0.0})
            sign = -1 if sale["is_return"] else 1
            agg["units"] += sign
            agg["revenue"] += sign * sale["price"]
        snap.connected["wb"] = True
    except RuntimeError as exc:
        snap.errors.append(f"Wildberries: {exc}")


def collect_snapshot(s: Settings, window_days: int | None = None) -> MpSnapshot:
    snap = MpSnapshot(window_days=window_days or s.sales_window_days)
    collect_ozon(snap, s)
    collect_wb(snap, s)
    return snap


def classify(per_day: float, physical: int, transit: int, lead: int, safety: int, cover: int) -> tuple[str, int, float | None]:
    """Status, units to order now and days of cover for one SKU."""
    if per_day <= 0:
        return (STATUS_EMPTY if physical <= 0 else STATUS_NO_SALES), 0, None
    days = physical / per_day
    with_transit = (physical + transit) / per_day
    need = math.ceil(per_day * (lead + safety + cover) - (physical + transit))
    if with_transit < lead:
        return STATUS_URGENT, max(need, 0), days
    if with_transit < lead + safety:
        return STATUS_ORDER, max(need, 0), days
    if days > lead + 2 * cover:
        return STATUS_EXCESS, 0, days
    return STATUS_OK, 0, days


def build_inventory(book: Book, snap: MpSnapshot, s: Settings) -> list[dict[str, Any]]:
    if snap.names:
        book.sync_names(snap.names)
    own = book.own_stock()
    transit = book.in_transit()
    products = {p["sku"]: p for p in book.products()}
    skus = set(products) | set(own) | set(snap.ozon_stock) | set(snap.wb_stock) | set(transit)

    rows = []
    for sku in sorted(skus):
        p = products.get(sku, {})
        if p and not p.get("active", 1):
            continue
        oz = snap.ozon_stock.get(sku, {})
        wb = snap.wb_stock.get(sku, {})
        tracked = sku in own
        own_qty = own[sku] if tracked else max(oz.get("fbs", 0), 0)
        physical = own_qty + oz.get("fbo", 0) + wb.get("qty", 0) + wb.get("to_client", 0)
        oz_units = snap.ozon_sales.get(sku, {}).get("units", 0.0)
        wb_units = snap.wb_sales.get(sku, {}).get("units", 0.0)
        per_day = max(0.0, (oz_units + wb_units) / snap.window_days)
        lead = int(p.get("lead_time_days") or s.lead_time_days)
        safety = int(p.get("safety_days") if p.get("safety_days") is not None else s.safety_days)
        cover = int(p.get("cover_days") or s.cover_days)
        status, order_qty, days = classify(per_day, physical, transit.get(sku, 0), lead, safety, cover)
        cost = float(p.get("cost_rub") or 0)
        price = snap.ozon_price.get(sku) or snap.wb_price.get(sku)

        mp_stock = oz.get("fbo", 0) + oz.get("fbs", 0) + wb.get("qty", 0)
        action = ""
        if own_qty > 0 and per_day > 0 and mp_stock / per_day < 14:
            action = "Отгрузить на МП"
        elif order_qty:
            action = f"Заказать {order_qty} шт"

        rows.append(
            {
                "sku": sku,
                "name": p.get("name") or snap.names.get(sku, ""),
                "image": snap.images.get(sku),
                "own": own_qty,
                "own_source": "складской учёт" if tracked else ("по FBS Ozon" if oz.get("fbs") else "—"),
                "ozon_fbo": oz.get("fbo", 0),
                "ozon_fbs": oz.get("fbs", 0),
                "ozon_reserved": oz.get("fbo_reserved", 0) + oz.get("fbs_reserved", 0),
                "wb": wb.get("qty", 0),
                "wb_to_client": wb.get("to_client", 0),
                "physical": physical,
                "in_transit": transit.get(sku, 0),
                "sales_ozon": oz_units,
                "sales_wb": wb_units,
                "per_day": round(per_day, 2),
                "days_cover": round(days, 0) if days is not None else None,
                "lead_time": lead,
                "status": status,
                "order_qty": order_qty,
                "action": action,
                "cost_rub": cost,
                "price": price,
                "value_cost": round(physical * cost, 2),
                "value_retail": round(physical * price, 2) if price else None,
            }
        )
    return rows
