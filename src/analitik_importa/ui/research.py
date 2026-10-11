from __future__ import annotations

from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from analitik_importa.analyze import analyze_niche
from analitik_importa.catalog import NICHE_PRESETS, PRESETS_BY_LABEL, builtin_category_paths, split_path
from analitik_importa.config import Settings
from analitik_importa.models import (
    Marketplace,
    MarketplaceMetrics,
    NicheQuery,
    NicheReport,
    UnitEconInput,
    UnitEconResult,
    Verdict,
)
from analitik_importa.report import VERDICT_COLOR, VERDICT_RU, reports_dir, save_report
from analitik_importa.trend_scan import FACTOR_RU, WEIGHTS, ScanResult, latest_scan, run_scan, save_scan
from analitik_importa.ui import nav
from analitik_importa.ui.common import MP_LABELS, Kpi, fmt_num, fmt_rub, hero, kpi_row, settings, verdict_banner
from analitik_importa.unit_econ import calculate

CUSTOM_NICHE = "Своя ниша (ввести вручную)"


@st.cache_data(ttl=600, show_spinner=False)
def load_reports(_mtime_key: float) -> list[tuple[Path, NicheReport]]:
    items: list[tuple[Path, NicheReport]] = []
    for path in sorted(reports_dir().glob("*.json"), reverse=True):
        try:
            items.append((path, NicheReport.model_validate_json(path.read_text(encoding="utf-8"))))
        except ValueError:
            continue
    return items


def reports() -> list[tuple[Path, NicheReport]]:
    files = list(reports_dir().glob("*.json"))
    key = max((f.stat().st_mtime for f in files), default=0.0) + len(files)
    return load_reports(key)


def reports_table(items: list[tuple[Path, NicheReport]]) -> pd.DataFrame:
    rows = []
    for path, r in items:
        sources = [m for m in (r.ebay, r.mpstats_wb, r.mpstats_ozon, r.amazon) if m is not None]
        if not sources:
            data_label = "только экономика"
        elif any("STUB" in note for m in sources for note in m.notes):
            data_label = "тестовые"
        else:
            data_label = "живые"
        rows.append(
            {
                "Дата": r.generated_at.astimezone().strftime("%d.%m.%Y %H:%M"),
                "Ниша": r.query.keywords,
                "Балл": r.score.total if r.score else None,
                "Решение": VERDICT_RU[r.score.verdict] if r.score else "—",
                "Маржа, %": r.unit_econ.margin_pct if r.unit_econ else None,
                "Прибыль/шт, ₽": r.unit_econ.profit_rub if r.unit_econ else None,
                "Данные": data_label,
                "Файл": path.stem,
            }
        )
    return pd.DataFrame(rows)


def score_chart(r: NicheReport) -> alt.Chart:
    s = r.score
    data = pd.DataFrame(
        [
            {"Фактор": "Спрос в РФ (MPSTATS)", "Балл": s.mpstats_component, "Вес": "55%"},
            {"Фактор": "Amazon", "Балл": s.amazon_component, "Вес": "20%"},
            {"Фактор": "eBay", "Балл": s.ebay_component, "Вес": "15%"},
            {"Фактор": "Маржа", "Балл": s.margin_component, "Вес": "10%"},
        ]
    )
    return (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=6)
        .encode(
            x=alt.X("Балл:Q", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Фактор:N", sort=None, title=None),
            color=alt.Color(
                "Балл:Q",
                scale=alt.Scale(domain=[0, 40, 65, 100], range=["#dc2626", "#f59e0b", "#10b981", "#047857"]),
                legend=None,
            ),
            tooltip=["Фактор", "Балл", "Вес"],
        )
        .properties(height=190)
    )


