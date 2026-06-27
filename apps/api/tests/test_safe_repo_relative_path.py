"""Tests for the shared repo-relative path gate (must-fix).

Code-evidence rows carry a ``file_path`` that becomes a public GitHub
``…/blob/<branch>/<path>`` link, an "exact location" citation chip, and an
evidence trace on anonymous recruiter surfaces. The old code did
``str(raw).strip().lstrip("/")`` which silently *converted* an absolute path
like ``/Users/alice/private/secret.py`` into the apparently-relative
``Users/alice/private/secret.py`` (and left ``C:\\Users\\…`` untouched) — so a
developer's private filesystem location leaked into public output and passed
the Step 7 gate.

``safe_repo_relative_path`` rejects those values outright (returns ``None``)
instead of normalizing them, while still preserving genuine repo-relative
paths. These tests pin the hostile cases the Codex review required.
"""

from __future__ import annotations

import pytest

from app.services.safe_public_url import safe_repo_relative_path

# Absolute / local / Windows / UNC / file:// / traversal paths that MUST be
# rejected (return None) — never converted into a fake repo-relative path.
HOSTILE_PATHS = [
    "/Users/alice/private/secret.py",
    "/home/alice/.ssh/id_rsa",
    "/private/var/secret.py",
    "/var/log/auth.log",
    "/tmp/leak.py",
    "/etc/passwd",
    "/root/.bashrc",
    "C:\\Users\\alice\\private\\secret.py",
    "C:/Users/alice/private/secret.py",
    "D:\\work\\secret.py",
    "\\\\server\\share\\file.py",
    "//server/share/file.py",
    "file:///Users/alice/private/secret.py",
    "file://localhost/etc/passwd",
    "https://evil.example.com/secret.py",
    "s3://bucket/secret.py",
    "../secrets.py",
    "..\\secrets.py",
    "app/../../../etc/passwd",
    "https://store.example.com/object/sign/x?token=abc123",
    "config.py?access_token=sk-secret",
    # Home-relative paths (~/… / ~user/…) leak a developer's home directory.
    "~/secret.py",
    "~alice/secret.py",
    # Single-slash file: URL (file:/…) — not caught by a naive "://" check.
    "file:/Users/alice/private/secret.py",
    # URL-encoded traversal that only reveals "../" after decoding.
    "%2e%2e/secrets.py",
    "%2E%2E/secrets.py",
    "..%2fsecrets.py",
    "..%5csecrets.py",
    "%2e%2e%2fsecrets.py",
    "%2e%2e%5csecrets.py",
    # Double-encoded traversal (%252e → %2e → "."): two decode passes catch it.
    "%252e%252e/secrets.py",
    "%252e%252e%252fsecrets.py",
    # URL-encoded absolute / home / scheme paths.
    "%2fetc%2fpasswd",
    "%7e/secret.py",
    "",
    "   ",
]

# Genuine repo-relative paths that MUST survive (optionally normalized).
SAFE_PATHS = [
    ("apps/api/main.py", "apps/api/main.py"),
    ("src/components/Button.tsx", "src/components/Button.tsx"),
    ("README.md", "README.md"),
    ("package.json", "package.json"),
    ("app/services/foo.py", "app/services/foo.py"),
    ("src/model/train.py", "src/model/train.py"),
    # Safe backslashes in an otherwise-relative path are normalized to slashes.
    ("src\\components\\Button.tsx", "src/components/Button.tsx"),
]


@pytest.mark.parametrize("value", HOSTILE_PATHS)
def test_hostile_paths_are_rejected(value: str) -> None:
    assert safe_repo_relative_path(value) is None


@pytest.mark.parametrize("value,expected", SAFE_PATHS)
def test_safe_repo_relative_paths_survive(value: str, expected: str) -> None:
    assert safe_repo_relative_path(value) == expected


@pytest.mark.parametrize("value", [None, 123, 12.5, [], {}, object()])
def test_non_string_values_are_rejected(value: object) -> None:
    assert safe_repo_relative_path(value) is None


def test_windows_absolute_is_rejected_not_normalized() -> None:
    # The critical regression: a Windows absolute path must be REJECTED, not
    # normalized into ``C:/Users/alice/secret.py``.
    assert safe_repo_relative_path("C:\\Users\\alice\\secret.py") is None
    assert safe_repo_relative_path("C:/Users/alice/secret.py") is None


def test_posix_absolute_is_rejected_not_lstripped() -> None:
    # The critical regression: a POSIX absolute path must be REJECTED, not
    # lstrip("/")-ed into ``Users/alice/secret.py`` / ``etc/passwd``.
    for value in ("/Users/alice/secret.py", "/etc/passwd"):
        result = safe_repo_relative_path(value)
        assert result is None
        # And it must not have been silently converted to a relative form.
        assert result != value.lstrip("/")


def test_home_relative_paths_are_rejected() -> None:
    # ~/… and ~user/… leak a developer's home directory.
    assert safe_repo_relative_path("~/secret.py") is None
    assert safe_repo_relative_path("~alice/secret.py") is None


def test_single_slash_file_scheme_is_rejected() -> None:
    # file:/… (single slash) is NOT caught by a naive "://" check.
    assert safe_repo_relative_path("file:/Users/alice/private/secret.py") is None


def test_encoded_traversal_is_rejected() -> None:
    # Traversal that only appears after URL-decoding must still be rejected.
    for value in (
        "%2e%2e/secrets.py",
        "%2E%2E/secrets.py",
        "..%2fsecrets.py",
        "%2e%2e%2fsecrets.py",
    ):
        assert safe_repo_relative_path(value) is None


def test_double_encoded_traversal_is_rejected() -> None:
    # %252e → %2e → "." needs a second decode pass to reveal the traversal.
    assert safe_repo_relative_path("%252e%252e/secrets.py") is None


def test_safe_relative_path_survives() -> None:
    # Required positive case: a genuine repo-relative path is preserved verbatim.
    assert safe_repo_relative_path("apps/api/main.py") == "apps/api/main.py"
