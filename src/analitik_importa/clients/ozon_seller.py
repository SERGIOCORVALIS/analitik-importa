from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from analitik_importa.config import Settings, get_settings

BASE_URL = "https://api-seller.ozon.ru"


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_url(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value or None


class OzonSellerClient:
    """Ozon Seller API — data of the seller's own store only (not category-wide demand)."""

    def __init__(self, settings: Settings | None = None, timeout: float = 30.0) -> None:
        self.settings = settings or get_settings()
        self.settings.require_ozon_seller()
        self._timeout = timeout

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Client-Id": self.settings.ozon_client_id,
            "Api-Key": self.settings.ozon_api_key,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(f"{BASE_URL}{path}", headers=headers, json=body)
        if response.status_code == 429:
            raise RuntimeError("Ozon Seller API rate limited (429).")
        if response.status_code >= 400:
            raise RuntimeError(f"Ozon Seller HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    def seller_info(self) -> dict[str, Any]:
        return self._post("/v1/seller/info", {})

    def list_products(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        """All products across pages (visibility=ALL)."""
        items: list[dict[str, Any]] = []
        last_id = ""
        while True:
            data = self._post(
                "/v3/product/list",
                {"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": min(limit, 1000)},
            )
            result = data.get("result") or {}
            page = result.get("items") or []
            items.extend(page)
            last_id = result.get("last_id") or ""
            if not page or not last_id or len(items) >= limit:
                return items[:limit]

    def product_details(self, offer_ids: list[str]) -> list[dict[str, Any]]:
        """Name, price, status and stock per product, flattened for tables."""
        rows: list[dict[str, Any]] = []
        for start in range(0, len(offer_ids), 1000):
            data = self._post("/v3/product/info/list", {"offer_id": offer_ids[start : start + 1000]})
            for item in data.get("items") or []:
                stocks = (item.get("stocks") or {}).get("stocks") or []
                statuses = item.get("statuses") or {}
                price = _to_float(item.get("price"))
                present = sum(int(s.get("present") or 0) for s in stocks)
                rows.append(
                    {
                        "image": _first_url(item.get("primary_image")) or _first_url(item.get("images")),
                        "name": item.get("name"),
                        "offer_id": item.get("offer_id"),
                        "sku": item.get("sku"),
                        "price": price,
                        "old_price": _to_float(item.get("old_price")),
                        "currency": item.get("currency_code"),
                        "status": statuses.get("status_name"),
                        "moderation": statuses.get("moderate_status"),
                        "stock_present": present,
                        "stock_reserved": sum(int(s.get("reserved") or 0) for s in stocks),
                        "stock_value": price * present if price is not None else None,
                        "stock_sources": ", ".join(sorted({str(s.get("source")).upper() for s in stocks})),
                        "archived": bool(item.get("is_archived") or item.get("is_autoarchived")),
                        "created_at": item.get("created_at"),
                    }
                )
        return rows

    def stocks_by_offer(self) -> dict[str, dict[str, int]]:
        """offer_id -> FBO (on Ozon warehouses) and FBS (declared from your warehouse) stock."""
        out: dict[str, dict[str, int]] = {}
        cursor = ""
        while True:
            data = self._post("/v4/product/info/stocks", {"filter": {"visibility": "ALL"}, "limit": 1000, "cursor": cursor})
            items = data.get("items") or []
            for item in items:
                row = out.setdefault(
                    item.get("offer_id") or "", {"fbo": 0, "fbo_reserved": 0, "fbs": 0, "fbs_reserved": 0}
                )
                for s in item.get("stocks") or []:
                    kind = "fbo" if str(s.get("type")).lower() == "fbo" else "fbs"
                    row[kind] += int(s.get("present") or 0)
                    row[f"{kind}_reserved"] += int(s.get("reserved") or 0)
            cursor = data.get("cursor") or ""
            if not items or not cursor:
                out.pop("", None)
                return out

    def sales_by_sku(self, d1: date, d2: date) -> dict[str, dict[str, float]]:
        """Ozon SKU -> ordered units and revenue for the period (Analytics API)."""
        out: dict[str, dict[str, float]] = {}
        offset = 0
        while True:
            data = self._post(
                "/v1/analytics/data",
                {
                    "date_from": d1.isoformat(),
                    "date_to": d2.isoformat(),
                    "metrics": ["ordered_units", "revenue"],
                    "dimension": ["sku"],
                    "limit": 1000,
                    "offset": offset,
                },
            )
            rows = (data.get("result") or {}).get("data") or []
            for r in rows:
                dims = r.get("dimensions") or [{}]
                metrics = r.get("metrics") or [0, 0]
                out[str(dims[0].get("id"))] = {"units": float(metrics[0] or 0), "revenue": float(metrics[1] or 0)}
            if len(rows) < 1000:
                return out
            offset += 1000

    def finance(self, d1: date, d2: date) -> dict[str, float]:
        """Cash-flow statement summed over the period (chunks of up to 30 days)."""
        totals = {"revenue": 0.0, "returns": 0.0, "commission": 0.0, "services": 0.0, "logistics": 0.0}
        start = d1
        while start <= d2:
            end = min(d2, start + timedelta(days=29))
            data = self._post(
                "/v1/finance/cash-flow-statement/list",
                {
                    "date": {"from": f"{start}T00:00:00.000Z", "to": f"{end}T23:59:59.000Z"},
                    "with_details": False,
                    "page": 1,
                    "page_size": 100,
                },
            )
            for cf in (data.get("result") or {}).get("cash_flows") or []:
                totals["revenue"] += float(cf.get("orders_amount") or 0)
                totals["returns"] += abs(float(cf.get("returns_amount") or 0))
                totals["commission"] += abs(float(cf.get("commission_amount") or 0))
                totals["services"] += abs(float(cf.get("services_amount") or 0))
                totals["logistics"] += abs(float(cf.get("item_delivery_and_return_amount") or 0))
            start = end + timedelta(days=1)
        return {k: round(v, 2) for k, v in totals.items()}

    def check(self) -> dict[str, Any]:
        info = self.seller_info()
        company = info.get("company") or {}
        subscription = info.get("subscription") or {}
        products = self.list_products(limit=1000)
        return {
            "ok": True,
            "company": company.get("name"),
            "subscription": subscription.get("type"),
            "products": len(products),
        }