def cost_chart(e: UnitEconResult, sell_rub: float) -> alt.Chart:
    parts = [
        ("Закупка в Китае", e.cost_rub, "#64748b"),
        ("Карго до РФ", e.cargo_rub, "#94a3b8"),
        ("Комиссия МП", e.commission_rub, "#f59e0b"),
        ("Реклама", e.ads_rub, "#fb923c"),
        ("Брак / возвраты", e.defect_rub, "#f87171"),
        ("Логистика МП", e.logistics_mp_rub, "#a78bfa"),
        ("Прибыль" if e.profit_rub >= 0 else "Убыток", e.profit_rub, "#10b981" if e.profit_rub >= 0 else "#dc2626"),
    ]
    data = pd.DataFrame(
        [
            {
                "Статья": name,
                "₽": round(value, 2),
                "Доля цены, %": round(value / sell_rub * 100, 1) if sell_rub else 0,
                "color": color,
            }
            for name, value, color in parts
            if value
        ]
    )
    return (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=6)
        .encode(
            x=alt.X("₽:Q", title="₽ с одной продажи"),
            y=alt.Y("Статья:N", sort=None, title=None),
            color=alt.Color("color:N", scale=None, legend=None),
            tooltip=["Статья", "₽", "Доля цены, %"],
        )
        .properties(height=260)
    )


def metrics_block(title: str, m: MarketplaceMetrics | None, rub: bool) -> None:
    st.markdown(f"**{title}**")
    if m is None:
        st.caption("Нет данных по источнику")
        return
    if any("STUB" in n for n in m.notes):
        st.caption("⚠ тестовые данные (заглушка)")
    cur = "₽" if rub else (m.currency or "")
    c1, c2 = st.columns(2)
    c1.metric("Медианная цена", f"{fmt_num(m.price_median, 0 if rub else 2)} {cur}")
    c2.metric("Позиций", fmt_num(m.item_count))
    if rub:
        c3, c4 = st.columns(2)
        c3.metric("Продажи, шт", fmt_num(m.sales))
        c4.metric("Продавцов", fmt_num(m.sellers))
        if m.revenue is not None:
            st.metric("Выручка за период", fmt_rub(m.revenue))
    else:
        c3, c4 = st.columns(2)
        c3.metric("Коридор цен P25–P75", f"{fmt_num(m.price_p25, 2)}–{fmt_num(m.price_p75, 2)}")
        c4.metric("Рейтинг", fmt_num(m.avg_rating, 2) if m.avg_rating else "—")
    if m.top_listings:
        with st.expander("Топ позиций"):
            st.dataframe(
                pd.DataFrame([{"Товар": li.title, "Цена": li.price, "Валюта": li.currency} for li in m.top_listings]),
                hide_index=True,
                width="stretch",
            )


def render_report(r: NicheReport) -> None:
    if r.score:
        verdict_banner(
            r.score.verdict,
            f"Ниша «{r.query.keywords}» — {fmt_num(r.score.total, 1)} из 100",
            "Порог: от 65 — брать, 40–65 — тестовая партия, ниже 40 — не брать.",
        )
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Из чего сложился балл")
        if r.score:
            st.altair_chart(score_chart(r), width="stretch")
            with st.expander("Подробное обоснование"):
                for line in r.score.rationale:
                    st.write("•", line)
    with right:
        st.subheader("Экономика единицы")
        e = r.unit_econ
        if e:
            st.metric("Маржа", f"{e.margin_pct:.1f}%")
            st.metric("Прибыль с продажи", fmt_rub(e.profit_rub))
            st.metric("Цена безубыточности", fmt_rub(e.breakeven_sell_rub))
            st.caption(f"Площадка: {MP_LABELS.get(e.marketplace.value, e.marketplace.value)}")
        else:
            st.caption("Не считалась — укажите закупку в CNY и цену продажи.")

    st.subheader("Данные по площадкам")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metrics_block("Wildberries", r.mpstats_wb, rub=True)
    with c2:
        metrics_block("Ozon", r.mpstats_ozon, rub=True)
    with c3:
        metrics_block("eBay", r.ebay, rub=False)
    with c4:
        metrics_block("Amazon", r.amazon, rub=False)
    st.caption("Amazon показывает каталог, цены и рейтинги — это не объём продаж в России.")

    if r.errors:
        st.warning("Пропущено при сборе данных:\n\n" + "\n".join(f"- {e}" for e in r.errors))


# ---------------------------------------------------------------- pages


