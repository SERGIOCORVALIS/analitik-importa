from __future__ import annotations

import time
from datetime import date
from typing import Any

import httpx

from analitik_importa.config import Settings, get_settings

BASE_URL = "https://api-performance.ozon.ru"
MICRO = 1_000_000  # budgets in the API are in millionths of a rouble

STATE_RU = {
    "CAMPAIGN_STATE_RUNNING": "Активна",
    "CAMPAIGN_STATE_PLANNED": "Запланирована",
    "CAMPAIGN_STATE_STOPPED": "Остановлена (нет бюджета)",
    "CAMPAIGN_STATE_INACTIVE": "Выключена",
    "CAMPAIGN_STATE_ARCHIVED": "В архиве",
    "CAMPAIGN_STATE_MODERATION_DRAFT": "Черновик",
    "CAMPAIGN_STATE_MODERATION_IN_PROGRESS": "На модерации",
    "CAMPAIGN_STATE_MODERATION_FAILED": "Не прошла модерацию",
    "CAMPAIGN_STATE_FINISHED": "Завершена",
}
TYPE_RU = {
    "SKU": "Оплата за клик",
    "ALL_SKU_PROMO": "Оплата за заказ — все товары",
    "SEARCH_PROMO": "Оплата за заказ",
    "BANNER": "Баннер",
    "VIDEO_BANNER": "Видеобаннер",
    "BRAND_SHELF": "Брендовая полка",
}
PLACEMENT_RU = {
    "PLACEMENT_TOP_PROMOTION": "Поиск",
    "PLACEMENT_SEARCH_AND_CATEGORY": "Поиск и рекомендации",
}
STRATEGY_RU = {
    "MAX_CLICKS": "Автостратегия: максимум кликов",
    "TOP_MAX_CLICKS": "Автостратегия в поиске",
    "TARGET_BIDS": "Средняя стоимость клика (свои ставки)",
    "TOP_PROMOTION": "Вывод в топ",
    "TARGET_CIR": "Целевой расход (ДРР)",
}
ALL_SKU_BIDS = (5, 7, 9)


