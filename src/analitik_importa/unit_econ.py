from __future__ import annotations

from analitik_importa.models import UnitEconInput, UnitEconResult, Verdict


def calculate(inp: UnitEconInput) -> UnitEconResult:
    """China purchase + cargo + MP fees → margin and verdict."""
    cost_rub = inp.cost_cny * inp.cny_rub_rate
    cargo_rub = inp.weight_kg * inp.cargo_per_kg_rub
    landed = cost_rub + cargo_rub

    commission_rub = inp.sell_rub * (inp.commission_pct / 100.0)
    ads_rub = inp.sell_rub * (inp.ads_pct / 100.0)
    defect_rub = inp.sell_rub * (inp.defect_pct / 100.0)
    logistics_mp = inp.logistics_mp_rub

    total_costs = landed + commission_rub + ads_rub + defect_rub + logistics_mp
    profit = inp.sell_rub - total_costs
    margin_pct = (profit / inp.sell_rub) * 100.0 if inp.sell_rub else 0.0

    variable_pct = (inp.commission_pct + inp.ads_pct + inp.defect_pct) / 100.0
    if variable_pct >= 1.0:
        breakeven = float("inf")
    else:
        breakeven = (landed + logistics_mp) / (1.0 - variable_pct)

    if margin_pct >= inp.target_margin_pct:
        verdict = Verdict.TAKE
    elif margin_pct >= inp.target_margin_pct * 0.6:
        verdict = Verdict.TEST
    else:
        verdict = Verdict.SKIP

    return UnitEconResult(
        cost_rub=round(cost_rub, 2),
        cargo_rub=round(cargo_rub, 2),
        landed_cost_rub=round(landed, 2),
        commission_rub=round(commission_rub, 2),
        ads_rub=round(ads_rub, 2),
        defect_rub=round(defect_rub, 2),
        logistics_mp_rub=round(logistics_mp, 2),
        total_costs_rub=round(total_costs, 2),
        profit_rub=round(profit, 2),
        margin_pct=round(margin_pct, 2),
        breakeven_sell_rub=round(breakeven, 2) if breakeven != float("inf") else breakeven,
        verdict=verdict,
        marketplace=inp.marketplace,
    )
