from __future__ import annotations

import base64
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from xml.dom import minidom

from analitik_importa.config import ROOT_DIR
from analitik_importa.models import MarketplaceMetrics, NicheReport, UnitEconResult, Verdict


def reports_dir() -> Path:
    path = ROOT_DIR / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def favicon_link_tags() -> str:
    """Embed favicon as data URIs so standalone HTML reports work offline."""
    assets = ROOT_DIR / "assets"
    tags: list[str] = []
    mapping = [
        ("favicon.ico", "image/x-icon", None),
        ("favicon-32.png", "image/png", "32x32"),
        ("favicon-16.png", "image/png", "16x16"),
    ]
    for name, mime, sizes in mapping:
        path = assets / name
        if not path.is_file():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        size_attr = f' sizes="{sizes}"' if sizes else ""
        tags.append(f'<link rel="icon" type="{mime}"{size_attr} href="data:{mime};base64,{data}" />')
    return "\n  ".join(tags)


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE)
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:80] or "niche"


def _fmt_num(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{digits}f}".replace(",", " ")
    return f"{value:,}".replace(",", " ")


def _fmt_money(value: float | None, currency: str | None = None) -> str:
    if value is None:
        return "—"
    cur = f" {currency}" if currency else ""
    return f"{_fmt_num(value)}{cur}"


VERDICT_RU = {
    Verdict.TAKE: "БРАТЬ",
    Verdict.TEST: "ТЕСТ (малая партия)",
    Verdict.SKIP: "НЕ БРАТЬ",
}

VERDICT_COLOR = {
    Verdict.TAKE: "#0f766e",
    Verdict.TEST: "#b45309",
    Verdict.SKIP: "#b91c1c",
}

VERDICT_BG = {
    Verdict.TAKE: "#ccfbf1",
    Verdict.TEST: "#ffedd5",
    Verdict.SKIP: "#fee2e2",
}


def report_skeleton_markdown(keywords: str = "<ниша>") -> str:
    return f"""# Отчёт по нише: {keywords}

Дата: {datetime.now(timezone.utc).date().isoformat()}

## 1. Ниша / пример SKU
- Описание:
- Пример SKU:

## 2. Площадки (спрос)
| Источник | Метрики | Комментарий |
|----------|---------|-------------|
| WB (MPSTATS) | | |
| Ozon (MPSTATS) | | |
| eBay | | |
| Amazon (каталог) | | Amazon ≠ объём продаж РФ |

## 3. Юнит-экономика (Китай → РФ)
- Закупка CNY:
- Курс:
- Карго:
- Цена продажи:
- Маржа %:
- Вердикт:

## 4. Риски
- Сертификация / маркировка:
- Вес / габариты:
- Возвраты / брак:

## 5. Вердикт
- take / test / skip
- Почему:
- Источники и дата выгрузки:
"""


def unit_econ_to_markdown(r: UnitEconResult) -> str:
    return "\n".join(
        [
            f"- Площадка: `{r.marketplace.value}`",
            f"- Себестоимость с доставкой: {_fmt_num(r.landed_cost_rub)} ₽",
            f"- Все затраты: {_fmt_num(r.total_costs_rub)} ₽",
            f"- Прибыль с единицы: {_fmt_num(r.profit_rub)} ₽",
            f"- Маржа: {_fmt_num(r.margin_pct)}%",
            f"- Точка безубытка (цена): {_fmt_num(r.breakeven_sell_rub)} ₽",
            f"- Вердикт: **{VERDICT_RU.get(r.verdict, r.verdict.value)}**",
        ]
    )


