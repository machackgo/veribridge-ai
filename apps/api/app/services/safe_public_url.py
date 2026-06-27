"""Shared safe-public-URL gate for recruiter-facing direct links (must-fix).

Public reports / passports may surface *direct* outbound links (a public
GitHub repo, a deployed site, a Website Proof target). A link is only safe to
expose to an anonymous recruiter when its target is genuinely reachable on the
public internet. This module is the single source of truth for that decision
so every public surface agrees on what "public-safe" means.

Rejected (never linked publicly):

* non-http(s) schemes: ``file:``, ``data:``, ``blob:``, ``javascript:`` …
* loopback / unspecified hosts: ``localhost``, ``127.0.0.1``, ``0.0.0.0``, ``::1``
* RFC1918 / private IPs: ``10.0.0.0/8``, ``172.16.0.0/12``, ``192.168.0.0/16``
* link-local / reserved IPs: ``169.254.0.0/16`` and friends
* private / internal hostname suffixes: ``.local``, ``.internal``, ``.localhost``
* bare intranet-style hostnames with no public suffix (no dot)
* storage / signed / upload URLs and obvious token / signature query params

The check is intentionally conservative: any parsing ambiguity returns
``False`` so a questionable URL is omitted rather than advertised.
"""

from __future__ import annotations

import ipaddress
import re

from urllib.parse import unquote, urlsplit

__all__ = ["is_safe_public_url", "safe_public_url", "safe_repo_relative_path"]

_ALLOWED_SCHEMES = {"http", "https"}

# Hosts that always resolve to the local machine / no real host.
_DISALLOWED_HOSTS = {
    "localhost",
    "0.0.0.0",  # noqa: S104 - matched as an unsafe target, not bound
    "127.0.0.1",
    "::1",
    "ip6-localhost",
    "ip6-loopback",
}

# Private / internal hostname suffixes that never resolve on the public DNS.
_DISALLOWED_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".intranet",
    ".lan",
    ".corp",
    ".home",
    ".test",
    ".example",
    ".invalid",
)

# Path fragments that indicate a private storage / signed-object URL.
_UNSAFE_PATH_FRAGMENTS = (
    "/storage/v1/object",
    "/object/sign",
)

# Query-parameter names that mark a signed / tokenized URL (AWS/GCS/Supabase…).
_UNSAFE_QUERY_KEYS = {
    "token",
    "access_token",
    "signature",
    "sig",
    "expires",
    "x-goog-signature",
}


def _parse_ip(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


def is_safe_public_url(url: object) -> bool:
    """Return ``True`` only when ``url`` is safe to link publicly.

    Anything that is not a plain ``http(s)`` URL pointing at a publicly
    resolvable host is rejected (see the module docstring for the full list).
    """
    if not isinstance(url, str):
        return False
    candidate = url.strip()
    if not candidate:
        return False

    try:
        parts = urlsplit(candidate)
    except ValueError:
        return False

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return False  # blocks file:, data:, blob:, javascript:, mailto:, …

    try:
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False

    if host in _DISALLOWED_HOSTS:
        return False
    if any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _DISALLOWED_HOST_SUFFIXES):
        return False

    ip = _parse_ip(host)
    if ip is not None:
        # IP literal: only public, globally-routable addresses are allowed.
        if not _is_public_ip(ip):
            return False
    else:
        # Hostname: require a public suffix (a dot + alphabetic TLD) so bare
        # intranet hostnames like ``server`` / ``intranet`` are rejected.
        if "." not in host:
            return False
        tld = host.rsplit(".", 1)[-1]
        if len(tld) < 2 or not tld.isalpha():
            return False

    path = (parts.path or "").lower()
    if any(fragment in path for fragment in _UNSAFE_PATH_FRAGMENTS):
        return False

    query = (parts.query or "").lower()
    if query:
        for pair in query.split("&"):
            key = pair.split("=", 1)[0].strip()
            if key in _UNSAFE_QUERY_KEYS or key.startswith("x-amz-"):
                return False

    return True


def safe_public_url(url: object) -> str | None:
    """Return the trimmed URL when it is public-safe, otherwise ``None``."""
    if is_safe_public_url(url):
        return url.strip()  # type: ignore[union-attr]
    return None


# ── Repo-relative path gate (must-fix) ────────────────────────────────────────
#
# Code-evidence rows carry a ``file_path`` that becomes a public GitHub
# ``…/blob/<branch>/<path>`` link, an "exact location" citation chip, and an
# evidence trace on anonymous recruiter surfaces. That value MUST be a genuine
# repo-relative path (``apps/api/main.py``). It must NEVER be an absolute /
# local / Windows / UNC / ``file://`` path, because those leak a developer's
# private filesystem into public output.
#
# The old code did ``str(raw).strip().lstrip("/")`` which silently *converted*
# ``/Users/alice/secret.py`` into the apparently-relative ``Users/alice/...``
# (and left ``C:\Users\...`` untouched) — hiding the leak instead of blocking
# it. This helper rejects those values outright rather than normalizing them.

