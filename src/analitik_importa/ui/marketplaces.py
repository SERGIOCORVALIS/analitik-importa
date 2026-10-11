from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from analitik_importa.ui import nav
from analitik_importa.ui.common import Kpi, fmt_num, fmt_rub, hero, kpi_row, refresh_button, settings, snapshot


@st.cache_data(ttl=300, show_spinner=False)
def ozon_store(client_id: str, api_key: str) -> tuple[dict, pd.DataFrame]:
    from analitik_importa.clients.ozon_seller import OzonSellerClient

    client = OzonSellerClient(settings())
    info = client.seller_info()
    offer_ids = [p["offer_id"] for p in client.list_products() if p.get("offer_id")]
    details = client.product_details(offer_ids) if offer_ids else []
    return info, pd.DataFrame(details)


@st.cache_data(ttl=600, show_spinner=False)
def wb_store(token: str, days: int) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from analitik_importa.clients.wb_seller import WbSellerClient

    client = WbSellerClient(settings())
    info = client.seller_info()
    cards = pd.DataFrame(client.cards())
    stocks = pd.DataFrame(client.stocks())
    orders = pd.DataFrame(client.orders(days))
    return info, cards, stocks, orders


def not_connected(name: str, keys: str) -> None:
    st.warning(f"{name} не подключён. Укажите {keys} в «Настройках».")
    if st.button("Открыть настройки"):
        st.switch_page(nav.page("settings"))


def page_ozon() -> None:
    s = settings()
    hero("Ozon", "Ваш магазин: товары, цены, остатки FBO/FBS и продажи.")
    if not (s.ozon_client_id and s.ozon_api_key):
        not_connected("Ozon", "Client-Id и API-ключ")
        return

    if st.button("↻ Обновить"):
        ozon_store.clear()
    try:
        with st.spinner("Загружаю магазин…"):
            info, df = ozon_store(s.ozon_client_id, s.ozon_api_key)
    except RuntimeError as exc:
        st.error(f"Ozon не ответил: {exc}")
        return

    company = info.get("company") or {}
    sub = (info.get("subscription") or {}).get("type") or "—"
    st.caption(f"{company.get('name', '—')} · подписка {sub} · данные кешируются на 5 минут")
    if df.empty:
        st.info("В магазине нет товаров.")
        return

    snap = snapshot()
    sales_units = sum(v["units"] for v in snap.ozon_sales.values())
    sales_rub = sum(v["revenue"] for v in snap.ozon_sales.values())
    kpi_row(
        [
            Kpi("Товаров", fmt_num(len(df)), f"продаётся: {int((df['status'] == 'Продается').sum())}", "#005bff"),
            Kpi("Остаток", f"{fmt_num(df['stock_present'].sum())} шт", f"в резерве {fmt_num(df['stock_reserved'].sum())}", "#0ea5e9"),
            Kpi("Остаток в ценах продажи", fmt_rub(df["stock_value"].sum()), accent="#10b981"),
            Kpi(f"Заказано за {snap.window_days} дн.", f"{fmt_num(sales_units)} шт", fmt_rub(sales_rub), "#f59e0b"),
        ]
    )

    no_stock = df[(df["stock_present"] == 0) & (~df["archived"])]
    if not no_stock.empty:
        st.warning(f"Без остатка: {', '.join(no_stock['offer_id'])} — товары не продаются, пока нет стока.")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Остатки по товарам**")
        chart = (
            alt.Chart(df)
            .mark_bar(cornerRadiusEnd=6, color="#005bff")
            .encode(
                x=alt.X("stock_present:Q", title="шт"),
                y=alt.Y("offer_id:N", sort="-x", title=None),
                tooltip=[alt.Tooltip("name:N", title="Товар"), alt.Tooltip("stock_present:Q", title="Остаток"),
                         alt.Tooltip("price:Q", title="Цена, ₽")],
            )
            .properties(height=max(200, 28 * len(df)))
        )
        st.altair_chart(chart, width="stretch")
    with right:
        st.markdown("**Статусы**")
        statuses = df["status"].fillna("—").value_counts().rename_axis("Статус").reset_index(name="Товаров")
        st.dataframe(statuses, hide_index=True, width="stretch")

    st.markdown("**Каталог**")
    table = df[["image", "name", "offer_id", "sku", "price", "old_price", "stock_present", "stock_reserved", "stock_sources", "status"]]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        row_height=48,
        column_config={
            "image": st.column_config.ImageColumn("Фото", width="small"),
            "name": st.column_config.TextColumn("Название", width="large"),
            "offer_id": "Артикул",
            "sku": st.column_config.NumberColumn("SKU", format="%d"),
            "price": st.column_config.NumberColumn("Цена, ₽", format="%.0f"),
            "old_price": st.column_config.NumberColumn("Цена до скидки, ₽", format="%.0f"),
            "stock_present": "Остаток",
            "stock_reserved": "Резерв",
            "stock_sources": "Склад",
            "status": "Статус",
        },
    )


