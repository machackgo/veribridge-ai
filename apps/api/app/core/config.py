from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
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
    # It is NOT the Postgres DATABASE_URL — they are different things.
    supabase_url: str = Field(default="", alias="SUPABASE_URL")

    supabase_anon_key: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_ANON_KEY"
    )

    # Server-side only — bypasses RLS.  Never expose to a browser.
    supabase_service_role_key: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_SERVICE_ROLE_KEY"
    )

    # ── Auth ──────────────────────────────────────────────────────
    # SUPABASE_JWT_SECRET signs all Supabase Auth JWTs with HS256.
    # Find it at: Supabase dashboard → Settings → API → JWT Settings → JWT Secret.
    # Required for token verification in production.
    # When absent (dev only), falls back to DEMO_USER_ID.
    supabase_jwt_secret: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_JWT_SECRET"
    )

    # ── Demo / development overrides ─────────────────────────────
    # Fallback user ID used when no Authorization header is present
    # and ENVIRONMENT != "production".  Set to the real auth user UUID
    # created by scripts/create_demo_auth_user.py.
    demo_user_id: str = Field(
        default="00000000-0000-0000-0000-000000000001",
        alias="DEMO_USER_ID",
    )

    # ── Database (direct Postgres connection) ────────────────────
    # Used by async SQLAlchemy — NOT the same as SUPABASE_URL.
    database_url: SecretStr = Field(
        default=SecretStr(""), alias="DATABASE_URL"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Validators ────────────────────────────────────────────────

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url_format(cls, v: str) -> str:
        """
        Reject obviously wrong SUPABASE_URL values at startup.

        Common mistakes caught here:
          - Using the Postgres host  (db.xxx.supabase.co)
          - Using http:// instead of https://
          - Leaving the placeholder value from .env.example
          - Trailing whitespace from copy-paste
        """
        v = v.strip()
        if not v:
            return v  # empty is OK — supabase_configured checks presence

        parsed = urlparse(v)

        if parsed.scheme != "https":
            raise ValueError(
                f"SUPABASE_URL must start with 'https://'. "
                f"Found scheme: {parsed.scheme!r}. "
                "The REST API URL looks like: https://yourref.supabase.co\n"
                "Note: DATABASE_URL (the Postgres connection string) is different — "
                "do not use it here."
            )

        host = parsed.netloc.lower()
        if not host:
            raise ValueError("SUPABASE_URL has no hostname after 'https://'.")

        if not host.endswith(".supabase.co"):
            raise ValueError(
                f"SUPABASE_URL host must end with '.supabase.co'. "
                f"Got: {host!r}. "
                "Do not use the direct Postgres host (db.xxx.supabase.co); "
                "use the project REST URL (xxx.supabase.co)."
            )

        if host.startswith("db."):
            raise ValueError(
                "SUPABASE_URL appears to be the Postgres host (starts with 'db.'). "
                "Use the project REST URL instead: "
                f"https://{host[3:]} "
                "(remove the 'db.' prefix and use https://)."
            )

        return v.rstrip("/")  # normalise: strip trailing slash

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
        """True when both URL and service-role key are present."""
        return bool(
            self.supabase_url
            and self.supabase_service_role_key.get_secret_value()
        )

    @property
    def supabase_url_host(self) -> str:
        """Return only the hostname — safe to log."""
        return urlparse(self.supabase_url).netloc if self.supabase_url else ""

    @property
    def auth_configured(self) -> bool:
        """True when JWT verification is possible (secret is present)."""
        return bool(self.supabase_jwt_secret.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