# Tokens that flag an absolute POSIX path we must never expose.
_UNSAFE_POSIX_PREFIXES = (
    "/users/",
    "/home/",
    "/private/",
    "/var/",
    "/tmp/",
    "/etc/",
    "/root/",
    "/mnt/",
    "/opt/",
    "/usr/",
    "/srv/",
)

# Query/param-style keys that mark a signed or tokenized storage path.
_UNSAFE_PATH_TOKENS = (
    "://",  # any scheme (file://, https://, s3://, …)
    "token=",
    "signature=",
    "x-amz-",
    "x-goog-",
    "access_token",
)

# A leading URL/URI scheme (``file:``, ``file://``, ``https://``, ``s3:``,
# ``mailto:`` …) or a Windows drive letter (``C:``). Either is unsafe as a
# repo-relative path; genuine relative paths never start with ``<scheme>:``.
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def _is_unsafe_repo_form(text: str) -> bool:
    """Return ``True`` if ``text`` (a raw *or* URL-decoded candidate) is unsafe.

    Applied to the raw value and to one/two URL-decoded passes so traversal or
    an absolute/scheme path that only appears *after* percent-decoding
    (``%2e%2e/…``, ``..%2f…``, ``%252e%252e/…``) is still rejected.
    """
    if not text:
        return False  # emptiness is handled by the caller
    lowered = text.lower()
    norm = text.replace("\\", "/")
    lowered_norm = lowered.replace("\\", "/")

    # Home-relative path: ``~/secret.py`` / ``~alice/secret.py``.
    if text.startswith("~"):
        return True
    # Any URI scheme (file:, file://, https://, s3:, …) or Windows drive (C:).
    if _SCHEME_RE.match(text):
        return True
    # Signed-storage / token fragments.
    if any(token in lowered for token in _UNSAFE_PATH_TOKENS):
        return True
    # UNC path (\\server\share\file) or //server/share.
    if text.startswith("\\\\") or norm.startswith("//"):
        return True
    # POSIX absolute path (do NOT lstrip("/") into a fake relative path).
    if norm.startswith("/"):
        return True
    if any(lowered_norm.startswith(prefix) for prefix in _UNSAFE_POSIX_PREFIXES):
        return True
    # Traversal in any segment.
    if ".." in norm.split("/"):
        return True
    return False


def safe_repo_relative_path(value: object) -> str | None:
    """Return a safe repo-relative path, or ``None`` if ``value`` is unsafe.

    Accepts only genuine repo-relative paths (``apps/api/main.py``,
    ``src/components/Button.tsx``, ``README.md``). Backslash separators in an
    otherwise-safe relative path are normalized to forward slashes
    (``src\\components\\Button.tsx`` → ``src/components/Button.tsx``).

    Returns ``None`` — never a "cleaned up" path — for anything that could leak
    a private filesystem location into public output:

    * empty / ``None`` / non-string values
    * POSIX absolute paths (``/Users/…``, ``/home/…``, ``/etc/passwd``, ``/…``)
    * Windows absolute paths (``C:\\Users\\…``, ``C:/Users/…``)
    * UNC paths (``\\\\server\\share\\file``)
    * home-relative paths (``~/secret.py``, ``~alice/secret.py``)
    * ``file:`` / ``file://`` and any other scheme URL / signed storage path
    * traversal (``../`` or ``..\\``)
    * traversal/absolute/scheme paths hidden behind URL-encoding
      (``%2e%2e/…``, ``..%2f…``, ``%2e%2e%2f…``, double-encoded ``%252e%252e/…``)
    * values carrying obvious secret/token query fragments

    Both the raw value and one/two URL-decoded passes are inspected (a bounded
    number of passes — never an unbounded decode loop). Callers must drop the
    field (or substitute a neutral limitation) when this returns ``None`` — they
    must not fall back to ``lstrip("/")``.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None

    # Inspect the raw value and up to two URL-decode passes so traversal /
    # absolute / scheme paths that only surface after percent-decoding are still
    # rejected. Two passes catches double-encoding (``%252e`` → ``%2e`` → ``.``)
    # without an unbounded decode loop.
    candidate = raw
    for _ in range(2):
        if _is_unsafe_repo_form(candidate):
            return None
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    else:
        # Loop exhausted both passes without breaking — check the final form too.
        if _is_unsafe_repo_form(candidate):
            return None

    # Normalize backslashes to slashes and drop empty segments from the (now
    # known-safe) raw path; require something left.
    normalized = raw.replace("\\", "/")
    cleaned = "/".join(seg for seg in normalized.split("/") if seg)
    if not cleaned:
        return None

    return cleaned
