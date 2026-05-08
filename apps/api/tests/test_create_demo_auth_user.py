"""
Tests for scripts/create_demo_auth_user.py

No real Supabase calls are made.  We test:
- .env loading and parsing
- URL validation
- "already exists" error detection
- success output formatting
- password length guard
- missing environment variable detection
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Import helpers from the script under test ─────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.create_demo_auth_user import (
    _find_existing_user,
    _is_already_exists_error,
    _load_env_file,
    _validate_supabase_url,
)


# ── .env file loading ─────────────────────────────────────────────────────────


class TestLoadEnvFile:
    def test_loads_simple_key_value(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("FOO_TEST_VAR=hello\n")
        os.environ.pop("FOO_TEST_VAR", None)
        _load_env_file(env)
        assert os.environ.get("FOO_TEST_VAR") == "hello"
        del os.environ["FOO_TEST_VAR"]

    def test_loads_double_quoted_value(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text('BAR_TEST_VAR="quoted value"\n')
        os.environ.pop("BAR_TEST_VAR", None)
        _load_env_file(env)
        assert os.environ.get("BAR_TEST_VAR") == "quoted value"
        del os.environ["BAR_TEST_VAR"]

    def test_loads_single_quoted_value(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("BAZ_TEST_VAR='single'\n")
        os.environ.pop("BAZ_TEST_VAR", None)
        _load_env_file(env)
        assert os.environ.get("BAZ_TEST_VAR") == "single"
        del os.environ["BAZ_TEST_VAR"]

    def test_ignores_comments(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text(
            textwrap.dedent("""\
                # This is a comment
                COMMENT_TEST=yes
                # another comment
            """)
        )
        os.environ.pop("COMMENT_TEST", None)
        _load_env_file(env)
        assert os.environ.get("COMMENT_TEST") == "yes"
        del os.environ["COMMENT_TEST"]

    def test_ignores_blank_lines(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("\n\nBLANK_TEST=ok\n\n")
        os.environ.pop("BLANK_TEST", None)
        _load_env_file(env)
        assert os.environ.get("BLANK_TEST") == "ok"
        del os.environ["BLANK_TEST"]

    def test_does_not_override_existing_env_var(self, tmp_path: Path) -> None:
        """Environment wins over .env file (setdefault semantics)."""
        env = tmp_path / ".env"
        env.write_text("OVERRIDE_TEST=from_file\n")
        os.environ["OVERRIDE_TEST"] = "from_env"
        _load_env_file(env)
        assert os.environ["OVERRIDE_TEST"] == "from_env"
        del os.environ["OVERRIDE_TEST"]

    def test_exits_when_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.env"
        with pytest.raises(SystemExit) as exc_info:
            _load_env_file(missing)
        assert exc_info.value.code == 1


# ── URL validation ────────────────────────────────────────────────────────────


class TestValidateSupabaseUrl:
    def test_valid_url_passes(self) -> None:
        _validate_supabase_url("https://abc123.supabase.co")  # must not raise

    def test_http_url_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _validate_supabase_url("http://abc123.supabase.co")
        assert exc_info.value.code == 1

    def test_postgres_host_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _validate_supabase_url("https://db.abc123.supabase.co")
        assert exc_info.value.code == 1

    def test_non_supabase_host_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _validate_supabase_url("https://example.com")
        assert exc_info.value.code == 1

    def test_bare_host_without_scheme_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _validate_supabase_url("abc123.supabase.co")
        assert exc_info.value.code == 1


# ── Error detection helpers ───────────────────────────────────────────────────


class TestIsAlreadyExistsError:
    def test_detects_user_already_registered(self) -> None:
        assert _is_already_exists_error("User already registered") is True

    def test_detects_already_been_registered(self) -> None:
        assert _is_already_exists_error("This email has already been registered") is True

    def test_detects_already_exists(self) -> None:
        assert _is_already_exists_error("User already exists in database") is True

    def test_detects_email_address_is_already(self) -> None:
        assert _is_already_exists_error("email address is already in use") is True

    def test_detects_duplicate_key(self) -> None:
        assert _is_already_exists_error("duplicate key value") is True

    def test_detects_unique_constraint(self) -> None:
        assert _is_already_exists_error("unique constraint violated") is True

    def test_case_insensitive(self) -> None:
        assert _is_already_exists_error("USER ALREADY REGISTERED") is True

    def test_returns_false_for_unrelated_error(self) -> None:
        assert _is_already_exists_error("Invalid service role key") is False
        assert _is_already_exists_error("Network timeout") is False
        assert _is_already_exists_error("") is False


# ── find_existing_user ────────────────────────────────────────────────────────


class TestFindExistingUser:
    def _make_admin(self, users_pages: list[list]) -> MagicMock:
        """Build a mock admin client that returns pages of users."""
        admin = MagicMock()
        admin.list_users.side_effect = users_pages
        return admin

    def _mock_user(self, email: str, user_id: str = "uuid-1") -> MagicMock:
        u = MagicMock()
        u.email = email
        u.id = user_id
        return u

    def test_finds_user_on_first_page(self) -> None:
        target = self._mock_user("target@example.com", "found-uuid")
        other = self._mock_user("other@example.com", "other-uuid")
        admin = self._make_admin([[target, other]])
        result = _find_existing_user(admin, "target@example.com")
        assert result is target
        assert result.id == "found-uuid"

    def test_finds_user_on_second_page(self) -> None:
        # First page full (50 items), second page has the target
        first_page = [self._mock_user(f"u{i}@x.com") for i in range(50)]
        target = self._mock_user("target@example.com", "page2-uuid")
        admin = self._make_admin([first_page, [target]])
        result = _find_existing_user(admin, "target@example.com")
        assert result is target

    def test_returns_none_when_user_not_found(self) -> None:
        other = self._mock_user("other@example.com")
        admin = self._make_admin([[other]])
        result = _find_existing_user(admin, "missing@example.com")
        assert result is None

    def test_returns_none_when_list_is_empty(self) -> None:
        admin = self._make_admin([[]])
        result = _find_existing_user(admin, "any@example.com")
        assert result is None

    def test_email_comparison_is_case_insensitive(self) -> None:
        target = self._mock_user("Target@Example.COM", "ci-uuid")
        admin = self._make_admin([[target]])
        result = _find_existing_user(admin, "target@example.com")
        assert result is target


# ── main() integration (no real network) ─────────────────────────────────────


class TestMainIntegration:
    def test_main_exits_1_on_short_password(self, tmp_path: Path, capsys) -> None:
        env = tmp_path / ".env"
        env.write_text(
            "SUPABASE_URL=https://test.supabase.co\n"
            "SUPABASE_SERVICE_ROLE_KEY=fake-key\n"
        )
        from scripts import create_demo_auth_user as script
        with (
            patch.object(script, "_find_env_file", return_value=env),
            patch("getpass.getpass", side_effect=["short", "short"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            script.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "8 characters" in captured.err

    def test_main_exits_1_on_password_mismatch(self, tmp_path: Path, capsys) -> None:
        env = tmp_path / ".env"
        env.write_text(
            "SUPABASE_URL=https://test.supabase.co\n"
            "SUPABASE_SERVICE_ROLE_KEY=fake-key\n"
        )
        from scripts import create_demo_auth_user as script
        with (
            patch.object(script, "_find_env_file", return_value=env),
            patch("getpass.getpass", side_effect=["password123", "different123"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            script.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "do not match" in captured.err

    def test_get_required_env_exits_when_missing(self, capsys) -> None:
        """_get_required_env exits with code 1 for an unset variable."""
        from scripts.create_demo_auth_user import _get_required_env
        key = "__VB_NONEXISTENT_TEST_KEY_XYZ__"
        os.environ.pop(key, None)  # ensure not set
        with pytest.raises(SystemExit) as exc_info:
            _get_required_env(key)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert key in captured.err

    def test_get_required_env_returns_value_when_set(self) -> None:
        """_get_required_env returns the value without printing it."""
        from scripts.create_demo_auth_user import _get_required_env
        key = "__VB_TEST_KEY_SET__"
        os.environ[key] = "expected_value"
        try:
            result = _get_required_env(key)
            assert result == "expected_value"
        finally:
            del os.environ[key]

    def test_main_does_not_print_service_key(
        self, tmp_path: Path, capsys
    ) -> None:
        """The service-role key must never appear in stdout or stderr."""
        env = tmp_path / ".env"
        secret_key = "super-secret-service-role-key-CANARY"
        env.write_text(
            f"SUPABASE_URL=https://test.supabase.co\n"
            f"SUPABASE_SERVICE_ROLE_KEY={secret_key}\n"
        )
        from scripts import create_demo_auth_user as script
        mock_user = MagicMock()
        mock_user.id = "test-uuid-123"
        mock_user.email = "mohammedmubashir@wpi.edu"
        mock_response = MagicMock()
        mock_response.user = mock_user
        mock_client = MagicMock()
        mock_client.auth.admin.create_user.return_value = mock_response
        with (
            patch.object(script, "_find_env_file", return_value=env),
            patch("getpass.getpass", side_effect=["password123", "password123"]),
            patch("supabase.create_client", return_value=mock_client),
        ):
            script.main()
        captured = capsys.readouterr()
        assert secret_key not in captured.out
        assert secret_key not in captured.err

    def test_main_handles_already_exists_gracefully(
        self, tmp_path: Path, capsys
    ) -> None:
        env = tmp_path / ".env"
        env.write_text(
            "SUPABASE_URL=https://test.supabase.co\n"
            "SUPABASE_SERVICE_ROLE_KEY=fake-key\n"
        )
        from scripts import create_demo_auth_user as script
        existing_user = MagicMock()
        existing_user.id = "existing-uuid-abc"
        existing_user.email = "mohammedmubashir@wpi.edu"
        mock_client = MagicMock()
        # create_user raises "already registered" error
        mock_client.auth.admin.create_user.side_effect = Exception(
            "User already registered"
        )
        # list_users returns the existing user
        mock_client.auth.admin.list_users.return_value = [existing_user]
        with (
            patch.object(script, "_find_env_file", return_value=env),
            patch("getpass.getpass", side_effect=["password123", "password123"]),
            patch("supabase.create_client", return_value=mock_client),
        ):
            script.main()
        captured = capsys.readouterr()
        assert "existing-uuid-abc" in captured.out
        assert "already exists" in captured.out.lower() or "found existing" in captured.out.lower()
