from __future__ import annotations

import time
from typing import Any

import httpx

from analitik_importa.config import Settings, get_settings
from analitik_importa.models import ListingSnippet, Marketplace, MarketplaceMetrics
from analitik_importa.stats_util import price_stats

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayClient:
    """Live eBay Browse API client (analytics only)."""

    def __init__(self, settings: Settings | None = None, timeout: float = 30.0) -> None:
        self.settings = settings or get_settings()
        self._stub = self.settings.use_api_stubs
        if not self._stub:
            self.settings.require_ebay()
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_token(self, client: httpx.Client) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        response = client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": SCOPE},
            auth=(self.settings.ebay_client_id, self.settings.ebay_client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code == 401:
            raise RuntimeError("eBay OAuth failed (401). Check EBAY_CLIENT_ID/SECRET.")
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "?")
            raise RuntimeError(f"eBay rate limited (429). Retry-After={retry}")
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = now + int(payload.get("expires_in", 7200))
        return self._token

    def search(
        self,
        keywords: str,
        *,
        limit: int = 50,
        marketplace_id: str | None = None,
    ) -> MarketplaceMetrics:
        marketplace_id = marketplace_id or self.settings.ebay_marketplace_id
        limit = max(1, min(limit, 200))
        if self._stub:
            from analitik_importa.stubs import stub_ebay_search

            return stub_ebay_search(keywords, limit=limit)

        with httpx.Client(timeout=self._timeout) as client:
            token = self._get_token(client)
            response = client.get(
                BROWSE_SEARCH_URL,
                params={"q": keywords, "limit": str(limit)},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 401:
                self._token = None
                raise RuntimeError("eBay Browse unauthorized (401).")
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "?")
                raise RuntimeError(f"eBay rate limited (429). Retry-After={retry}")
            response.raise_for_status()
            data = response.json()

        items = data.get("itemSummaries") or []
        prices: list[float] = []
        currency: str | None = None
        listings: list[ListingSnippet] = []

        for item in items:
            price_obj = item.get("price") or {}
            value = price_obj.get("value")
            cur = price_obj.get("currency")
            if cur and currency is None:
                currency = cur
            price_f: float | None = None
            if value is not None:
                try:
                    price_f = float(value)
                    prices.append(price_f)
                except (TypeError, ValueError):
                    price_f = None
            listings.append(
                ListingSnippet(
                    title=item.get("title") or "",
                    price=price_f,
                    currency=cur,
                    url=item.get("itemWebUrl"),
                    extra={
                        "itemId": item.get("itemId"),
                        "condition": item.get("condition"),
                    },
                )
            )

        p25, med, p75 = price_stats(prices)
        return MarketplaceMetrics(
            source=Marketplace.EBAY,
            query=keywords,
            item_count=len(items),
            price_median=med,
            price_p25=p25,
            price_p75=p75,
            currency=currency,
            top_listings=listings[:10],
            notes=[f"marketplace_id={marketplace_id}", "active listings via Browse API"],
            raw_summary={"total": data.get("total"), "href": data.get("href")},
        )

    def check(self) -> dict[str, Any]:
        metrics = self.search("usb cable", limit=1)
        return {
            "ok": True,
            "stub": self._stub,
            "item_count": metrics.item_count,
            "query": metrics.query,
            "marketplace": self.settings.ebay_marketplace_id,
        }
