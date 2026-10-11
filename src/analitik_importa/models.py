from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Marketplace(str, Enum):
    WB = "wb"
    OZON = "ozon"
    YM = "ym"
    AVITO = "avito"
    EBAY = "ebay"
    AMAZON = "amazon"


class Verdict(str, Enum):
    TAKE = "take"
    TEST = "test"
    SKIP = "skip"


class UnitEconInput(BaseModel):
    cost_cny: float = Field(gt=0)
    sell_rub: float = Field(gt=0)
    marketplace: Marketplace = Marketplace.WB
    cny_rub_rate: float = Field(gt=0)
    weight_kg: float = Field(gt=0)
    cargo_per_kg_rub: float = Field(ge=0)
    commission_pct: float = Field(ge=0)
    ads_pct: float = Field(ge=0)
    defect_pct: float = Field(ge=0)
    target_margin_pct: float = Field(ge=0)
    logistics_mp_rub: float = Field(default=0.0, ge=0)


class UnitEconResult(BaseModel):
    cost_rub: float
    cargo_rub: float
    landed_cost_rub: float
    commission_rub: float
    ads_rub: float
    defect_rub: float
    logistics_mp_rub: float
    total_costs_rub: float
    profit_rub: float
    margin_pct: float
    breakeven_sell_rub: float
    verdict: Verdict
    marketplace: Marketplace


class ListingSnippet(BaseModel):
    title: str
    price: float | None = None
    currency: str | None = None
    url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MarketplaceMetrics(BaseModel):
    source: Marketplace
    query: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    item_count: int = 0
    price_median: float | None = None
    price_p25: float | None = None
    price_p75: float | None = None
    currency: str | None = None
    revenue: float | None = None
    sales: float | None = None
    sellers: int | None = None
    avg_rating: float | None = None
    top_listings: list[ListingSnippet] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    raw_summary: dict[str, Any] = Field(default_factory=dict)


class NicheQuery(BaseModel):
    keywords: str
    wb_category_path: str | None = None
    ozon_category_path: str | None = None
    cost_cny: float | None = None
    sell_rub: float | None = None
    weight_kg: float | None = None
    marketplace: Marketplace = Marketplace.WB


class NicheScore(BaseModel):
    total: float
    mpstats_component: float
    amazon_component: float
    ebay_component: float
    margin_component: float
    verdict: Verdict
    rationale: list[str] = Field(default_factory=list)


class NicheReport(BaseModel):
    query: NicheQuery
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ebay: MarketplaceMetrics | None = None
    mpstats_wb: MarketplaceMetrics | None = None
    mpstats_ozon: MarketplaceMetrics | None = None
    amazon: MarketplaceMetrics | None = None
    unit_econ: UnitEconResult | None = None
    score: NicheScore | None = None
    errors: list[str] = Field(default_factory=list)
