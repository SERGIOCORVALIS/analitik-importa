from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from analitik_importa.clients.ozon_performance import (
    ALL_SKU_BIDS,
    PLACEMENT_RU,
    STRATEGY_RU,
    OzonPerformanceClient,
)
from analitik_importa.ui import nav
from analitik_importa.ui.common import Kpi, badge, fmt_num, fmt_rub, hero, kpi_row, settings
from analitik_importa.ui.finance import period_picker

OZON_BLUE = "#005bff"
STATE_COLOR = {"CAMPAIGN_STATE_RUNNING": "#10b981", "CAMPAIGN_STATE_STOPPED": "#dc2626",
               "CAMPAIGN_STATE_INACTIVE": "#94a3b8", "CAMPAIGN_STATE_MODERATION_FAILED": "#dc2626"}


def client() -> OzonPerformanceClient:
    return OzonPerformanceClient(settings())


@st.cache_data(ttl=120, show_spinner=False)
def load_campaigns(perf_id: str) -> list[dict[str, Any]]:
    return client().campaigns()


@st.cache_data(ttl=600, show_spinner=False)
def load_daily(perf_id: str, d1: date, d2: date) -> list[dict[str, Any]]:
    return client().daily(d1, d2)


@st.cache_data(ttl=120, show_spinner=False)
def load_cpo(perf_id: str) -> list[dict[str, Any]]:
    return client().cpo_products()


@st.cache_data(ttl=600, show_spinner=False)
def load_cpo_min_bids(perf_id: str, skus: tuple[str, ...]) -> dict[str, float]:
    return client().cpo_min_bids(list(skus)) if skus else {}


@st.cache_data(ttl=120, show_spinner=False)
def load_cpc_products(perf_id: str, campaign_id: str) -> list[dict[str, Any]]:
    return client().campaign_products(campaign_id)


@st.cache_data(ttl=300, show_spinner=False)
def load_catalog(ozon_id: str, ozon_key: str) -> pd.DataFrame:
    """Товары магазина из Seller API: SKU → артикул, название, фото, цена."""
    if not (ozon_id and ozon_key):
        return pd.DataFrame(columns=["sku", "offer_id", "name", "image", "price", "stock_present"])
    from analitik_importa.ui.marketplaces import ozon_store

    _, df = ozon_store(ozon_id, ozon_key)
    if df.empty:
        return df
    df = df[df["sku"].notna()].copy()
    df["sku"] = df["sku"].astype("int64").astype(str)
    return df


def reset_caches() -> None:
    for fn in (load_campaigns, load_daily, load_cpo, load_cpc_products):
        fn.clear()


def act(done: str, fn: Callable[[], Any]) -> None:
    try:
        with st.spinner("Отправляю в Ozon…"):
            result = fn()
    except Exception as exc:  # show API refusal (limits, moderation, wrong strategy) as-is
        st.error(f"Ozon отклонил действие: {exc}")
        return
    reset_caches()
    st.session_state["ads_flash"] = (done, result)
    st.rerun()


def show_flash() -> None:
    flash = st.session_state.pop("ads_flash", None)
    if not flash:
        return
    done, result = flash
    st.success(done)
    errors = []
    if isinstance(result, list):
        errors = [f"{r.get('sku')}: {r.get('error')}" for r in result if isinstance(r, dict) and r.get("error")]
    if errors:
        st.warning("Не для всех товаров: " + "; ".join(errors))


def sku_label(catalog: pd.DataFrame) -> Callable[[str], str]:
    names = dict(zip(catalog["sku"], catalog["offer_id"] + " · " + catalog["name"].fillna(""))) if not catalog.empty else {}
    return lambda sku: names.get(sku, sku)


def not_connected() -> None:
    st.warning("Рекламный кабинет не подключён. Укажите ключи Performance API в «Настройках → Маркетплейсы».")
    st.markdown(
        """
**Как получить ключи (2 минуты):**
1. [seller.ozon.ru](https://seller.ozon.ru) → **Продвижение → Performance API** (или «Настройки → API-ключи → Performance API»).
2. «Создать сервисный аккаунт» → скопируйте **Client ID** (вида `…@advertising.performance.ozon.ru`) и **Client Secret**.
3. Вставьте их в «Настройки → Маркетплейсы → Ozon Performance API».
"""
    )
    if st.button("Открыть настройки"):
        st.switch_page(nav.page("settings"))


