"""pydantic-settings config. Rewrites the Supabase URL for asyncpg."""

from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    api_key: str = ""
    cors_origins: str = "http://localhost:5173"

    # Single-org build: the one organization this deployment serves. Seed creates the
    # org with this exact id, so it is stable and can be pinned here.
    org_id: UUID = UUID("11111111-1111-1111-1111-111111111111")

    # Foundry via Azure AI Projects SDK: Entra ID auth (az login / AZURE_* env), no
    # API key. Endpoint is the project endpoint; calls reference the hosted agent by
    # name + version (the agent config owns the model).
    foundry_project_endpoint: str = ""
    foundry_agent_name: str = "SyncUp-Agent"
    foundry_agent_version: str = "1"

    discord_bot_token: str = ""
    discord_test_guild_id: str = ""
    # Run the Discord bot in this process. Turn OFF for the --reload API dev loop so you
    # never get two gateway sessions on one token (the cause of 10062 Unknown interaction).
    enable_bot: bool = True

    @property
    def async_database_url(self) -> str:
        """postgresql:// -> postgresql+asyncpg://, and drop ?sslmode= (asyncpg rejects it)."""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url.split("?")[0]  # ponytail: strips every query param; only sslmode is expected

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()  # type: ignore[call-arg]
