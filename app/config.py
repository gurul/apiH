"""Settings from env / .env. h_mode drives live-vs-mock H everywhere."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hai_api_key: str = ""
    hai_agent: str = "h/web-surfer-pro"
    api_h_mock_h: bool = True
    api_h_database_url: str = "sqlite:///./data/api_h.db"
    api_h_host: str = "127.0.0.1"
    api_h_port: int = 8000
    log_level: str = "INFO"

    @property
    def h_mode(self) -> str:
        """"live" only when a key is present and mock is explicitly off."""
        return "live" if (self.hai_api_key and not self.api_h_mock_h) else "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
