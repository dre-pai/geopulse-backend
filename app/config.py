from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GeoPulse API"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "postgresql+psycopg2://geopulse:geopulse@localhost:5432/geopulse"

    celery_broker_url: str = "amqp://geopulse:geopulse@localhost:5672//"
    celery_result_backend: str = (
        "db+postgresql+psycopg2://geopulse:geopulse@localhost:5432/geopulse"
    )

    gdelt_last_update_url: str = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
    gdelt_fetch_interval_minutes: int = 15

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    ai_summary_enabled: bool = False

    world_bank_base_url: str = "https://api.worldbank.org/v2"
    # REST Countries v3 is deprecated/key-gated; use public mledoze dataset instead
    countries_dataset_url: str = (
        "https://raw.githubusercontent.com/mledoze/countries/master/countries.json"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
