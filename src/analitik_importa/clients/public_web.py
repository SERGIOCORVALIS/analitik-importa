"""Keyless scrapers of public search pages (Yandex Market, Amazon.com).

Only numbers that are printed on the page are extracted; nothing is estimated.
"""

from __future__ import annotations

import html
import random
import re
import time

import httpx
from pydantic import BaseModel

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class BlockedError(RuntimeError):
    """The site answered with a captcha / anti-bot page."""


class ProductHit(BaseModel):
    source: str
    item_id: str
    title: str
    price: float | None = None
    currency: str | None = None
    rating: float | None = None
    reviews: int | None = None
    bought: int | None = None
    bought_label: str | None = None
    url: str | None = None
    image: str | None = None
    sponsored: bool = False


_SPACES = re.compile(r"[\s\u2009\u2006\u2005\u00a0\u202f]+")


def _num(text: str | None) -> float | None:
    if not text:
        return None
    raw = _SPACES.sub("", text).replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return html.unescape(m.group(1)).strip() if m else None


class _PoliteClient:
    def __init__(self, base_headers: dict[str, str], min_delay: float, timeout: float = 25.0) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", **base_headers},
            timeout=timeout,
            follow_redirects=True,
        )
        self._min_delay = min_delay
        self._last = 0.0

    def get(self, url: str, params: dict[str, str]) -> httpx.Response:
        wait = self._min_delay + random.uniform(0, 1.0) - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            return self._client.get(url, params=params)
        finally:
            self._last = time.monotonic()

    def close(self) -> None:
        self._client.close()


# ------------------------------------------------------------ Yandex Market

_YM_TITLE = re.compile(r'data-auto="snippet-title"[^>]*>([^<]+)')
_YM_LINK = re.compile(r'href="(/(?:card|product)/[^"?]+)')
_YM_PRICE = re.compile(r"Цена\s+([\d\s\u2009\u00a0]+)\s*₽")
_YM_RATING = re.compile(r"Рейтинг товара: ([\d.]+)")
_YM_REVIEWS = re.compile(r"Оценок: \(([\d\s\u2009\u00a0]+)\)")
_YM_BOUGHT = re.compile(r"([\d][\d\s\u2009\u00a0,]*)\s*(тыс\.?)?\s*купил\w*")
_YM_IMAGE = re.compile(r'<img[^>]+src="(https://avatars\.mds\.yandex\.net/[^"]+)"')


def _ym_bought(snippet: str) -> tuple[int | None, str | None]:
    m = _YM_BOUGHT.search(snippet)
    if not m:
        return None, None
    value = _num(m.group(1))
    if value is None:
        return None, None
    if m.group(2):
        value *= 1000
    label = _SPACES.sub(" ", m.group(0)).strip()
    return int(value), label


def parse_yandex_market(page: str) -> list[ProductHit]:
    hits: dict[str, ProductHit] = {}
    for snippet in page.split('data-zone-name="productSnippet"')[1:]:
        title = _first(_YM_TITLE, snippet)
        link = _first(_YM_LINK, snippet)
        if not title or not link:
            continue
        item_id = link.rstrip("/").rsplit("/", 1)[-1]
        bought, bought_label = _ym_bought(snippet)
        reviews = _num(_first(_YM_REVIEWS, snippet))
        hit = ProductHit(
            source="yandex_market",
            item_id=item_id,
            title=title,
            price=_num(_first(_YM_PRICE, snippet)),
            currency="RUB",
            rating=_num(_first(_YM_RATING, snippet)),
            reviews=int(reviews) if reviews is not None else None,
            bought=bought,
            bought_label=bought_label,
            url=f"https://market.yandex.ru{link}",
            image=_first(_YM_IMAGE, snippet),
            sponsored="sponsored=1" in snippet[:4000],
        )
        if item_id not in hits or (hits[item_id].sponsored and not hit.sponsored):
            hits[item_id] = hit
    return list(hits.values())


