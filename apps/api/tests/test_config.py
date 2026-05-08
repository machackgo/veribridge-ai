"""
Tests for app/core/config.py — verifies that Settings loads from
environment variables and that Supabase-related fields are present
and correctly typed.

No real credentials are read, printed, or asserted here.
"""
import os

import pytest
from pydantic import SecretStr

from app.core.config import Settings


def make_settings(**overrides: str) -> Settings:
    """Create a Settings instance with test values, bypassing .env file."""
    return Settings.model_validate(
        {
            "APP_NAME": "test-api",
            "APP_VERSION": "0.0.0-test",
            "API_V1_PREFIX": "/api/v1",
            "CORS_ORIGINS": "http://localhost:3000",
            "ENVIRONMENT": "test",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "anon-key-placeholder",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-placeholder",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/test",
            **overrides,
        }
    )


class TestSettingsLoad:
    def test_app_fields_load(self) -> None:
        s = make_settings()
        assert s.app_name == "test-api"
        assert s.app_version == "0.0.0-test"
        assert s.api_v1_prefix == "/api/v1"
        assert s.environment == "test"

    def test_cors_origins_parsed(self) -> None:
        s = make_settings(CORS_ORIGINS="http://localhost:3000,https://app.example.com")
        assert s.cors_origins == ["http://localhost:3000", "https://app.example.com"]

    def test_cors_origins_single(self) -> None:
        s = make_settings(CORS_ORIGINS="http://localhost:3000")
        assert s.cors_origins == ["http://localhost:3000"]


class TestSupabaseFields:
    def test_supabase_url_is_string(self) -> None:
        s = make_settings()
        assert isinstance(s.supabase_url, str)
        assert s.supabase_url.startswith("https://")

    def test_supabase_anon_key_is_secret(self) -> None:
        s = make_settings()
        # Field must be a SecretStr — value not exposed via str()
        assert isinstance(s.supabase_anon_key, SecretStr)
        assert "anon-key" not in str(s.supabase_anon_key)

    def test_supabase_service_role_key_is_secret(self) -> None:
        s = make_settings()
        assert isinstance(s.supabase_service_role_key, SecretStr)
        assert "service-role" not in str(s.supabase_service_role_key)

    def test_database_url_is_secret(self) -> None:
        s = make_settings()
        assert isinstance(s.database_url, SecretStr)
        # Raw connection string (with password) must not appear in repr
        assert "pass" not in str(s.database_url)

    def test_supabase_configured_true_when_set(self) -> None:
        s = make_settings()
        assert s.supabase_configured is True

    def test_supabase_configured_false_when_url_missing(self) -> None:
        s = make_settings(SUPABASE_URL="")
        assert s.supabase_configured is False

    def test_supabase_configured_false_when_key_missing(self) -> None:
        s = make_settings(SUPABASE_SERVICE_ROLE_KEY="")
        assert s.supabase_configured is False


class TestDefaultsForLocalDev:
    def test_supabase_unconfigured_when_empty_strings(self) -> None:
        """supabase_configured is False when URL and key are empty strings."""
        s = make_settings(SUPABASE_URL="", SUPABASE_SERVICE_ROLE_KEY="")
        assert s.supabase_url == ""
        assert s.supabase_configured is False

    def test_supabase_configured_false_when_only_url_set(self) -> None:
        """supabase_configured requires both URL and service-role key."""
        s = make_settings(SUPABASE_SERVICE_ROLE_KEY="")
        assert s.supabase_configured is False

    def test_settings_loads_without_error(self) -> None:
        """Settings can be constructed with all Supabase fields empty."""
        s = make_settings(
            SUPABASE_URL="",
            SUPABASE_ANON_KEY="",
            SUPABASE_SERVICE_ROLE_KEY="",
            DATABASE_URL="",
        )
        assert s.app_name == "test-api"
        assert s.supabase_configured is False
