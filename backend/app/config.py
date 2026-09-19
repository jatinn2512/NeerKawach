"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FloodOps API"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    open_meteo_enabled: bool = True
    open_meteo_base_url: str = "https://api.open-meteo.com"
    rainviewer_enabled: bool = True
    rainviewer_base_url: str = "https://api.rainviewer.com/public/weather-maps.json"
    rainfall_http_timeout_seconds: float = 20.0
    rainfall_http_retries: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Return the comma-separated CORS setting as normalized origins."""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