def stats_frame(daily: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(daily)
    if df.empty:
        return pd.DataFrame(columns=["campaign_id", "title", "date", "views", "clicks", "spent", "orders", "orders_rub"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def ratios(views: float, clicks: float, spent: float, orders_rub: float) -> tuple[float | None, float | None, float | None]:
    ctr = clicks / views * 100 if views else None
    cpc = spent / clicks if clicks else None
    drr = spent / orders_rub * 100 if orders_rub else None
    return ctr, cpc, drr


def page_ads() -> None:
    s = settings()
    hero("Реклама Ozon", "Рекламный кабинет: кампании, ставки, оплата за заказ и за клик, расход и ДРР.")
    if not (s.ozon_perf_client_id and s.ozon_perf_client_secret):
        not_connected()
        return

    d1, d2 = period_picker("ads")
    c1, c2 = st.columns([5, 1])
    if c2.button("↻ Обновить", width="stretch", key="ads_refresh"):
        reset_caches()
        load_catalog.clear()
    perf_id = s.ozon_perf_client_id
    try:
        with st.spinner("Загружаю рекламный кабинет…"):
            campaigns = load_campaigns(perf_id)
            stats = stats_frame(load_daily(perf_id, d1, d2))
    except RuntimeError as exc:
        st.error(str(exc))
        return
    try:
        catalog = load_catalog(s.ozon_client_id, s.ozon_api_key)
    except RuntimeError as exc:
        catalog = load_catalog("", "")
        st.warning(f"Каталог Ozon Seller недоступен ({exc}) — товары будут показаны только по SKU.")
    running = sum(c["state"] == "CAMPAIGN_STATE_RUNNING" for c in campaigns)
    c1.caption(f"Кампаний: {len(campaigns)} · активных: {running} · данные кешируются на 2–10 минут")
    show_flash()

    views, clicks, spent = stats["views"].sum(), stats["clicks"].sum(), stats["spent"].sum()
    orders, orders_rub = stats["orders"].sum(), stats["orders_rub"].sum()
    ctr, cpc, drr = ratios(views, clicks, spent, orders_rub)
    kpi_row(
        [
            Kpi("Расход на рекламу", fmt_rub(spent), f"{d1.strftime('%d.%m')}–{d2.strftime('%d.%m')}", OZON_BLUE),
            Kpi("Показы", fmt_num(views), f"клики {fmt_num(clicks)} · CTR {fmt_num(ctr, 2)}%" if ctr is not None else "кликов нет", "#0ea5e9"),
            Kpi("Цена клика", fmt_rub(cpc) if cpc is not None else "—", "средняя", "#a855f7"),
            Kpi("Заказы с рекламы", f"{fmt_num(orders)} шт", fmt_rub(orders_rub), "#10b981"),
            Kpi("ДРР", f"{fmt_num(drr, 1)}%" if drr is not None else "—", "расход ÷ выручка с рекламы",
                "#dc2626" if drr and drr > s.ads_pct * 1.5 else "#f59e0b"),
        ]
    )

    t_camp, t_cpc, t_cpo, t_new, t_rep = st.tabs(
        ["Кампании", "Оплата за клик", "Оплата за заказ", "Новая кампания", "Отчёты по товарам"]
    )
    with t_camp:
        tab_campaigns(campaigns, stats)
    with t_cpc:
        tab_cpc(perf_id, campaigns, catalog)
    with t_cpo:
        tab_cpo(perf_id, campaigns, catalog)
    with t_new:
        tab_new(catalog)
    with t_rep:
        tab_reports(d1, d2)


def tab_campaigns(campaigns: list[dict[str, Any]], stats: pd.DataFrame) -> None:
    if not campaigns:
        st.info("В кабинете нет кампаний. Создайте первую во вкладке «Новая кампания».")
        return
    per = stats.groupby("campaign_id")[["views", "clicks", "spent", "orders", "orders_rub"]].sum() if not stats.empty else None
    rows = []
    for c in campaigns:
        v = per.loc[c["id"]] if per is not None and c["id"] in per.index else None
        views, clicks, spent, orders, orders_rub = (float(v[k]) for k in ("views", "clicks", "spent", "orders", "orders_rub")) if v is not None else (0.0,) * 5
        ctr, cpc, drr = ratios(views, clicks, spent, orders_rub)
        rows.append({
            "Кампания": c["title"], "ID": c["id"], "Тип": c["type_ru"], "Статус": c["state_ru"],
            "Бюджет в неделю, ₽": c["weekly_budget"] or None, "Показы": views, "Клики": clicks, "CTR, %": ctr,
            "Расход, ₽": spent, "Заказы": orders, "Выручка с рекламы, ₽": orders_rub, "ДРР, %": drr,
        })
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={k: st.column_config.NumberColumn(format="%.0f") for k in
                       ("Бюджет в неделю, ₽", "Показы", "Клики", "Расход, ₽", "Заказы", "Выручка с рекламы, ₽")}
        | {"CTR, %": st.column_config.NumberColumn(format="%.2f"), "ДРР, %": st.column_config.NumberColumn(format="%.1f")},
    )

    if not stats.empty:
        by_day = stats.groupby("date")[["views", "clicks", "spent", "orders"]].sum().reset_index()
        base = alt.Chart(by_day).encode(x=alt.X("date:T", title=None))
        st.altair_chart(
            alt.layer(
                base.mark_area(opacity=0.2, color=OZON_BLUE, line=True).encode(y=alt.Y("views:Q", title="Показы")),
                base.mark_bar(color="#f59e0b", opacity=0.8).encode(y=alt.Y("spent:Q", title="Расход, ₽")),
            ).resolve_scale(y="independent").encode(
                tooltip=[alt.Tooltip("date:T", title="Дата"), alt.Tooltip("views:Q", title="Показы"),
                         alt.Tooltip("clicks:Q", title="Клики"), alt.Tooltip("spent:Q", title="Расход, ₽"),
                         alt.Tooltip("orders:Q", title="Заказы")]
            ).properties(height=240),
            width="stretch",
        )

    st.markdown("#### Управление кампанией")
    by_id = {c["id"]: c for c in campaigns}
    cid = st.selectbox("Кампания", list(by_id), format_func=lambda i: f"{by_id[i]['title']} · {by_id[i]['type_ru']} · {by_id[i]['state_ru']}")
    camp = by_id[cid]
    running = camp["state"] == "CAMPAIGN_STATE_RUNNING"
    st.markdown(badge(f"● {camp['state_ru']}", STATE_COLOR.get(camp["state"], "#64748b")) + f' <span class="hint">ID {cid} · '
                f'создана {camp["created_at"]} · {camp["payment"] or "—"}</span>', unsafe_allow_html=True)

    if camp["type"] == "ALL_SKU_PROMO":
        st.caption("Ozon сам продвигает все ваши товары и списывает процент только с заказов, пришедших из рекламы.")
        c1, c2, c3 = st.columns([1, 1, 2])
        if running and c1.button("Выключить", key="all_off", width="stretch"):
            act("Продвижение всех товаров выключено", lambda: client().all_sku_deactivate())
        if not running and c1.button("Включить", key="all_on", type="primary", width="stretch"):
            act("Продвижение всех товаров включено", lambda: client().all_sku_activate())
        bid = c3.segmented_control("Ставка, % от цены заказа", list(ALL_SKU_BIDS), default=None, key="all_bid",
                                   format_func=lambda b: f"{b}%")
        if c2.button("Применить ставку", key="all_bid_btn", width="stretch", disabled=bid is None):
            act(f"Ставка {bid}% установлена", lambda: client().all_sku_set_bid(int(bid)))
        return

    c1, c2 = st.columns(2)
    if running and c1.button("Выключить кампанию", key=f"off_{cid}", width="stretch"):
        act("Кампания выключена", lambda: client().deactivate(cid))
    if not running and c1.button("Включить кампанию", key=f"on_{cid}", type="primary", width="stretch"):
        act("Кампания включена", lambda: client().activate(cid))

    if camp["type"] == "SKU":
        with st.form(f"budget_{cid}"):
            st.markdown("**Бюджет и сроки**")
            f1, f2, f3 = st.columns(3)
            weekly = f1.number_input("Бюджет в неделю, ₽", min_value=0.0, value=float(camp["weekly_budget"]), step=500.0,
                                     help="0 — без ограничения. Минимум у Ozon: 2 000 ₽ × количество товаров")
            start = f2.date_input("Начало", value=None, min_value=date.today(), help="Пусто — не менять")
            end = f3.date_input("Окончание", value=None, min_value=date.today(), help="Пусто — не менять")
            if st.form_submit_button("Сохранить", type="primary"):
                act("Параметры кампании обновлены", lambda: client().update_campaign(cid, weekly, start, end))


def tab_cpc(perf_id: str, campaigns: list[dict[str, Any]], catalog: pd.DataFrame) -> None:
    cpc = {c["id"]: c for c in campaigns if c["type"] == "SKU"}
    if not cpc:
        st.info("Кампаний с оплатой за клик нет. Создайте её во вкладке «Новая кампания».")
        return
    cid = st.selectbox("Кампания с оплатой за клик", list(cpc), key="cpc_camp",
                       format_func=lambda i: f"{cpc[i]['title']} · {cpc[i]['state_ru']}")
    strategy = cpc[cid]["strategy"]
    st.caption(f"Стратегия: {STRATEGY_RU.get(strategy, strategy or 'ручные ставки')}. "
               "Свои ставки учитываются только при стратегии «Средняя стоимость клика».")
    try:
        products = pd.DataFrame(load_cpc_products(perf_id, cid))
    except RuntimeError as exc:
        st.error(str(exc))
        return
    label = sku_label(catalog)

    if products.empty:
        st.info("В кампании пока нет товаров.")
    else:
        if st.button("Показать конкурентные ставки", key="cpc_comp"):
            try:
                comp = client().competitive_bids(cid, products["sku"].tolist())
                st.session_state[f"comp_{cid}"] = comp
            except RuntimeError as exc:
                st.error(str(exc))
        comp = st.session_state.get(f"comp_{cid}", {})
        products["competitive"] = products["sku"].map(comp)
        products["name"] = products["sku"].map(label)
        edited = st.data_editor(
            products[["name", "sku", "bid", "competitive"]], hide_index=True, width="stretch", key=f"cpc_ed_{cid}",
            disabled=["name", "sku", "competitive"],
            column_config={
                "name": st.column_config.TextColumn("Товар", width="large"), "sku": "SKU",
                "bid": st.column_config.NumberColumn("Ставка за клик, ₽", min_value=0.0, step=1.0, format="%.2f"),
                "competitive": st.column_config.NumberColumn("Конкурентная, ₽", format="%.2f"),
            },
        )
        changed = edited[edited["bid"].round(2) != products["bid"].round(2)]
        if st.button(f"Сохранить ставки ({len(changed)})", type="primary", disabled=changed.empty, key="cpc_save"):
            bids = [{"sku": r.sku, "bid_rub": float(r.bid)} for r in changed.itertuples()]
            act(f"Ставки обновлены: {len(bids)}", lambda: client().update_bids(cid, bids))

    st.markdown("**Добавить товары**")
    in_camp = set(products["sku"]) if not products.empty else set()
    options = [s for s in catalog["sku"].tolist() if s not in in_camp] if not catalog.empty else []
    c1, c2, c3 = st.columns([3, 1, 1])
    add = c1.multiselect("Товары магазина", options, format_func=label, key="cpc_add", placeholder="выберите товары")
    bid = c2.number_input("Ставка, ₽", min_value=0.0, value=0.0, step=1.0, key="cpc_add_bid",
                          help="0 — Ozon поставит конкурентную ставку")
    if c3.button("Добавить", type="primary", disabled=not add, width="stretch", key="cpc_add_btn"):
        act(f"Добавлено товаров: {len(add)}", lambda: client().add_products(cid, [{"sku": s, "bid_rub": bid or None} for s in add]))

    if not products.empty:
        st.markdown("**Убрать товары из кампании**")
        c1, c2 = st.columns([4, 1])
        rm = c1.multiselect("Товары кампании", products["sku"].tolist(), format_func=label, key="cpc_rm")
        if c2.button("Убрать", disabled=not rm, width="stretch", key="cpc_rm_btn"):
            act(f"Убрано товаров: {len(rm)}", lambda: client().delete_products(cid, rm))


def tab_cpo(perf_id: str, campaigns: list[dict[str, Any]], catalog: pd.DataFrame) -> None:
    st.caption("Оплата за заказ: товар показывается в поиске выше, а Ozon списывает ставку (% от цены) только "
               "с заказов, пришедших из продвижения. Ставка фиксированная — её назначает Ozon.")
    try:
        cpo = pd.DataFrame(load_cpo(perf_id))
        skus = tuple(catalog["sku"]) if not catalog.empty else tuple(cpo["sku"]) if not cpo.empty else ()
        min_bids = load_cpo_min_bids(perf_id, skus)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    label = sku_label(catalog)

    base = catalog[["sku", "offer_id", "name", "image", "price", "stock_present"]].copy() if not catalog.empty else \
        pd.DataFrame({"sku": list(skus)})
    if not cpo.empty:
        base = base.merge(cpo[["sku", "enabled", "bid_pct", "bid_rub", "visibility", "views_week", "views_prev_week"]],
                          on="sku", how="outer")
    for col in ("enabled", "bid_pct", "bid_rub", "visibility", "views_week", "views_prev_week"):
        if col not in base:
            base[col] = None
    base["in_promo"] = base["enabled"].map({True: "Включено", False: "На паузе"}).fillna("Не участвует")
    base["fixed_bid"] = base["sku"].map(min_bids)
    if "price" in base:
        base["cost_per_order"] = base["price"] * base["fixed_bid"] / 100

    enabled = int((base["in_promo"] == "Включено").sum())
    st.markdown(badge(f"● в продвижении: {enabled} из {len(base)}", "#10b981" if enabled else "#94a3b8"),
                unsafe_allow_html=True)
    cols = [c for c in ("image", "offer_id", "name", "sku", "price", "stock_present", "in_promo", "fixed_bid",
                        "cost_per_order", "visibility", "views_week", "views_prev_week") if c in base]
    st.dataframe(
        base[cols], hide_index=True, width="stretch", row_height=48,
        column_config={
            "image": st.column_config.ImageColumn("Фото", width="small"), "offer_id": "Артикул",
            "name": st.column_config.TextColumn("Товар", width="large"), "sku": "SKU",
            "price": st.column_config.NumberColumn("Цена, ₽", format="%.0f"),
            "stock_present": st.column_config.NumberColumn("Остаток", format="%d"),
            "in_promo": "Продвижение",
            "fixed_bid": st.column_config.NumberColumn("Ставка Ozon, %", format="%.0f"),
            "cost_per_order": st.column_config.NumberColumn("Платите за заказ, ₽", format="%.0f"),
            "visibility": st.column_config.NumberColumn("Индекс видимости", format="%.0f"),
            "views_week": st.column_config.NumberColumn("Показы за неделю", format="%.0f"),
            "views_prev_week": st.column_config.NumberColumn("Неделей ранее", format="%.0f"),
        },
    )
    if "cost_per_order" in base and base["cost_per_order"].notna().any():
        st.caption("«Платите за заказ» = цена × ставка Ozon. Включайте продвижение, только если маржа товара больше этой суммы "
                   "(посчитайте в «Юнит-экономике»).")

    st.markdown("**Управление**")
    c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
    pick = c1.multiselect("Товары", base["sku"].dropna().tolist(), format_func=label, key="cpo_pick",
                          placeholder="выберите товары")
    if c2.button("Включить", type="primary", disabled=not pick, width="stretch", key="cpo_on"):
        act(f"Продвижение включено: {len(pick)}", lambda: client().cpo_enable(pick))
    if c3.button("Пауза", disabled=not pick, width="stretch", key="cpo_off"):
        act(f"Продвижение на паузе: {len(pick)}", lambda: client().cpo_disable(pick))
    if c4.button("Убрать", disabled=not pick, width="stretch", key="cpo_rm"):
        act(f"Убрано из продвижения: {len(pick)}", lambda: client().cpo_remove(pick))

    with st.expander("Акция «Морковск» (бонусы покупателям за заказ)"):
        st.caption("Ozon добавляет к ставке надбавку и даёт покупателю бонусы — товар заметнее в поиске.")
        c1, c2, c3 = st.columns([4, 1, 1])
        car = c1.multiselect("Товары", base["sku"].dropna().tolist(), format_func=label, key="car_pick")
        if c2.button("Включить", disabled=not car, width="stretch", key="car_on"):
            act("«Морковск» включён", lambda: client().carrots(car, True))
        if c3.button("Выключить", disabled=not car, width="stretch", key="car_off"):
            act("«Морковск» выключен", lambda: client().carrots(car, False))


def tab_new(catalog: pd.DataFrame) -> None:
    st.caption("Новая кампания с оплатой за клик. Минимальный бюджет у Ozon — 2 000 ₽ в неделю за каждый товар.")
    label = sku_label(catalog)
    with st.form("new_cpc"):
        title = st.text_input("Название", value=f"Клики {date.today().strftime('%d.%m.%Y')}")
        c1, c2 = st.columns(2)
        placement = c1.selectbox("Где показывать", list(PLACEMENT_RU), format_func=PLACEMENT_RU.get, index=1)
        strategy = c2.selectbox("Стратегия", list(STRATEGY_RU), format_func=STRATEGY_RU.get, index=2,
                                help="«Средняя стоимость клика» — вы сами задаёте ставки; автостратегии — Ozon подбирает их сам")
        c1, c2, c3 = st.columns(3)
        weekly = c1.number_input("Бюджет в неделю, ₽", min_value=0.0, value=2000.0, step=500.0, help="0 — без ограничения")
        start = c2.date_input("Начало", value=date.today(), min_value=date.today())
        end = c3.date_input("Окончание", value=None, min_value=date.today(), help="Пусто — бессрочно")
        skus = st.multiselect("Сразу добавить товары", catalog["sku"].tolist() if not catalog.empty else [], format_func=label)
        bid = st.number_input("Ставка за клик, ₽ (для своих ставок)", min_value=0.0, value=0.0, step=1.0,
                              help="0 — конкурентная ставка Ozon")
        if skus and weekly and weekly < 2000 * len(skus):
            st.caption(f"⚠️ Для {len(skus)} товаров Ozon может потребовать бюджет от {fmt_rub(2000 * len(skus))} в неделю.")
        if st.form_submit_button("Создать кампанию", type="primary"):
            def create() -> str:
                c = client()
                new_id = c.create_cpc_campaign(title.strip(), placement, strategy, weekly or None, start, end)
                if skus:
                    c.add_products(new_id, [{"sku": s, "bid_rub": bid or None} for s in skus])
                return new_id
            act("Кампания создана. Проверьте её статус и включите во вкладке «Кампании».", create)


def tab_reports(d1: date, d2: date) -> None:
    st.caption("Отчёты Ozon формируются асинхронно — обычно 10–60 секунд. Максимальный период — 62 дня.")
    if (d2 - d1).days > 61:
        d1 = d2 - timedelta(days=61)
        st.info(f"Период сокращён до 62 дней: с {d1.strftime('%d.%m.%Y')}.")
    reports = {
        "products": ("По товарам в продвижении (заказы, расход, ДРР)", lambda: client().products_report(d1, d2)),
        "all_sku_days": ("«Оплата за заказ — все товары»: по дням", lambda: client().all_sku_report(d1, d2, "products")),
        "all_sku_orders": ("«Оплата за заказ — все товары»: по заказам", lambda: client().all_sku_report(d1, d2, "orders")),
    }
    kind = st.radio("Отчёт", list(reports), format_func=lambda k: reports[k][0], key="rep_kind")
    if st.button("Сформировать", type="primary", key="rep_go"):
        try:
            with st.spinner("Ozon формирует отчёт…"):
                st.session_state["ads_report"] = (kind, d1, d2, reports[kind][1]())
        except RuntimeError as exc:
            st.error(str(exc))
    saved = st.session_state.get("ads_report")
    if not saved or saved[0] != kind:
        return
    _, r1, r2, rows = saved
    st.caption(f"{reports[kind][0]} · {r1.strftime('%d.%m.%Y')}–{r2.strftime('%d.%m.%Y')}")
    if not rows:
        st.info("За период в отчёте нет данных — по рекламе не было заказов и списаний.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("Скачать CSV", df.to_csv(index=False).encode("utf-8-sig"), file_name=f"ozon-ads-{kind}-{r1}-{r2}.csv",
                       mime="text/csv")
