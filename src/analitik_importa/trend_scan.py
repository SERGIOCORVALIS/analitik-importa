"""Automatic keyless scan: which China-import niches sell best right now.

Sources (public pages, no API keys):
- Yandex Market search  -> RU demand ("N купили"), prices, ratings, review counts
- Amazon.com search     -> global demand ("N+ bought in past month"), ratings
"""

from __future__ import annotations

import html
import json
import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

from pydantic import BaseModel, Field

from analitik_importa.catalog import NICHE_PRESETS, NichePreset
from analitik_importa.clients.public_web import (
    AmazonPublicScraper,
    BlockedError,
    ProductHit,
    YandexMarketScraper,
)
from analitik_importa.config import Settings, get_settings
from analitik_importa.models import Verdict
from analitik_importa.report import (
    VERDICT_BG,
    VERDICT_COLOR,
    VERDICT_RU,
    favicon_link_tags,
    reports_dir,
)
from analitik_importa.stats_util import price_stats

WEIGHTS = {"demand_ru": 40, "demand_world": 20, "competition": 15, "economics": 25}
FACTOR_RU = {
    "demand_ru": "Спрос в РФ (Я.Маркет)",
    "demand_world": "Мировой спрос (Amazon)",
    "competition": "Свободность ниши",
    "economics": "Экономика",
}
BLOCK_COOLDOWN_SEC = 75
MIN_PURCHASE_CNY = 5.0


class SourceStats(BaseModel):
    items: int = 0
    bought_total: int = 0
    bought_items: int = 0
    price_p25: float | None = None
    price_median: float | None = None
    price_p75: float | None = None
    avg_rating: float | None = None
    reviews_median: float | None = None
    top: list[ProductHit] = Field(default_factory=list)


class NicheScan(BaseModel):
    name: str
    section: str
    ru_query: str
    en_query: str
    weight_kg: float
    ym: SourceStats | None = None
    amazon: SourceStats | None = None
    max_cost_cny: float | None = None
    components: dict[str, float] = Field(default_factory=dict)
    total: float = 0.0
    verdict: Verdict = Verdict.SKIP
    rationale: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TopProduct(BaseModel):
    niche: str
    hit: ProductHit
    max_cost_cny: float | None = None


class ScanResult(BaseModel):
    generated_at: datetime
    niches: list[NicheScan]
    top_products: list[TopProduct] = Field(default_factory=list)
    assumptions: dict[str, float] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    duration_sec: float = 0.0


# ----------------------------------------------------------------- maths


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """0..100 rank of each value among the others (ties share the average rank)."""
    if not values:
        return {}
    if len(values) == 1:
        return {k: 50.0 for k in values}
    ordered = sorted(values.values())
    n = len(ordered)
    out = {}
    for key, v in values.items():
        below = sum(1 for x in ordered if x < v)
        equal = sum(1 for x in ordered if x == v)
        out[key] = (below + (equal - 1) / 2) / (n - 1) * 100.0
    return out


def _price_fit(price: float) -> float:
    """Price bands that usually work for China import on RU marketplaces."""
    if price < 400:
        return 15.0
    if price < 800:
        return 50.0
    if price < 1200:
        return 80.0
    if price <= 5000:
        return 100.0
    if price <= 12000:
        return 70.0
    return 40.0


def _variable_pct(s: Settings) -> float:
    commission = max(s.commission_wb_pct, s.commission_ozon_pct, s.commission_ym_pct)
    return (commission + s.ads_pct + s.defect_pct + s.target_margin_pct) / 100.0


def max_purchase_cny(sell_rub: float | None, weight_kg: float, s: Settings) -> float | None:
    """Highest China price (CNY) that still leaves the target margin at this sell price."""
    if not sell_rub:
        return None
    room = sell_rub * (1.0 - _variable_pct(s)) - weight_kg * s.cargo_per_kg_rub
    if room <= 0 or s.cny_rub_rate <= 0:
        return 0.0
    return round(room / s.cny_rub_rate, 1)


