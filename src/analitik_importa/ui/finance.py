from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from analitik_importa.accounting import TAX_MODES, MpFinance, build_pnl, collect_mp_finance
from analitik_importa.storage import EXPENSE_CATEGORIES
from analitik_importa.ui import nav
from analitik_importa.ui.common import Kpi, book, fmt_rub, hero, kpi_row, settings

MP_NAMES = {"": "Общий расход", "ozon": "Ozon", "wb": "Wildberries", "ym": "Яндекс Маркет", "avito": "Avito"}


def period_picker(key: str) -> tuple[date, date]:
    today = date.today()
    month_start = today.replace(day=1)
    prev_end = month_start - timedelta(days=1)
    presets = {
        "Этот месяц": (month_start, today),
        "Прошлый месяц": (prev_end.replace(day=1), prev_end),
        "Последние 30 дней": (today - timedelta(days=29), today),
        "Квартал (90 дней)": (today - timedelta(days=89), today),
        "С начала года": (today.replace(month=1, day=1), today),
        "Свой период": None,
    }
    c1, c2 = st.columns([2, 3])
    choice = c1.segmented_control("Период", list(presets), default="Этот месяц", key=f"{key}_preset") or "Этот месяц"
    if presets[choice] is None:
        rng = c2.date_input("Даты", value=(month_start, today), key=f"{key}_range")
        if isinstance(rng, tuple) and len(rng) == 2:
            return rng[0], rng[1]
        return month_start, today
    d1, d2 = presets[choice]
    c2.caption(f"{d1.strftime('%d.%m.%Y')} — {d2.strftime('%d.%m.%Y')}")
    return d1, d2


@st.cache_data(ttl=900, show_spinner=False)
def mp_finance(ozon_id: str, ozon_key: str, wb_token: str, d1: date, d2: date) -> tuple[dict[str, MpFinance], list[str]]:
    return collect_mp_finance(settings(), d1, d2)


