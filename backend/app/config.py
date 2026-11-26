from pydantic_settings import BaseSettings
from pydantic import field_validator

class Settings(BaseSettings):
    # Fabric ODBC Connection Configuration
    DB_DRIVER: str

    TENANT_ID: str
    CLIENT_ID: str
    CLIENT_SECRET: str

    FABRIC_SERVER: str
    FABRIC_DATABASE: str
    FABRIC_SCHEMA: str = "Infinix"

    # Updated Schema Tables
    TABLE_FCST_24MO: str = "sf_fcstState24mo"
    TABLE_FCST_24MO_LOCKED: str = "sf_fcstState24mo_locked"
    TABLE_DEPLETION: str = "sf_depletion"

    @field_validator("TABLE_FCST_24MO", "TABLE_FCST_24MO_LOCKED", "TABLE_DEPLETION", mode="before")
    @classmethod
    def normalize_legacy_table_names(cls, value):
        # Existing environment files may still contain the retired table names.
        return {
            "sf.fcstState24mo": "sf_fcstState24mo",
            "sf.fcstState24mo_locked": "sf_fcstState24mo_locked",
            "sf.depletion": "sf_depletion",
        }.get(value, value)

    TABLE_CHANGELOG: str = "fcstChangelog"
    TABLE_BUDGET: str = "budget"
    TABLE_DEMAND_ID_MASTER: str = "demand id master"
    TABLE_ITEM_MASTER: str = "item_master"
    TABLE_CHAIN_MASTER: str = "chain_master"

    # Microsoft Single Sign-On (SSO) Credentials
    AZURE_MS_AUTH_CLIENT_ID: str
    AZURE_MS_AUTH_CLIENT_SECRET: str
    AZURE_MS_AUTH_TENANT_ID: str
    AZURE_MS_AUTH_REDIRECT_URI: str
    FRONTEND_URL: str

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