def num(value: Any) -> float:
    """Ozon returns numbers as strings, sometimes with a decimal comma ("1 234,50")."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


def rub(micro: Any) -> float:
    return num(micro) / MICRO


def to_micro(rubles: float | None) -> str | None:
    return None if rubles is None else str(int(round(rubles * MICRO)))


class OzonPerformanceClient:
    """Ozon Performance API — рекламный кабинет продавца (кампании, ставки, статистика)."""

    def __init__(self, settings: Settings | None = None, timeout: float = 60.0) -> None:
        self.settings = settings or get_settings()
        self.settings.require_ozon_performance()
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._token = ""
        self._token_until = 0.0

    def close(self) -> None:
        self._http.close()

    def _auth(self) -> dict[str, str]:
        if not self._token or time.time() > self._token_until:
            r = self._http.post(
                "/api/client/token",
                json={
                    "client_id": self.settings.ozon_perf_client_id.strip(),
                    "client_secret": self.settings.ozon_perf_client_secret.strip(),
                    "grant_type": "client_credentials",
                },
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"Ozon Performance: не удалось получить токен (HTTP {r.status_code}). "
                    "Проверьте OZON_PERF_CLIENT_ID и OZON_PERF_CLIENT_SECRET."
                )
            data = r.json()
            self._token = data["access_token"]
            self._token_until = time.time() + int(data.get("expires_in") or 1800) - 60
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        for attempt in range(3):
            r = self._http.request(method, path, headers=self._auth(), **kw)
            if r.status_code == 429 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 401 and attempt < 2:
                self._token = ""
                continue
            break
        if r.status_code >= 400:
            try:
                msg = r.json().get("error") or r.text
            except ValueError:
                msg = r.text
            raise RuntimeError(f"Ozon Performance HTTP {r.status_code}: {str(msg)[:400]}")
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return r.text

    # ---------- кампании ----------

    def campaigns(self) -> list[dict[str, Any]]:
        rows = []
        for c in self._request("GET", "/api/client/campaign").get("list") or []:
            rows.append(
                {
                    "id": str(c.get("id")),
                    "title": c.get("title") or "",
                    "state": c.get("state") or "",
                    "state_ru": STATE_RU.get(c.get("state"), c.get("state")),
                    "type": c.get("advObjectType") or "",
                    "type_ru": TYPE_RU.get(c.get("advObjectType"), c.get("advObjectType")),
                    "payment": c.get("PaymentType") or c.get("paymentType") or "",
                    "placement": ", ".join(PLACEMENT_RU.get(p, p) for p in c.get("placement") or []),
                    "strategy": c.get("productAutopilotStrategy") or "",
                    "from_date": c.get("fromDate") or "",
                    "to_date": c.get("toDate") or "",
                    "weekly_budget": rub(c.get("weeklyBudget")),
                    "daily_budget": rub(c.get("dailyBudget")),
                    "budget": rub(c.get("budget")),
                    "created_at": (c.get("createdAt") or "")[:10],
                    "autocreated": bool(c.get("isAutocreated")),
                }
            )
        return rows

    def activate(self, campaign_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/client/campaign/{campaign_id}/activate", json={})

    def deactivate(self, campaign_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/client/campaign/{campaign_id}/deactivate", json={})

    def create_cpc_campaign(
        self,
        title: str,
        placement: str,
        strategy: str | None,
        weekly_budget_rub: float | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> str:
        body: dict[str, Any] = {"title": title, "placement": placement}
        if strategy:
            body["productAutopilotStrategy"] = strategy
        if weekly_budget_rub:
            body["weeklyBudget"] = to_micro(weekly_budget_rub)
        if from_date:
            body["fromDate"] = from_date.isoformat()
        if to_date:
            body["toDate"] = to_date.isoformat()
        return str(self._request("POST", "/api/client/campaign/cpc/v2/product", json=body).get("campaignId"))

    def update_campaign(
        self,
        campaign_id: str,
        weekly_budget_rub: float | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if weekly_budget_rub is not None:
            body["weeklyBudget"] = to_micro(weekly_budget_rub)
        if from_date:
            body["fromDate"] = from_date.isoformat()
        if to_date:
            body["toDate"] = to_date.isoformat()
        return self._request("PATCH", f"/api/client/campaign/{campaign_id}", json=body)

    # ---------- товары в оплате за клик ----------

    def campaign_products(self, campaign_id: str) -> list[dict[str, Any]]:
        rows, page = [], 1
        while True:
            data = self._request(
                "GET", f"/api/client/campaign/{campaign_id}/v2/products", params={"page": page, "pageSize": 100}
            )
            batch = data.get("products") or []
            for p in batch:
                rows.append(
                    {
                        "sku": str(p.get("sku")),
                        "title": p.get("title") or "",
                        "bid": rub(p.get("bid")),
                        "target_cir": p.get("targetCir"),
                        "top_position": p.get("topPosition"),
                    }
                )
            if len(batch) < 100:
                return rows
            page += 1

    def add_products(self, campaign_id: str, bids: list[dict[str, Any]]) -> Any:
        """bids: [{"sku": "...", "bid_rub": 15.0 | None}] — без ставки Ozon ставит конкурентную."""
        payload = [{"sku": str(b["sku"]), **({"bid": to_micro(b["bid_rub"])} if b.get("bid_rub") else {})} for b in bids]
        return self._request("POST", f"/api/client/campaign/{campaign_id}/products", json={"bids": payload})

    def update_bids(self, campaign_id: str, bids: list[dict[str, Any]]) -> Any:
        payload = [{"sku": str(b["sku"]), "bid": to_micro(b["bid_rub"])} for b in bids]
        return self._request("PUT", f"/api/client/campaign/{campaign_id}/products", json={"bids": payload})

    def delete_products(self, campaign_id: str, skus: list[str]) -> Any:
        return self._request("POST", f"/api/client/campaign/{campaign_id}/products/delete", json={"sku": skus})

    def competitive_bids(self, campaign_id: str, skus: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for i in range(0, len(skus), 200):
            data = self._request(
                "GET", f"/api/client/campaign/{campaign_id}/products/bids/competitive", params={"skus": skus[i : i + 200]}
            )
            out.update({str(b.get("sku")): rub(b.get("bid")) for b in data.get("bids") or []})
        return out

    def limits(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/client/limits/list").get("limits") or []

    # ---------- оплата за заказ ----------

    def all_sku_activate(self) -> dict[str, Any]:
        return self._request("GET", "/api/client/campaign/all_sku_promo/activate")

    def all_sku_deactivate(self) -> dict[str, Any]:
        return self._request("GET", "/api/client/campaign/all_sku_promo/deactivate")

    def all_sku_set_bid(self, bid_pct: int) -> dict[str, Any]:
        if bid_pct not in ALL_SKU_BIDS:
            raise ValueError(f"Ставка для «Оплата за заказ — все товары» может быть только {ALL_SKU_BIDS} %")
        return self._request("GET", "/api/client/campaign/all_sku_promo/set_bid", params={"bid": bid_pct})

    def cpo_products(self) -> list[dict[str, Any]]:
        rows, page = [], 1
        while True:
            data = self._request("POST", "/api/client/campaign/search_promo/v2/products", json={"page": page, "pageSize": 100})
            batch = data.get("products") or []
            for p in batch:
                views = p.get("views") or {}
                rows.append(
                    {
                        "sku": str(p.get("sku")),
                        "title": p.get("title") or "",
                        "image": p.get("imageUrl"),
                        "price": num(p.get("price")),
                        "enabled": bool(p.get("searchPromoStatus")),
                        "available": bool(p.get("isSearchPromoAvailable", True)),
                        "bid_pct": num(p.get("bid")),
                        "bid_rub": num(p.get("bidPrice")),
                        "visibility": num(p.get("visibilityIndex")),
                        "views_week": num(views.get("thisWeek")),
                        "views_prev_week": num(views.get("previousWeek")),
                    }
                )
            if len(batch) < 100:
                return rows
            page += 1

    def cpo_min_bids(self, skus: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for i in range(0, len(skus), 200):
            data = self._request("POST", "/api/client/search_promo/get_cpo_min_bids", json={"skus": skus[i : i + 200]})
            out.update({str(b.get("sku")): num(b.get("bid")) for b in data.get("bids") or []})
        return out

    def cpo_enable(self, skus: list[str]) -> list[dict[str, Any]]:
        return self._request("POST", "/api/client/search_promo/product/enable", json={"skus": skus}).get("response") or []

    def cpo_disable(self, skus: list[str]) -> Any:
        return self._request("POST", "/api/client/search_promo/product/disable", json={"skus": skus})

    def cpo_remove(self, skus: list[str]) -> Any:
        return self._request("POST", "/api/client/campaign/search_promo/v2/bids/delete", json={"sku": skus})

    def carrots(self, skus: list[str], enable: bool) -> dict[str, Any]:
        action = "enable" if enable else "disable"
        return self._request("POST", f"/api/client/campaign/search_promo/carrots/{action}", json={"skus": skus}).get(
            "skuToInfo"
        ) or {}

    def products_with_bonuses(self) -> list[str]:
        return [str(s) for s in self._request("GET", "/api/client/products_with_bonuses").get("skus") or []]

    # ---------- статистика ----------

    @staticmethod
    def _period(d1: date, d2: date) -> dict[str, str]:
        return {"dateFrom": d1.isoformat(), "dateTo": d2.isoformat()}

    def daily(self, d1: date, d2: date) -> list[dict[str, Any]]:
        rows = self._request("GET", "/api/client/statistics/daily/json", params=self._period(d1, d2)).get("rows") or []
        return [
            {
                "campaign_id": str(r.get("id")),
                "title": r.get("title") or "",
                "date": r.get("date"),
                "views": num(r.get("views")),
                "clicks": num(r.get("clicks")),
                "spent": num(r.get("moneySpent")),
                "orders": num(r.get("orders")),
                "orders_rub": num(r.get("ordersMoney")),
            }
            for r in rows
        ]

    def expense(self, d1: date, d2: date) -> list[dict[str, Any]]:
        rows = self._request("GET", "/api/client/statistics/expense/json", params=self._period(d1, d2)).get("rows") or []
        return [
            {
                "campaign_id": str(r.get("id")),
                "title": r.get("title") or "",
                "date": r.get("date"),
                "spent": num(r.get("moneySpent")),
                "bonus": num(r.get("bonusSpent")),
                "prepaid": num(r.get("prepaymentSpent")),
            }
            for r in rows
        ]

    def wait_report(self, uuid: str, timeout_sec: int = 180) -> Any:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            st = self._request("GET", f"/api/client/statistics/{uuid}")
            if st.get("state") == "ERROR":
                raise RuntimeError(f"Ozon не смог сформировать отчёт: {st.get('error') or 'ошибка'}")
            if st.get("state") == "OK":
                return self._request("GET", "/api/client/statistics/report", params={"UUID": uuid})
            time.sleep(3)
        raise RuntimeError("Отчёт формируется дольше 3 минут — попробуйте позже.")

    @staticmethod
    def _rows(report: Any) -> list[dict[str, Any]]:
        if isinstance(report, list):
            return report
        if not isinstance(report, dict):
            return []
        for key in ("rows", "report", "items", "products", "orders"):
            if isinstance(report.get(key), list):
                return report[key]
        for value in report.values():
            if isinstance(value, dict):
                rows = OzonPerformanceClient._rows(value)
                if rows:
                    return rows
        return []

    @staticmethod
    def _bounds(d1: date, d2: date) -> tuple[str, str]:
        return f"{d1.isoformat()}T00:00:00Z", f"{d2.isoformat()}T23:59:59Z"

    def products_report(self, d1: date, d2: date) -> list[dict[str, Any]]:
        """Отчёт по товарам в продвижении: ставка, заказы, расход, ДРР (оплата за заказ и за клик)."""
        f, t = self._bounds(d1, d2)
        uuid = self._request("POST", "/api/client/statistic/products/generate/json", json={"from": f, "to": t})["UUID"]
        return self._rows(self.wait_report(uuid))

    def all_sku_report(self, d1: date, d2: date, kind: str = "products") -> list[dict[str, Any]]:
        """kind: products — по дням (расход, продажи); orders — построчно по заказам."""
        f, t = self._bounds(d1, d2)
        uuid = self._request(
            "GET", f"/api/client/statistics/all_sku_promo/{kind}/generate/json",
            params={"timeBounds.from": f, "timeBounds.to": t},
        )["UUID"]
        return self._rows(self.wait_report(uuid))

    def check(self) -> dict[str, Any]:
        camps = self.campaigns()
        return {"ok": True, "campaigns": len(camps), "running": sum(c["state"] == "CAMPAIGN_STATE_RUNNING" for c in camps)}
