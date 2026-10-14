from __future__ import annotations

import streamlit as st

from analitik_importa.accounting import TAX_MODES
from analitik_importa.env_store import ENV_PATH, update_env
from analitik_importa.storage import DB_PATH
from analitik_importa.ui.common import _snapshot, badge, hero, settings


def save(values: dict[str, object]) -> None:
    update_env(values)
    _snapshot.clear()
    st.cache_data.clear()
    st.toast("Сохранено в .env", icon="✅")


def check(name: str, fn) -> None:
    try:
        with st.spinner(f"Проверяю {name}…"):
            info = fn()
        st.success(f"{name}: подключено — {info}")
    except Exception as exc:  # show any auth/network problem to the user
        st.error(f"{name}: {exc}")


def status_line() -> None:
    s = settings()
    items = [
        ("Ozon", bool(s.ozon_client_id and s.ozon_api_key)),
        ("Реклама Ozon", bool(s.ozon_perf_client_id and s.ozon_perf_client_secret)),
        ("Wildberries", bool(s.wb_api_token)),
        ("MPSTATS", bool(s.mpstats_token) and not s.use_api_stubs),
        ("eBay", bool(s.ebay_client_id and s.ebay_client_secret) and not s.use_api_stubs),
        ("Amazon API", bool(s.amazon_credential_id and s.amazon_credential_secret) and not s.use_api_stubs),
        ("Автопоиск (без ключей)", True),
    ]
    st.markdown(
        " ".join(badge(f"● {n}", "#10b981" if ok else "#94a3b8") for n, ok in items),
        unsafe_allow_html=True,
    )


