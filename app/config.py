"""Application configuration from environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-only-change-me"
    database_url: str = "sqlite:///./data/app.db"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"

    # Email: mock (log file) or mailjet (real send via Mailjet API)
    email_mode: str = "mock"
    mailjet_api_key: str = ""
    mailjet_api_secret: str = ""
    mailjet_from_email: str = "alizubair6475@gmail.com"
    mailjet_from_name: str = "Matt Photography"

    # Company letterhead (PDF + email)
    company_name: str = "Matt Photography"
    company_tagline: str = "Professional photography & visual storytelling"
    company_address: str = ""
    company_phone: str = ""
    company_email: str = "alizubair6475@gmail.com"
    company_website: str = ""

    # Customer portal — jobs book to this photographer (email match, else first photographer)
    photographer_email: str = ""
    default_shoot_amount_cents: int = 250000
    default_tax_rate: float = 0.08
    default_payment_due_days: int = 14
    app_base_url: str = "http://127.0.0.1:8000"


settings = Settings()
