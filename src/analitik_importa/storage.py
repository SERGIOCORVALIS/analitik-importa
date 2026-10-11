"""Local SQLite book: product catalog, own warehouse moves, China purchases, expenses."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from analitik_importa.config import ROOT_DIR

DB_PATH = Path(os.environ.get("ANALITIK_DB") or ROOT_DIR / "data" / "analitik.db")

MOVE_KINDS = {
    "receipt": "Приход (поставка из Китая)",
    "to_mp": "Отгрузка на склад маркетплейса",
    "return": "Возврат с маркетплейса",
    "writeoff": "Списание (брак, потеря)",
    "adjust": "Инвентаризация (корректировка)",
}
PURCHASE_STATUSES = {
    "ordered": "Заказано",
    "in_transit": "В пути",
    "received": "Получено",
    "cancelled": "Отменено",
}
EXPENSE_CATEGORIES = [
    "Реклама",
    "Упаковка и маркировка",
    "Фулфилмент",
    "Доставка до склада МП",
    "Сертификация",
    "Зарплата",
    "Аренда",
    "Сервисы и подписки",
    "Банк и эквайринг",
    "Прочее",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    cost_rub REAL NOT NULL DEFAULT 0,
    lead_time_days INTEGER,
    safety_days INTEGER,
    cover_days INTEGER,
    supplier TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dt TEXT NOT NULL,
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    kind TEXT NOT NULL,
    mp TEXT,
    purchase_id INTEGER,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cny REAL NOT NULL,
    cny_rub_rate REAL NOT NULL,
    cargo_rub REAL NOT NULL DEFAULT 0,
    other_rub REAL NOT NULL DEFAULT 0,
    supplier TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ordered',
    eta TEXT,
    received_at TEXT,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dt TEXT NOT NULL,
    category TEXT NOT NULL,
    amount REAL NOT NULL,
    mp TEXT,
    note TEXT NOT NULL DEFAULT ''
);
"""