def scan_now(fresh: bool) -> None:
    bar = st.progress(0.0, text="Запускаю автопоиск…")

    def progress(done: int, total: int, msg: str) -> None:
        bar.progress(min(done / total, 1.0) if total else 1.0, text=f"{done}/{total} · {msg}")

    result = run_scan(settings=settings(), progress=progress, use_cache=not fresh)
    save_scan(result)
    bar.empty()


def open_in_analysis(niche_name: str) -> None:
    preset = next((p for p in NICHE_PRESETS if p.name == niche_name), None)
    if preset is None:
        return
    # Widget keys of another page are dropped on navigation, so hand over a plain key.
    st.session_state["pending_preset"] = preset.label
    st.switch_page(nav.page("analyze"))


def niche_table(r: ScanResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Ниша": n.name,
                "Раздел": n.section,
                "Балл": n.total,
                "Решение": VERDICT_RU[n.verdict],
                "Купили на Я.Маркете, шт": n.ym.bought_total if n.ym else None,
                "Медианная цена, ₽": n.ym.price_median if n.ym else None,
                "Медиана оценок": n.ym.reviews_median if n.ym else None,
                "Amazon, покупок/мес": n.amazon.bought_total if n.amazon else None,
                "Макс. закупка, ¥": n.max_cost_cny,
            }
            for n in r.niches
        ]
    )


