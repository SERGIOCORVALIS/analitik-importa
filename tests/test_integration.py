import pytest

from analitik_importa.config import Settings


@pytest.mark.integration
def test_ebay_live_search():
    settings = Settings()
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        pytest.skip("EBAY credentials not configured")
    from analitik_importa.clients.ebay import EbayClient

    metrics = EbayClient(settings).search("usb cable", limit=5)
    assert metrics.item_count >= 1


@pytest.mark.integration
def test_mpstats_live_check():
    settings = Settings()
    if not settings.mpstats_token:
        pytest.skip("MPSTATS_TOKEN not configured")
    from analitik_importa.clients.mpstats import MpstatsClient

    result = MpstatsClient(settings).check()
    assert result.get("ok") is True


@pytest.mark.integration
def test_amazon_live_search():
    settings = Settings()
    if not (
        settings.amazon_credential_id
        and settings.amazon_credential_secret
        and settings.amazon_partner_tag
    ):
        pytest.skip("Amazon Creators credentials not configured")
    from analitik_importa.clients.amazon import AmazonClient

    metrics = AmazonClient(settings).search_items("usb cable", item_count=1)
    assert metrics.item_count >= 0  # empty catalog still means API accepted call
