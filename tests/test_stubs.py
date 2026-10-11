from analitik_importa.stubs import stub_amazon_search, stub_ebay_search, stub_mpstats_category


def test_stub_ebay():
    m = stub_ebay_search("earbuds", limit=10)
    assert m.item_count == 10
    assert m.price_median is not None
    assert any("STUB" in n for n in m.notes)


def test_stub_mpstats():
    m = stub_mpstats_category("wb", "Cat/Sub", d1="2026-08-01", d2="2026-09-01")
    assert m.sales and m.sales > 0
    assert m.sellers == 4


def test_stub_amazon():
    m = stub_amazon_search("power bank", item_count=5)
    assert m.item_count == 5
    assert m.avg_rating is not None