def page_settings() -> None:
    s = settings()
    hero("Настройки", "Подключения, параметры закупки, склада и налогов. Всё сохраняется в файл .env проекта.")
    status_line()
    st.write("")

    t_mp, t_stock, t_econ, t_tax, t_data = st.tabs(
        ["Маркетплейсы", "Склад и закупки", "Экономика товара", "Налоги", "Источники аналитики"]
    )

    with t_mp:
        with st.form("mp_keys"):
            st.markdown("##### Ozon Seller API")
            c1, c2 = st.columns([1, 2])
            ozon_id = c1.text_input("Client-Id", value=s.ozon_client_id)
            ozon_key = c2.text_input("API-ключ", value=s.ozon_api_key, type="password")
            st.caption("seller.ozon.ru → Настройки → Seller API → создать ключ (роль Admin read only достаточно).")
            st.markdown("##### Ozon Performance API — реклама")
            c1, c2 = st.columns([1, 2])
            perf_id = c1.text_input("Client ID", value=s.ozon_perf_client_id,
                                    placeholder="…@advertising.performance.ozon.ru")
            perf_secret = c2.text_input("Client Secret", value=s.ozon_perf_client_secret, type="password")
            st.caption("seller.ozon.ru → Продвижение → Performance API → создать сервисный аккаунт. "
                       "Даёт управление кампаниями, ставками и рекламную статистику.")
            st.markdown("##### Wildberries API")
            wb_token = st.text_input("Токен WB", value=s.wb_api_token, type="password")
            st.caption("seller.wildberries.ru → Настройки → Доступ к API. Категории: Контент, Статистика, Аналитика, "
                       "Цены и скидки; режим «Только на чтение».")
            if st.form_submit_button("Сохранить", type="primary"):
                save({"OZON_CLIENT_ID": ozon_id.strip(), "OZON_API_KEY": ozon_key.strip(),
                      "OZON_PERF_CLIENT_ID": perf_id.strip(), "OZON_PERF_CLIENT_SECRET": perf_secret.strip(),
                      "WB_API_TOKEN": wb_token.strip()})
        c1, c3, c2 = st.columns(3)
        if c1.button("Проверить Ozon", width="stretch", disabled=not (s.ozon_client_id and s.ozon_api_key)):
            from analitik_importa.clients.ozon_seller import OzonSellerClient

            check("Ozon", lambda: (lambda r: f"{r['company']}, товаров: {r['products']}")(OzonSellerClient(s).check()))
        if c3.button("Проверить рекламу Ozon", width="stretch", disabled=not (s.ozon_perf_client_id and s.ozon_perf_client_secret)):
            from analitik_importa.clients.ozon_performance import OzonPerformanceClient

            check("Ozon Performance", lambda: (lambda r: f"кампаний: {r['campaigns']}, активных: {r['running']}")(
                OzonPerformanceClient(s).check()))
        if c2.button("Проверить Wildberries", width="stretch", disabled=not s.wb_api_token):
            from analitik_importa.clients.wb_seller import WbSellerClient

            check("Wildberries", lambda: WbSellerClient(s).check().get("name") or "OK")

    with t_stock:
        with st.form("stock"):
            st.caption("Значения по умолчанию для всех товаров; для отдельного товара их можно изменить в «Каталоге».")
            c1, c2, c3, c4 = st.columns(4)
            lead = c1.number_input("Срок поставки из Китая, дн.", min_value=1, value=s.lead_time_days,
                                   help="От оплаты поставщику до появления товара на складе")
            safety = c2.number_input("Страховой запас, дн.", min_value=0, value=s.safety_days,
                                     help="Запас на задержки карго и всплески спроса")
            cover = c3.number_input("Запас после прихода, дн.", min_value=1, value=s.cover_days,
                                    help="На сколько дней продаж рассчитан один заказ")
            window = c4.number_input("Окно продаж для расчёта, дн.", min_value=7, max_value=90, value=s.sales_window_days)
            st.info(
                f"Логика: заказываем, когда остатка с учётом товара в пути хватит меньше чем на "
                f"{lead} + {safety} = {lead + safety} дн. Размер заказа — продажи в день × ({lead} + {safety} + {cover}) "
                "минус остаток и то, что уже едет."
            )
            if st.form_submit_button("Сохранить", type="primary"):
                save({"LEAD_TIME_DAYS": lead, "SAFETY_DAYS": safety, "COVER_DAYS": cover, "SALES_WINDOW_DAYS": window})

    with t_econ:
        with st.form("econ"):
            c1, c2, c3, c4 = st.columns(4)
            rate = c1.number_input("Курс ¥ → ₽", min_value=0.1, value=float(s.cny_rub_rate), step=0.1)
            cargo = c2.number_input("Карго, ₽/кг", min_value=0.0, value=float(s.cargo_per_kg_rub), step=10.0)
            weight = c3.number_input("Вес по умолчанию, кг", min_value=0.01, value=float(s.default_weight_kg), step=0.05)
            target = c4.number_input("Целевая маржа, %", min_value=1.0, value=float(s.target_margin_pct), step=1.0)
            c1, c2, c3, c4 = st.columns(4)
            c_wb = c1.number_input("Комиссия WB, %", min_value=0.0, value=float(s.commission_wb_pct), step=0.5)
            c_oz = c2.number_input("Комиссия Ozon, %", min_value=0.0, value=float(s.commission_ozon_pct), step=0.5)
            c_ym = c3.number_input("Комиссия ЯМ, %", min_value=0.0, value=float(s.commission_ym_pct), step=0.5)
            c_av = c4.number_input("Комиссия Avito, %", min_value=0.0, value=float(s.commission_avito_pct), step=0.5)
            c1, c2 = st.columns(2)
            ads = c1.number_input("Реклама, % от цены", min_value=0.0, value=float(s.ads_pct), step=0.5)
            defect = c2.number_input("Брак и возвраты, % от цены", min_value=0.0, value=float(s.defect_pct), step=0.5)
            if st.form_submit_button("Сохранить", type="primary"):
                save({
                    "CNY_RUB_RATE": rate, "CARGO_PER_KG_RUB": cargo, "DEFAULT_WEIGHT_KG": weight, "TARGET_MARGIN_PCT": target,
                    "COMMISSION_WB_PCT": c_wb, "COMMISSION_OZON_PCT": c_oz, "COMMISSION_YM_PCT": c_ym,
                    "COMMISSION_AVITO_PCT": c_av, "ADS_PCT": ads, "DEFECT_PCT": defect,
                })

    with t_tax:
        with st.form("tax"):
            modes = list(TAX_MODES)
            mode = st.selectbox("Система налогообложения", modes, index=modes.index(s.tax_mode) if s.tax_mode in modes else 0,
                                format_func=TAX_MODES.get)
            rate = st.number_input("Ставка, %", min_value=0.0, max_value=50.0, value=float(s.tax_rate_pct), step=0.5,
                                   help="УСН «Доходы» — обычно 6%, «Доходы минус расходы» — 15%, НПД — 4–6%")
            st.caption("Налог в бухгалтерии — оценка для управленческого учёта, не замена декларации.")
            if st.form_submit_button("Сохранить", type="primary"):
                save({"TAX_MODE": mode, "TAX_RATE_PCT": rate})

    with t_data:
        with st.form("analytics"):
            stubs = st.toggle("Тестовые данные для eBay / MPSTATS / Amazon API", value=s.use_api_stubs,
                              help="Выключите, когда вставите реальные ключи")
            mpstats = st.text_input("MPSTATS токен", value=s.mpstats_token, type="password",
                                    help="mpstats.io → профиль → API-токен (подписка «Внешняя аналитика»)")
            c1, c2 = st.columns(2)
            ebay_id = c1.text_input("eBay Client ID", value=s.ebay_client_id)
            ebay_secret = c2.text_input("eBay Client Secret", value=s.ebay_client_secret, type="password")
            c1, c2, c3 = st.columns(3)
            amz_id = c1.text_input("Amazon Credential ID", value=s.amazon_credential_id)
            amz_secret = c2.text_input("Amazon Credential Secret", value=s.amazon_credential_secret, type="password")
            amz_tag = c3.text_input("Amazon Partner Tag", value=s.amazon_partner_tag)
            if st.form_submit_button("Сохранить", type="primary"):
                save({
                    "USE_API_STUBS": stubs, "MPSTATS_TOKEN": mpstats.strip(), "EBAY_CLIENT_ID": ebay_id.strip(),
                    "EBAY_CLIENT_SECRET": ebay_secret.strip(), "AMAZON_CREDENTIAL_ID": amz_id.strip(),
                    "AMAZON_CREDENTIAL_SECRET": amz_secret.strip(), "AMAZON_PARTNER_TAG": amz_tag.strip(),
                })
        st.caption("Автопоиск товаров работает без ключей: публичный поиск Яндекс Маркета и Amazon.")

    st.divider()
    st.caption(f"Файл настроек: `{ENV_PATH}` · база склада, закупок и расходов: `{DB_PATH}` (делайте резервную копию).")
