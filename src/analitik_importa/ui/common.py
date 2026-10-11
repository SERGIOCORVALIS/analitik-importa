from __future__ import annotations

import html
from dataclasses import dataclass

import streamlit as st

from analitik_importa.config import Settings
from analitik_importa.inventory import STATUS_COLOR, MpSnapshot, collect_snapshot
from analitik_importa.models import Verdict
from analitik_importa.report import VERDICT_BG, VERDICT_COLOR, VERDICT_RU
from analitik_importa.storage import Book

MP_LABELS = {"wb": "Wildberries", "ozon": "Ozon", "ym": "Яндекс Маркет", "avito": "Avito"}

CSS = """
<style>
  .block-container { padding-top: 1.2rem; max-width: 1480px; }
  [data-testid="stSidebarNav"] a span { font-size: 0.95rem; }
  .hero {
    background: linear-gradient(120deg, #1e1b4b 0%, #3730a3 45%, #6d28d9 100%);
    color: #fff; border-radius: 20px; padding: 22px 26px; margin-bottom: 18px;
    box-shadow: 0 12px 32px rgba(55, 48, 163, .25);
  }
  .hero h1 { color: #fff; font-size: 1.85rem; margin: 0; padding: 0; font-weight: 750; }
  .hero p { color: #c7d2fe; margin: 6px 0 0; font-size: 0.98rem; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; margin: 4px 0 18px; }
  .kpi {
    background: #fff; border: 1px solid #e6e9f2; border-radius: 16px; padding: 14px 16px 14px 18px;
    box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(16,24,40,.05); position: relative; overflow: hidden;
    color: #0f172a;
  }
  .kpi:before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 5px; background: var(--accent, #4f46e5); }
  .kpi .label { font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; color: #64748b; font-weight: 600; }
  .kpi .value { font-size: 1.65rem; font-weight: 750; margin-top: 4px; line-height: 1.15; }
  .kpi .sub { font-size: .82rem; color: #64748b; margin-top: 4px; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: .8rem; font-weight: 650; }
  .panel {
    background: #fff; border: 1px solid #e6e9f2; border-radius: 16px; padding: 14px 18px; color: #0f172a;
    box-shadow: 0 1px 2px rgba(16,24,40,.04);
  }
  .alert-row { display: flex; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px dashed #e2e8f0; }
  .alert-row:last-child { border-bottom: 0; }
  .verdict { border-radius: 14px; padding: 14px 18px; margin: 4px 0 14px; font-size: 1.02rem; border: 2px solid; }
  .verdict b { font-size: 1.4rem; }
  .src-card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; background: #fff; color: #0f172a; height: 100%; }
  .src-card .name { font-weight: 700; }
  .src-card .state { margin-top: 6px; font-size: 0.92rem; }
  .hint { color: #64748b; font-size: 0.9rem; }
  div[data-testid="stMetric"] {
    background: #fff; border: 1px solid #e6e9f2; border-radius: 14px; padding: 10px 14px;
  }
</style>
"""


NO_TRANSLATE_JS = """<script>
const root = document.documentElement;
root.lang = "ru";
root.setAttribute("translate", "no");
root.classList.add("notranslate");
if (!document.querySelector('meta[name="google"]')) {
  const m = document.createElement("meta");
  m.name = "google";
  m.content = "notranslate";
  document.head.appendChild(m);
}
</script>"""


def inject_css() -> None:
    # Browser auto-translate rewrites React-managed DOM and crashes the app with "removeChild" errors.
    st.html(NO_TRANSLATE_JS, unsafe_allow_javascript=True)
    st.markdown(CSS, unsafe_allow_html=True)


def settings() -> Settings:
    # Fresh instance on every rerun so edits to .env are picked up.
    return Settings()


@st.cache_resource
def book() -> Book:
    return Book()


def fmt_rub(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} ₽".replace(",", " ")


def fmt_num(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ")


def hero(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="hero"><h1>{html.escape(title)}</h1>'
        + (f"<p>{html.escape(subtitle)}</p>" if subtitle else "")
        + "</div>",
        unsafe_allow_html=True,
    )


@dataclass
class Kpi:
    label: str
    value: str
    sub: str = ""
    accent: str = "#4f46e5"


def kpi_row(items: list[Kpi]) -> None:
    cards = "".join(
        f'<div class="kpi" style="--accent:{k.accent}"><div class="label">{html.escape(k.label)}</div>'
        f'<div class="value">{html.escape(k.value)}</div>'
        + (f'<div class="sub">{html.escape(k.sub)}</div>' if k.sub else "")
        + "</div>"
        for k in items
    )
    st.markdown(f'<div class="kpis">{cards}</div>', unsafe_allow_html=True)


def badge(text: str, color: str) -> str:
    return f'<span class="badge" style="background:{color}1f;color:{color}">{html.escape(text)}</span>'


def status_badge(status: str) -> str:
    return badge(status, STATUS_COLOR.get(status, "#64748b"))


def verdict_banner(verdict: Verdict, title: str, detail: str = "") -> None:
    st.markdown(
        f'<div class="verdict" style="background:{VERDICT_BG[verdict]};'
        f'border-color:{VERDICT_COLOR[verdict]};color:{VERDICT_COLOR[verdict]}">'
        f"{title}: <b>{VERDICT_RU[verdict]}</b>"
        f"{'<br/>' + detail if detail else ''}</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=600, show_spinner=False)
def _snapshot(ozon_id: str, ozon_key: str, wb_token: str, window: int) -> MpSnapshot:
    return collect_snapshot(settings(), window)


def snapshot() -> MpSnapshot:
    s = settings()
    with st.spinner("Загружаю данные маркетплейсов…"):
        return _snapshot(s.ozon_client_id, s.ozon_api_key, s.wb_api_token, s.sales_window_days)


def refresh_button(key: str) -> None:
    if st.button("↻ Обновить данные МП", key=key, help="Данные маркетплейсов кешируются на 10 минут"):
        _snapshot.clear()
        st.rerun()


def connections_note(snap: MpSnapshot) -> None:
    parts = []
    for mp, label in (("ozon", "Ozon"), ("wb", "Wildberries")):
        parts.append(badge(f"● {label}: {'подключён' if snap.connected[mp] else 'не подключён'}",
                           "#10b981" if snap.connected[mp] else "#94a3b8"))
    st.markdown(
        " ".join(parts) + f' <span class="hint">· продажи за {snap.window_days} дн. · обновлено '
        f'{snap.fetched_at.strftime("%H:%M")}</span>',
        unsafe_allow_html=True,
    )
    for err in snap.errors:
        st.warning(err)
