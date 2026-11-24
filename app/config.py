from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@db:5432/app"
    fake_platform_url: str = "http://fake-platform:9000"
    token_encryption_key: str = "changeme-placeholder"  # real AES-GCM key arrives in Stage 3
    webhook_secret: str = "changeme-placeholder"  # real HMAC secret arrives in Stage 5


settings = Settings()