def summarize(hits: list[ProductHit], top_n: int = 5) -> SourceStats:
    prices = [h.price for h in hits if h.price]
    p25, med, p75 = price_stats(prices)
    ratings = [h.rating for h in hits if h.rating]
    reviews = [h.reviews for h in hits if h.reviews is not None]
    bought = [h.bought for h in hits if h.bought]
    ranked = sorted(hits, key=lambda h: (h.bought or 0, h.reviews or 0), reverse=True)
    return SourceStats(
        items=len(hits),
        bought_total=sum(bought),
        bought_items=len(bought),
        price_p25=p25,
        price_median=med,
        price_p75=p75,
        avg_rating=round(mean(ratings), 2) if ratings else None,
        reviews_median=median(reviews) if reviews else None,
        top=ranked[:top_n],
    )


def score_all(niches: list[NicheScan], s: Settings) -> None:
    """Demand and competition are ranked against the other niches of the same scan;
    economics is absolute (price band + room left for the China purchase)."""
    with_ym = {n.name: n for n in niches if n.ym and n.ym.items}
    demand_ru = percentile_ranks({k: n.ym.bought_total for k, n in with_ym.items()})
    competition = percentile_ranks(
        {k: -n.ym.reviews_median for k, n in with_ym.items() if n.ym.reviews_median is not None}
    )
    demand_world = percentile_ranks(
        {n.name: n.amazon.bought_total for n in niches if n.amazon and n.amazon.items}
    )

    for n in niches:
        comps: dict[str, float] = {}
        why: list[str] = []
        if n.name in demand_ru:
            comps["demand_ru"] = demand_ru[n.name]
            why.append(
                f"Я.Маркет: {n.ym.bought_items} из {n.ym.items} товаров первой страницы показывают покупки, "
                f"всего «купили» {n.ym.bought_total:,} шт. — больше, чем у {demand_ru[n.name]:.0f}% ниш скана.".replace(",", " ")
            )
        if n.name in competition:
            comps["competition"] = competition[n.name]
            why.append(
                f"Медиана оценок у товаров выдачи — {n.ym.reviews_median:.0f}: "
                + ("лидеры с большим числом отзывов, войти дороже." if competition[n.name] < 40 else "ниша не забита отзывами лидеров.")
            )
        if n.ym and n.ym.price_median:
            share = (n.max_cost_cny or 0) * s.cny_rub_rate / n.ym.price_median
            comps["economics"] = 0.5 * _price_fit(n.ym.price_median) + 0.5 * min(100.0, share / 0.35 * 100.0)
            why.append(
                f"Медианная цена {n.ym.price_median:,.0f} ₽ → закупка в Китае не дороже "
                f"{n.max_cost_cny or 0:.0f} ¥, чтобы сохранить маржу {s.target_margin_pct:.0f}%.".replace(",", " ")
            )
        if n.name in demand_world:
            comps["demand_world"] = demand_world[n.name]
            why.append(
                f"Amazon: {n.amazon.bought_items} товаров с отметкой «bought in past month», "
                f"в сумме не менее {n.amazon.bought_total:,} покупок за месяц.".replace(",", " ")
            )

        weight = sum(WEIGHTS[k] for k in comps)
        total = sum(comps[k] * WEIGHTS[k] for k in comps) / weight if weight else 0.0
        if weight and weight < 100:
            missing = [FACTOR_RU[k] for k in WEIGHTS if k not in comps]
            why.append("Нет данных: " + ", ".join(missing) + " — балл посчитан по остальным факторам.")
        if "demand_ru" not in comps:
            total = min(total, 39.0)
            why.append("Без данных о спросе в РФ ниша не рекомендуется — перезапустите скан позже.")
        elif n.max_cost_cny is not None and n.max_cost_cny < MIN_PURCHASE_CNY:
            total = min(total, 39.0)
            why.append(
                f"При медианной цене закупка должна быть дешевле {MIN_PURCHASE_CNY:.0f} ¥ — "
                "с карго и комиссиями такой товар в одиночку не окупится (только в наборах)."
            )

        n.components = {k: round(v, 1) for k, v in comps.items()}
        n.total = round(total, 1)
        n.verdict = Verdict.TAKE if total >= 65 else Verdict.TEST if total >= 40 else Verdict.SKIP
        n.rationale = why


# ------------------------------------------------------------------ scan

Progress = Callable[[int, int, str], None]


def _cache_path() -> Path:
    return scans_dir() / f"cache-{datetime.now().strftime('%Y%m%d')}.json"