def page_wb() -> None:
    s = settings()
    hero("Wildberries", "Ваш магазин: карточки, остатки на складах WB и заказы.")
    if not s.wb_api_token:
        not_connected("Wildberries", "токен WB API")
        st.markdown(
            """
**Как получить токен (2 минуты):**
1. [seller.wildberries.ru](https://seller.wildberries.ru) → профиль → **Настройки → Доступ к API**.
2. «Создать новый токен» → тип **Базовый**, отметьте категории **Контент, Статистика, Аналитика, Цены и скидки**.
3. Включите **«Только на чтение»** — дашборду не нужно ничего менять в кабинете.
4. Скопируйте токен и вставьте в «Настройки → Маркетплейсы».
"""
        )
        return

    c1, c2 = st.columns([4, 1])
    if c2.button("↻ Обновить", width="stretch"):
        wb_store.clear()
    try:
        with st.spinner("Загружаю магазин Wildberries…"):
            info, cards, stocks, orders = wb_store(s.wb_api_token, s.sales_window_days)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    c1.caption(f"{info.get('name') or info.get('tradeMark') or '—'} · данные кешируются на 10 минут")

    total_stock = int(stocks["qty"].sum()) if not stocks.empty else 0
    to_client = int(stocks["to_client"].sum()) if not stocks.empty else 0
    live = orders[~orders["cancelled"]] if not orders.empty else orders
    kpi_row(
        [
            Kpi("Карточек", fmt_num(len(cards)), accent="#cb11ab"),
            Kpi("На складах WB", f"{fmt_num(total_stock)} шт", f"едет к клиентам {fmt_num(to_client)}", "#a21caf"),
            Kpi(f"Заказов за {s.sales_window_days} дн.", fmt_num(len(live)),
                fmt_rub(live["price"].sum() if not live.empty else 0), "#f59e0b"),
            Kpi("Отмен", fmt_num(int(orders["cancelled"].sum()) if not orders.empty else 0), accent="#dc2626"),
        ]
    )

    if not live.empty:
        st.markdown("**Заказы по дням**")
        daily = live.groupby("date").agg(Заказы=("sku", "count"), Сумма=("price", "sum")).reset_index()
        st.altair_chart(
            alt.Chart(daily).mark_area(line=True, color="#cb11ab", opacity=0.25)
            .encode(x=alt.X("date:T", title=None), y=alt.Y("Заказы:Q"), tooltip=["date", "Заказы", "Сумма"])
            .properties(height=220),
            width="stretch",
        )

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Остатки по товарам**")
        if stocks.empty:
            st.caption("На складах WB товара нет.")
        else:
            by_sku = stocks.groupby("sku")[["qty", "to_client", "from_client"]].sum().reset_index()
            if not cards.empty:
                by_sku = by_sku.merge(cards[["sku", "name", "image"]], on="sku", how="left")
            st.dataframe(
                by_sku, hide_index=True, width="stretch", row_height=48,
                column_config={
                    "image": st.column_config.ImageColumn("Фото", width="small"), "sku": "Артикул", "name": "Товар",
                    "qty": "На складах", "to_client": "К клиенту", "from_client": "Возвраты в пути",
                },
            )
    with right:
        st.markdown("**По складам**")
        if not stocks.empty:
            wh = stocks.groupby("warehouse")["qty"].sum().reset_index().sort_values("qty", ascending=False)
            st.altair_chart(
                alt.Chart(wh).mark_bar(cornerRadiusEnd=6, color="#cb11ab")
                .encode(x=alt.X("qty:Q", title="шт"), y=alt.Y("warehouse:N", sort="-x", title=None))
                .properties(height=max(160, 26 * len(wh))),
                width="stretch",
            )

    if not cards.empty:
        with st.expander(f"Все карточки ({len(cards)})"):
            st.dataframe(
                cards, hide_index=True, width="stretch", row_height=48,
                column_config={"image": st.column_config.ImageColumn("Фото", width="small"), "nm_id": "nmID",
                               "sku": "Артикул", "name": "Название", "subject": "Предмет", "brand": "Бренд"},
            )
