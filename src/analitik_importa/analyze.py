from __future__ import annotations

from datetime import date, timedelta

from analitik_importa.config import Settings, get_settings
from analitik_importa.models import Marketplace, NicheQuery, NicheReport, UnitEconInput
from analitik_importa.scoring import compute_niche_score
from analitik_importa.unit_econ import calculate


def _default_period() -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=30)
    return start.isoformat(), end.isoformat()


def analyze_niche(
    query: NicheQuery,
    *,
    settings: Settings | None = None,
    ebay_limit: int = 50,
    skip_ebay: bool = False,
    skip_mpstats: bool = False,
    skip_amazon: bool = False,
) -> NicheReport:
    settings = settings or get_settings()
    report = NicheReport(query=query)
    d1, d2 = _default_period()

    if not skip_ebay:
        try:
            from analitik_importa.clients.ebay import EbayClient

            report.ebay = EbayClient(settings).search(query.keywords, limit=ebay_limit)
        except Exception as exc:  # noqa: BLE001 — collect per-source errors in report
            report.errors.append(f"eBay: {exc}")

    if not skip_mpstats:
        try:
            from analitik_importa.clients.mpstats import MpstatsClient

            client = MpstatsClient(settings)
            wb_path = query.wb_category_path
            oz_path = query.ozon_category_path
            if wb_path:
                report.mpstats_wb = client.get_category("wb", wb_path, d1=d1, d2=d2)
            else:
                report.errors.append(
                    "MPSTATS WB skipped: pass --wb-path (category path), keywords alone are not enough"
                )
            if oz_path:
                report.mpstats_ozon = client.get_category("ozon", oz_path, d1=d1, d2=d2)
            else:
                report.errors.append(
                    "MPSTATS Ozon skipped: pass --ozon-path (category path)"
                )
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"MPSTATS: {exc}")

    if not skip_amazon:
        try:
            from analitik_importa.clients.amazon import AmazonClient

            report.amazon = AmazonClient(settings).search_items(query.keywords)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Amazon: {exc}")

    if query.cost_cny is not None and query.sell_rub is not None:
        weight = query.weight_kg if query.weight_kg is not None else settings.default_weight_kg
        mp = query.marketplace
        report.unit_econ = calculate(
            UnitEconInput(
                cost_cny=query.cost_cny,
                sell_rub=query.sell_rub,
                marketplace=mp,
                cny_rub_rate=settings.cny_rub_rate,
                weight_kg=weight,
                cargo_per_kg_rub=settings.cargo_per_kg_rub,
                commission_pct=settings.commission_pct_for(mp.value),
                ads_pct=settings.ads_pct,
                defect_pct=settings.defect_pct,
                target_margin_pct=settings.target_margin_pct,
            )
        )

    report.score = compute_niche_score(
        wb=report.mpstats_wb,
        ozon=report.mpstats_ozon,
        amazon=report.amazon,
        ebay=report.ebay,
        unit_econ=report.unit_econ,
        target_margin_pct=settings.target_margin_pct,
    )
    return report


def build_unit_econ_input(
    *,
    cost_cny: float,
    sell_rub: float,
    marketplace: str,
    weight_kg: float | None = None,
    settings: Settings | None = None,
) -> UnitEconInput:
    settings = settings or get_settings()
    mp = Marketplace(marketplace.lower())
    return UnitEconInput(
        cost_cny=cost_cny,
        sell_rub=sell_rub,
        marketplace=mp,
        cny_rub_rate=settings.cny_rub_rate,
        weight_kg=weight_kg if weight_kg is not None else settings.default_weight_kg,
        cargo_per_kg_rub=settings.cargo_per_kg_rub,
        commission_pct=settings.commission_pct_for(mp.value),
        ads_pct=settings.ads_pct,
        defect_pct=settings.defect_pct,
        target_margin_pct=settings.target_margin_pct,
    )
