"""pydantic-settings config. Rewrites the Supabase URL for asyncpg."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    api_key: str = ""
    cors_origins: str = "http://localhost:5173"

    foundry_base_url: str = ""
    foundry_api_key: str = ""
    foundry_model: str = ""

    discord_bot_token: str = ""
    discord_test_guild_id: str = ""

    @property
    def async_database_url(self) -> str:
        """postgresql:// -> postgresql+asyncpg://, and drop ?sslmode= (asyncpg rejects it)."""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url.split("?")[0]  # ponytail: strips every query param; only sslmode is expected

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()  # type: ignore[call-arg]
