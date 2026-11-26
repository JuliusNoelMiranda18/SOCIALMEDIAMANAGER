from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@db:5432/app"
    fake_platform_url: str = "http://fake-platform:9000"
    # base64 of 32 bytes; validated when the api starts (app/main.py), not here,
    # because fake_platform imports these settings too.
    token_encryption_key: str = ""
    fake_client_id: str = ""
    fake_client_secret: str = ""
    public_base_url: str = "http://api:8000"
    publish_timeout_seconds: float = 5
    publish_max_attempts: int = 5
    backoff_base_ms: int = 500
    backoff_cap_ms: int = 30000
    max_retry_after_seconds: int = 60
    webhook_secret: str = "changeme-placeholder"  # `make env` writes a real one
    webhook_tolerance_seconds: int = 300  # replay window, both directions
    job_lease_seconds: float = 30
    job_max_attempts: int = 5
    worker_poll_seconds: float = 1
    dev_endpoints: bool = False  # registers /_dev/advance-time (test clock); never in prod
    media_dir: str = "/srv/media"
    llm_provider: str = "none"  # "none" (templates only) or "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    llm_timeout_seconds: float = 10
    # Integer micro-USD per million tokens; 0 = free tier.
    price_micro_usd_per_million_input: int = 0
    price_micro_usd_per_million_output: int = 0


settings = Settings()
