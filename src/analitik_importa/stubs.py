from __future__ import annotations

from analitik_importa.models import ListingSnippet, Marketplace, MarketplaceMetrics
from analitik_importa.stats_util import price_stats


def stub_ebay_search(keywords: str, *, limit: int = 50) -> MarketplaceMetrics:
    """Deterministic demo data for eBay Browse when USE_API_STUBS=1."""
    base_prices = [12.99, 15.5, 18.0, 19.99, 22.5, 24.0, 27.99, 29.5, 31.0, 34.99]
    n = max(1, min(limit, len(base_prices) * 3))
    prices = (base_prices * ((n // len(base_prices)) + 1))[:n]
    p25, med, p75 = price_stats(prices)
    listings = [
        ListingSnippet(
            title=f"[STUB] {keywords} sample listing #{i + 1}",
            price=prices[i],
            currency="USD",
            url=f"https://www.ebay.com/itm/stub-{i + 1}",
            extra={"itemId": f"stub-{i + 1}", "condition": "New"},
        )
        for i in range(min(10, n))
    ]
    return MarketplaceMetrics(
        source=Marketplace.EBAY,
        query=keywords,
        item_count=n,
        price_median=med,
        price_p25=p25,
        price_p75=p75,
        currency="USD",
        top_listings=listings,
        notes=["STUB DATA — not live eBay API", "marketplace_id=EBAY_US"],
        raw_summary={"stub": True, "total": n},
    )


def stub_mpstats_category(
    mp: str,
    path: str,
    *,
    d1: str,
    d2: str,
) -> MarketplaceMetrics:
    """Deterministic demo category grid for MPSTATS when USE_API_STUBS=1."""
    source = {
        "wb": Marketplace.WB,
        "ozon": Marketplace.OZON,
        "ym": Marketplace.YM,
    }.get(mp, Marketplace.WB)

    rows = [
        {"title": f"[STUB] {path} SKU A", "price": 1290, "revenue": 420_000, "sales": 320, "seller": "SellerA"},
        {"title": f"[STUB] {path} SKU B", "price": 1490, "revenue": 380_000, "sales": 255, "seller": "SellerB"},
        {"title": f"[STUB] {path} SKU C", "price": 990, "revenue": 310_000, "sales": 410, "seller": "SellerC"},
        {"title": f"[STUB] {path} SKU D", "price": 1790, "revenue": 290_000, "sales": 160, "seller": "SellerA"},
        {"title": f"[STUB] {path} SKU E", "price": 1190, "revenue": 250_000, "sales": 210, "seller": "SellerD"},
    ]
    prices = [float(r["price"]) for r in rows]
    p25, med, p75 = price_stats(prices)
    listings = [
        ListingSnippet(
            title=str(r["title"]),
            price=float(r["price"]),
            currency="RUB",
            extra={"sku": f"stub-{i}", "revenue": r["revenue"], "sales": r["sales"]},
        )
        for i, r in enumerate(rows, start=1)
    ]
    return MarketplaceMetrics(
        source=source,
        query=path,
        item_count=len(rows),
        price_median=med,
        price_p25=p25,
        price_p75=p75,
        currency="RUB",
        revenue=float(sum(r["revenue"] for r in rows)),
        sales=float(sum(r["sales"] for r in rows)),
        sellers=len({r["seller"] for r in rows}),
        top_listings=listings,
        notes=[
            "STUB DATA — not live MPSTATS API",
            f"period={d1}..{d2}",
            f"mp={mp}",
        ],
        raw_summary={"stub": True, "row_count": len(rows)},
    )


def stub_amazon_search(keywords: str, *, item_count: int = 10) -> MarketplaceMetrics:
    """Deterministic demo catalog for Amazon Creators when USE_API_STUBS=1."""
    samples = [
        (19.99, 4.4, 1200),
        (24.5, 4.2, 860),
        (17.0, 4.6, 2100),
        (29.99, 4.1, 540),
        (21.5, 4.5, 980),
        (26.0, 4.3, 700),
        (15.99, 4.0, 430),
        (32.0, 4.7, 1500),
        (22.99, 4.4, 1100),
        (18.5, 4.2, 640),
    ]
    n = max(1, min(item_count, len(samples)))
    prices = [s[0] for s in samples[:n]]
    ratings = [s[1] for s in samples[:n]]
    p25, med, p75 = price_stats(prices)
    listings = [
        ListingSnippet(
            title=f"[STUB] {keywords} ASIN sample {i + 1}",
            price=samples[i][0],
            currency="USD",
            url=f"https://www.amazon.com/dp/STUB{i + 1:04d}",
            extra={
                "asin": f"STUB{i + 1:04d}",
                "rating": samples[i][1],
                "review_count": samples[i][2],
            },
        )
        for i in range(n)
    ]
    return MarketplaceMetrics(
        source=Marketplace.AMAZON,
        query=keywords,
        item_count=n,
        price_median=med,
        price_p25=p25,
        price_p75=p75,
        currency="USD",
        avg_rating=sum(ratings) / len(ratings),
        top_listings=listings,
        notes=[
            "STUB DATA — not live Amazon Creators API",
            "Amazon = catalog/price/rating, NOT RU sales volume",
        ],
        raw_summary={"stub": True, "returned": n},
    )
