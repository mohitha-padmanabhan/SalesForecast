from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Fabric ODBC Connection Configuration
    DB_DRIVER: str = "ODBC Driver 18 for SQL Server"

    TENANT_ID: str = ""
    CLIENT_ID: str = ""
    CLIENT_SECRET: str = ""

    FABRIC_SERVER: str = ""
    FABRIC_DATABASE: str = ""
    FABRIC_SCHEMA: str = ""

    # Updated Schema Tables
    TABLE_FCST_24MO: str = "sf.fcstState24mo"
    TABLE_FCST_24MO_LOCKED: str = "sf.fcstState24mo_locked"
    TABLE_DEPLETION: str = "sf.depletion"
    TABLE_CHANGELOG: str = "fcstChangelog"
    TABLE_BUDGET: str = "budget"
    TABLE_ITEM_MASTER: str = "item_master"
    TABLE_CHAIN_MASTER: str = "chain_master"

    # Microsoft Single Sign-On (SSO) Credentials
    AZURE_MS_AUTH_CLIENT_ID: str = ""
    AZURE_MS_AUTH_CLIENT_SECRET: str = ""
    AZURE_MS_AUTH_TENANT_ID: str = ""
    AZURE_MS_AUTH_REDIRECT_URI: str = "http://localhost:8000/auth/callback"
    FRONTEND_URL: str = "http://localhost:5173"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()