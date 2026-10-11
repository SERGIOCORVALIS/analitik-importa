from analitik_importa.models import Marketplace, UnitEconInput
from analitik_importa.stats_util import percentile, price_stats
from analitik_importa.unit_econ import calculate
from analitik_importa.scoring import compute_niche_score
from analitik_importa.models import MarketplaceMetrics, Verdict


def test_unit_econ_take():
    result = calculate(
        UnitEconInput(
            cost_cny=20,
            sell_rub=2500,
            marketplace=Marketplace.WB,
            cny_rub_rate=12.5,
            weight_kg=0.2,
            cargo_per_kg_rub=450,
            commission_pct=15,
            ads_pct=8,
            defect_pct=3,
            target_margin_pct=25,
        )
    )
    assert result.cost_rub == 250.0
    assert result.cargo_rub == 90.0
    assert result.landed_cost_rub == 340.0
    assert result.margin_pct > 25
    assert result.verdict == Verdict.TAKE


def test_unit_econ_skip_low_margin():
    result = calculate(
        UnitEconInput(
            cost_cny=100,
            sell_rub=1500,
            marketplace=Marketplace.OZON,
            cny_rub_rate=12.5,
            weight_kg=1.0,
            cargo_per_kg_rub=450,
            commission_pct=15,
            ads_pct=10,
            defect_pct=5,
            target_margin_pct=25,
        )
    )
    assert result.margin_pct < 25
    assert result.verdict in (Verdict.SKIP, Verdict.TEST)


def test_price_stats():
    p25, med, p75 = price_stats([10, 20, 30, 40, 50])
    assert med == 30
    assert p25 == 20
    assert p75 == 40
    assert price_stats([]) == (None, None, None)


def test_percentile_single():
    assert percentile([7.0], 50) == 7.0


def test_scoring_empty_sources_skip():
    score = compute_niche_score(
        wb=None,
        ozon=None,
        amazon=None,
        ebay=None,
        unit_econ=None,
        target_margin_pct=25,
    )
    assert score.total == 0
    assert score.verdict == Verdict.SKIP


def test_scoring_with_ebay_density():
    ebay = MarketplaceMetrics(
        source=Marketplace.EBAY,
        query="earbuds",
        item_count=50,
        price_median=29.0,
        currency="USD",
    )
    score = compute_niche_score(
        wb=None,
        ozon=None,
        amazon=None,
        ebay=ebay,
        unit_econ=None,
        target_margin_pct=25,
    )
    assert score.ebay_component > 0
    assert score.total > 0
