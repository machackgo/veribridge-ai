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

from urllib.parse import urlsplit

__all__ = ["is_safe_public_url", "safe_public_url"]

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
