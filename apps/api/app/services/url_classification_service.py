"""URL classification helpers for public-vs-local website proof logic."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse


UrlReachabilityClass = Literal["public", "local_private", "invalid"]


@dataclass(frozen=True)
class UrlClassification:
    raw_url: str
    classification: UrlReachabilityClass
    hostname: str
    reason: str

    @property
    def is_public_live_url(self) -> bool:
        return self.classification == "public"

    @property
    def is_local_or_private(self) -> bool:
        return self.classification in ("local_private", "invalid")


def classify_website_url(raw_url: str | None) -> UrlClassification:
    url = (raw_url or "").strip()
    if not url:
        return UrlClassification(url, "invalid", "", "URL is empty.")
    if not url.startswith(("http://", "https://")):
        return UrlClassification(url, "invalid", "", "URL must start with http:// or https://.")

    try:
        parsed = urlparse(url)
    except Exception:
        return UrlClassification(url, "invalid", "", "URL could not be parsed.")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return UrlClassification(url, "invalid", "", "URL has no hostname.")

    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return UrlClassification(url, "local_private", host, f"Local/private hostname detected ({host}).")
    if host.endswith(".local") or host.endswith(".internal"):
        return UrlClassification(url, "local_private", host, f"Internal/local hostname detected ({host}).")

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified:
            return UrlClassification(url, "local_private", host, f"Local/private IP address detected ({host}).")
    except ValueError:
        pass

    return UrlClassification(url, "public", host, "Public HTTP(S) hostname.")


def local_private_live_check_note() -> str:
    return (
        "Local/private website detected — public live website check is not applicable. "
        "Verification will rely on workflow recording, DOM/visual evidence, GitHub, "
        "transcript, and optional documents."
    )
