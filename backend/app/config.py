"""Central configuration. Every secret and tunable lives here, loaded from
environment variables (or a local .env file) — never hardcoded."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API keys
    serpapi_api_key: str = ""
    google_maps_api_key: str = ""
    groq_api_key: str = ""

    # LLM
    groq_model: str = "llama-3.3-70b-versatile"

    # Money — passed straight to SerpApi and used for every displayed price
    currency: str = "INR"

    # Cache
    cache_path: str = "where_to_cache.sqlite3"
    cache_ttl_flights: int = 3600
    cache_ttl_hotels: int = 3600
    cache_ttl_places: int = 86400
    cache_ttl_routes: int = 86400

    # Fixture-backed clients + scripted LLM; a full demo run costs zero API calls
    fake_apis: bool = False

    cors_origins: str = "http://localhost:3000"

    def ttl_for(self, service: str) -> int:
        return {
            "flights": self.cache_ttl_flights,
            "hotels": self.cache_ttl_hotels,
            "places": self.cache_ttl_places,
            "routes": self.cache_ttl_routes,
        }.get(service, 3600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
