from __future__ import annotations

from analitik_importa.models import (
    MarketplaceMetrics,
    NicheScore,
    UnitEconResult,
    Verdict,
)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def score_mpstats(wb: MarketplaceMetrics | None, ozon: MarketplaceMetrics | None) -> tuple[float, list[str]]:
    notes: list[str] = []
    parts: list[float] = []

    for label, m in (("WB", wb), ("Ozon", ozon)):
        if m is None or m.item_count == 0:
            notes.append(f"{label}: no data")
            continue
        # More sales/revenue → higher demand; many sellers → lower opportunity.
        sales = m.sales or 0.0
        revenue = m.revenue or 0.0
        sellers = m.sellers or m.item_count
        demand = _clamp((sales / 1000.0) * 20 + (revenue / 1_000_000.0) * 30)
        competition_penalty = _clamp(sellers / 50.0 * 40)
        part = _clamp(demand + 40 - competition_penalty)
        parts.append(part)
        notes.append(
            f"{label}: items={m.item_count}, sales={sales}, revenue={revenue}, "
            f"sellers≈{sellers}, component={part:.1f}"
        )

    if not parts:
        return 0.0, notes or ["MPSTATS: missing"]
    return sum(parts) / len(parts), notes


def score_amazon(m: MarketplaceMetrics | None) -> tuple[float, list[str]]:
    if m is None or m.item_count == 0:
        return 0.0, ["Amazon: no data"]
    rating = m.avg_rating or 0.0
    # Mid prices with decent ratings signal a healthy catalog niche.
    price_spread = 0.0
    if m.price_p25 and m.price_p75 and m.price_p25 > 0:
        price_spread = (m.price_p75 - m.price_p25) / m.price_p25
    spread_score = _clamp(50 - abs(price_spread - 0.4) * 40)
    rating_score = _clamp(rating / 5.0 * 50)
    total = _clamp(spread_score * 0.4 + rating_score * 0.6)
    return total, [
        f"Amazon: items={m.item_count}, avg_rating={rating}, "
        f"price_median={m.price_median}, component={total:.1f}",
        "Note: Amazon score is catalog/price/rating only, not RU volume",
    ]


def score_ebay(m: MarketplaceMetrics | None) -> tuple[float, list[str]]:
    if m is None or m.item_count == 0:
        return 0.0, ["eBay: no data"]
    density = _clamp(m.item_count / 50.0 * 60)
    price_ok = 40.0 if m.price_median else 0.0
    total = _clamp(density * 0.6 + price_ok * 0.4)
    return total, [
        f"eBay: items={m.item_count}, median={m.price_median} {m.currency}, component={total:.1f}"
    ]


def score_margin(econ: UnitEconResult | None, target_pct: float) -> tuple[float, list[str]]:
    if econ is None:
        return 0.0, ["Unit econ: not calculated"]
    ratio = econ.margin_pct / target_pct if target_pct else 0.0
    total = _clamp(ratio * 70)
    return total, [f"Margin={econ.margin_pct}% vs target {target_pct}% → {total:.1f}"]


def compute_niche_score(
    *,
    wb: MarketplaceMetrics | None,
    ozon: MarketplaceMetrics | None,
    amazon: MarketplaceMetrics | None,
    ebay: MarketplaceMetrics | None,
    unit_econ: UnitEconResult | None,
    target_margin_pct: float,
) -> NicheScore:
    """Weights: MPSTATS 55%, Amazon 20%, eBay 15%, margin 10%."""
    mp_c, mp_notes = score_mpstats(wb, ozon)
    am_c, am_notes = score_amazon(amazon)
    eb_c, eb_notes = score_ebay(ebay)
    mg_c, mg_notes = score_margin(unit_econ, target_margin_pct)

    total = mp_c * 0.55 + am_c * 0.20 + eb_c * 0.15 + mg_c * 0.10
    if total >= 65:
        verdict = Verdict.TAKE
    elif total >= 40:
        verdict = Verdict.TEST
    else:
        verdict = Verdict.SKIP

    return NicheScore(
        total=round(total, 2),
        mpstats_component=round(mp_c, 2),
        amazon_component=round(am_c, 2),
        ebay_component=round(eb_c, 2),
        margin_component=round(mg_c, 2),
        verdict=verdict,
        rationale=mp_notes + am_notes + eb_notes + mg_notes,
    )