def niche_report_to_markdown(report: NicheReport) -> str:
    lines = [
        f"# Отчёт по нише: {report.query.keywords}",
        f"Сформирован (UTC): {report.generated_at.isoformat()}",
        "",
    ]
    if report.score:
        v = report.score.verdict
        lines += [
            "## Итог",
            f"- Балл: **{_fmt_num(report.score.total)} / 100**",
            f"- Решение: **{VERDICT_RU.get(v, v.value)}** (`{v.value}`)",
            f"- MPSTATS (РФ): {_fmt_num(report.score.mpstats_component)}",
            f"- Amazon (каталог): {_fmt_num(report.score.amazon_component)}",
            f"- eBay: {_fmt_num(report.score.ebay_component)}",
            f"- Маржа: {_fmt_num(report.score.margin_component)}",
            "",
            "### Почему так",
        ]
        lines += [f"- {x}" for x in report.score.rationale]
        lines.append("")

    def block(title: str, metrics: MarketplaceMetrics | None) -> None:
        lines.append(f"## {title}")
        if metrics is None:
            lines.append("_нет данных_")
            lines.append("")
            return
        lines.append(f"- Карточек/листингов: {metrics.item_count}")
        lines.append(f"- Медианная цена: {_fmt_money(metrics.price_median, metrics.currency)}")
        lines.append(
            f"- Ценовой коридор P25–P75: "
            f"{_fmt_money(metrics.price_p25, metrics.currency)} — "
            f"{_fmt_money(metrics.price_p75, metrics.currency)}"
        )
        if metrics.revenue is not None:
            lines.append(f"- Выручка (оценка): {_fmt_num(metrics.revenue)} {metrics.currency or ''}".rstrip())
        if metrics.sales is not None:
            lines.append(f"- Продажи (шт., оценка): {_fmt_num(metrics.sales, 0)}")
        if metrics.sellers is not None:
            lines.append(f"- Продавцов: {metrics.sellers}")
        if metrics.avg_rating is not None:
            lines.append(f"- Средний рейтинг: {_fmt_num(metrics.avg_rating)}")
        for note in metrics.notes:
            lines.append(f"- Примечание: {note}")
        if metrics.top_listings:
            lines.append("- Топ позиций:")
            for item in metrics.top_listings[:5]:
                lines.append(
                    f"  - {item.title[:80]} | {_fmt_money(item.price, item.currency)}"
                )
        lines.append("")

    block("eBay (глобальный ориентир цены)", report.ebay)
    block("Wildberries (MPSTATS)", report.mpstats_wb)
    block("Ozon (MPSTATS)", report.mpstats_ozon)
    block("Amazon (каталог / цена / рейтинг)", report.amazon)

    lines.append("## Юнит-экономика (Китай → РФ)")
    if report.unit_econ:
        lines.append(unit_econ_to_markdown(report.unit_econ))
    else:
        lines.append("_не считалась — передайте --cost-cny и --sell-rub_")
    lines.append("")

    if report.errors:
        lines.append("## Ошибки / пропуски")
        lines += [f"- {e}" for e in report.errors]
        lines.append("")

    lines.append(
        "## Важно\n"
        "- Amazon Creators API — каталог/цена/рейтинг, не объём продаж в РФ.\n"
        "- Цифры только из API/заглушек или явных параметров экономики.\n"
    )
    return "\n".join(lines)


def _metric_cards_html(m: MarketplaceMetrics | None) -> str:
    if m is None:
        return '<p class="empty">Нет данных по этому источнику</p>'
    rows = [
        ("Листингов", str(m.item_count)),
        ("Медиана цены", _fmt_money(m.price_median, m.currency)),
        ("P25", _fmt_money(m.price_p25, m.currency)),
        ("P75", _fmt_money(m.price_p75, m.currency)),
    ]
    if m.revenue is not None:
        rows.append(("Выручка", _fmt_num(m.revenue)))
    if m.sales is not None:
        rows.append(("Продажи, шт.", _fmt_num(m.sales, 0)))
    if m.sellers is not None:
        rows.append(("Продавцы", str(m.sellers)))
    if m.avg_rating is not None:
        rows.append(("Рейтинг", _fmt_num(m.avg_rating)))

    cards = "".join(
        f'<div class="metric"><div class="metric-label">{html.escape(k)}</div>'
        f'<div class="metric-value">{html.escape(v)}</div></div>'
        for k, v in rows
    )
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in m.notes)
    listings = ""
    if m.top_listings:
        items = "".join(
            "<tr>"
            f"<td>{html.escape(item.title[:90])}</td>"
            f"<td>{html.escape(_fmt_money(item.price, item.currency))}</td>"
            "</tr>"
            for item in m.top_listings[:8]
        )
        listings = (
            '<table class="listings"><thead><tr><th>Товар</th><th>Цена</th></tr></thead>'
            f"<tbody>{items}</tbody></table>"
        )
    return (
        f'<div class="metrics-grid">{cards}</div>'
        f'<ul class="notes">{notes}</ul>'
        f"{listings}"
    )


