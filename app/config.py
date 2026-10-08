"""Application settings, read from environment variables (and an optional .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    """Typed settings. Names map to upper case environment variables (DATABASE_URL, ...)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    max_upload_mb: int = 25
    max_uncompressed_mb: int = 200
    max_zip_entries: int = 50
    max_features: int = 100_000
    log_level: str = "INFO"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * MB

    @property
    def max_uncompressed_bytes(self) -> int:
        return self.max_uncompressed_mb * MB


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object (clear the cache in tests that change env vars)."""
    return Settings()
