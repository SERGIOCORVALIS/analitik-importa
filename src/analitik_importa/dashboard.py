from __future__ import annotations

from datetime import datetime

import streamlit as st

from analitik_importa.ui import nav
from analitik_importa.ui.ads import page_ads
from analitik_importa.ui.common import inject_css
from analitik_importa.ui.finance import page_accounting, page_expenses
from analitik_importa.ui.home import page_home
from analitik_importa.ui.marketplaces import page_ozon, page_wb
from analitik_importa.ui.research import page_analyze, page_autoscan, page_econ, page_history
from analitik_importa.ui.settings_page import page_settings
from analitik_importa.ui.stock import page_catalog, page_inventory, page_moves, page_plan, page_purchases

st.set_page_config(page_title="Analitik Importa", page_icon="📦", layout="wide", initial_sidebar_state="expanded")
inject_css()


def p(key: str, fn, title: str, icon: str, default: bool = False) -> st.Page:
    return nav.register(key, st.Page(fn, title=title, icon=icon, url_path=key, default=default))


pages = {
    "": [p("home", page_home, "Командный центр", ":material/space_dashboard:", default=True)],
    "Закупка": [
        p("autoscan", page_autoscan, "Автопоиск товаров", ":material/travel_explore:"),
        p("plan", page_plan, "План закупок", ":material/shopping_cart_checkout:"),
        p("analyze", page_analyze, "Анализ ниши", ":material/query_stats:"),
        p("econ", page_econ, "Юнит-экономика", ":material/calculate:"),
    ],
    "Склад": [
        p("inventory", page_inventory, "Остатки", ":material/inventory_2:"),
        p("purchases", page_purchases, "Закупки и поставки", ":material/local_shipping:"),
        p("moves", page_moves, "Движение товара", ":material/swap_horiz:"),
        p("catalog", page_catalog, "Каталог и себестоимость", ":material/sell:"),
    ],
    "Маркетплейсы": [
        p("ozon", page_ozon, "Ozon", ":material/storefront:"),
        p("ads", page_ads, "Реклама Ozon", ":material/campaign:"),
        p("wb", page_wb, "Wildberries", ":material/storefront:"),
    ],
    "Финансы": [
        p("accounting", page_accounting, "Бухгалтерия", ":material/account_balance:"),
        p("expenses", page_expenses, "Расходы", ":material/receipt_long:"),
    ],
    "Система": [
        p("history", page_history, "История отчётов", ":material/history:"),
        p("settings", page_settings, "Настройки", ":material/settings:"),
    ],
}

current = st.navigation(pages, position="sidebar", expanded=True)

with st.sidebar:
    st.divider()
    st.caption("Панков Сергей Владимирович, правообладатель")
    st.markdown("**📦 Analitik Importa**")
    st.caption(f"Китай → Ozon · Wildberries · ЯМ  \nОбновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

current.run()