def page_accounting() -> None:
    s = settings()
    hero("Бухгалтерия", "Управленческий отчёт: выручка, удержания маркетплейсов, себестоимость, расходы, налог и деньги.")
    d1, d2 = period_picker("pnl")
    c1, c2 = st.columns([5, 1])
    if c2.button("↻ Обновить", width="stretch"):
        mp_finance.clear()
    with st.spinner("Собираю финансовые отчёты маркетплейсов…"):
        by_mp, errors = mp_finance(s.ozon_client_id, s.ozon_api_key, s.wb_api_token, d1, d2)
    pnl = build_pnl(book(), s, d1, d2, by_mp, errors)
    c1.caption(
        "Источники: " + (", ".join(by_mp) if by_mp else "маркетплейсы не подключены")
        + f" · налог: {TAX_MODES.get(s.tax_mode, s.tax_mode)}"
    )
    for err in pnl.errors:
        st.warning(err)

    margin = pnl.margin_pct
    kpi_row(
        [
            Kpi("Выручка", fmt_rub(pnl.revenue), f"возвраты {fmt_rub(pnl.returns)}", "#4f46e5"),
            Kpi("Удержания МП", fmt_rub(pnl.mp_fees), "комиссии, логистика, хранение", "#f59e0b"),
            Kpi("Себестоимость продаж", fmt_rub(pnl.cogs), accent="#64748b"),
            Kpi("Чистая прибыль", fmt_rub(pnl.net_profit), f"маржа {margin:.1f}%" if margin is not None else "нет выручки",
                "#10b981" if pnl.net_profit >= 0 else "#dc2626"),
            Kpi("Денежный поток", fmt_rub(pnl.cash_flow), f"к выплате от МП {fmt_rub(pnl.payout)}",
                "#0ea5e9" if pnl.cash_flow >= 0 else "#dc2626"),
        ]
    )
    if pnl.cogs_missing:
        st.warning(
            "Нет себестоимости у проданных товаров: " + ", ".join(pnl.cogs_missing)
            + ". Укажите её в «Каталоге» — иначе прибыль завышена."
        )
        if st.button("Открыть каталог"):
            st.switch_page(nav.page("catalog"))

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Отчёт о прибылях и убытках")
        lines = pnl.lines()
        totals = {"Валовая прибыль", "Прибыль до налога", "Чистая прибыль"}
        df = pd.DataFrame(lines, columns=["Статья", "Сумма, ₽"])
        st.dataframe(
            df.style.apply(
                lambda r: ["font-weight:700;background:#eef2ff" if r["Статья"] in totals else "" for _ in r], axis=1
            ).format({"Сумма, ₽": lambda v: f"{v:,.0f}".replace(",", " ")}),
            hide_index=True,
            width="stretch",
            height=min(600, 38 * (len(df) + 1)),
        )
        st.caption(f"Налог: {pnl.tax_note}. Себестоимость = продано шт × средняя себестоимость из каталога.")
    with right:
        st.markdown("#### Куда уходит выручка")
        parts = [
            ("Возвраты", pnl.returns, "#f87171"),
            ("Удержания МП", pnl.mp_fees, "#f59e0b"),
            ("Себестоимость", pnl.cogs, "#64748b"),
            ("Расходы", pnl.expenses_total, "#a855f7"),
            ("Налог", pnl.tax, "#0ea5e9"),
            ("Прибыль", max(pnl.net_profit, 0), "#10b981"),
        ]
        pie = pd.DataFrame([{"Статья": n, "₽": round(v, 2), "c": c} for n, v, c in parts if v > 0])
        if pie.empty:
            st.caption("За период нет движения денег.")
        else:
            st.altair_chart(
                alt.Chart(pie).mark_arc(innerRadius=70, cornerRadius=4)
                .encode(theta="₽:Q", color=alt.Color("c:N", scale=None), tooltip=["Статья", "₽"])
                .properties(height=280),
                width="stretch",
            )
            st.dataframe(pie[["Статья", "₽"]], hide_index=True, width="stretch")

    if by_mp:
        st.markdown("#### По маркетплейсам")
        mp_df = pd.DataFrame(
            [
                {
                    "Маркетплейс": name, "Выручка": m.revenue, "Возвраты": m.returns, "Комиссия": m.commission,
                    "Логистика": m.logistics, "Прочие удержания": m.other, "К выплате": m.payout,
                    "Продано, шт": sum(v for v in m.units.values() if v > 0),
                }
                for name, m in by_mp.items()
            ]
        )
        st.dataframe(mp_df, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.0f") for c in mp_df.columns[1:]})

    if s.ozon_perf_client_id and s.ozon_perf_client_secret:
        ads_block(s.ozon_perf_client_id, d1, d2, pnl.revenue)

    st.markdown("#### Деньги за период")
    cash = pd.DataFrame(
        [
            ("Поступит / поступило от маркетплейсов", pnl.payout),
            ("Оплачено закупок в Китае", -pnl.purchases_paid),
            ("Расходы", -pnl.expenses_total),
            ("Налог (оценка)", -pnl.tax),
            ("Итого денежный поток", pnl.cash_flow),
        ],
        columns=["Статья", "Сумма, ₽"],
    )
    st.dataframe(cash, hide_index=True, width="stretch", column_config={"Сумма, ₽": st.column_config.NumberColumn(format="%.0f")})
    st.caption("Денежный поток отличается от прибыли: закупка уходит деньгами сразу, а в себестоимость попадает по мере продаж.")


def ads_block(perf_id: str, d1: date, d2: date, revenue: float) -> None:
    from analitik_importa.ui.ads import load_daily

    try:
        rows = load_daily(perf_id, d1, d2)
    except RuntimeError as exc:
        st.warning(f"Реклама Ozon: {exc}")
        return
    spent = sum(r["spent"] for r in rows)
    ads_rev = sum(r["orders_rub"] for r in rows)
    st.markdown("#### Реклама Ozon")
    kpi_row(
        [
            Kpi("Расход на рекламу", fmt_rub(spent), "по данным Performance API", "#005bff"),
            Kpi("Выручка с рекламы", fmt_rub(ads_rev), f"ДРР {spent / ads_rev * 100:.1f}%" if ads_rev else "заказов с рекламы нет",
                "#10b981"),
            Kpi("Доля рекламы в выручке", f"{spent / revenue * 100:.1f}%" if revenue else "—", "расход ÷ вся выручка", "#f59e0b"),
        ]
    )
    st.caption("В прибыль этот блок отдельно не вычитается. Реклама, оплаченная из выплат Ozon (оплата за заказ — всегда), "
               "уже входит в «Удержания МП». Если пополняете рекламный кабинет отдельно с карты или по счёту — "
               "внесите пополнение в «Расходы» с категорией «Реклама».")
    if st.button("Открыть рекламу Ozon"):
        st.switch_page(nav.page("ads"))


def page_expenses() -> None:
    b = book()
    hero("Расходы", "Всё, что не удерживают маркетплейсы: реклама вне МП, упаковка, фулфилмент, зарплаты, сервисы.")
    with st.form("expense", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1, 2, 2, 2])
        dt = c1.date_input("Дата", value=date.today())
        category = c2.selectbox("Категория", EXPENSE_CATEGORIES)
        amount = c3.number_input("Сумма, ₽", min_value=0.0, value=0.0, step=100.0)
        mp = c4.selectbox("Относится к", list(MP_NAMES), format_func=MP_NAMES.get)
        note = st.text_input("Комментарий")
        if st.form_submit_button("Добавить расход", type="primary"):
            if amount <= 0:
                st.error("Укажите сумму.")
            else:
                b.add_expense(amount, category, dt, mp or None, note)
                st.success("Расход добавлен.")
                st.rerun()

    rows = pd.DataFrame(b.expenses())
    if rows.empty:
        st.caption("Расходов пока нет.")
        return
    rows["month"] = rows["dt"].str[:7]
    month = date.today().strftime("%Y-%m")
    kpi_row(
        [
            Kpi("В этом месяце", fmt_rub(rows[rows["month"] == month]["amount"].sum()), accent="#a855f7"),
            Kpi("Всего записано", fmt_rub(rows["amount"].sum()), f"{len(rows)} записей", "#4f46e5"),
        ]
    )
    left, right = st.columns([3, 2])
    with left:
        st.altair_chart(
            alt.Chart(rows).mark_bar(cornerRadiusEnd=4)
            .encode(x=alt.X("month:N", title=None), y=alt.Y("sum(amount):Q", title="₽"),
                    color=alt.Color("category:N", title="Категория"), tooltip=["month", "category", "sum(amount)"])
            .properties(height=260),
            width="stretch",
        )
    with right:
        by_cat = rows.groupby("category")["amount"].sum().sort_values(ascending=False).reset_index()
        st.dataframe(by_cat, hide_index=True, width="stretch",
                     column_config={"category": "Категория", "amount": st.column_config.NumberColumn("₽", format="%.0f")})

    view = rows.copy()
    view["mp"] = view["mp"].map(lambda m: MP_NAMES.get(m or "", "—"))
    st.dataframe(
        view[["id", "dt", "category", "amount", "mp", "note"]], hide_index=True, width="stretch",
        column_config={"id": "№", "dt": "Дата", "category": "Категория",
                       "amount": st.column_config.NumberColumn("Сумма, ₽", format="%.0f"), "mp": "Маркетплейс", "note": "Комментарий"},
    )
    c1, c2 = st.columns([3, 1])
    victim = c1.selectbox("Удалить запись", view["id"].tolist(), index=None, placeholder="№ записи",
                          format_func=lambda i: f"#{i} · {view[view['id'] == i].iloc[0]['category']} · "
                                                f"{fmt_rub(view[view['id'] == i].iloc[0]['amount'])}")
    c2.write("")
    if c2.button("Удалить", width="stretch", disabled=victim is None):
        b.delete_expense(int(victim))
        st.rerun()
