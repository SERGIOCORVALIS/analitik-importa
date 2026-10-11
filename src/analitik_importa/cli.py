from __future__ import annotations

from typing import Optional

import typer

from analitik_importa.analyze import analyze_niche, build_unit_econ_input
from analitik_importa.config import get_settings
from analitik_importa.models import Marketplace, NicheQuery
from analitik_importa.report import (
    VERDICT_RU,
    dump_json,
    report_skeleton_markdown,
    save_report,
    unit_econ_to_markdown,
)
from analitik_importa.unit_econ import calculate

app = typer.Typer(
    name="analitik",
    help="China→RU marketplace import analytics (eBay + MPSTATS + Amazon Creators).",
    no_args_is_help=True,
)
ebay_app = typer.Typer(help="eBay Browse API")
mpstats_app = typer.Typer(help="MPSTATS WB/Ozon/YM")
amazon_app = typer.Typer(help="Amazon Creators API")
ozon_app = typer.Typer(help="Ozon Seller API (your own store)")
check_app = typer.Typer(help="Smoke-check live API credentials")

app.add_typer(ozon_app, name="ozon")
app.add_typer(ebay_app, name="ebay")
app.add_typer(mpstats_app, name="mpstats")
app.add_typer(amazon_app, name="amazon")
app.add_typer(check_app, name="check")


