from __future__ import annotations

import time
from typing import Any

import httpx

from analitik_importa.config import Settings, get_settings
from analitik_importa.models import ListingSnippet, Marketplace, MarketplaceMetrics
from analitik_importa.stats_util import price_stats

TOKEN_URL = "https://api.amazon.com/auth/o2/token"
API_BASE = "https://creatorsapi.amazon"
SCOPE = "creatorsapi::default"


class AmazonClient:
    """Live Amazon Creators API (Associates). Catalog/price/rating — not RU sales volume."""

    def __init__(self, settings: Settings | None = None, timeout: float = 30.0) -> None:
        self.settings = settings or get_settings()
        self._stub = self.settings.use_api_stubs
        if not self._stub:
            self.settings.require_amazon()
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_token(self, client: httpx.Client) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        response = client.post(
            TOKEN_URL,
            json={
                "grant_type": "client_credentials",
                "client_id": self.settings.amazon_credential_id,
                "client_secret": self.settings.amazon_credential_secret,
                "scope": SCOPE,
            },
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 401:
            raise RuntimeError("Amazon OAuth failed (401). Check Creators API credentials.")
        if response.status_code == 429:
            raise RuntimeError("Amazon token endpoint rate limited (429).")
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = now + int(payload.get("expires_in", 3600))
        return self._token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-marketplace": self.settings.amazon_marketplace,
        }

    def search_items(self, keywords: str, *, item_count: int = 10) -> MarketplaceMetrics:
        item_count = max(1, min(item_count, 10))
        if self._stub:
            from analitik_importa.stubs import stub_amazon_search

            return stub_amazon_search(keywords, item_count=item_count)

        body = {
            "keywords": keywords,
            "partnerTag": self.settings.amazon_partner_tag,
            "partnerType": "Associates",
            "marketplace": self.settings.amazon_marketplace,
            "itemCount": item_count,
            "resources": [
                "images.primary.small",
                "itemInfo.title",
                "offersV2.listings.price",
                "customerReviews.starRating",
                "customerReviews.count",
            ],
        }
        with httpx.Client(timeout=self._timeout) as client:
            token = self._get_token(client)
            response = client.post(
                f"{API_BASE}/catalog/v1/searchItems",
                headers=self._headers(token),
                json=body,
            )
            if response.status_code == 401:
                self._token = None
                raise RuntimeError("Amazon Creators API unauthorized (401).")
            if response.status_code == 429:
                raise RuntimeError("Amazon Creators API rate limited (429).")
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Amazon HTTP {response.status_code}: {response.text[:500]}"
                )
            data = response.json()

        items = self._extract_items(data)
        prices: list[float] = []
        ratings: list[float] = []
        listings: list[ListingSnippet] = []
        currency: str | None = None

        for item in items:
            asin = item.get("asin") or item.get("ASIN")
            title = self._dig(item, "itemInfo", "title", "displayValue") or ""
            price, cur = self._extract_price(item)
            if cur and currency is None:
                currency = cur
            if price is not None:
                prices.append(price)
            rating = self._dig(item, "customerReviews", "starRating")
            if isinstance(rating, (int, float)):
                ratings.append(float(rating))
            review_count = self._dig(item, "customerReviews", "count")
            detail = item.get("detailPageURL") or item.get("detailPageUrl")
            listings.append(
                ListingSnippet(
                    title=str(title),
                    price=price,
                    currency=cur,
                    url=detail,
                    extra={"asin": asin, "rating": rating, "review_count": review_count},
                )
            )

        p25, med, p75 = price_stats(prices)
        avg_rating = sum(ratings) / len(ratings) if ratings else None
        return MarketplaceMetrics(
            source=Marketplace.AMAZON,
            query=keywords,
            item_count=len(items),
            price_median=med,
            price_p25=p25,
            price_p75=p75,
            currency=currency,
            avg_rating=avg_rating,
            top_listings=listings[:10],
            notes=[
                f"marketplace={self.settings.amazon_marketplace}",
                "Amazon Creators API = catalog/price/rating, NOT RU sales volume",
            ],
            raw_summary={"returned": len(items)},
        )

    def get_items(self, asins: list[str]) -> dict[str, Any]:
        if not asins:
            raise ValueError("asins must be non-empty")
        if self._stub:
            return {
                "stub": True,
                "itemsResult": {
                    "items": [
                        {
                            "asin": a,
                            "itemInfo": {"title": {"displayValue": f"[STUB] {a}"}},
                        }
                        for a in asins[:10]
                    ]
                },
            }
        body = {
            "itemIds": asins[:10],
            "itemIdType": "ASIN",
            "marketplace": self.settings.amazon_marketplace,
            "partnerTag": self.settings.amazon_partner_tag,
            "partnerType": "Associates",
            "resources": [
                "images.primary.small",
                "itemInfo.title",
                "offersV2.listings.price",
                "customerReviews.starRating",
                "customerReviews.count",
            ],
        }
        with httpx.Client(timeout=self._timeout) as client:
            token = self._get_token(client)
            response = client.post(
                f"{API_BASE}/catalog/v1/getItems",
                headers=self._headers(token),
                json=body,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Amazon getItems HTTP {response.status_code}: {response.text[:500]}"
                )
            return response.json()

    def check(self) -> dict[str, Any]:
        metrics = self.search_items("usb cable", item_count=1)
        return {
            "ok": True,
            "stub": self._stub,
            "item_count": metrics.item_count,
            "marketplace": self.settings.amazon_marketplace,
        }

    @staticmethod
    def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
        search_result = data.get("searchResult") or data.get("itemsResult") or {}
        items = search_result.get("items") or data.get("items") or []
        return [i for i in items if isinstance(i, dict)]

    @staticmethod
    def _dig(obj: Any, *keys: str) -> Any:
        cur = obj
        for key in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    @classmethod
    def _extract_price(cls, item: dict[str, Any]) -> tuple[float | None, str | None]:
        offers = cls._dig(item, "offersV2", "listings") or []
        if isinstance(offers, list) and offers:
            price_obj = (offers[0] or {}).get("price") or {}
            amount = price_obj.get("amount") or price_obj.get("displayAmount")
            currency = price_obj.get("currency") or price_obj.get("currencyCode")
            if isinstance(amount, str):
                cleaned = "".join(ch for ch in amount if ch.isdigit() or ch == ".")
                try:
                    return float(cleaned), currency
                except ValueError:
                    return None, currency
            if isinstance(amount, (int, float)):
                return float(amount), currency
        return None, None