def _load_cache() -> dict[str, dict[str, list[ProductHit]]]:
    path = _cache_path()
    if not path.exists():
        return {"ym": {}, "amazon": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {src: {q: [ProductHit.model_validate(h) for h in hits] for q, hits in raw.get(src, {}).items()} for src in ("ym", "amazon")}
    except (ValueError, OSError):
        return {"ym": {}, "amazon": {}}


def _save_cache(cache: dict[str, dict[str, list[ProductHit]]]) -> None:
    data = {src: {q: [h.model_dump() for h in hits] for q, hits in by_q.items()} for src, by_q in cache.items()}
    _cache_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _worker(
    name: str,
    scraper_factory: Callable[[], YandexMarketScraper | AmazonPublicScraper],
    jobs: list[tuple[int, str]],
    cached: dict[str, list[ProductHit]],
    out: dict[int, list[ProductHit] | str],
    events: queue.Queue,
    cooldown_sec: float,
) -> None:
    scraper = scraper_factory()
    blocked: str | None = None
    retried = False
    try:
        for idx, q in jobs:
            if q in cached:
                out[idx] = cached[q]
                events.put((name, f"{q} (сегодня уже собрано)"))
                continue
            while not blocked:
                try:
                    out[idx] = scraper.search(q)
                    break
                except BlockedError as exc:
                    if retried:
                        blocked = f"{name}: {exc}"
                        break
                    retried = True
                    events.put((name, f"капча, пауза {cooldown_sec:.0f} с и повтор", False))
                    time.sleep(cooldown_sec)
                except Exception as exc:  # network / parsing problems for a single query
                    out[idx] = f"{name}: {exc}"
                    break
            if blocked:
                out[idx] = blocked
            events.put((name, q))
    finally:
        scraper.close()
        events.put((name, None))


def run_scan(
    presets: list[NichePreset] | None = None,
    settings: Settings | None = None,
    progress: Progress | None = None,
    use_ym: bool = True,
    use_amazon: bool = True,
    use_cache: bool = True,
    cooldown_sec: float = BLOCK_COOLDOWN_SEC,
) -> ScanResult:
    s = settings or get_settings()
    presets = presets or NICHE_PRESETS
    started = datetime.now(timezone.utc)
    cache = _load_cache() if use_cache else {"ym": {}, "amazon": {}}
    ym_out: dict[int, list[ProductHit] | str] = {}
    amz_out: dict[int, list[ProductHit] | str] = {}
    events: queue.Queue = queue.Queue()
    threads = []
    if use_ym:
        jobs = [(i, p.search_ru) for i, p in enumerate(presets)]
        threads.append(
            threading.Thread(
                target=_worker,
                args=("Яндекс Маркет", lambda: YandexMarketScraper(min_delay=3.5), jobs, cache["ym"], ym_out, events, cooldown_sec),
            )
        )
    if use_amazon:
        jobs = [(i, p.keywords) for i, p in enumerate(presets)]
        threads.append(
            threading.Thread(
                target=_worker,
                args=("Amazon", AmazonPublicScraper, jobs, cache["amazon"], amz_out, events, cooldown_sec),
            )
        )
    for t in threads:
        t.start()

    total = len(presets) * len(threads)
    done = 0
    finished = 0
    while finished < len(threads):
        name, q, *flag = events.get()
        if q is None:
            finished += 1
            continue
        counts = not flag
        done += counts
        if progress:
            progress(done, total, f"{name}: {q}")
    for t in threads:
        t.join()

    for out, src, key in ((ym_out, "ym", "search_ru"), (amz_out, "amazon", "keywords")):
        for i, res in out.items():
            if isinstance(res, list) and res:
                cache[src][getattr(presets[i], key)] = res
    _save_cache(cache)

    niches: list[NicheScan] = []
    errors: set[str] = set()
    for i, p in enumerate(presets):
        n = NicheScan(name=p.name, section=p.section, ru_query=p.search_ru, en_query=p.keywords, weight_kg=p.weight_kg)
        for out, attr in ((ym_out, "ym"), (amz_out, "amazon")):
            if i not in out:
                continue
            res = out[i]
            if isinstance(res, str):
                n.errors.append(res)
                errors.add(res)
            elif res:
                setattr(n, attr, summarize(res))
            else:
                n.errors.append(f"{'Яндекс Маркет' if attr == 'ym' else 'Amazon'}: пустая выдача")
        if n.ym:
            n.max_cost_cny = max_purchase_cny(n.ym.price_median, p.weight_kg, s)
        niches.append(n)

    score_all(niches, s)
    niches.sort(key=lambda n: n.total, reverse=True)
    weights = {p.name: p.weight_kg for p in presets}
    tops = [
        TopProduct(niche=n.name, hit=h, max_cost_cny=max_purchase_cny(h.price, weights[n.name], s))
        for n in niches
        if n.ym
        for h in n.ym.top
        if h.bought
    ]
    tops.sort(key=lambda t: t.hit.bought or 0, reverse=True)

    return ScanResult(
        generated_at=started,
        niches=niches,
        top_products=tops[:30],
        assumptions={
            "cny_rub_rate": s.cny_rub_rate,
            "cargo_per_kg_rub": s.cargo_per_kg_rub,
            "commission_pct": max(s.commission_wb_pct, s.commission_ozon_pct, s.commission_ym_pct),
            "ads_pct": s.ads_pct,
            "defect_pct": s.defect_pct,
            "target_margin_pct": s.target_margin_pct,
        },
        errors=sorted(errors),
        duration_sec=round((datetime.now(timezone.utc) - started).total_seconds(), 1),
    )


# --------------------------------------------------------------- storage


def scans_dir() -> Path:
    d = reports_dir() / "scans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_scan(result: ScanResult) -> dict[str, Path]:
    stem = "scan-" + result.generated_at.astimezone().strftime("%Y%m%d-%H%M%S")
    json_path = scans_dir() / f"{stem}.json"
    html_path = scans_dir() / f"{stem}.html"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    html_path.write_text(scan_to_html(result), encoding="utf-8")
    return {"json": json_path, "html": html_path}


def list_scans() -> list[Path]:
    return sorted(scans_dir().glob("scan-*.json"), reverse=True)


def load_scan(path: Path) -> ScanResult:
    return ScanResult.model_validate_json(path.read_text(encoding="utf-8"))


def latest_scan() -> tuple[Path, ScanResult] | None:
    for path in list_scans():
        try:
            return path, load_scan(path)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ html


def _rub(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f} ₽".replace(",", " ")


def _int(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f}".replace(",", " ")


def scan_to_html(r: ScanResult) -> str:
    e = html.escape
    when = r.generated_at.astimezone().strftime("%d.%m.%Y %H:%M")
    counts = {v: sum(1 for n in r.niches if n.verdict == v) for v in Verdict}

    rows = []
    for i, n in enumerate(r.niches, 1):
        bar = f'<div class="bar"><span style="width:{n.total:.0f}%;background:{VERDICT_COLOR[n.verdict]}"></span></div>'
        rows.append(
            f"<tr><td>{i}</td><td><b>{e(n.name)}</b><div class='muted'>{e(n.section)}</div></td>"
            f"<td>{bar}<b>{n.total:.0f}</b></td>"
            f"<td><span class='pill' style='background:{VERDICT_BG[n.verdict]};color:{VERDICT_COLOR[n.verdict]}'>"
            f"{e(VERDICT_RU[n.verdict])}</span></td>"
            f"<td>{_int(n.ym.bought_total) if n.ym else '—'}</td>"
            f"<td>{_rub(n.ym.price_median) if n.ym else '—'}</td>"
            f"<td>{_int(n.ym.reviews_median) if n.ym else '—'}</td>"
            f"<td>{_int(n.amazon.bought_total) if n.amazon else '—'}</td>"
            f"<td>{'—' if n.max_cost_cny is None else f'{n.max_cost_cny:.0f} ¥'}</td></tr>"
        )

    cards = []
    for t in r.top_products[:12]:
        h = t.hit
        img = f'<img src="{e(h.image)}" alt=""/>' if h.image else ""
        cards.append(
            f'<a class="card" href="{e(h.url or "#")}" target="_blank">{img}'
            f'<div class="t">{e(h.title[:110])}</div>'
            f'<div class="muted">{e(t.niche)}</div>'
            f"<div><b>{_rub(h.price)}</b> · ★ {h.rating or '—'} · {_int(h.reviews)} оценок</div>"
            f"<div class='buy'>{e(h.bought_label or '')}</div>"
            f"<div class='muted'>закупка ≤ {'—' if t.max_cost_cny is None else f'{t.max_cost_cny:.0f} ¥'}</div></a>"
        )

    details = []
    for n in r.niches[:10]:
        lines = "".join(f"<li>{e(x)}</li>" for x in n.rationale + n.errors)
        details.append(f"<details><summary><b>{e(n.name)}</b> — {n.total:.0f}</summary><ul>{lines}</ul></details>")

    a = r.assumptions
    errors = "".join(f"<li>{e(x)}</li>" for x in r.errors)
    icons = favicon_link_tags()
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
{icons}
<title>Автопоиск товаров — {when}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:0;padding:24px}}
h1{{margin:0 0 4px}} .muted{{color:#64748b;font-size:12px}}
.kpis{{display:flex;gap:12px;margin:16px 0}} .kpi{{flex:1;background:#fff;border-radius:12px;padding:14px;border:1px solid #e2e8f0}}
.kpi b{{font-size:26px;display:block}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden}}
th,td{{padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:left;font-size:14px}} th{{background:#1d4ed8;color:#fff}}
.bar{{display:inline-block;width:90px;height:8px;background:#e2e8f0;border-radius:4px;margin-right:6px;vertical-align:middle}}
.bar span{{display:block;height:8px;border-radius:4px}}
.pill{{padding:3px 10px;border-radius:999px;font-weight:600;font-size:12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px;color:#0f172a;text-decoration:none;font-size:13px}}
.card img{{width:100%;height:160px;object-fit:contain}} .card .t{{font-weight:600;margin:6px 0}} .buy{{color:#047857;font-weight:600}}
details{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:8px 12px;margin:6px 0}}
</style></head><body>
<h1>Автопоиск товаров для импорта из Китая</h1>
<div class="muted">{when} · {len(r.niches)} ниш · сбор занял {r.duration_sec:.0f} c · источники: Яндекс Маркет (поиск), Amazon.com (поиск)</div>
<div class="kpis">
<div class="kpi" style="border-color:{VERDICT_COLOR[Verdict.TAKE]}"><b style="color:{VERDICT_COLOR[Verdict.TAKE]}">{counts[Verdict.TAKE]}</b>брать</div>
<div class="kpi" style="border-color:{VERDICT_COLOR[Verdict.TEST]}"><b style="color:{VERDICT_COLOR[Verdict.TEST]}">{counts[Verdict.TEST]}</b>тестовая партия</div>
<div class="kpi" style="border-color:{VERDICT_COLOR[Verdict.SKIP]}"><b style="color:{VERDICT_COLOR[Verdict.SKIP]}">{counts[Verdict.SKIP]}</b>не брать</div>
</div>
<h2>Рейтинг ниш</h2>
<table><tr><th>#</th><th>Ниша</th><th>Балл</th><th>Решение</th><th>Купили на Я.Маркете, шт</th>
<th>Медианная цена</th><th>Медиана оценок</th><th>Amazon, покупок/мес</th><th>Макс. закупка</th></tr>
{''.join(rows)}</table>
<h2>Самые покупаемые товары сегодня</h2><div class="grid">{''.join(cards)}</div>
<h2>Почему так (топ-10)</h2>{''.join(details)}
<h2>Как читать</h2>
<ul class="muted">
<li>«Купили» — счётчик, который Яндекс Маркет печатает на карточках первой страницы поиска; сумма по найденным товарам.</li>
<li>Amazon — отметки «N+ bought in past month» (нижняя граница) на первой странице поиска amazon.com. Это мировой, не российский спрос.</li>
<li>Макс. закупка — цена в Китае, при которой на медианной цене сохраняется маржа {a.get('target_margin_pct', 0):.0f}%:
курс {a.get('cny_rub_rate', 0)} ₽/¥, карго {a.get('cargo_per_kg_rub', 0):.0f} ₽/кг, комиссия {a.get('commission_pct', 0):.0f}%,
реклама {a.get('ads_pct', 0):.0f}%, брак {a.get('defect_pct', 0):.0f}%.</li>
<li>Wildberries, Ozon и eBay без API-ключей не отдают данные (защита от ботов); подключите MPSTATS для точных продаж WB/Ozon.</li>
</ul>
{f'<h2>Проблемы при сборе</h2><ul>{errors}</ul>' if errors else ''}
</body></html>"""
