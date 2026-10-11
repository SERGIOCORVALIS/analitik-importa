from __future__ import annotations

import time
from typing import Any, Literal

import httpx

from analitik_importa.config import Settings, get_settings
from analitik_importa.models import ListingSnippet, Marketplace, MarketplaceMetrics
from analitik_importa.stats_util import price_stats

BASE_URL = "https://mpstats.io/api"
MpCode = Literal["wb", "ozon", "ym"]


class MpstatsClient:
    """Live MPSTATS Analytics API (WB / Ozon / Yandex Market)."""

    def __init__(self, settings: Settings | None = None, timeout: float = 60.0) -> None:
        self.settings = settings or get_settings()
        self._stub = self.settings.use_api_stubs
        if not self._stub:
            self.settings.require_mpstats()
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "X-Mpstats-TOKEN": self.settings.mpstats_token,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retries_on_202: int = 5,
    ) -> Any:
        url = f"{BASE_URL}{path}"
        with httpx.Client(timeout=self._timeout) as client:
            for attempt in range(retries_on_202):
                response = client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                )
                if response.status_code == 401:
                    raise RuntimeError("MPSTATS unauthorized (401). Check MPSTATS_TOKEN.")
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "60")
                    raise RuntimeError(f"MPSTATS rate limited (429). Retry-After={retry}")
                if response.status_code == 202:
                    time.sleep(2 + attempt)
                    continue
                if response.status_code >= 400:
                    detail = response.text[:500]
                    raise RuntimeError(f"MPSTATS HTTP {response.status_code}: {detail}")
                if not response.content:
                    return {}
                return response.json()
        raise RuntimeError("MPSTATS still processing (202) after retries.")

    def get_category(
        self,
        mp: MpCode,
        path: str,
        *,
        d1: str,
        d2: str,
        start_row: int = 0,
        end_row: int = 100,
        fbs: int | None = None,
    ) -> MarketplaceMetrics:
        """Fetch category items for wb|ozon|ym."""
        if self._stub:
            from analitik_importa.stubs import stub_mpstats_category

            return stub_mpstats_category(mp, path, d1=d1, d2=d2)

        if mp == "wb":
            api_path = "/wb/get/category"
            source = Marketplace.WB
        elif mp == "ozon":
            api_path = "/oz/get/category"
            source = Marketplace.OZON
        elif mp == "ym":
            api_path = "/ym/get/category"
            source = Marketplace.YM
        else:
            raise ValueError(f"Unsupported mp: {mp}")

        params: dict[str, Any] = {"d1": d1, "d2": d2, "path": path}
        if fbs is not None and mp in ("wb", "ozon"):
            params["fbs"] = fbs

        body = {
            "startRow": start_row,
            "endRow": end_row,
            "filterModel": {},
            "sortModel": [{"colId": "revenue", "sort": "desc"}],
        }
        data = self._request("POST", api_path, params=params, json_body=body)
        rows = self._extract_rows(data)

        prices: list[float] = []
        revenues: list[float] = []
        sales_vals: list[float] = []
        sellers: set[str] = set()
        listings: list[ListingSnippet] = []

        for row in rows:
            price = self._num(row, "final_price", "price", "avg_price", "finalPrice")
            if price is not None:
                prices.append(price)
            rev = self._num(row, "revenue", "sales_revenue")
            if rev is not None:
                revenues.append(rev)
            sold = self._num(row, "sales", "count_sell", "sells")
            if sold is not None:
                sales_vals.append(sold)
            seller = row.get("seller") or row.get("seller_name") or row.get("supplier")
            if seller:
                sellers.add(str(seller))
            title = str(row.get("name") or row.get("title") or row.get("sku_name") or "")
            sku = row.get("id") or row.get("sku") or row.get("nm_id")
            listings.append(
                ListingSnippet(
                    title=title,
                    price=price,
                    currency="RUB",
                    url=None,
                    extra={"sku": sku, "revenue": rev, "sales": sold},
                )
            )

        p25, med, p75 = price_stats(prices)
        return MarketplaceMetrics(
            source=source,
            query=path,
            item_count=len(rows),
            price_median=med,
            price_p25=p25,
            price_p75=p75,
            currency="RUB",
            revenue=sum(revenues) if revenues else None,
            sales=sum(sales_vals) if sales_vals else None,
            sellers=len(sellers) if sellers else None,
            top_listings=listings[:10],
            notes=[f"period={d1}..{d2}", f"mp={mp}"],
            raw_summary={"row_count": len(rows), "total": data.get("total") if isinstance(data, dict) else None},
        )

    def list_categories(self, mp: MpCode) -> list[str]:
        """Full category paths ("Раздел/Подраздел/...") from the MPSTATS tree. Empty in stub mode."""
        if self._stub:
            return []
        api_path = {"wb": "/wb/get/categories", "ozon": "/oz/get/categories", "ym": "/ym/get/categories"}.get(mp)
        if api_path is None:
            raise ValueError(f"Unsupported mp: {mp}")
        data = self._request("GET", api_path)
        paths: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for child in node:
                    walk(child)
            elif isinstance(node, dict):
                path = node.get("path")
                if isinstance(path, str) and path.strip():
                    paths.add(path.strip())
                for value in node.values():
                    if isinstance(value, (list, dict)):
                        walk(value)

        walk(data)
        return sorted(paths)

    def get_item(self, mp: MpCode, item_id: str | int, *, d1: str, d2: str) -> dict[str, Any]:
        if self._stub:
            return {
                "stub": True,
                "mp": mp,
                "id": item_id,
                "d1": d1,
                "d2": d2,
                "name": f"[STUB] item {item_id}",
                "revenue": 100000,
                "sales": 80,
            }
        if mp == "wb":
            path = f"/wb/get/item/{item_id}"
        elif mp == "ozon":
            path = f"/oz/get/item/{item_id}"
        elif mp == "ym":
            path = f"/ym/get/item/{item_id}"
        else:
            raise ValueError(f"Unsupported mp: {mp}")
        return self._request("GET", path, params={"d1": d1, "d2": d2})

    def check(self) -> dict[str, Any]:
        if self._stub:
            return {"ok": True, "stub": True, "note": "USE_API_STUBS=1"}
        # Lightweight authenticated call: user limits endpoint when available,
        # otherwise a tiny category probe may fail on path — prefer limits.
        try:
            data = self._request("GET", "/user/check/limits", retries_on_202=1)
            return {"ok": True, "limits": data}
        except RuntimeError:
            # Fallback: empty-body probe that still validates the token.
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(
                    f"{BASE_URL}/user/check/limits",
                    headers=self._headers(),
                )
                if response.status_code == 401:
                    raise RuntimeError("MPSTATS unauthorized (401). Check MPSTATS_TOKEN.") from None
                if response.status_code == 404:
                    # Token accepted by gateway shape; some tariffs hide limits.
                    return {"ok": True, "note": "token present; limits endpoint unavailable"}
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"MPSTATS check failed HTTP {response.status_code}: {response.text[:300]}"
                    )
                return {"ok": True, "limits": response.json() if response.content else {}}

    @staticmethod
    def _extract_rows(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            for key in ("data", "items", "rows", "result"):
                val = data.get(key)
                if isinstance(val, list):
                    return [r for r in val if isinstance(r, dict)]
        return []

    @staticmethod
    def _num(row: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            if key in row and row[key] is not None:
                try:
                    return float(row[key])
                except (TypeError, ValueError):
                    continue
        return None
