from datetime import date

import pytest

from analitik_importa.accounting import MpFinance, build_pnl, tax_for
from analitik_importa.config import Settings
from analitik_importa.env_store import update_env
from analitik_importa.inventory import (
    STATUS_EXCESS,
    STATUS_NO_SALES,
    STATUS_OK,
    STATUS_ORDER,
    STATUS_URGENT,
    MpSnapshot,
    build_inventory,
    classify,
)
from analitik_importa.storage import Book


@pytest.fixture
def book(tmp_path):
    return Book(tmp_path / "t.db")


@pytest.fixture
def s():
    return Settings(_env_file=None, lead_time_days=40, safety_days=10, cover_days=60, sales_window_days=30)


def test_purchase_receive_updates_stock_and_average_cost(book):
    pid = book.add_purchase("A-1", 100, unit_cny=10, cny_rub_rate=12, cargo_rub=1000)
    assert book.in_transit() == {"A-1": 100}
    book.receive_purchase(pid)
    assert book.own_stock() == {"A-1": 100}
    assert book.in_transit() == {}
    assert book.products()[0]["cost_rub"] == 130.0  # (100*10*12 + 1000) / 100

    pid2 = book.add_purchase("A-1", 100, unit_cny=15, cny_rub_rate=12)
    book.receive_purchase(pid2, stock_elsewhere=0)
    assert book.products()[0]["cost_rub"] == 155.0  # (100*130 + 100*180) / 200
    book.receive_purchase(pid2)  # idempotent
    assert book.own_stock()["A-1"] == 200


def test_moves_signs(book):
    book.add_move("B", 50, "receipt")
    book.add_move("B", 20, "to_mp", mp="ozon")
    book.add_move("B", 3, "writeoff")
    book.add_move("B", -2, "adjust")
    assert book.own_stock()["B"] == 25


def test_classify():
    assert classify(0, 10, 0, 40, 10, 60)[0] == STATUS_NO_SALES
    status, qty, days = classify(2, 50, 0, 40, 10, 60)
    assert status == STATUS_URGENT and qty == 2 * 110 - 50 and days == 25
    assert classify(2, 70, 15, 40, 10, 60)[0] == STATUS_ORDER
    assert classify(2, 120, 0, 40, 10, 60) == (STATUS_OK, 0, 60)
    assert classify(1, 500, 0, 40, 10, 60)[0] == STATUS_EXCESS


def test_inventory_merges_sources_without_double_counting_fbs(book, s):
    snap = MpSnapshot(window_days=30)
    snap.names = {"X": "Товар X", "Y": "Товар Y"}
    snap.ozon_stock = {"X": {"fbo": 30, "fbs": 50, "fbo_reserved": 0, "fbs_reserved": 0}}
    snap.wb_stock = {"X": {"qty": 20, "to_client": 5, "from_client": 0}}
    snap.ozon_sales = {"X": {"units": 60, "revenue": 60000}}
    snap.wb_sales = {"X": {"units": 30, "revenue": 30000}}
    snap.ozon_stock["Y"] = {"fbo": 0, "fbs": 40, "fbo_reserved": 0, "fbs_reserved": 0}

    rows = {r["sku"]: r for r in build_inventory(book, snap, s)}
    # Y has no own-warehouse moves -> FBS stands in for own stock
    assert rows["Y"]["own"] == 40 and rows["Y"]["physical"] == 40
    # X: once tracked, own warehouse comes from the book and FBS is not added
    book.add_move("X", 10, "receipt")
    rows = {r["sku"]: r for r in build_inventory(book, snap, s)}
    assert rows["X"]["physical"] == 10 + 30 + 20 + 5
    assert rows["X"]["per_day"] == 3.0
    assert rows["X"]["status"] == STATUS_URGENT
    assert {p["sku"] for p in book.products()} == {"X", "Y"}


def test_pnl_and_tax(book, s):
    book.update_product("A", cost_rub=100)
    book.add_expense(500, "Реклама", date(2026, 10, 5))
    book.add_purchase("A", 10, 5, 12, created=date(2026, 10, 2))
    mp = {"Ozon": MpFinance(revenue=10000, returns=1000, commission=1500, logistics=500, other=200, units={"A": 20, "B": 3})}
    pnl = build_pnl(book, s, date(2026, 10, 1), date(2026, 10, 31), mp)
    assert pnl.cogs == 2000 and pnl.cogs_missing == ["B"]
    assert pnl.gross_profit == 10000 - 1000 - 2200 - 2000
    assert pnl.tax == pytest.approx(9000 * 0.06)
    assert pnl.net_profit == pytest.approx(4800 - 500 - 540)
    assert pnl.purchases_paid == 600
    assert pnl.cash_flow == pytest.approx(mp["Ozon"].payout - 600 - 500 - 540)
    assert tax_for("usn15", 15, 9000, -100)[0] == 0


def test_update_env_keeps_comments(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nOZON_CLIENT_ID=1\nOTHER=x\n", encoding="utf-8")
    update_env({"ozon_client_id": "123456", "WB_API_TOKEN": "abc def"}, path=env)
    text = env.read_text(encoding="utf-8")
    assert "# comment" in text and "OZON_CLIENT_ID=123456" in text and "OTHER=x" in text
    assert 'WB_API_TOKEN="abc def"' in text
