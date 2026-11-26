from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@db:5432/app"
    fake_platform_url: str = "http://fake-platform:9000"
    token_encryption_key: str = "changeme-placeholder"  # real AES-GCM key arrives in Stage 3
    webhook_secret: str = "changeme-placeholder"  # real HMAC secret arrives in Stage 5
    media_dir: str = "/srv/media"
    llm_provider: str = "none"  # "none" (templates only) or "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    llm_timeout_seconds: float = 10
    # Integer micro-USD per million tokens; 0 = free tier.
    price_micro_usd_per_million_input: int = 0
    price_micro_usd_per_million_output: int = 0


settings = Settings()
