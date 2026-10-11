"""Wildberries Seller API — your own store: cards, prices, stocks, sales, finance report.

One token from seller.wildberries.ru → Настройки → Доступ к API with categories
Контент, Статистика, Аналитика, Цены и скидки (read-only is enough).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from analitik_importa.config import Settings, get_settings

COMMON = "https://common-api.wildberries.ru"
CONTENT = "https://content-api.wildberries.ru"
PRICES = "https://discounts-prices-api.wildberries.ru"
STATS = "https://statistics-api.wildberries.ru"
ANALYTICS = "https://seller-analytics-api.wildberries.ru"


class WbSellerClient:
    def __init__(self, settings: Settings | None = None, timeout: float = 60.0) -> None:
        self.settings = settings or get_settings()
        self.settings.require_wb_seller()
        self._timeout = timeout

    def _request(self, method: str, url: str, *, params: dict | None = None, json: Any = None,
                 retries: int = 3) -> Any:
        headers = {"Authorization": self.settings.wb_api_token.strip()}
        for attempt in range(retries + 1):
            with httpx.Client(timeout=self._timeout) as client:
                r = client.request(method, url, headers=headers, params=params, json=json)
            if r.status_code == 429 and attempt < retries:
                time.sleep(float(r.headers.get("X-Ratelimit-Retry") or r.headers.get("Retry-After") or 20))
                continue
            if r.status_code == 401:
                raise RuntimeError("WB: токен не принят (401). Проверьте WB_API_TOKEN и его категории доступа.")
            if r.status_code == 403:
                raise RuntimeError(f"WB: у токена нет доступа к {url.split('/')[2]} (403). Добавьте категорию в токен.")
            if r.status_code >= 400:
                raise RuntimeError(f"WB HTTP {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else None
        raise RuntimeError("WB: превышен лимит запросов (429), повторите через минуту.")

    # ------------------------------------------------------------- store

    def seller_info(self) -> dict[str, Any]:
        return self._request("GET", f"{COMMON}/api/v1/seller-info") or {}

    def cards(self) -> list[dict[str, Any]]:
        """All product cards: nmID, vendorCode, title, photo."""
        out: list[dict[str, Any]] = []
        cursor: dict[str, Any] = {"limit": 100}
        while True:
            data = self._request(
                "POST",
                f"{CONTENT}/content/v2/get/cards/list",
                json={"settings": {"cursor": cursor, "filter": {"withPhoto": -1}}},
            ) or {}
            cards = data.get("cards") or []
            for c in cards:
                photos = c.get("photos") or []
                out.append(
                    {
                        "nm_id": c.get("nmID"),
                        "sku": c.get("vendorCode") or str(c.get("nmID")),
                        "name": c.get("title") or "",
                        "subject": c.get("subjectName") or "",
                        "brand": c.get("brand") or "",
                        "image": (photos[0].get("c246x328") or photos[0].get("big")) if photos else None,
                    }
                )
            nxt = data.get("cursor") or {}
            if len(cards) < cursor["limit"] or not nxt.get("nmID"):
                return out
            cursor = {"limit": 100, "updatedAt": nxt.get("updatedAt"), "nmID": nxt.get("nmID")}

    def prices(self) -> dict[int, dict[str, float]]:
        """nmID -> price before discount / discounted price."""
        out: dict[int, dict[str, float]] = {}
        offset = 0
        while True:
            data = self._request("GET", f"{PRICES}/api/v2/list/goods/filter", params={"limit": 1000, "offset": offset}) or {}
            goods = (data.get("data") or {}).get("listGoods") or []
            for g in goods:
                sizes = g.get("sizes") or [{}]
                out[g.get("nmID")] = {
                    "price": float(sizes[0].get("price") or 0),
                    "discounted": float(sizes[0].get("discountedPrice") or 0),
                }
            if len(goods) < 1000:
                return out
            offset += 1000

    def stocks(self) -> list[dict[str, Any]]:
        """Stocks on WB warehouses (FBO), one row per product × warehouse."""
        try:
            rows = self._request("GET", f"{STATS}/api/v1/supplier/stocks", params={"dateFrom": "2019-06-20T00:00:00"}) or []
            return [
                {
                    "sku": r.get("supplierArticle") or str(r.get("nmId")),
                    "nm_id": r.get("nmId"),
                    "warehouse": r.get("warehouseName"),
                    "qty": int(r.get("quantity") or 0),
                    "to_client": int(r.get("inWayToClient") or 0),
                    "from_client": int(r.get("inWayFromClient") or 0),
                    "price": float(r.get("Price") or 0),
                    "discount": float(r.get("Discount") or 0),
                }
                for r in rows
            ]
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc) and "HTTP 410" not in str(exc):
                raise
        return self._warehouse_remains()

    def _warehouse_remains(self) -> list[dict[str, Any]]:
        """Fallback: async warehouse remains report (Analytics category)."""
        task = self._request(
            "GET", f"{ANALYTICS}/api/v1/warehouse_remains", params={"groupByNm": "true", "groupBySa": "true", "groupByWarehouse": "true"}
        )
        task_id = (task or {}).get("data", {}).get("taskId")
        if not task_id:
            raise RuntimeError("WB: не удалось создать отчёт об остатках")
        for _ in range(20):
            time.sleep(5)
            status = self._request("GET", f"{ANALYTICS}/api/v1/warehouse_remains/tasks/{task_id}/status") or {}
            if (status.get("data") or {}).get("status") == "done":
                break
        rows = self._request("GET", f"{ANALYTICS}/api/v1/warehouse_remains/tasks/{task_id}/download") or []
        out = []
        for r in rows:
            for w in r.get("warehouses") or []:
                name = w.get("warehouseName") or ""
                if name.startswith("В пути") or name.startswith("Всего"):
                    continue
                out.append(
                    {
                        "sku": r.get("vendorCode") or str(r.get("nmId")),
                        "nm_id": r.get("nmId"),
                        "warehouse": name,
                        "qty": int(w.get("quantity") or 0),
                        "to_client": 0,
                        "from_client": 0,
                        "price": 0.0,
                        "discount": 0.0,
                    }
                )
        return out

    # -------------------------------------------------------------- sales

    def sales(self, days: int = 30) -> list[dict[str, Any]]:
        """Sales (S…) and returns (R…) since N days ago."""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
        rows = self._request("GET", f"{STATS}/api/v1/supplier/sales", params={"dateFrom": since}) or []
        return [
            {
                "date": (r.get("date") or "")[:10],
                "sku": r.get("supplierArticle") or str(r.get("nmId")),
                "nm_id": r.get("nmId"),
                "is_return": str(r.get("saleID") or "").startswith("R"),
                "price": float(r.get("priceWithDisc") or r.get("finishedPrice") or 0),
                "for_pay": float(r.get("forPay") or 0),
            }
            for r in rows
        ]

    def orders(self, days: int = 30) -> list[dict[str, Any]]:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
        rows = self._request("GET", f"{STATS}/api/v1/supplier/orders", params={"dateFrom": since}) or []
        return [
            {
                "date": (r.get("date") or "")[:10],
                "sku": r.get("supplierArticle") or str(r.get("nmId")),
                "price": float(r.get("priceWithDisc") or r.get("finishedPrice") or 0),
                "cancelled": bool(r.get("isCancel")),
            }
            for r in rows
        ]

    def finance_report(self, d1: date, d2: date) -> dict[str, float]:
        """Weekly realization report rows summed into P&L lines."""
        totals = {
            "revenue": 0.0, "returns": 0.0, "for_pay": 0.0, "commission": 0.0, "logistics": 0.0,
            "storage": 0.0, "penalty": 0.0, "acceptance": 0.0, "deduction": 0.0, "sold_units": 0.0, "returned_units": 0.0,
        }
        rrdid = 0
        while True:
            rows = self._request(
                "GET",
                f"{STATS}/api/v5/supplier/reportDetailByPeriod",
                params={"dateFrom": d1.isoformat(), "dateTo": d2.isoformat(), "limit": 100000, "rrdid": rrdid},
            ) or []
            for r in rows:
                doc = (r.get("doc_type_name") or "").lower()
                retail = float(r.get("retail_amount") or 0)
                pay = float(r.get("ppvz_for_pay") or 0)
                qty = float(r.get("quantity") or 0)
                if doc.startswith("возврат"):
                    totals["returns"] += retail
                    totals["for_pay"] -= pay
                    totals["returned_units"] += qty
                elif doc.startswith("продажа"):
                    totals["revenue"] += retail
                    totals["for_pay"] += pay
                    totals["commission"] += retail - pay
                    totals["sold_units"] += qty
                totals["logistics"] += float(r.get("delivery_rub") or 0)
                totals["storage"] += float(r.get("storage_fee") or 0)
                totals["penalty"] += float(r.get("penalty") or 0)
                totals["acceptance"] += float(r.get("acceptance") or 0)
                totals["deduction"] += float(r.get("deduction") or 0)
            if not rows:
                return {k: round(v, 2) for k, v in totals.items()}
            rrdid = rows[-1].get("rrd_id") or 0

    def check(self) -> dict[str, Any]:
        info = self.seller_info()
        return {"ok": True, "name": info.get("name") or info.get("tradeMark"), "sid": info.get("sid")}
