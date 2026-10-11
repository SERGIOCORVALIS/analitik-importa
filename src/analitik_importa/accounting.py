"""Management P&L for a period: marketplace reports + cost of goods + own expenses + tax estimate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from analitik_importa.config import Settings
from analitik_importa.storage import Book

TAX_MODES = {
    "usn6": "УСН «Доходы» — % от выручки",
    "usn15": "УСН «Доходы минус расходы» — % от прибыли",
    "npd": "НПД (самозанятый) — % от выручки",
    "osno": "ОСНО — налог считает бухгалтер",
    "none": "Не учитывать налог",
}


@dataclass
class MpFinance:
    revenue: float = 0.0
    returns: float = 0.0
    commission: float = 0.0
    logistics: float = 0.0
    other: float = 0.0
    units: dict[str, float] = field(default_factory=dict)

    @property
    def payout(self) -> float:
        return self.revenue - self.returns - self.commission - self.logistics - self.other


@dataclass
class Pnl:
    d1: date
    d2: date
    by_mp: dict[str, MpFinance]
    cogs: float
    cogs_missing: list[str]
    expenses: dict[str, float]
    tax: float
    tax_note: str
    purchases_paid: float
    errors: list[str] = field(default_factory=list)

    @property
    def revenue(self) -> float:
        return sum(m.revenue for m in self.by_mp.values())

    @property
    def returns(self) -> float:
        return sum(m.returns for m in self.by_mp.values())

    @property
    def net_revenue(self) -> float:
        return self.revenue - self.returns

    @property
    def mp_fees(self) -> float:
        return sum(m.commission + m.logistics + m.other for m in self.by_mp.values())

    @property
    def payout(self) -> float:
        return sum(m.payout for m in self.by_mp.values())

    @property
    def expenses_total(self) -> float:
        return sum(self.expenses.values())

    @property
    def gross_profit(self) -> float:
        return self.net_revenue - self.mp_fees - self.cogs

    @property
    def profit_before_tax(self) -> float:
        return self.gross_profit - self.expenses_total

    @property
    def net_profit(self) -> float:
        return self.profit_before_tax - self.tax

    @property
    def margin_pct(self) -> float | None:
        return self.net_profit / self.net_revenue * 100 if self.net_revenue else None

    @property
    def cash_flow(self) -> float:
        """Money in from marketplaces minus money out for purchases and expenses."""
        return self.payout - self.purchases_paid - self.expenses_total - self.tax

    def lines(self) -> list[tuple[str, float]]:
        out = [("Выручка (продажи)", self.revenue), ("Возвраты", -self.returns)]
        out.append(("Комиссии маркетплейсов", -sum(m.commission for m in self.by_mp.values())))
        out.append(("Логистика маркетплейсов", -sum(m.logistics for m in self.by_mp.values())))
        out.append(("Хранение, штрафы, прочие услуги МП", -sum(m.other for m in self.by_mp.values())))
        out.append(("Себестоимость проданных товаров", -self.cogs))
        out.append(("Валовая прибыль", self.gross_profit))
        for cat, amount in sorted(self.expenses.items(), key=lambda x: -x[1]):
            out.append((f"Расход: {cat}", -amount))
        out.append(("Прибыль до налога", self.profit_before_tax))
        out.append(("Налог (оценка)", -self.tax))
        out.append(("Чистая прибыль", self.net_profit))
        return out


def tax_for(mode: str, rate_pct: float, net_revenue: float, profit_before_tax: float) -> tuple[float, str]:
    rate = rate_pct / 100
    if mode in ("usn6", "npd"):
        return max(0.0, net_revenue * rate), f"{rate_pct:g}% от выручки за вычетом возвратов"
    if mode == "usn15":
        return max(0.0, profit_before_tax * rate), f"{rate_pct:g}% от прибыли (упрощённо, без минимального налога 1%)"
    if mode == "osno":
        return 0.0, "ОСНО: НДС и налог на прибыль здесь не считаются"
    return 0.0, "Налог не учитывается"


def build_pnl(book: Book, s: Settings, d1: date, d2: date, by_mp: dict[str, MpFinance], errors: list[str] | None = None) -> Pnl:
    costs = {p["sku"]: float(p["cost_rub"] or 0) for p in book.products()}
    units: dict[str, float] = {}
    for m in by_mp.values():
        for sku, n in m.units.items():
            units[sku] = units.get(sku, 0.0) + n
    cogs = sum(n * costs.get(sku, 0.0) for sku, n in units.items() if n > 0)
    missing = sorted(sku for sku, n in units.items() if n > 0 and not costs.get(sku))

    expenses: dict[str, float] = {}
    for e in book.expenses(d1, d2):
        expenses[e["category"]] = expenses.get(e["category"], 0.0) + float(e["amount"])

    pnl = Pnl(
        d1=d1, d2=d2, by_mp=by_mp, cogs=round(cogs, 2), cogs_missing=missing, expenses=expenses,
        tax=0.0, tax_note="", purchases_paid=book.purchases_paid(d1, d2), errors=list(errors or []),
    )
    pnl.tax, pnl.tax_note = tax_for(s.tax_mode, s.tax_rate_pct, pnl.net_revenue, pnl.profit_before_tax)
    pnl.tax = round(pnl.tax, 2)
    return pnl


def collect_mp_finance(s: Settings, d1: date, d2: date) -> tuple[dict[str, MpFinance], list[str]]:
    out: dict[str, MpFinance] = {}
    errors: list[str] = []
    if s.ozon_client_id and s.ozon_api_key:
        from analitik_importa.clients.ozon_seller import OzonSellerClient

        try:
            client = OzonSellerClient(s)
            fin = client.finance(d1, d2)
            m = MpFinance(
                revenue=fin["revenue"], returns=fin["returns"], commission=fin["commission"],
                logistics=fin["logistics"], other=fin["services"],
            )
            offers = [p["offer_id"] for p in client.list_products() if p.get("offer_id")]
            sku_to_offer = {str(d["sku"]): d["offer_id"] for d in client.product_details(offers) if d.get("sku")} if offers else {}
            for ozon_sku, v in client.sales_by_sku(d1, d2).items():
                if ozon_sku in sku_to_offer:
                    m.units[sku_to_offer[ozon_sku]] = v["units"]
            out["Ozon"] = m
        except RuntimeError as exc:
            errors.append(f"Ozon: {exc}")
    if s.wb_api_token:
        from analitik_importa.clients.wb_seller import WbSellerClient

        try:
            client = WbSellerClient(s)
            fin = client.finance_report(d1, d2)
            m = MpFinance(
                revenue=fin["revenue"], returns=fin["returns"], commission=fin["commission"], logistics=fin["logistics"],
                other=fin["storage"] + fin["penalty"] + fin["acceptance"] + fin["deduction"],
            )
            days = (date.today() - d1).days + 1
            for sale in client.sales(days):
                if d1.isoformat() <= sale["date"] <= d2.isoformat():
                    m.units[sale["sku"]] = m.units.get(sale["sku"], 0.0) + (-1 if sale["is_return"] else 1)
            out["Wildberries"] = m
        except RuntimeError as exc:
            errors.append(f"Wildberries: {exc}")
    return out, errors
