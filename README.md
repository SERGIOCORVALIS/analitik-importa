# Analitik Importa

Агент аналитики ниш для импорта из Китая и продажи на РФ маркетплейсах.

Источники:

- **eBay Browse API** — глобальный ценовой коридор (только аналитика)
- **MPSTATS API** — Wildberries / Ozon / Яндекс Маркет
- **Amazon Creators API** — каталог / цена / рейтинг (не объём продаж в РФ)
- **Unit economics** — локальный расчёт маржи Китай → РФ МП

## Setup

```powershell
cd c:\Users\dolma\Documents\ANALITIK-IMPORTA
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env
```

Заполните `.env` перед этапами 2–4:

| Ключи | Где взять |
|-------|-----------|
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` | https://developer.ebay.com |
| `MPSTATS_TOKEN` | https://mpstats.io/userpanel |
| `OZON_CLIENT_ID`, `OZON_API_KEY` | seller.ozon.ru → Настройки → Seller API (данные только вашего магазина) |
| `AMAZON_CREDENTIAL_ID`, `AMAZON_CREDENTIAL_SECRET`, `AMAZON_PARTNER_TAG` | Amazon Associates → Creators API |

## CLI

```powershell
.\.venv\Scripts\analitik --help

# Этап 1 — юнит-экономика
.\.venv\Scripts\analitik econ --cost-cny 25 --sell-rub 2990 --mp wb
.\.venv\Scripts\analitik report-skeleton "powerbank"

# Smoke API
.\.venv\Scripts\analitik check ebay
.\.venv\Scripts\analitik check mpstats
.\.venv\Scripts\analitik check amazon
.\.venv\Scripts\analitik check ozon

# Ozon Seller — ваш магазин
.\.venv\Scripts\analitik ozon products

# Источники
.\.venv\Scripts\analitik ebay search "wireless earbuds" --limit 50
.\.venv\Scripts\analitik mpstats category --mp wb --path "Электроника/..." --from 2026-08-01 --to 2026-09-01
.\.venv\Scripts\analitik amazon search "power bank 20000"

# Сводный анализ
.\.venv\Scripts\analitik analyze "powerbank" `
  --wb-path "..." --ozon-path "..." `
  --cost-cny 25 --sell-rub 2990 --mp wb
```

Отчёты пишутся в `reports/*.html`, `*.xml`, `*.md`, `*.json`.

## Автопоиск товаров без API-ключей

Двойной клик по [`run_autoscan.bat`](run_autoscan.bat) (или `analitik scan --open`) — за ~2–3 минуты проходит по всем нишам из `catalog.py` и открывает отчёт `reports/scans/scan-*.html`.

| Источник | Что берём | Ограничение |
|---|---|---|
| Яндекс Маркет, поиск | «N купили», цена, рейтинг, число оценок | только первая страница выдачи; при частых запусках бывает капча |
| Amazon.com, поиск | «N+ bought in past month», рейтинг, оценки | мировой спрос, не РФ; цены скрыты для доставки вне США |

Wildberries, Ozon, eBay, AliExpress и 1688 без ключей данные не отдают (403 / рендер скриптами). Закупочная цена из Китая не собирается — вместо неё считается **максимальная закупка в ¥**, при которой на медианной цене остаётся `TARGET_MARGIN_PCT`.

Результаты за день кешируются в `reports/scans/cache-YYYYMMDD.json`: повторный запуск после капчи дособирает только недостающее.

## Дашборд управления

Двойной клик по [`run_dashboard.bat`](run_dashboard.bat) — откроется http://localhost:8501 (после обновления кода перезапустите его).

| Раздел | Страницы |
|---|---|
| Командный центр | задачи на сегодня, запас в днях, лучшие ниши, итоги месяца |
| Закупка | автопоиск товаров, план закупок, анализ ниши, юнит-экономика |
| Склад | остатки (свой склад + Ozon FBO/FBS + WB + в пути), закупки и поставки, движение товара, каталог и себестоимость |
| Маркетплейсы | Ozon, реклама Ozon (Performance API: кампании, ставки, оплата за заказ/клик, отчёты), Wildberries |
| Финансы | бухгалтерия (P&L, налог, деньги), расходы |
| Система | история отчётов, настройки (ключи, сроки поставки, налоги — пишутся в `.env`) |

Остаток на руках = свой склад + Ozon FBO + WB (+ едет к покупателю WB). Пока по артикулу нет движений в учёте, свой склад берётся из Ozon FBS.
Заказать = продажи в день × (срок поставки + страховой запас + покрытие) − (на руках + в пути).
Склад, закупки и расходы хранятся в `data/analitik.db` — делайте резервную копию.

## Автозапуск (Windows)

Двойной клик по [`run_analyze.bat`](run_analyze.bat) — сам поднимет `.venv`, поставит пакет, прогонит анализ и откроет цветной HTML-отчёт.

Параметры по умолчанию внутри bat (ниша `powerbank`). Можно передать свои:

```bat
run_analyze.bat "powerbank" "Электроника/Powerbanks" "Электроника/Powerbanks" 25 2990 wb
```

## Tests

```powershell
.\.venv\Scripts\pytest -q
.\.venv\Scripts\pytest -q -m integration
```

## Этапы

1. Unit economics + CLI + Cursor rule — без внешних ключей
2. eBay — после ключей developer.ebay.com
3. MPSTATS — после подписки «Внешняя аналитика»
4. Amazon Creators — после Associates credentials
5. `analyze` + scoring — объединяет источники

## Лицензия / License

Единственный и исключительный правообладатель: Панков Сергей Владимирович (Sergey Vladimirovich Pankov). Код проприетарный; любые действия с ним (копирование, изменение, использование, публикация, распространение, форк, производные произведения, продажа, сублицензирование) — только с его предварительного письменного согласия. Публичная видимость репозитория не даёт лицензии. См. [LICENSE](LICENSE) и [NOTICE](NOTICE).

Sole and exclusive copyright holder: Панков Сергей Владимирович (Sergey Vladimirovich Pankov). Proprietary code; any action with it (copying, modifying, using, publishing, distributing, forking, derivative works, selling, sublicensing) requires his prior written consent. Public visibility grants no license. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