def page_autoscan() -> None:
    hero(
        "Автопоиск товаров",
        "Каждый день дашборд сам проходит по нишам для импорта из Китая и собирает публичные данные "
        "без API-ключей: спрос и цены с Яндекс Маркета, мировой спрос с Amazon.",
    )

    found = latest_scan()
    today = datetime.now().date()
    stale = found is None or found[1].generated_at.astimezone().date() != today
    c1, c2 = st.columns([2, 1])
    refresh = c2.button("Обновить сейчас", type="primary", width="stretch")
    if refresh or (stale and not st.session_state.get("autoscan_started")):
        st.session_state["autoscan_started"] = True
        with c1:
            st.info("Собираю свежие данные — это займёт 2–3 минуты.")
        scan_now(fresh=refresh)
        found = latest_scan()
    if found is None:
        st.warning("Скан ещё не выполнялся.")
        return

    path, r = found
    c1.caption(
        f"Данные от {r.generated_at.astimezone().strftime('%d.%m.%Y %H:%M')} · "
        f"{len(r.niches)} ниш · сбор {r.duration_sec:.0f} с"
    )
    if r.errors:
        st.warning("Часть данных не собрана:\n\n" + "\n".join(f"- {e}" for e in r.errors))

    counts = {v: sum(1 for n in r.niches if n.verdict == v) for v in Verdict}
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ниш проверено", len(r.niches))
    k2.metric("Брать", counts[Verdict.TAKE])
    k3.metric("Тестовая партия", counts[Verdict.TEST])
    k4.metric("Не брать", counts[Verdict.SKIP])

    best = r.niches[0]
    verdict_banner(
        best.verdict,
        f"Лучшая ниша сегодня — «{best.name}», {best.total:.0f} из 100",
        " ".join(best.rationale[:2]),
    )

    st.subheader("Рейтинг ниш")
    df = niche_table(r)
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=6)
        .encode(
            x=alt.X("Балл:Q", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Ниша:N", sort="-x", title=None),
            color=alt.Color(
                "Решение:N",
                scale=alt.Scale(
                    domain=[VERDICT_RU[v] for v in Verdict],
                    range=[VERDICT_COLOR[v] for v in Verdict],
                ),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=list(df.columns),
        )
        .properties(height=max(300, 22 * len(df)))
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        column_config={
            "Балл": st.column_config.ProgressColumn("Балл", min_value=0, max_value=100, format="%.0f"),
            "Медианная цена, ₽": st.column_config.NumberColumn(format="%.0f"),
            "Медиана оценок": st.column_config.NumberColumn(format="%.0f"),
            "Макс. закупка, ¥": st.column_config.NumberColumn(format="%.0f"),
        },
    )
    st.caption(
        "Балл: спрос в РФ 40%, мировой спрос 20%, свободность ниши (мало отзывов у лидеров) 15%, экономика 25%. "
        "Спрос и конкуренция — место ниши среди остальных в этом скане. "
        "«Макс. закупка» — цена в Китае, при которой на медианной цене остаётся целевая маржа."
    )

    st.subheader("Самые покупаемые товары сегодня")
    tops = pd.DataFrame(
        [
            {
                "Фото": t.hit.image,
                "Товар": t.hit.title,
                "Ниша": t.niche,
                "Цена, ₽": t.hit.price,
                "Купили": t.hit.bought,
                "Рейтинг": t.hit.rating,
                "Оценок": t.hit.reviews,
                "Макс. закупка, ¥": t.max_cost_cny,
                "Ссылка": t.hit.url,
            }
            for t in r.top_products
        ]
    )
    if tops.empty:
        st.caption("Яндекс Маркет не показал счётчики покупок.")
    else:
        st.dataframe(
            tops,
            hide_index=True,
            width="stretch",
            row_height=64,
            column_config={
                "Фото": st.column_config.ImageColumn("Фото", width="small"),
                "Товар": st.column_config.TextColumn("Товар", width="large"),
                "Цена, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Макс. закупка, ¥": st.column_config.NumberColumn(format="%.0f"),
                "Ссылка": st.column_config.LinkColumn("Ссылка", display_text="открыть"),
            },
        )

    st.subheader("Разбор ниши")
    name = st.selectbox("Ниша", [n.name for n in r.niches], key="scan_niche")
    n = next(x for x in r.niches if x.name == name)
    verdict_banner(n.verdict, f"«{n.name}» — {n.total:.0f} из 100")
    left, right = st.columns([3, 2])
    with left:
        comp = pd.DataFrame(
            [
                {"Фактор": FACTOR_RU[k], "Балл": n.components.get(k), "Вес": f"{WEIGHTS[k]}%"}
                for k in WEIGHTS
                if k in n.components
            ]
        )
        if not comp.empty:
            st.altair_chart(
                alt.Chart(comp)
                .mark_bar(cornerRadiusEnd=6)
                .encode(
                    x=alt.X("Балл:Q", scale=alt.Scale(domain=[0, 100])),
                    y=alt.Y("Фактор:N", sort=None, title=None),
                    color=alt.Color(
                        "Балл:Q",
                        scale=alt.Scale(domain=[0, 40, 65, 100], range=["#dc2626", "#f59e0b", "#10b981", "#047857"]),
                        legend=None,
                    ),
                    tooltip=["Фактор", "Балл", "Вес"],
                )
                .properties(height=170),
                width="stretch",
            )
        for line in n.rationale + n.errors:
            st.write("•", line)
    with right:
        if n.ym:
            st.metric("Медианная цена на Я.Маркете", fmt_rub(n.ym.price_median))
            st.metric("Коридор цен P25–P75", f"{fmt_rub(n.ym.price_p25)} – {fmt_rub(n.ym.price_p75)}")
        st.metric("Закупка в Китае не дороже", f"{n.max_cost_cny:.0f} ¥" if n.max_cost_cny is not None else "—")
        st.caption(f"Расчётный вес с упаковкой: {n.weight_kg} кг")
        if st.button(
            "Открыть в «Анализе ниши»",
            help="Подставит нишу и категории — там можно посчитать точную экономику и подключить MPSTATS.",
        ):
            open_in_analysis(n.name)

    for title, stats in (("Лидеры Яндекс Маркета", n.ym), ("Лидеры Amazon", n.amazon)):
        if stats and stats.top:
            with st.expander(title):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Фото": h.image,
                                "Товар": h.title,
                                "Цена": h.price,
                                "Покупки": h.bought_label,
                                "Рейтинг": h.rating,
                                "Оценок": h.reviews,
                                "Ссылка": h.url,
                            }
                            for h in stats.top
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Фото": st.column_config.ImageColumn("Фото", width="small"),
                        "Товар": st.column_config.TextColumn("Товар", width="large"),
                        "Ссылка": st.column_config.LinkColumn("Ссылка", display_text="открыть"),
                    },
                )

    html_path = path.with_suffix(".html")
    if html_path.exists():
        st.download_button("Скачать цветной отчёт (HTML)", html_path.read_bytes(), file_name=html_path.name, mime="text/html")
    st.caption(
        "Wildberries, Ozon и eBay без ключей данные не отдают (защита от ботов). "
        "Для точных продаж WB/Ozon подключите MPSTATS в «Настройках»."
    )


