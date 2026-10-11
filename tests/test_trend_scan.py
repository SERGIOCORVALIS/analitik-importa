from analitik_importa.clients.public_web import parse_amazon_search, parse_yandex_market
from analitik_importa.config import Settings
from analitik_importa.models import Verdict
from analitik_importa.trend_scan import NicheScan, max_purchase_cny, percentile_ranks, score_all, summarize

YM_PAGE = (
    "<div data-zone-name=\"productSnippet\">"
    '<a href="/card/poverbank-5000/4814369712?ogV=357&amp;sponsored=1">'
    '<span data-auto="snippet-title" class="x">Повербанк 5000 mAh</span>'
    '<img src="https://avatars.mds.yandex.net/get-mpic/1/a/orig" alt="Повербанк"/>'
    "<span>Цена 1\u2009543 ₽ вместо </span>"
    "<span>Рейтинг товара: 4.4 из 5</span><span>Оценок: (48)\u2005·\u2005255 купили</span></a></div>"
    "<div data-zone-name=\"productSnippet\">"
    '<a href="/card/hoco-j72/5887088804?x=1"><span data-auto="snippet-title">Hoco J72</span>'
    "<span>Цена 791 ₽</span><span>Рейтинг товара: 4.7 из 5</span>"
    "<span>Оценок: (173)\u2005·\u20051,2 тыс. купили</span></a></div>"
)

AMZ_PAGE = (
    '<div data-asin="B0HKFWXQFX" data-component-type="s-search-result">'
    '<img class="s-image" src="https://m.media-amazon.com/images/I/a.jpg"/>'
    '<h2 aria-label="Power Bank 20000mAh"><span>Power Bank 20000mAh</span></h2>'
    '<span>4.6 out of 5 stars</span><a aria-label="1,994 ratings"></a>'
    "<span>3K+ bought in past month</span></div>"
    '<div data-asin="B0H2YVZY2S" data-component-type="s-search-result">'
    '<h2 aria-label="Mini Charger"><span>Mini Charger</span></h2></div>'
)


def test_parse_yandex_market():
    hits = parse_yandex_market(YM_PAGE)
    assert len(hits) == 2
    a, b = hits
    assert a.item_id == "4814369712" and a.title == "Повербанк 5000 mAh"
    assert a.price == 1543 and a.rating == 4.4 and a.reviews == 48 and a.bought == 255
    assert a.sponsored and a.image.startswith("https://avatars")
    assert b.bought == 1200 and b.price == 791 and not b.sponsored


def test_parse_amazon():
    hits = parse_amazon_search(AMZ_PAGE)
    assert [h.item_id for h in hits] == ["B0HKFWXQFX", "B0H2YVZY2S"]
    assert hits[0].bought == 3000 and hits[0].reviews == 1994 and hits[0].rating == 4.6
    assert hits[1].bought is None


def test_percentile_ranks():
    ranks = percentile_ranks({"a": 1, "b": 5, "c": 10})
    assert ranks == {"a": 0.0, "b": 50.0, "c": 100.0}
    assert percentile_ranks({"x": 3}) == {"x": 50.0}


def test_max_purchase_keeps_target_margin():
    s = Settings(_env_file=None)
    cost = max_purchase_cny(3000, 0.3, s)
    variable = max(s.commission_wb_pct, s.commission_ozon_pct, s.commission_ym_pct) + s.ads_pct + s.defect_pct
    profit = 3000 * (1 - variable / 100) - cost * s.cny_rub_rate - 0.3 * s.cargo_per_kg_rub
    assert abs(profit / 3000 * 100 - s.target_margin_pct) < 0.1
    assert max_purchase_cny(100, 1.0, s) == 0.0


def test_score_all_ranks_and_caps():
    s = Settings(_env_file=None)
    ym = parse_yandex_market(YM_PAGE)
    strong = NicheScan(name="strong", section="x", ru_query="q", en_query="q", weight_kg=0.3, ym=summarize(ym))
    strong.max_cost_cny = max_purchase_cny(strong.ym.price_median, 0.3, s)
    no_ru = NicheScan(name="no_ru", section="x", ru_query="q", en_query="q", weight_kg=0.3,
                      amazon=summarize(parse_amazon_search(AMZ_PAGE)))
    score_all([strong, no_ru], s)
    assert "demand_ru" in strong.components and strong.total > 0
    assert no_ru.total <= 39 and no_ru.verdict == Verdict.SKIP