class YandexMarketScraper:
    BASE = "https://market.yandex.ru/search"

    def __init__(self, min_delay: float = 2.0) -> None:
        self._http = _PoliteClient({"Accept-Language": "ru-RU,ru;q=0.9"}, min_delay)

    def search(self, query: str) -> list[ProductHit]:
        r = self._http.get(self.BASE, {"text": query})
        if r.status_code != 200:
            raise RuntimeError(f"Яндекс Маркет ответил {r.status_code}")
        if "showcaptcha" in str(r.url) or "smartcaptcha" in r.text[:50000].lower():
            raise BlockedError("Яндекс Маркет показал капчу — повторите позже")
        return parse_yandex_market(r.text)

    def close(self) -> None:
        self._http.close()


# ------------------------------------------------------------------ Amazon

_AMZ_RESULT = re.compile(r'data-asin="([A-Z0-9]{10})"[^>]*data-component-type="s-search-result"')
_AMZ_TITLE = re.compile(r'<h2[^>]*aria-label="([^"]+)"')
_AMZ_TITLE_SPAN = re.compile(r"<h2[^>]*>\s*<span[^>]*>([^<]+)")
_AMZ_RATING = re.compile(r"([\d.]+) out of 5 stars")
_AMZ_REVIEWS = re.compile(r'aria-label="([\d,]+) ratings"')
_AMZ_BOUGHT = re.compile(r"([\d.]+)(K|M)?\+ bought in past month")
_AMZ_IMAGE = re.compile(r'<img class="s-image" src="([^"]+)"')
_AMZ_PRICE = re.compile(r'class="a-offscreen">\$([\d,]+\.\d{2})<')


def _amz_bought(item: str) -> tuple[int | None, str | None]:
    m = _AMZ_BOUGHT.search(item)
    if not m:
        return None, None
    value = float(m.group(1)) * {"K": 1_000, "M": 1_000_000}.get(m.group(2) or "", 1)
    return int(value), m.group(0)


def parse_amazon_search(page: str) -> list[ProductHit]:
    hits: dict[str, ProductHit] = {}
    starts = list(_AMZ_RESULT.finditer(page))
    for pos, m in enumerate(starts):
        asin = m.group(1)
        item = page[m.end() : starts[pos + 1].start() if pos + 1 < len(starts) else len(page)]
        title = _first(_AMZ_TITLE, item) or _first(_AMZ_TITLE_SPAN, item)
        if not title or asin in hits:
            continue
        bought, bought_label = _amz_bought(item)
        reviews = _first(_AMZ_REVIEWS, item)
        price = _first(_AMZ_PRICE, item)
        hits[asin] = ProductHit(
            source="amazon",
            item_id=asin,
            title=title.removeprefix("Sponsored Ad - "),
            price=float(price.replace(",", "")) if price else None,
            currency="USD" if price else None,
            rating=_num(_first(_AMZ_RATING, item)),
            reviews=int(reviews.replace(",", "")) if reviews else None,
            bought=bought,
            bought_label=bought_label,
            url=f"https://www.amazon.com/dp/{asin}",
            image=_first(_AMZ_IMAGE, item),
            sponsored="Sponsored" in item[:6000],
        )
    return list(hits.values())


class AmazonPublicScraper:
    BASE = "https://www.amazon.com/s"

    def __init__(self, min_delay: float = 2.0) -> None:
        self._http = _PoliteClient({"Accept-Language": "en-US,en;q=0.9"}, min_delay)

    def search(self, keywords: str) -> list[ProductHit]:
        r = self._http.get(self.BASE, {"k": keywords})
        if r.status_code != 200:
            raise RuntimeError(f"Amazon ответил {r.status_code}")
        if "captcha" in r.text[:20000].lower() and "s-search-result" not in r.text:
            raise BlockedError("Amazon показал капчу — повторите позже")
        return parse_amazon_search(r.text)

    def close(self) -> None:
        self._http.close()