def niche_report_to_html(report: NicheReport) -> str:
    score = report.score
    verdict = score.verdict if score else Verdict.SKIP
    verdict_label = VERDICT_RU.get(verdict, verdict.value)
    color = VERDICT_COLOR[verdict]
    bg = VERDICT_BG[verdict]
    total = _fmt_num(score.total) if score else "—"

    bars = ""
    if score:
        parts = [
            ("MPSTATS РФ", score.mpstats_component, "#2563eb"),
            ("Amazon", score.amazon_component, "#7c3aed"),
            ("eBay", score.ebay_component, "#0891b2"),
            ("Маржа", score.margin_component, "#059669"),
        ]
        for label, value, bar_color in parts:
            width = max(0, min(100, value))
            bars += (
                f'<div class="bar-row"><span>{html.escape(label)}</span>'
                f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%;'
                f'background:{bar_color}"></div></div>'
                f"<strong>{_fmt_num(value)}</strong></div>"
            )

    rationale = ""
    if score and score.rationale:
        rationale = "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in score.rationale) + "</ul>"

    econ_html = '<p class="empty">Не считалась — укажите --cost-cny и --sell-rub</p>'
    if report.unit_econ:
        e = report.unit_econ
        econ_html = f"""
        <div class="metrics-grid">
          <div class="metric"><div class="metric-label">Площадка</div><div class="metric-value">{html.escape(e.marketplace.value.upper())}</div></div>
          <div class="metric"><div class="metric-label">Себестоимость</div><div class="metric-value">{html.escape(_fmt_num(e.landed_cost_rub))} ₽</div></div>
          <div class="metric"><div class="metric-label">Все затраты</div><div class="metric-value">{html.escape(_fmt_num(e.total_costs_rub))} ₽</div></div>
          <div class="metric"><div class="metric-label">Прибыль</div><div class="metric-value">{html.escape(_fmt_num(e.profit_rub))} ₽</div></div>
          <div class="metric accent"><div class="metric-label">Маржа</div><div class="metric-value">{html.escape(_fmt_num(e.margin_pct))}%</div></div>
          <div class="metric"><div class="metric-label">Безубыток</div><div class="metric-value">{html.escape(_fmt_num(e.breakeven_sell_rub))} ₽</div></div>
        </div>
        <p class="inline-verdict" style="color:{VERDICT_COLOR[e.verdict]}">
          Вердикт экономики: <strong>{html.escape(VERDICT_RU[e.verdict])}</strong>
        </p>
        """

    errors = ""
    if report.errors:
        errors = (
            '<section class="card warn"><h2>Ошибки / пропуски</h2><ul>'
            + "".join(f"<li>{html.escape(e)}</li>" for e in report.errors)
            + "</ul></section>"
        )

    title = html.escape(report.query.keywords)
    generated = html.escape(report.generated_at.isoformat())

    icons = favicon_link_tags()
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Отчёт: {title}</title>
  {icons}
  <style>
    :root {{
      --bg: #f4f7fb;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --accent: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Gill Sans", Candara, Calibri, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(1200px 500px at 10% -10%, #dbeafe 0%, transparent 55%),
        radial-gradient(900px 400px at 100% 0%, #d1fae5 0%, transparent 50%),
        var(--bg);
      line-height: 1.45;
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 18px 48px; }}
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #0f766e 120%);
      color: #fff;
      border-radius: 22px;
      padding: 28px 26px;
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.22);
    }}
    .hero h1 {{ margin: 0 0 8px; font-size: 1.85rem; letter-spacing: -0.02em; }}
    .hero .sub {{ opacity: 0.85; font-size: 0.95rem; }}
    .badge {{
      display: inline-block;
      margin-top: 16px;
      padding: 10px 16px;
      border-radius: 999px;
      font-weight: 700;
      letter-spacing: 0.02em;
      background: {bg};
      color: {color};
      border: 2px solid {color};
    }}
    .score-big {{
      margin-top: 14px;
      font-size: 2.4rem;
      font-weight: 800;
    }}
    .grid {{ display: grid; gap: 16px; margin-top: 18px; }}
    @media (min-width: 800px) {{
      .grid-2 {{ grid-template-columns: 1fr 1fr; }}
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px 18px 14px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}
    .card h2 {{
      margin: 0 0 12px;
      font-size: 1.1rem;
      color: #1e293b;
    }}
    .card.wb {{ border-top: 4px solid #8b5cf6; }}
    .card.ozon {{ border-top: 4px solid #005bff; }}
    .card.ebay {{ border-top: 4px solid #e53238; }}
    .card.amazon {{ border-top: 4px solid #ff9900; }}
    .card.econ {{ border-top: 4px solid #059669; }}
    .card.warn {{ border-top: 4px solid #dc2626; background: #fff7f7; }}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
    }}
    .metric {{
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
    }}
    .metric.accent {{ background: #ecfdf5; border-color: #a7f3d0; }}
    .metric-label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric-value {{ font-size: 1.05rem; font-weight: 700; margin-top: 4px; }}
    .notes {{ color: var(--muted); font-size: 0.9rem; padding-left: 18px; }}
    .listings {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.92rem; }}
    .listings th, .listings td {{ border-bottom: 1px solid var(--line); text-align: left; padding: 8px 6px; }}
    .listings th {{ color: var(--muted); font-weight: 600; font-size: 0.8rem; }}
    .bar-row {{ display: grid; grid-template-columns: 110px 1fr 52px; gap: 10px; align-items: center; margin: 8px 0; }}
    .bar-track {{ height: 12px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }}
    .bar-fill {{ height: 100%; border-radius: 999px; }}
    .empty {{ color: var(--muted); font-style: italic; }}
    .inline-verdict {{ margin-top: 12px; }}
    footer {{ margin-top: 18px; color: var(--muted); font-size: 0.85rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <div class="sub">Аналитика импорта · Китай → РФ маркетплейсы</div>
      <h1>{title}</h1>
      <div class="sub">Сформирован: {generated}</div>
      <div class="score-big">{html.escape(total)} <span style="font-size:1rem;font-weight:500">/ 100</span></div>
      <div class="badge">{html.escape(verdict_label)}</div>
    </header>

    <section class="card" style="margin-top:18px">
      <h2>Разбивка балла</h2>
      {bars or '<p class="empty">Нет скоринга</p>'}
      <h2 style="margin-top:18px">Почему так</h2>
      {rationale or '<p class="empty">Нет пояснений</p>'}
    </section>

    <div class="grid grid-2">
      <section class="card wb"><h2>Wildberries (MPSTATS)</h2>{_metric_cards_html(report.mpstats_wb)}</section>
      <section class="card ozon"><h2>Ozon (MPSTATS)</h2>{_metric_cards_html(report.mpstats_ozon)}</section>
      <section class="card ebay"><h2>eBay</h2>{_metric_cards_html(report.ebay)}</section>
      <section class="card amazon"><h2>Amazon (каталог)</h2>{_metric_cards_html(report.amazon)}</section>
    </div>

    <section class="card econ" style="margin-top:16px">
      <h2>Юнит-экономика (Китай → РФ)</h2>
      {econ_html}
    </section>

    {errors}

    <footer>
      Amazon = каталог/цена/рейтинг, не объём продаж РФ. Цифры из API или заглушек (STUB), без выдуманных метрик.
    </footer>
  </div>
</body>
</html>
"""


def _xml_text(parent: ET.Element, tag: str, text: str | None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = "" if text is None else str(text)
    return el


def _metrics_to_xml(parent: ET.Element, tag: str, m: MarketplaceMetrics | None) -> None:
    node = ET.SubElement(parent, tag)
    if m is None:
        node.set("available", "false")
        return
    node.set("available", "true")
    node.set("source", m.source.value)
    _xml_text(node, "query", m.query)
    _xml_text(node, "itemCount", str(m.item_count))
    _xml_text(node, "priceMedian", None if m.price_median is None else str(m.price_median))
    _xml_text(node, "priceP25", None if m.price_p25 is None else str(m.price_p25))
    _xml_text(node, "priceP75", None if m.price_p75 is None else str(m.price_p75))
    _xml_text(node, "currency", m.currency)
    if m.revenue is not None:
        _xml_text(node, "revenue", str(m.revenue))
    if m.sales is not None:
        _xml_text(node, "sales", str(m.sales))
    if m.sellers is not None:
        _xml_text(node, "sellers", str(m.sellers))
    if m.avg_rating is not None:
        _xml_text(node, "avgRating", str(m.avg_rating))
    notes = ET.SubElement(node, "notes")
    for note in m.notes:
        _xml_text(notes, "note", note)
    listings = ET.SubElement(node, "topListings")
    for item in m.top_listings[:10]:
        li = ET.SubElement(listings, "listing")
        _xml_text(li, "title", item.title)
        _xml_text(li, "price", None if item.price is None else str(item.price))
        _xml_text(li, "currency", item.currency)
        if item.url:
            _xml_text(li, "url", item.url)


def niche_report_to_data_xml(report: NicheReport) -> str:
    """Machine-readable structured XML (no styling)."""
    root = ET.Element("NicheReport")
    root.set("version", "1.0")
    root.set("generatedAt", report.generated_at.isoformat())

    query = ET.SubElement(root, "Query")
    _xml_text(query, "keywords", report.query.keywords)
    if report.query.wb_category_path:
        _xml_text(query, "wbPath", report.query.wb_category_path)
    if report.query.ozon_category_path:
        _xml_text(query, "ozonPath", report.query.ozon_category_path)

    summary = ET.SubElement(root, "Summary")
    if report.score:
        _xml_text(summary, "score", str(report.score.total))
        _xml_text(summary, "verdict", report.score.verdict.value)
        _xml_text(summary, "verdictRu", VERDICT_RU[report.score.verdict])
        comps = ET.SubElement(summary, "components")
        _xml_text(comps, "mpstats", str(report.score.mpstats_component))
        _xml_text(comps, "amazon", str(report.score.amazon_component))
        _xml_text(comps, "ebay", str(report.score.ebay_component))
        _xml_text(comps, "margin", str(report.score.margin_component))
        rationale = ET.SubElement(summary, "rationale")
        for item in report.score.rationale:
            _xml_text(rationale, "item", item)

    sources = ET.SubElement(root, "Sources")
    _metrics_to_xml(sources, "Wildberries", report.mpstats_wb)
    _metrics_to_xml(sources, "Ozon", report.mpstats_ozon)
    _metrics_to_xml(sources, "Ebay", report.ebay)
    _metrics_to_xml(sources, "Amazon", report.amazon)

    econ = ET.SubElement(root, "UnitEconomics")
    if report.unit_econ:
        e = report.unit_econ
        econ.set("available", "true")
        _xml_text(econ, "marketplace", e.marketplace.value)
        _xml_text(econ, "landedCostRub", str(e.landed_cost_rub))
        _xml_text(econ, "totalCostsRub", str(e.total_costs_rub))
        _xml_text(econ, "profitRub", str(e.profit_rub))
        _xml_text(econ, "marginPct", str(e.margin_pct))
        _xml_text(econ, "breakevenSellRub", str(e.breakeven_sell_rub))
        _xml_text(econ, "verdict", e.verdict.value)
        _xml_text(econ, "verdictRu", VERDICT_RU[e.verdict])
    else:
        econ.set("available", "false")

    if report.errors:
        errors = ET.SubElement(root, "Errors")
        for err in report.errors:
            _xml_text(errors, "error", err)

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    parsed = minidom.parseString(xml_bytes)
    pretty = parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    lines = [ln for ln in pretty.splitlines() if ln.strip()]
    return "\n".join(lines) + "\n"


def niche_report_to_xml(report: NicheReport) -> str:
    """Colorful XHTML report (valid XML) — open in a browser for styled view."""
    body = niche_report_to_html(report)
    body = body.replace("<!DOCTYPE html>\n", "", 1)
    body = body.replace(
        '<html lang="ru">',
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="ru" xml:lang="ru">',
        1,
    )
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body.strip() + "\n"


def save_report(report: NicheReport) -> dict[str, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = reports_dir() / f"{slugify(report.query.keywords)}-{stamp}"
    paths = {
        "md": base.with_suffix(".md"),
        "json": base.with_suffix(".json"),
        "html": base.with_suffix(".html"),
        "xml": base.with_suffix(".xml"),
        "data_xml": Path(str(base) + ".data.xml"),
    }
    paths["md"].write_text(niche_report_to_markdown(report), encoding="utf-8")
    paths["json"].write_text(report.model_dump_json(indent=2), encoding="utf-8")
    paths["html"].write_text(niche_report_to_html(report), encoding="utf-8")
    paths["xml"].write_text(niche_report_to_xml(report), encoding="utf-8")
    paths["data_xml"].write_text(niche_report_to_data_xml(report), encoding="utf-8")
    return paths


def dump_json(data: object) -> str:
    if hasattr(data, "model_dump"):
        return json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
