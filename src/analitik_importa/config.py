from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Temporary demo mode for eBay / MPSTATS / Amazon until live keys are ready.
    use_api_stubs: bool = False

    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_marketplace_id: str = "EBAY_US"

    mpstats_token: str = ""

    ozon_client_id: str = ""
    ozon_api_key: str = ""

    wb_api_token: str = ""

    amazon_credential_id: str = ""
    amazon_credential_secret: str = ""
    amazon_partner_tag: str = ""
    amazon_marketplace: str = "www.amazon.com"

    cny_rub_rate: float = Field(default=12.5, gt=0)
    cargo_per_kg_rub: float = Field(default=450.0, ge=0)
    default_weight_kg: float = Field(default=0.3, gt=0)
    commission_wb_pct: float = Field(default=15.0, ge=0)
    commission_ozon_pct: float = Field(default=15.0, ge=0)
    commission_ym_pct: float = Field(default=12.0, ge=0)
    commission_avito_pct: float = Field(default=5.0, ge=0)
    ads_pct: float = Field(default=8.0, ge=0)
    defect_pct: float = Field(default=3.0, ge=0)
    target_margin_pct: float = Field(default=25.0, ge=0)

    # Stock planning defaults (per product they can be overridden in the catalog).
    lead_time_days: int = Field(default=45, ge=1)
    safety_days: int = Field(default=14, ge=0)
    cover_days: int = Field(default=60, ge=1)
    sales_window_days: int = Field(default=30, ge=7, le=90)

    # Accounting: usn6 | usn15 | npd | osno | none
    tax_mode: str = "usn6"
    tax_rate_pct: float = Field(default=6.0, ge=0)

    def require_ebay(self) -> None:
        if not self.ebay_client_id.strip() or not self.ebay_client_secret.strip():
            raise RuntimeError(
                "eBay credentials missing. Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env "
                "(see https://developer.ebay.com)."
            )

    def require_mpstats(self) -> None:
        if not self.mpstats_token.strip():
            raise RuntimeError(
                "MPSTATS_TOKEN missing. Set it in .env after activating "
                "Внешняя аналитика at https://mpstats.io/userpanel"
            )

    def require_ozon_seller(self) -> None:
        missing = [
            name
            for name, value in (
                ("OZON_CLIENT_ID", self.ozon_client_id),
                ("OZON_API_KEY", self.ozon_api_key),
            )
            if not value.strip()
        ]
        if missing:
            raise RuntimeError(
                "Ozon Seller API credentials missing: "
                + ", ".join(missing)
                + ". See seller.ozon.ru -> Настройки -> Seller API."
            )

    def require_wb_seller(self) -> None:
        if not self.wb_api_token.strip():
            raise RuntimeError(
                "WB_API_TOKEN missing. Создайте токен: seller.wildberries.ru → Настройки → Доступ к API "
                "(категории: Контент, Статистика, Аналитика, Цены и скидки; режим «Только чтение»)."
            )

    def require_amazon(self) -> None:
        missing = [
            name
            for name, value in (
                ("AMAZON_CREDENTIAL_ID", self.amazon_credential_id),
                ("AMAZON_CREDENTIAL_SECRET", self.amazon_credential_secret),
                ("AMAZON_PARTNER_TAG", self.amazon_partner_tag),
            )
            if not value.strip()
        ]
        if missing:
            raise RuntimeError(
                "Amazon Creators API credentials missing: "
                + ", ".join(missing)
                + ". Register Associates + Creators API credentials first."
            )

    def commission_pct_for(self, marketplace: str) -> float:
        key = marketplace.strip().lower()
        mapping = {
            "wb": self.commission_wb_pct,
            "wildberries": self.commission_wb_pct,
            "ozon": self.commission_ozon_pct,
            "oz": self.commission_ozon_pct,
            "ym": self.commission_ym_pct,
            "yandex": self.commission_ym_pct,
            "yandex_market": self.commission_ym_pct,
            "avito": self.commission_avito_pct,
        }
        if key not in mapping:
            raise ValueError(f"Unknown marketplace for commission: {marketplace}")
        return mapping[key]


@lru_cache
def get_settings() -> Settings:
    return Settings()