@st.cache_data(ttl=86400, show_spinner=False)
def mpstats_categories(mp: str, token: str) -> list[str]:
    from analitik_importa.clients.mpstats import MpstatsClient

    return MpstatsClient(settings()).list_categories(mp)  # type: ignore[arg-type]


def category_options(s: Settings, mp: str) -> tuple[list[str], str]:
    """Category paths for the picker and a human note about where they come from."""
    if s.mpstats_token and not s.use_api_stubs:
        try:
            live = mpstats_categories(mp, s.mpstats_token)
        except RuntimeError as exc:
            return builtin_category_paths(mp), f"MPSTATS не отдал список категорий ({exc}); показан базовый список."
        if live:
            return live, f"Полный каталог MPSTATS: {len(live)} категорий."
    return (
        builtin_category_paths(mp),
        "Базовый список популярных категорий для импорта. После подключения MPSTATS здесь появится полный каталог.",
    )


def category_picker(title: str, prefix: str, paths: list[str]) -> str:
    """Section → subcategory selects, with an option to type the path manually."""
    manual = st.toggle("Ввести путь вручную", key=f"{prefix}_manual")
    if manual:
        return st.text_input(
            f"{title}: путь категории",
            key=f"{prefix}_manual_path",
            placeholder="Раздел/Подраздел/Категория",
        ).strip()

    wanted = st.session_state.get(f"{prefix}_path")
    if wanted and wanted not in paths:
        st.caption(f"Категории «{wanted}» нет в каталоге — выберите ближайшую.")

    sections = sorted({split_path(p)[0] for p in paths})
    if st.session_state.get(f"{prefix}_section") not in sections:
        st.session_state[f"{prefix}_section"] = sections[0]
    section = st.selectbox(f"{title}: раздел", sections, key=f"{prefix}_section")

    in_section = [p for p in paths if split_path(p)[0] == section]
    if st.session_state.get(f"{prefix}_path") not in in_section:
        st.session_state[f"{prefix}_path"] = in_section[0]
    return st.selectbox(
        f"{title}: категория",
        in_section,
        key=f"{prefix}_path",
        format_func=lambda p: split_path(p)[1],
    )


def apply_preset() -> None:
    label = st.session_state.get("preset", "")
    if label == CUSTOM_NICHE:
        st.session_state["keywords"] = ""
        return
    preset = PRESETS_BY_LABEL.get(label)
    if preset is None:
        return
    st.session_state["keywords"] = preset.keywords
    for prefix, path in (("wb", preset.wb_path), ("ozon", preset.ozon_path)):
        st.session_state[f"{prefix}_section"] = split_path(path)[0]
        st.session_state[f"{prefix}_path"] = path
        st.session_state[f"{prefix}_manual"] = False
    st.session_state["ozon_same"] = preset.wb_path == preset.ozon_path


