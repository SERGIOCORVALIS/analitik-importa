from datetime import date

import httpx
import pytest

from analitik_importa.clients import ozon_performance as op
from analitik_importa.config import Settings


def make_client(handler) -> op.OzonPerformanceClient:
    c = op.OzonPerformanceClient(Settings(ozon_perf_client_id="id", ozon_perf_client_secret="secret"))
    c._http = httpx.Client(base_url=op.BASE_URL, transport=httpx.MockTransport(handler))
    return c


def token_or(handler):
    def wrapped(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/client/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800, "token_type": "Bearer"})
        assert request.headers["Authorization"] == "Bearer t"
        return handler(request)

    return wrapped


def test_number_parsing():
    assert op.num("1 234,50") == 1234.5
    assert op.num("") == 0.0
    assert op.rub("2000000000") == 2000.0
    assert op.to_micro(15.5) == "15500000"
    assert op.to_micro(None) is None


def test_requires_credentials():
    with pytest.raises(RuntimeError, match="OZON_PERF_CLIENT_ID"):
        op.OzonPerformanceClient(Settings(ozon_perf_client_id="", ozon_perf_client_secret=""))


def test_campaigns_and_daily_parsing():
    def handler(request):
        if request.url.path == "/api/client/campaign":
            return httpx.Response(200, json={"list": [{
                "id": "43189161", "title": "Все товары", "state": "CAMPAIGN_STATE_RUNNING",
                "advObjectType": "ALL_SKU_PROMO", "PaymentType": "CPO", "weeklyBudget": "14000000000",
                "placement": ["PLACEMENT_TOP_PROMOTION"], "createdAt": "2026-09-24T16:13:44Z"}]})
        return httpx.Response(200, json={"rows": [
            {"id": "43189161", "title": "Все товары", "date": "2026-10-01", "views": "81", "clicks": "6",
             "moneySpent": "120,50", "orders": "2", "ordersMoney": "1 980,00"}]})

    c = make_client(token_or(handler))
    camp = c.campaigns()[0]
    assert camp["state_ru"] == "Активна" and camp["type_ru"].startswith("Оплата за заказ")
    assert camp["weekly_budget"] == 14000.0 and camp["placement"] == "Поиск"
    row = c.daily(date(2026, 10, 1), date(2026, 10, 1))[0]
    assert row["spent"] == 120.5 and row["orders_rub"] == 1980.0 and row["clicks"] == 6


def test_update_bids_sends_micro_rubles():
    seen = {}

    def handler(request):
        seen["method"], seen["path"], seen["body"] = request.method, request.url.path, request.content
        return httpx.Response(200, json={})

    make_client(token_or(handler)).update_bids("777", [{"sku": 123, "bid_rub": 12.5}])
    assert seen["method"] == "PUT" and seen["path"] == "/api/client/campaign/777/products"
    assert b'"bid":"12500000"' in seen["body"].replace(b" ", b"")


def test_all_sku_bid_validated_before_request():
    c = make_client(token_or(lambda r: pytest.fail("no request expected")))
    with pytest.raises(ValueError):
        c.all_sku_set_bid(6)


def test_report_rows_unwrap_nested():
    assert op.OzonPerformanceClient._rows({"rows": [{"a": 1}]}) == [{"a": 1}]
    assert op.OzonPerformanceClient._rows({"report": {"rows": [{"b": 2}]}}) == [{"b": 2}]
    assert op.OzonPerformanceClient._rows({}) == []


def test_http_error_is_readable():
    c = make_client(token_or(lambda r: httpx.Response(400, json={"error": "Кампания не найдена"})))
    with pytest.raises(RuntimeError, match="Кампания не найдена"):
        c.campaign_products("1")