@app.command("econ")
def econ_cmd(
    cost_cny: float = typer.Option(..., help="Purchase cost in CNY"),
    sell_rub: float = typer.Option(..., help="Sell price on marketplace, RUB"),
    mp: str = typer.Option("wb", help="wb|ozon|ym|avito"),
    weight_kg: Optional[float] = typer.Option(None, help="Weight kg (default from .env)"),
    as_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Calculate unit economics for China→RU listing."""
    result = calculate(
        build_unit_econ_input(
            cost_cny=cost_cny,
            sell_rub=sell_rub,
            marketplace=mp,
            weight_kg=weight_kg,
        )
    )
    if as_json:
        typer.echo(dump_json(result))
    else:
        typer.echo(unit_econ_to_markdown(result))


@app.command("report-skeleton")
def report_skeleton_cmd(
    keywords: str = typer.Argument("<ниша>", help="Niche title for skeleton"),
) -> None:
    """Print empty niche report markdown template."""
    typer.echo(report_skeleton_markdown(keywords))


@ebay_app.command("search")
def ebay_search(
    keywords: str = typer.Argument(..., help="Search keywords"),
    limit: int = typer.Option(50, min=1, max=200),
    marketplace_id: Optional[str] = typer.Option(None, help="EBAY_US|EBAY_DE|..."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from analitik_importa.clients.ebay import EbayClient

    metrics = EbayClient().search(keywords, limit=limit, marketplace_id=marketplace_id)
    if as_json:
        typer.echo(dump_json(metrics))
    else:
        typer.echo(f"eBay items={metrics.item_count}")
        typer.echo(f"median={metrics.price_median} {metrics.currency}")
        typer.echo(f"p25={metrics.price_p25} p75={metrics.price_p75}")
        for item in metrics.top_listings[:10]:
            typer.echo(f"- {item.title[:90]} | {item.price} {item.currency}")


@mpstats_app.command("category")
def mpstats_category(
    mp: str = typer.Option(..., "--mp", help="wb|ozon|ym"),
    path: str = typer.Option(..., "--path", help="Category path"),
    date_from: str = typer.Option(..., "--from", help="YYYY-MM-DD"),
    date_to: str = typer.Option(..., "--to", help="YYYY-MM-DD"),
    end_row: int = typer.Option(100, help="endRow for grid request"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from analitik_importa.clients.mpstats import MpstatsClient

    if mp not in ("wb", "ozon", "ym"):
        raise typer.BadParameter("mp must be wb|ozon|ym")
    metrics = MpstatsClient().get_category(
        mp,  # type: ignore[arg-type]
        path,
        d1=date_from,
        d2=date_to,
        end_row=end_row,
    )
    if as_json:
        typer.echo(dump_json(metrics))
    else:
        typer.echo(f"{mp} path={path} items={metrics.item_count}")
        typer.echo(f"revenue={metrics.revenue} sales={metrics.sales} sellers={metrics.sellers}")
        typer.echo(f"median={metrics.price_median} RUB")
        for item in metrics.top_listings[:10]:
            typer.echo(f"- {item.title[:90]} | {item.price}")


@mpstats_app.command("item")
def mpstats_item(
    mp: str = typer.Option(..., "--mp", help="wb|ozon|ym"),
    item_id: str = typer.Option(..., "--id"),
    date_from: str = typer.Option(..., "--from"),
    date_to: str = typer.Option(..., "--to"),
) -> None:
    from analitik_importa.clients.mpstats import MpstatsClient

    if mp not in ("wb", "ozon", "ym"):
        raise typer.BadParameter("mp must be wb|ozon|ym")
    data = MpstatsClient().get_item(mp, item_id, d1=date_from, d2=date_to)  # type: ignore[arg-type]
    typer.echo(dump_json(data))


@amazon_app.command("search")
def amazon_search(
    keywords: str = typer.Argument(...),
    item_count: int = typer.Option(10, min=1, max=10),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from analitik_importa.clients.amazon import AmazonClient

    metrics = AmazonClient().search_items(keywords, item_count=item_count)
    if as_json:
        typer.echo(dump_json(metrics))
    else:
        typer.echo(f"Amazon items={metrics.item_count} rating≈{metrics.avg_rating}")
        typer.echo(f"median={metrics.price_median} {metrics.currency}")
        for note in metrics.notes:
            typer.echo(f"note: {note}")
        for item in metrics.top_listings:
            typer.echo(f"- {item.title[:90]} | {item.price} {item.currency}")


@check_app.command("ebay")
def check_ebay() -> None:
    from analitik_importa.clients.ebay import EbayClient

    typer.echo(dump_json(EbayClient().check()))


@check_app.command("mpstats")
def check_mpstats() -> None:
    from analitik_importa.clients.mpstats import MpstatsClient

    typer.echo(dump_json(MpstatsClient().check()))


@check_app.command("ozon")
def check_ozon() -> None:
    from analitik_importa.clients.ozon_seller import OzonSellerClient

    typer.echo(dump_json(OzonSellerClient().check()))


@ozon_app.command("products")
def ozon_products(
    limit: int = typer.Option(1000, min=1),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List products of your Ozon store."""
    from analitik_importa.clients.ozon_seller import OzonSellerClient

    items = OzonSellerClient().list_products(limit=limit)
    if as_json:
        typer.echo(dump_json(items))
        return
    typer.echo(f"Товаров: {len(items)}")
    for item in items:
        stock = "FBO" if item.get("has_fbo_stocks") else ("FBS" if item.get("has_fbs_stocks") else "нет остатков")
        archived = " [архив]" if item.get("archived") else ""
        typer.echo(f"- {item.get('offer_id')} | sku={item.get('sku')} | {stock}{archived}")


@check_app.command("amazon")
def check_amazon() -> None:
    from analitik_importa.clients.amazon import AmazonClient

    typer.echo(dump_json(AmazonClient().check()))


@app.command("analyze")
def analyze_cmd(
    keywords: str = typer.Argument(..., help="Niche keywords"),
    wb_path: Optional[str] = typer.Option(None, "--wb-path"),
    ozon_path: Optional[str] = typer.Option(None, "--ozon-path"),
    cost_cny: Optional[float] = typer.Option(None),
    sell_rub: Optional[float] = typer.Option(None),
    weight_kg: Optional[float] = typer.Option(None),
    mp: str = typer.Option("wb", help="Marketplace for unit econ"),
    ebay_limit: int = typer.Option(50),
    skip_ebay: bool = typer.Option(False),
    skip_mpstats: bool = typer.Option(False),
    skip_amazon: bool = typer.Option(False),
    save: bool = typer.Option(True, help="Write reports/*.md|json|html|xml"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run multi-source niche analysis and optional unit economics."""
    query = NicheQuery(
        keywords=keywords,
        wb_category_path=wb_path,
        ozon_category_path=ozon_path,
        cost_cny=cost_cny,
        sell_rub=sell_rub,
        weight_kg=weight_kg,
        marketplace=Marketplace(mp.lower()),
    )
    report = analyze_niche(
        query,
        ebay_limit=ebay_limit,
        skip_ebay=skip_ebay,
        skip_mpstats=skip_mpstats,
        skip_amazon=skip_amazon,
    )
    if save:
        paths = save_report(report)
        for kind, path in paths.items():
            typer.echo(f"saved ({kind}): {path}")
        # Prefer colorful HTML in console tip
        typer.echo(f"Откройте цветной отчёт: {paths['html']}")
    if as_json:
        typer.echo(dump_json(report))
    else:
        from analitik_importa.report import niche_report_to_markdown

        typer.echo(niche_report_to_markdown(report))


@app.command("scan")
def scan_cmd(
    limit: int = typer.Option(0, help="Scan only the first N niches (0 = all)"),
    skip_amazon: bool = typer.Option(False),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done"),
) -> None:
    """Keyless auto-scan of all niches: Yandex Market + Amazon public search."""
    from analitik_importa.catalog import NICHE_PRESETS
    from analitik_importa.trend_scan import run_scan, save_scan

    presets = NICHE_PRESETS[:limit] if limit else NICHE_PRESETS
    typer.echo(f"Сканирую {len(presets)} ниш (Яндекс Маркет{'' if skip_amazon else ' + Amazon'})…")
    result = run_scan(
        presets,
        use_amazon=not skip_amazon,
        progress=lambda done, total, msg: typer.echo(f"  [{done}/{total}] {msg}"),
    )
    paths = save_scan(result)
    typer.echo("")
    typer.echo(f"{'#':>2}  {'Балл':>4}  {'Решение':<20} Ниша")
    for i, n in enumerate(result.niches, 1):
        typer.echo(f"{i:>2}  {n.total:>4.0f}  {VERDICT_RU[n.verdict]:<20} {n.name}")
    for err in result.errors:
        typer.echo(f"! {err}")
    typer.echo(f"\nОтчёт: {paths['html']}")
    if open_report:
        typer.launch(str(paths["html"]))


@app.callback()
def _main() -> None:
    # Ensure settings load early for clearer env errors in subcommands.
    get_settings()


if __name__ == "__main__":
    app()
