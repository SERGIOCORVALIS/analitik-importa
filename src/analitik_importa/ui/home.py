from __future__ import annotations

import html
from datetime import date, datetime

import pandas as pd
import streamlit as st

from analitik_importa.accounting import build_pnl
from analitik_importa.inventory import STATUS_EMPTY, STATUS_ORDER, STATUS_URGENT
from analitik_importa.report import VERDICT_COLOR, VERDICT_RU
from analitik_importa.trend_scan import latest_scan
from analitik_importa.ui import nav
from analitik_importa.ui.common import (
    Kpi,
    badge,
    book,
    connections_note,
    fmt_num,
    fmt_rub,
    hero,
    kpi_row,
    refresh_button,
    settings,
    snapshot,
)
from analitik_importa.ui.finance import mp_finance
from analitik_importa.ui.stock import inventory_df


def todo(level: str, text: str, page_key: str, button: str) -> None:
    colors = {"high": "#dc2626", "mid": "#f59e0b", "info": "#4f46e5", "ok": "#10b981"}
    labels = {"high": "срочно", "mid": "важно", "info": "к сведению", "ok": "всё хорошо"}
    c1, c2 = st.columns([5, 1])
    c1.markdown(f'{badge(labels[level], colors[level])} {html.escape(text)}', unsafe_allow_html=True)
    if c2.button(button, key=f"todo_{page_key}_{text[:20]}", width="stretch"):
        st.switch_page(nav.page(page_key))


