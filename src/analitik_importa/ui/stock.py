from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from analitik_importa.inventory import (
    STATUS_COLOR,
    STATUS_EXCESS,
    STATUS_ORDER,
    STATUS_URGENT,
    build_inventory,
)
from analitik_importa.storage import MOVE_KINDS, PURCHASE_STATUSES
from analitik_importa.ui.common import (
    Kpi,
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

MP_CHOICES = {"": "—", "ozon": "Ozon", "wb": "Wildberries", "ym": "Яндекс Маркет", "avito": "Avito"}


def inventory_df() -> pd.DataFrame:
    rows = build_inventory(book(), snapshot(), settings())
    return pd.DataFrame(rows)


def sku_options() -> list[str]:
    return [p["sku"] for p in book().products()]


def sku_label(sku: str) -> str:
    names = {p["sku"]: p["name"] for p in book().products()}
    name = names.get(sku) or ""
    return f"{sku} · {name[:60]}" if name else sku


STOCK_COLUMNS = {
    "image": st.column_config.ImageColumn("Фото", width="small"),
    "sku": "Артикул",
    "name": st.column_config.TextColumn("Товар", width="medium"),
    "status": "Статус",
    "physical": st.column_config.NumberColumn("Всего, шт", help="Свой склад + Ozon FBO + склады WB + в пути к клиенту WB"),
    "own": st.column_config.NumberColumn("Свой склад", help="По складскому учёту, а пока его нет — заявленный FBS Ozon"),
    "ozon_fbo": st.column_config.NumberColumn("Ozon FBO"),
    "ozon_fbs": st.column_config.NumberColumn("Ozon FBS", help="Сколько выставлено на Ozon с вашего склада"),
    "wb": st.column_config.NumberColumn("WB склады"),
    "wb_to_client": st.column_config.NumberColumn("WB к клиенту"),
    "in_transit": st.column_config.NumberColumn("Едет из Китая"),
    "per_day": st.column_config.NumberColumn("Продаж/день", format="%.2f"),
    "days_cover": st.column_config.NumberColumn("Хватит, дн.", format="%.0f"),
    "order_qty": st.column_config.NumberColumn("Дозаказать, шт"),
    "action": "Что сделать",
    "cost_rub": st.column_config.NumberColumn("Себест., ₽", format="%.0f"),
    "price": st.column_config.NumberColumn("Цена, ₽", format="%.0f"),
    "value_cost": st.column_config.NumberColumn("Запас по себест., ₽", format="%.0f"),
    "value_retail": st.column_config.NumberColumn("Запас в ценах, ₽", format="%.0f"),
}


def stock_kpis(df: pd.DataFrame) -> None:
    urgent = int((df["status"] == STATUS_URGENT).sum()) if not df.empty else 0
    order = int((df["status"] == STATUS_ORDER).sum()) if not df.empty else 0
    kpi_row(
        [
            Kpi("Товаров (SKU)", fmt_num(len(df)), accent="#4f46e5"),
            Kpi("Всего на руках и на МП", f"{fmt_num(df['physical'].sum() if not df.empty else 0)} шт",
                f"свой склад {fmt_num(df['own'].sum() if not df.empty else 0)} шт", "#0ea5e9"),
            Kpi("Запас по себестоимости", fmt_rub(df["value_cost"].sum() if not df.empty else 0),
                f"в ценах продажи {fmt_rub(df['value_retail'].sum() if not df.empty else 0)}", "#10b981"),
            Kpi("Едет из Китая", f"{fmt_num(df['in_transit'].sum() if not df.empty else 0)} шт", accent="#a855f7"),
            Kpi("Нужно заказать", f"{urgent + order} SKU", f"из них срочно: {urgent}",
                "#dc2626" if urgent else "#f59e0b" if order else "#10b981"),
        ]
    )


def style_status(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    def color(v: str) -> str:
        c = STATUS_COLOR.get(v)
        return f"color:{c};font-weight:600" if c else ""

    return df.style.map(color, subset=["status"])


# ------------------------------------------------------------------ pages


def page_inventory() -> None:
    hero("Остатки", "Свой склад, Ozon, Wildberries и товары в пути из Китая — в одной таблице.")
    c1, c2 = st.columns([4, 1])
    with c2:
        refresh_button("inv_refresh")
    with c1:
        connections_note(snapshot())
    df = inventory_df()
    if df.empty:
        st.info("Товаров пока нет. Подключите Ozon/WB в «Настройках» или добавьте товар в «Каталоге».")
        return
    stock_kpis(df)

    f1, f2 = st.columns([2, 3])
    statuses = f1.multiselect("Статус", list(STATUS_COLOR), placeholder="все статусы")
    query = f2.text_input("Поиск по артикулу или названию", placeholder="например, MAX-BOOK")
    shown = df
    if statuses:
        shown = shown[shown["status"].isin(statuses)]
    if query:
        mask = shown["sku"].str.contains(query, case=False, na=False) | shown["name"].str.contains(query, case=False, na=False)
        shown = shown[mask]

    tab_table, tab_chart = st.tabs(["Таблица", "Где лежит товар"])
    with tab_table:
        cols = ["image", "sku", "name", "status", "physical", "own", "ozon_fbo", "ozon_fbs", "wb", "wb_to_client",
                "in_transit", "per_day", "days_cover", "order_qty", "action", "cost_rub", "price", "value_cost"]
        st.dataframe(style_status(shown[cols]), hide_index=True, width="stretch", column_config=STOCK_COLUMNS, row_height=48)
        st.caption(
            "«Всего» не включает Ozon FBS: это ваш же склад, выставленный на Ozon. "
            "Пока по артикулу нет складских движений, свой склад берётся из FBS Ozon."
        )
    with tab_chart:
        long = shown.melt(
            id_vars=["sku"], value_vars=["own", "ozon_fbo", "wb", "wb_to_client", "in_transit"],
            var_name="where", value_name="qty",
        )
        labels = {"own": "Свой склад", "ozon_fbo": "Ozon FBO", "wb": "WB склады", "wb_to_client": "WB к клиенту",
                  "in_transit": "Едет из Китая"}
        long["Где"] = long["where"].map(labels)
        long = long[long["qty"] > 0]
        if long.empty:
            st.caption("Нет остатков для графика.")
        else:
            st.altair_chart(
                alt.Chart(long)
                .mark_bar(cornerRadiusEnd=4)
                .encode(
                    x=alt.X("sum(qty):Q", title="шт"),
                    y=alt.Y("sku:N", sort="-x", title=None),
                    color=alt.Color("Где:N", scale=alt.Scale(
                        domain=list(labels.values()), range=["#4f46e5", "#005bff", "#cb11ab", "#f472b6", "#a855f7"])),
                    tooltip=["sku", "Где", "qty"],
                )
                .properties(height=max(220, 26 * shown["sku"].nunique())),
                width="stretch",
            )

    wh = snapshot().wb_warehouses
    if wh:
        with st.expander("Остатки по складам Wildberries"):
            st.dataframe(pd.DataFrame(wh), hide_index=True, width="stretch")


def page_plan() -> None:
    s = settings()
    hero(
        "План закупок",
        f"Что и сколько заказать в Китае: скорость продаж за {s.sales_window_days} дн., "
        f"срок поставки {s.lead_time_days} дн., страховой запас {s.safety_days} дн., запас после прихода {s.cover_days} дн.",
    )
    refresh_button("plan_refresh")
    df = inventory_df()
    if df.empty:
        st.info("Нет товаров для планирования.")
        return

    need = df[df["order_qty"] > 0].copy()
    excess = df[df["status"] == STATUS_EXCESS]
    budget = float((need["order_qty"] * need["cost_rub"]).sum()) if not need.empty else 0.0
    kpi_row(
        [
            Kpi("Позиций к заказу", fmt_num(len(need)), accent="#f59e0b"),
            Kpi("Штук к заказу", fmt_num(need["order_qty"].sum() if not need.empty else 0), accent="#0ea5e9"),
            Kpi("Бюджет по текущей себестоимости", fmt_rub(budget), "оценка по средней себестоимости", "#4f46e5"),
            Kpi("Избыток запаса", f"{len(excess)} SKU", "деньги заморожены в товаре", "#6366f1"),
        ]
    )

    if need.empty:
        st.success("Сейчас дозаказывать ничего не нужно: остатков с учётом товаров в пути хватает.")
        if (df["per_day"] == 0).all():
            st.caption("Продаж за выбранный период нет — план появится, когда пойдут продажи.")
    else:
        st.markdown("#### Сформировать заказ поставщику")
        st.caption("Отметьте позиции, поправьте количество и укажите цену в юанях — закупки появятся в разделе «Закупки и поставки».")
        editor = need[["sku", "name", "status", "per_day", "days_cover", "physical", "in_transit", "order_qty", "cost_rub"]].copy()
        editor.insert(0, "take", True)
        editor["unit_cny"] = 0.0
        edited = st.data_editor(
            editor,
            hide_index=True,
            width="stretch",
            disabled=["sku", "name", "status", "per_day", "days_cover", "physical", "in_transit", "cost_rub"],
            column_config={
                "take": st.column_config.CheckboxColumn("В заказ"),
                "sku": "Артикул",
                "name": "Товар",
                "status": "Статус",
                "per_day": st.column_config.NumberColumn("Продаж/день", format="%.2f"),
                "days_cover": st.column_config.NumberColumn("Хватит, дн.", format="%.0f"),
                "physical": "Остаток",
                "in_transit": "В пути",
                "order_qty": st.column_config.NumberColumn("Заказать, шт", min_value=1, step=1),
                "cost_rub": st.column_config.NumberColumn("Себест., ₽", format="%.0f"),
                "unit_cny": st.column_config.NumberColumn("Цена, ¥/шт", min_value=0.0, step=0.5, format="%.2f"),
            },
            key="plan_editor",
        )
        c1, c2, c3 = st.columns(3)
        rate = c1.number_input("Курс ¥ → ₽", min_value=0.1, value=float(s.cny_rub_rate), step=0.1)
        eta = c2.date_input("Ожидаемая дата прихода", value=date.today() + timedelta(days=s.lead_time_days))
        supplier = c3.text_input("Поставщик")
        if st.button("Оформить закупки", type="primary"):
            chosen = edited[edited["take"]]
            missing = chosen[chosen["unit_cny"] <= 0]["sku"].tolist()
            if missing:
                st.error("Укажите цену в юанях для: " + ", ".join(missing))
            elif chosen.empty:
                st.warning("Ничего не отмечено.")
            else:
                for r in chosen.itertuples():
                    book().add_purchase(r.sku, int(r.order_qty), float(r.unit_cny), rate, supplier=supplier, eta=eta)
                st.success(f"Создано закупок: {len(chosen)}. Карго добавьте в «Закупках и поставках», когда будет счёт.")

    if not excess.empty:
        with st.expander(f"Избыток запаса ({len(excess)})"):
            st.dataframe(excess[["sku", "name", "physical", "per_day", "days_cover", "value_cost"]], hide_index=True,
                         width="stretch", column_config=STOCK_COLUMNS)
            st.caption("Подумайте об акции или снижении цены: запас больше, чем на два цикла поставки.")


def page_purchases() -> None:
    s = settings()
    b = book()
    hero("Закупки и поставки", "Заказы в Китае: сколько заказано, что едет, что пришло и во что обошлось.")
    purchases = pd.DataFrame(b.purchases())

    if not purchases.empty:
        active = purchases[purchases["status"].isin(["ordered", "in_transit"])]
        month = purchases[purchases["created"] >= date.today().replace(day=1).isoformat()]
        kpi_row(
            [
                Kpi("Заказано, не отправлено", f"{fmt_num(active[active['status'] == 'ordered']['qty'].sum())} шт", accent="#f59e0b"),
                Kpi("В пути", f"{fmt_num(active[active['status'] == 'in_transit']['qty'].sum())} шт",
                    fmt_rub(active[active["status"] == "in_transit"]["total_rub"].sum()), "#a855f7"),
                Kpi("Закуплено в этом месяце", fmt_rub(month[month["status"] != "cancelled"]["total_rub"].sum()), accent="#4f46e5"),
                Kpi("Всего закупок", fmt_num(len(purchases)), accent="#0ea5e9"),
            ]
        )

    with st.expander("➕ Новая закупка", expanded=purchases.empty):
        with st.form("new_purchase", clear_on_submit=True):
            c1, c2 = st.columns([2, 1])
            options = sku_options()
            sku = c1.selectbox("Товар", options, format_func=sku_label, index=None, placeholder="выберите артикул")
            new_sku = c2.text_input("…или новый артикул")
            c1, c2, c3, c4 = st.columns(4)
            qty = c1.number_input("Количество, шт", min_value=1, value=100, step=10)
            unit_cny = c2.number_input("Цена, ¥/шт", min_value=0.0, value=0.0, step=0.5)
            rate = c3.number_input("Курс ¥ → ₽", min_value=0.1, value=float(s.cny_rub_rate), step=0.1)
            cargo = c4.number_input("Карго всего, ₽", min_value=0.0, value=0.0, step=100.0)
            c1, c2, c3 = st.columns(3)
            other = c1.number_input("Прочее (сертификат, упаковка), ₽", min_value=0.0, value=0.0, step=100.0)
            supplier = c2.text_input("Поставщик")
            eta = c3.date_input("Ожидаемый приход", value=date.today() + timedelta(days=s.lead_time_days))
            note = st.text_input("Комментарий")
            if st.form_submit_button("Сохранить закупку", type="primary"):
                target = new_sku.strip() or sku
                if not target:
                    st.error("Выберите или введите артикул.")
                elif unit_cny <= 0:
                    st.error("Укажите цену за штуку в юанях.")
                else:
                    pid = b.add_purchase(target, int(qty), unit_cny, rate, cargo, other, supplier, eta, note)
                    st.success(f"Закупка #{pid} сохранена.")
                    st.rerun()

    if purchases.empty:
        st.caption("Закупок пока нет.")
        return

    st.markdown("#### Все закупки")
    view = purchases.copy()
    view["Статус"] = view["status"].map(PURCHASE_STATUSES)
    st.dataframe(
        view[["id", "created", "sku", "qty", "unit_cny", "cny_rub_rate", "cargo_rub", "other_rub", "total_rub", "unit_rub",
              "supplier", "Статус", "eta", "received_at", "note"]],
        hide_index=True,
        width="stretch",
        column_config={
            "id": "№", "created": "Дата", "sku": "Артикул", "qty": "Шт",
            "unit_cny": st.column_config.NumberColumn("¥/шт", format="%.2f"),
            "cny_rub_rate": st.column_config.NumberColumn("Курс", format="%.2f"),
            "cargo_rub": st.column_config.NumberColumn("Карго, ₽", format="%.0f"),
            "other_rub": st.column_config.NumberColumn("Прочее, ₽", format="%.0f"),
            "total_rub": st.column_config.NumberColumn("Итого, ₽", format="%.0f"),
            "unit_rub": st.column_config.NumberColumn("Себест. 1 шт, ₽", format="%.0f"),
            "supplier": "Поставщик", "eta": "Ожидается", "received_at": "Получено", "note": "Комментарий",
        },
    )

    open_ids = view[view["status"].isin(["ordered", "in_transit"])]
    if not open_ids.empty:
        st.markdown("#### Изменить статус")
        c1, c2, c3 = st.columns([3, 2, 1])
        pid = c1.selectbox(
            "Закупка",
            open_ids["id"].tolist(),
            format_func=lambda i: (lambda r: f"#{i} · {r['sku']} · {r['qty']} шт · {PURCHASE_STATUSES[r['status']]}")(
                open_ids[open_ids["id"] == i].iloc[0]
            ),
        )
        status = c2.selectbox("Новый статус", ["in_transit", "received", "cancelled"], format_func=PURCHASE_STATUSES.get)
        c3.write("")
        if c3.button("Применить", type="primary", width="stretch"):
            if status == "received":
                row = open_ids[open_ids["id"] == pid].iloc[0]
                snap = snapshot()
                elsewhere = snap.ozon_stock.get(row["sku"], {}).get("fbo", 0) + snap.wb_stock.get(row["sku"], {}).get("qty", 0)
                b.receive_purchase(int(pid), stock_elsewhere=elsewhere)
                st.success("Товар оприходован на свой склад, себестоимость пересчитана по средней.")
            else:
                b.set_purchase_status(int(pid), status)
            st.rerun()


def page_moves() -> None:
    b = book()
    hero("Движение товара", "Свой склад: приход, отгрузки на склады маркетплейсов, возвраты, списания и инвентаризация.")
    own = b.own_stock()

    t_move, t_count = st.tabs(["Записать движение", "Инвентаризация"])
    with t_move:
        with st.form("move", clear_on_submit=True):
            c1, c2, c3 = st.columns([3, 2, 1])
            sku = c1.selectbox("Товар", sku_options(), format_func=sku_label, index=None, placeholder="выберите артикул")
            kind = c2.selectbox("Операция", [k for k in MOVE_KINDS if k != "adjust"], format_func=MOVE_KINDS.get, index=1)
            qty = c3.number_input("Шт", min_value=1, value=10, step=1)
            c1, c2, c3 = st.columns(3)
            mp = c1.selectbox("Маркетплейс", list(MP_CHOICES), format_func=MP_CHOICES.get)
            dt = c2.date_input("Дата", value=date.today())
            note = c3.text_input("Комментарий", placeholder="номер поставки, причина…")
            if st.form_submit_button("Записать", type="primary"):
                if not sku:
                    st.error("Выберите товар.")
                else:
                    b.add_move(sku, int(qty), kind, mp or None, note, dt)
                    st.success("Записано.")
                    st.rerun()
        st.caption("Приход из Китая удобнее оформлять в «Закупках и поставках» — там же пересчитается себестоимость.")
    with t_count:
        st.caption("Посчитали товар на складе — введите факт, разница запишется корректировкой.")
        with st.form("count"):
            c1, c2 = st.columns([3, 1])
            sku = c1.selectbox("Товар", sku_options(), format_func=sku_label, index=None, placeholder="выберите артикул", key="count_sku")
            fact = c2.number_input("Факт, шт", min_value=0, value=0, step=1)
            if st.form_submit_button("Сохранить факт", type="primary"):
                if not sku:
                    st.error("Выберите товар.")
                else:
                    delta = int(fact) - own.get(sku, 0)
                    if delta:
                        b.add_move(sku, delta, "adjust", note=f"Инвентаризация: факт {fact}")
                    else:
                        b.add_move(sku, 0, "adjust", note=f"Инвентаризация: факт {fact}, без расхождений")
                    st.success(f"Учтено. Расхождение: {delta:+d} шт.")
                    st.rerun()

    moves = pd.DataFrame(b.moves())
    st.markdown("#### Последние движения")
    if moves.empty:
        st.caption("Движений пока нет.")
        return
    moves["Операция"] = moves["kind"].map(MOVE_KINDS)
    moves["МП"] = moves["mp"].map(lambda m: MP_CHOICES.get(m or "", "—"))
    st.dataframe(
        moves[["dt", "sku", "Операция", "qty", "МП", "note"]],
        hide_index=True,
        width="stretch",
        column_config={"dt": "Дата", "sku": "Артикул", "qty": st.column_config.NumberColumn("Шт", format="%+d"), "note": "Комментарий"},
    )


def page_catalog() -> None:
    s = settings()
    b = book()
    hero("Каталог и себестоимость", "Себестоимость, сроки поставки и поставщики — на них опираются план закупок и бухгалтерия.")
    snapshot()  # registers marketplace listings in the catalog
    products = pd.DataFrame(b.products())
    if products.empty:
        st.info("Каталог пуст: подключите маркетплейсы или добавьте товар ниже.")
    else:
        no_cost = int((products["cost_rub"] <= 0).sum())
        if no_cost:
            st.warning(f"У {no_cost} товаров не указана себестоимость — без неё прибыль в бухгалтерии будет завышена.")
        st.caption(
            f"Пустые сроки = значения по умолчанию из «Настроек»: поставка {s.lead_time_days} дн., "
            f"страховой запас {s.safety_days} дн., запас после прихода {s.cover_days} дн."
        )
        cols = ["sku", "name", "cost_rub", "lead_time_days", "safety_days", "cover_days", "supplier", "notes", "active"]
        view = products[cols].copy()
        view["active"] = view["active"].astype(bool)
        edited = st.data_editor(
            view,
            hide_index=True,
            width="stretch",
            disabled=["sku"],
            column_config={
                "sku": "Артикул",
                "name": st.column_config.TextColumn("Название", width="large"),
                "cost_rub": st.column_config.NumberColumn("Себестоимость, ₽", min_value=0.0, format="%.2f"),
                "lead_time_days": st.column_config.NumberColumn("Поставка, дн.", min_value=1, step=1),
                "safety_days": st.column_config.NumberColumn("Страх. запас, дн.", min_value=0, step=1),
                "cover_days": st.column_config.NumberColumn("Запас после прихода, дн.", min_value=1, step=1),
                "supplier": "Поставщик",
                "notes": "Заметки",
                "active": st.column_config.CheckboxColumn("Активен"),
            },
            key="catalog_editor",
        )
        if st.button("Сохранить изменения", type="primary"):
            changed = 0
            for (_, old), (_, new) in zip(view.iterrows(), edited.iterrows()):
                diff = {}
                for col in cols[1:]:
                    a, bval = old[col], new[col]
                    if pd.isna(a) and pd.isna(bval):
                        continue
                    if a != bval:
                        diff[col] = None if pd.isna(bval) else (int(bval) if col == "active" else bval)
                if diff:
                    b.update_product(new["sku"], **diff)
                    changed += 1
            st.success(f"Сохранено товаров: {changed}.")
            st.rerun()

    with st.expander("➕ Добавить товар вручную"):
        with st.form("new_product", clear_on_submit=True):
            c1, c2, c3 = st.columns([1, 2, 1])
            sku = c1.text_input("Артикул")
            name = c2.text_input("Название")
            cost = c3.number_input("Себестоимость, ₽", min_value=0.0, value=0.0)
            if st.form_submit_button("Добавить"):
                if not sku.strip():
                    st.error("Укажите артикул.")
                else:
                    b.upsert_product(sku.strip(), name)
                    if cost:
                        b.update_product(sku.strip(), cost_rub=cost)
                    st.success("Добавлено.")
                    st.rerun()