class Book:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    # -------------------------------------------------------------- products

    def products(self, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM products" + (" WHERE active = 1" if active_only else "") + " ORDER BY sku"
        return self._rows(sql)

    EDITABLE = ("name", "cost_rub", "lead_time_days", "safety_days", "cover_days", "supplier", "notes", "active")

    def upsert_product(self, sku: str, name: str = "") -> None:
        """Register a product; a marketplace name fills an empty name but never overwrites yours."""
        sku = sku.strip()
        if not sku:
            raise ValueError("Артикул не может быть пустым")
        with self._conn() as c:
            exists = c.execute("SELECT name FROM products WHERE sku = ?", (sku,)).fetchone()
            if exists is None:
                c.execute(
                    "INSERT INTO products (sku, name, created_at) VALUES (?, ?, ?)",
                    (sku, name, datetime.now().isoformat(timespec="seconds")),
                )
            elif name and not exists["name"]:
                c.execute("UPDATE products SET name = ? WHERE sku = ?", (name, sku))

    def update_product(self, sku: str, **fields: Any) -> None:
        self.upsert_product(sku)
        with self._conn() as c:
            for key, value in fields.items():
                if key not in self.EDITABLE:
                    raise ValueError(f"Поле нельзя менять: {key}")
                c.execute(f"UPDATE products SET {key} = ? WHERE sku = ?", (value, sku))

    def sync_names(self, items: dict[str, str]) -> int:
        """Register marketplace listings (sku -> name); returns how many were new."""
        known = {p["sku"] for p in self.products()}
        for sku, name in items.items():
            self.upsert_product(sku, name)
        return len(set(items) - known)

    # ------------------------------------------------------------ warehouse

    def add_move(self, sku: str, qty: int, kind: str, mp: str | None = None, note: str = "",
                 dt: date | None = None, purchase_id: int | None = None) -> None:
        if kind not in MOVE_KINDS:
            raise ValueError(f"Неизвестный тип движения: {kind}")
        if kind in ("to_mp", "writeoff") and qty > 0:
            qty = -qty
        if kind in ("receipt", "return") and qty < 0:
            qty = -qty
        self.upsert_product(sku)
        with self._conn() as c:
            c.execute(
                "INSERT INTO stock_moves (dt, sku, qty, kind, mp, purchase_id, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ((dt or date.today()).isoformat(), sku, int(qty), kind, mp, purchase_id, note),
            )

    def moves(self, limit: int = 500) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM stock_moves ORDER BY dt DESC, id DESC LIMIT ?", (limit,))

    def own_stock(self) -> dict[str, int]:
        rows = self._rows("SELECT sku, SUM(qty) AS qty FROM stock_moves GROUP BY sku")
        return {r["sku"]: int(r["qty"] or 0) for r in rows}

    def shipped_to_mp(self, d1: date, d2: date) -> dict[str, int]:
        rows = self._rows(
            "SELECT sku, -SUM(qty) AS qty FROM stock_moves WHERE kind = 'to_mp' AND dt BETWEEN ? AND ? GROUP BY sku",
            (d1.isoformat(), d2.isoformat()),
        )
        return {r["sku"]: int(r["qty"] or 0) for r in rows}

    # ------------------------------------------------------------ purchases

    @staticmethod
    def purchase_total(p: dict[str, Any]) -> float:
        return p["qty"] * p["unit_cny"] * p["cny_rub_rate"] + p["cargo_rub"] + p["other_rub"]

    def add_purchase(self, sku: str, qty: int, unit_cny: float, cny_rub_rate: float, cargo_rub: float = 0.0,
                     other_rub: float = 0.0, supplier: str = "", eta: date | None = None, note: str = "",
                     created: date | None = None) -> int:
        if qty <= 0:
            raise ValueError("Количество должно быть больше нуля")
        self.upsert_product(sku)
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO purchases (created, sku, qty, unit_cny, cny_rub_rate, cargo_rub, other_rub, supplier, eta, note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ((created or date.today()).isoformat(), sku, int(qty), unit_cny, cny_rub_rate, cargo_rub, other_rub,
                 supplier, eta.isoformat() if eta else None, note),
            )
            return int(cur.lastrowid)

    def purchases(self) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM purchases ORDER BY created DESC, id DESC")
        for r in rows:
            r["total_rub"] = round(self.purchase_total(r), 2)
            r["unit_rub"] = round(r["total_rub"] / r["qty"], 2) if r["qty"] else 0.0
        return rows

    def set_purchase_status(self, purchase_id: int, status: str) -> None:
        if status not in PURCHASE_STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        if status == "received":
            self.receive_purchase(purchase_id)
            return
        with self._conn() as c:
            c.execute("UPDATE purchases SET status = ? WHERE id = ? AND status != 'received'", (status, purchase_id))

    def receive_purchase(self, purchase_id: int, stock_elsewhere: int = 0, dt: date | None = None) -> None:
        """Put goods on the own warehouse and update moving-average unit cost.

        stock_elsewhere: units of this SKU already on marketplace warehouses (they carry the old cost).
        """
        rows = self._rows("SELECT * FROM purchases WHERE id = ?", (purchase_id,))
        if not rows:
            raise ValueError(f"Закупка #{purchase_id} не найдена")
        p = rows[0]
        if p["status"] == "received":
            return
        sku = p["sku"]
        unit = self.purchase_total(p) / p["qty"]
        old_qty = max(0, self.own_stock().get(sku, 0) + stock_elsewhere)
        product = next((x for x in self.products() if x["sku"] == sku), None)
        old_cost = float(product["cost_rub"]) if product else 0.0
        new_cost = unit if old_qty == 0 or old_cost == 0 else (old_qty * old_cost + p["qty"] * unit) / (old_qty + p["qty"])
        when = dt or date.today()
        self.add_move(sku, p["qty"], "receipt", note=f"Закупка #{purchase_id}", dt=when, purchase_id=purchase_id)
        with self._conn() as c:
            c.execute("UPDATE purchases SET status = 'received', received_at = ? WHERE id = ?", (when.isoformat(), purchase_id))
        self.update_product(sku, cost_rub=round(new_cost, 2))

    def in_transit(self) -> dict[str, int]:
        rows = self._rows(
            "SELECT sku, SUM(qty) AS qty FROM purchases WHERE status IN ('ordered', 'in_transit') GROUP BY sku"
        )
        return {r["sku"]: int(r["qty"] or 0) for r in rows}

    def purchases_paid(self, d1: date, d2: date) -> float:
        rows = self._rows(
            "SELECT * FROM purchases WHERE status != 'cancelled' AND created BETWEEN ? AND ?",
            (d1.isoformat(), d2.isoformat()),
        )
        return round(sum(self.purchase_total(r) for r in rows), 2)

    # ------------------------------------------------------------- expenses

    def add_expense(self, amount: float, category: str, dt: date | None = None, mp: str | None = None, note: str = "") -> None:
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        with self._conn() as c:
            c.execute(
                "INSERT INTO expenses (dt, category, amount, mp, note) VALUES (?, ?, ?, ?, ?)",
                ((dt or date.today()).isoformat(), category, amount, mp, note),
            )

    def expenses(self, d1: date | None = None, d2: date | None = None) -> list[dict[str, Any]]:
        if d1 and d2:
            return self._rows(
                "SELECT * FROM expenses WHERE dt BETWEEN ? AND ? ORDER BY dt DESC, id DESC", (d1.isoformat(), d2.isoformat())
            )
        return self._rows("SELECT * FROM expenses ORDER BY dt DESC, id DESC")

    def delete_expense(self, expense_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