def page_home() -> None:
    s = settings()
    b = book()
    hero(
        "Командный центр",
        f"{datetime.now().strftime('%d.%m.%Y')} · что купить, сколько осталось, сколько заработали.",
    )
    c1, c2 = st.columns([4, 1])
    with c2:
        refresh_button("home_refresh")
    snap = snapshot()
    with c1:
        connections_note(snap)

    df = inventory_df()
    today = date.today()
    month_start = today.replace(day=1)
    by_mp, errors = mp_finance(s.ozon_client_id, s.ozon_api_key, s.wb_api_token, month_start, today)
    pnl = build_pnl(b, s, month_start, today, by_mp, errors)

    urgent = df[df["status"] == STATUS_URGENT] if not df.empty else df
    order = df[df["status"] == STATUS_ORDER] if not df.empty else df
    sales_units = sum(v["units"] for v in snap.ozon_sales.values()) + sum(v["units"] for v in snap.wb_sales.values())
    kpi_row(
        [
            Kpi("Выручка за месяц", fmt_rub(pnl.revenue), f"прибыль {fmt_rub(pnl.net_profit)}",
                "#10b981" if pnl.net_profit >= 0 else "#dc2626"),
            Kpi(f"Продано за {snap.window_days} дн.", f"{fmt_num(sales_units)} шт", "Ozon + WB", "#4f46e5"),
            Kpi("Товар на руках и на МП", f"{fmt_num(df['physical'].sum() if not df.empty else 0)} шт",
                f"по себестоимости {fmt_rub(df['value_cost'].sum() if not df.empty else 0)}", "#0ea5e9"),
            Kpi("Едет из Китая", f"{fmt_num(df['in_transit'].sum() if not df.empty else 0)} шт", accent="#a855f7"),
            Kpi("Нужно заказать", f"{len(urgent) + len(order)} SKU", f"срочно: {len(urgent)}",
                "#dc2626" if len(urgent) else "#f59e0b" if len(order) else "#10b981"),
        ]
    )

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.markdown("#### Что сделать сегодня")
            items = 0
            if len(urgent):
                todo("high", f"Срочно дозаказать: {', '.join(urgent['sku'].head(5))} — товар закончится раньше, чем придёт новая партия.",
                     "plan", "План")
                items += 1
            if len(order):
                todo("mid", f"Пора заказывать: {', '.join(order['sku'].head(5))}.", "plan", "План")
                items += 1
            ship = df[df["action"] == "Отгрузить на МП"] if not df.empty else df
            if len(ship):
                todo("mid", f"Отгрузить на склады МП со своего склада: {', '.join(ship['sku'].head(5))}.", "moves", "Склад")
                items += 1
            empty = df[(df["status"] == STATUS_EMPTY)] if not df.empty else df
            if len(empty):
                todo("info", f"Нет в наличии: {len(empty)} SKU.", "inventory", "Остатки")
                items += 1
            no_cost = [p["sku"] for p in b.products() if p["active"] and not p["cost_rub"]]
            if no_cost:
                todo("info", f"Не указана себестоимость у {len(no_cost)} товаров — прибыль считается неточно.", "catalog", "Каталог")
                items += 1
            late = [p for p in b.purchases() if p["status"] in ("ordered", "in_transit") and p["eta"] and p["eta"] < today.isoformat()]
            if late:
                todo("mid", f"Просрочен приход по {len(late)} закупкам — уточните у карго.", "purchases", "Закупки")
                items += 1
            if not snap.connected["wb"]:
                todo("info", "Wildberries не подключён — остатки и продажи WB не учитываются.", "settings", "Подключить")
                items += 1
            if not items:
                todo("ok", "Срочных задач нет.", "inventory", "Остатки")

        if not df.empty:
            with st.container(border=True):
                st.markdown("#### Остатки: на сколько дней хватит")
                view = df[df["per_day"] > 0][["sku", "name", "status", "physical", "per_day", "days_cover", "order_qty"]]
                if view.empty:
                    st.caption(f"Продаж за {snap.window_days} дн. нет — прогноз остатков появится с первыми продажами.")
                    st.dataframe(
                        df[["sku", "name", "physical", "own_source"]].sort_values("physical", ascending=False),
                        hide_index=True, width="stretch",
                        column_config={"sku": "Артикул", "name": "Товар", "physical": "Всего, шт", "own_source": "Откуда остаток"},
                    )
                else:
                    st.dataframe(
                        view.sort_values("days_cover"), hide_index=True, width="stretch",
                        column_config={
                            "sku": "Артикул", "name": "Товар", "status": "Статус", "physical": "Всего, шт",
                            "per_day": st.column_config.NumberColumn("Продаж/день", format="%.2f"),
                            "days_cover": st.column_config.ProgressColumn("Хватит, дн.", min_value=0, max_value=120, format="%.0f"),
                            "order_qty": "Дозаказать",
                        },
                    )

    with right:
        with st.container(border=True):
            st.markdown("#### Что выгодно закупать сейчас")
            found = latest_scan()
            if found is None:
                st.caption("Автопоиск ещё не запускался.")
            else:
                _, r = found
                st.caption(f"Автопоиск от {r.generated_at.astimezone().strftime('%d.%m %H:%M')}")
                for n in r.niches[:6]:
                    color = VERDICT_COLOR[n.verdict]
                    st.markdown(
                        f'<div class="alert-row"><b style="min-width:34px;color:{color}">{n.total:.0f}</b>'
                        f'<span style="flex:1">{html.escape(n.name)}</span>{badge(VERDICT_RU[n.verdict], color)}</div>',
                        unsafe_allow_html=True,
                    )
            if st.button("Открыть автопоиск", width="stretch"):
                st.switch_page(nav.page("autoscan"))

        with st.container(border=True):
            st.markdown("#### Месяц в цифрах")
            fin = pd.DataFrame(pnl.lines(), columns=["Статья", "₽"])
            keep = {"Выручка (продажи)", "Комиссии маркетплейсов", "Логистика маркетплейсов", "Себестоимость проданных товаров",
                    "Чистая прибыль"}
            st.dataframe(fin[fin["Статья"].isin(keep)], hide_index=True, width="stretch",
                         column_config={"₽": st.column_config.NumberColumn(format="%.0f")})
            if st.button("Открыть бухгалтерию", width="stretch"):
                st.switch_page(nav.page("accounting"))