def page_analyze() -> None:
    s = settings()
    hero(
        "Анализ ниши",
        "Выберите нишу и категорию — дашборд соберёт спрос в РФ, мировые цены и экономику единицы "
        "и выдаст решение: брать, тестировать или нет.",
    )

    pending = st.session_state.pop("pending_preset", None)
    if pending:
        st.session_state["preset"] = pending
        apply_preset()
    st.session_state.setdefault("preset", NICHE_PRESETS[0].label)
    if "keywords" not in st.session_state:
        apply_preset()
    st.session_state.setdefault("ozon_same", True)

    with st.container(border=True):
        st.markdown("#### 1. Ниша")
        c1, c2 = st.columns([3, 2])
        c1.selectbox(
            "Готовые ниши для импорта из Китая",
            [p.label for p in NICHE_PRESETS] + [CUSTOM_NICHE],
            key="preset",
            on_change=apply_preset,
            help="Выбор подставит ключевые слова и категории. Всё можно поправить ниже.",
        )
        keywords = c2.text_input(
            "Ключевые слова для поиска на eBay и Amazon",
            key="keywords",
            help="Лучше по-английски: так ищут eBay и Amazon. Это же название будет у отчёта.",
        )

    with st.container(border=True):
        st.markdown("#### 2. Категория на маркетплейсах")
        wb_paths, wb_note = category_options(s, "wb")
        st.caption(wb_note)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Wildberries**")
            wb_path = category_picker("WB", "wb", wb_paths)
        with c2:
            st.markdown("**Ozon**")
            same = st.checkbox("Та же категория, что на WB", key="ozon_same")
            if same:
                ozon_path = wb_path
                st.caption(f"Ozon: {wb_path or '—'}")
            else:
                ozon_paths, _ = category_options(s, "ozon")
                ozon_path = category_picker("Ozon", "ozon", ozon_paths)
        if s.use_api_stubs:
            st.caption("Сейчас MPSTATS в тестовом режиме: цифры по категориям будут демонстрационными.")

    with st.container(border=True):
        st.markdown("#### 3. Экономика товара")
        c1, c2, c3, c4 = st.columns(4)
        cost_cny = c1.number_input("Закупка, ¥", min_value=0.0, value=25.0, step=1.0)
        sell_rub = c2.number_input("Цена продажи, ₽", min_value=0.0, value=2990.0, step=50.0)
        weight = c3.number_input("Вес, кг", min_value=0.01, value=float(s.default_weight_kg), step=0.05)
        mp = c4.selectbox("Площадка для расчёта", list(MP_LABELS), format_func=MP_LABELS.get)

    with st.container(border=True):
        st.markdown("#### 4. Источники")
        c1, c2, c3, c4 = st.columns(4)
        use_mpstats = c1.checkbox("MPSTATS (WB, Ozon)", value=True)
        use_ebay = c2.checkbox("eBay", value=True)
        use_amazon = c3.checkbox("Amazon", value=True)
        save = c4.checkbox("Сохранить отчёт", value=True)

    submitted = st.button("Запустить анализ", type="primary", width="stretch")

    if submitted:
        if not keywords.strip():
            st.error("Укажите нишу.")
            return
        query = NicheQuery(
            keywords=keywords.strip(),
            wb_category_path=wb_path.strip() or None,
            ozon_category_path=ozon_path.strip() or None,
            cost_cny=cost_cny or None,
            sell_rub=sell_rub or None,
            weight_kg=weight,
            marketplace=Marketplace(mp),
        )
        with st.spinner("Собираю данные…"):
            report = analyze_niche(
                query,
                settings=s,
                skip_ebay=not use_ebay,
                skip_mpstats=not use_mpstats,
                skip_amazon=not use_amazon,
            )
        st.session_state["last_report"] = report
        if save:
            paths = save_report(report)
            st.session_state["last_paths"] = paths

    report = st.session_state.get("last_report")
    if report:
        st.divider()
        render_report(report)
        paths = st.session_state.get("last_paths")
        if paths:
            st.download_button(
                "Скачать цветной отчёт (HTML)",
                paths["html"].read_bytes(),
                file_name=paths["html"].name,
                mime="text/html",
            )


