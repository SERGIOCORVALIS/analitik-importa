from analitik_importa.models import Marketplace, NicheQuery, NicheReport, NicheScore, Verdict
from analitik_importa.report import niche_report_to_html, niche_report_to_xml, save_report
from analitik_importa.stubs import stub_amazon_search, stub_ebay_search, stub_mpstats_category


def _sample_report() -> NicheReport:
    return NicheReport(
        query=NicheQuery(
            keywords="powerbank",
            wb_category_path="Электроника/Powerbanks",
            ozon_category_path="Электроника/Powerbanks",
            cost_cny=25,
            sell_rub=2990,
        ),
        ebay=stub_ebay_search("powerbank", limit=10),
        mpstats_wb=stub_mpstats_category("wb", "Электроника/Powerbanks", d1="2026-08-01", d2="2026-09-01"),
        mpstats_ozon=stub_mpstats_category("ozon", "Электроника/Powerbanks", d1="2026-08-01", d2="2026-09-01"),
        amazon=stub_amazon_search("powerbank", item_count=5),
        score=NicheScore(
            total=80,
            mpstats_component=90,
            amazon_component=50,
            ebay_component=40,
            margin_component=100,
            verdict=Verdict.TAKE,
            rationale=["demo"],
        ),
    )


def test_html_report_has_russian_verdict():
    html = niche_report_to_html(_sample_report())
    assert "БРАТЬ" in html
    assert "Юнит-экономика" in html
    assert "metrics-grid" in html


def test_xml_is_xhtml():
    xml = niche_report_to_xml(_sample_report())
    assert xml.startswith("<?xml")
    assert "xmlns=\"http://www.w3.org/1999/xhtml\"" in xml
    assert "БРАТЬ" in xml


def test_save_report_writes_xml_html(tmp_path, monkeypatch):
    import analitik_importa.report as report_mod

    monkeypatch.setattr(report_mod, "reports_dir", lambda: tmp_path)
    paths = save_report(_sample_report())
    assert paths["html"].exists()
    assert paths["xml"].exists()
    assert paths["data_xml"].exists()
    assert "БРАТЬ" in paths["html"].read_text(encoding="utf-8")
