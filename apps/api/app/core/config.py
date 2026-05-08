from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App identity ──────────────────────────────────────────────
    app_name: str = Field(default="careerproof-api", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # ── CORS ─────────────────────────────────────────────────────
    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        alias="CORS_ORIGINS",
    )

    # ── Supabase ─────────────────────────────────────────────────
    # SUPABASE_URL is the project REST/API base URL, e.g.
    # https://<project-ref>.supabase.co
    # It is not a secret but should still be env-driven.
    supabase_url: str = Field(default="", alias="SUPABASE_URL")

    # SUPABASE_ANON_KEY is safe for browser/public clients.
    # The backend should prefer the service-role key for server-side
    # operations so it can bypass RLS where needed (parsers, matchers).
    supabase_anon_key: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_ANON_KEY"
    )

    # SUPABASE_SERVICE_ROLE_KEY bypasses RLS — never expose to the
    # browser or include in client-side code.
    supabase_service_role_key: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_SERVICE_ROLE_KEY"
    )

    # ── Database (direct Postgres connection) ────────────────────
    # Used by async SQLAlchemy / psycopg for server-side queries.
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    # Supabase: use the "Transaction" pooler URL for serverless,
    # or the direct URL for long-lived server processes.
    database_url: SecretStr = Field(
        default=SecretStr(""), alias="DATABASE_URL"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Derived properties ────────────────────────────────────────
    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins_raw.split(",")
            if origin.strip()
        ]

    @property
    def supabase_configured(self) -> bool:
        """True when the minimum Supabase environment is present."""
        return bool(
            self.supabase_url
            and self.supabase_service_role_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