def page_econ() -> None:
    s = settings()
    hero("Юнит-экономика", "Сколько вы зарабатываете с одной продажи товара, привезённого из Китая.")

    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Товар**")
        cost_cny = st.number_input("Закупка, ¥", min_value=0.1, value=25.0, step=1.0)
        sell_rub = st.number_input("Цена продажи, ₽", min_value=1.0, value=2990.0, step=50.0)
        weight = st.number_input("Вес, кг", min_value=0.01, value=float(s.default_weight_kg), step=0.05)
        mp = st.selectbox("Площадка", list(MP_LABELS), format_func=MP_LABELS.get)
        with st.expander("Ставки и курс", expanded=False):
            rate = st.number_input("Курс ¥ → ₽", min_value=0.1, value=float(s.cny_rub_rate), step=0.1)
            cargo = st.number_input("Карго, ₽/кг", min_value=0.0, value=float(s.cargo_per_kg_rub), step=10.0)
            commission = st.number_input(
                "Комиссия МП, %", min_value=0.0, value=float(s.commission_pct_for(mp)), step=0.5
            )
            ads = st.number_input("Реклама, %", min_value=0.0, value=float(s.ads_pct), step=0.5)
            defect = st.number_input("Брак / возвраты, %", min_value=0.0, value=float(s.defect_pct), step=0.5)
            logistics = st.number_input("Логистика МП, ₽/шт", min_value=0.0, value=0.0, step=10.0)
            target = st.number_input("Целевая маржа, %", min_value=1.0, value=float(s.target_margin_pct), step=1.0)

    def econ_for(price: float) -> UnitEconResult:
        return calculate(
            UnitEconInput(
                cost_cny=cost_cny,
                sell_rub=price,
                marketplace=Marketplace(mp),
                cny_rub_rate=rate,
                weight_kg=weight,
                cargo_per_kg_rub=cargo,
                commission_pct=commission,
                ads_pct=ads,
                defect_pct=defect,
                target_margin_pct=target,
                logistics_mp_rub=logistics,
            )
        )

    e = econ_for(sell_rub)
    with right:
        verdict_banner(e.verdict, "Решение по экономике", f"Целевая маржа — {target:.0f}%")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Маржа", f"{e.margin_pct:.1f}%")
        c2.metric("Прибыль/шт", fmt_rub(e.profit_rub))
        c3.metric("Себестоимость в РФ", fmt_rub(e.landed_cost_rub))
        c4.metric("Безубыточная цена", fmt_rub(e.breakeven_sell_rub))
        st.markdown("**Куда уходит цена продажи**")
        st.altair_chart(cost_chart(e, sell_rub), width="stretch")

    st.subheader("Как маржа зависит от цены")
    prices = [round(sell_rub * k / 100) for k in range(60, 145, 5)]
    sens = pd.DataFrame(
        [
            {"Цена, ₽": p, "Маржа, %": r.margin_pct, "Прибыль/шт, ₽": r.profit_rub, "Решение": VERDICT_RU[r.verdict]}
            for p in prices
            for r in [econ_for(p)]
        ]
    )
    line = (
        alt.Chart(sens)
        .mark_line(point=True, color="#2563eb")
        .encode(x="Цена, ₽:Q", y="Маржа, %:Q", tooltip=list(sens.columns))
    )
    rule = alt.Chart(pd.DataFrame({"y": [target]})).mark_rule(color="#10b981", strokeDash=[6, 4]).encode(y="y:Q")
    current = alt.Chart(pd.DataFrame({"x": [sell_rub]})).mark_rule(color="#64748b").encode(x="x:Q")
    st.altair_chart((line + rule + current).properties(height=280), width="stretch")
    st.caption("Зелёная пунктирная линия — целевая маржа, серая вертикальная — текущая цена.")


def page_history() -> None:
    hero("История отчётов", "Все сохранённые анализы ниш.")
    items = reports()
    if not items:
        st.caption("Отчётов пока нет.")
        return

    df = reports_table(items)
    query = st.text_input("Поиск по нише")
    shown = df[df["Ниша"].str.contains(query, case=False, na=False)] if query else df
    st.dataframe(
        shown.drop(columns=["Файл"]),
        hide_index=True,
        width="stretch",
        column_config={
            "Балл": st.column_config.ProgressColumn("Балл", min_value=0, max_value=100, format="%.0f"),
            "Маржа, %": st.column_config.NumberColumn(format="%.1f"),
            "Прибыль/шт, ₽": st.column_config.NumberColumn(format="%.0f"),
        },
    )

    by_stem = {path.stem: (path, r) for path, r in items}
    options = list(shown["Файл"])
    if not options:
        return
    choice = st.selectbox(
        "Открыть отчёт",
        options,
        format_func=lambda stem: f"{by_stem[stem][1].query.keywords} — "
        f"{by_stem[stem][1].generated_at.astimezone().strftime('%d.%m.%Y %H:%M')}",
    )
    path, report = by_stem[choice]
    st.divider()
    render_report(report)
    html_path = path.with_suffix(".html")
    if html_path.exists():
        st.download_button("Скачать цветной отчёт (HTML)", html_path.read_bytes(), file_name=html_path.name, mime="text/html")
