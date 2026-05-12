"""Safe public website inspection for deployed website proof verification."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

WEBSITE_PUBLIC_INSPECTOR_VERSION = "website-public-inspection-v1"
MAX_HTML_BYTES = 500_000
MAX_TEXT_CHARS = 20_000
MAX_HEADINGS = 20


@dataclass(frozen=True)
class WebsiteInspectionResult:
    inspection_used: bool
    final_url: str | None = None
    status_code: int | None = None
    page_title: str | None = None
    meta_description: str | None = None
    headings: list[str] = field(default_factory=list)
    visible_text: str | None = None
    matched_signals: list[str] = field(default_factory=list)
    missing_signals: list[str] = field(default_factory=list)
    public_markers: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def text(self) -> str:
        parts = [
            self.final_url,
            self.page_title,
            self.meta_description,
            " ".join(self.headings),
            self.visible_text,
            " ".join(self.public_markers),
        ]
        return " ".join(part for part in parts if part)


class WebsitePublicInspectionService:
    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self._timeout_seconds = timeout_seconds

    def inspect_url(self, url: str | None) -> WebsiteInspectionResult:
        normalized_url, error = _validate_public_url(url)
        if error:
            return WebsiteInspectionResult(
                inspection_used=False,
                error=error,
                missing_signals=[_error_signal(error)],
            )

        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                follow_redirects=True,
                max_redirects=5,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "veribridge-ai-website-proof-verifier",
                },
            ) as client:
                return self._fetch_and_parse(client, normalized_url)
        except httpx.TimeoutException:
            return WebsiteInspectionResult(
                inspection_used=False,
                error="website_timeout",
                missing_signals=["Website request timed out; falling back to stored proof metadata."],
            )
        except httpx.HTTPError:
            return WebsiteInspectionResult(
                inspection_used=False,
                error="website_network_error",
                missing_signals=["Website request failed; falling back to stored proof metadata."],
            )

    def _fetch_and_parse(self, client: httpx.Client, url: str) -> WebsiteInspectionResult:
        with client.stream("GET", url) as response:
            final_url = str(response.url)
            if response.status_code >= 400:
                return WebsiteInspectionResult(
                    inspection_used=False,
                    final_url=final_url,
                    status_code=response.status_code,
                    error="website_http_error",
                    missing_signals=[f"Website returned HTTP {response.status_code}; falling back to stored proof metadata."],
                )

            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type:
                return WebsiteInspectionResult(
                    inspection_used=False,
                    final_url=final_url,
                    status_code=response.status_code,
                    error="website_non_html_response",
                    missing_signals=["Website response was not HTML; falling back to stored proof metadata."],
                )

            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_HTML_BYTES:
                return WebsiteInspectionResult(
                    inspection_used=False,
                    final_url=final_url,
                    status_code=response.status_code,
                    error="website_response_too_large",
                    missing_signals=["Website HTML exceeded the MVP size limit; falling back to stored proof metadata."],
                )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_HTML_BYTES:
                    return WebsiteInspectionResult(
                        inspection_used=False,
                        final_url=final_url,
                        status_code=response.status_code,
                        error="website_response_too_large",
                        missing_signals=["Website HTML exceeded the MVP size limit; falling back to stored proof metadata."],
                    )
                chunks.append(chunk)

        html = b"".join(chunks).decode("utf-8", errors="replace")
        parsed = _extract_html_signals(html)
        matched = [f"Website loaded successfully with HTTP {response.status_code}."]
        if parsed.page_title:
            matched.append("Website page title was extracted.")
        else:
            parsed.missing_signals.append("Website page title is missing.")
        if parsed.meta_description:
            matched.append("Website meta description was extracted.")
        else:
            parsed.missing_signals.append("Website meta description is missing.")
        if parsed.headings:
            matched.append("Website headings were extracted.")
        else:
            parsed.missing_signals.append("Website headings are missing.")
        if parsed.visible_text:
            matched.append("Website visible text was extracted.")
        else:
            parsed.missing_signals.append("Website visible text is empty.")

        return WebsiteInspectionResult(
            inspection_used=bool(parsed.visible_text or parsed.page_title or parsed.meta_description or parsed.headings),
            final_url=final_url,
            status_code=response.status_code,
            page_title=parsed.page_title,
            meta_description=parsed.meta_description,
            headings=parsed.headings,
            visible_text=parsed.visible_text,
            matched_signals=matched,
            missing_signals=parsed.missing_signals,
            public_markers=parsed.public_markers,
            error=None if (parsed.visible_text or parsed.page_title or parsed.meta_description or parsed.headings) else "website_empty_content",
        )


@dataclass
class _ParsedHtml:
    page_title: str | None = None
    meta_description: str | None = None
    headings: list[str] = field(default_factory=list)
    visible_text: str | None = None
    public_markers: list[str] = field(default_factory=list)
    missing_signals: list[str] = field(default_factory=list)


class _SignalHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta_description: str | None = None
        self.headings: list[str] = []
        self.text_parts: list[str] = []
        self.public_markers: set[str] = set()
        self._tag_stack: list[str] = []
        self._current_heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag)
        attr_map = {name.lower(): value or "" for name, value in attrs}
        if tag == "meta" and attr_map.get("name", "").lower() == "description":
            self.meta_description = _squash(attr_map.get("content")) or self.meta_description
        if tag in {"h1", "h2", "h3"}:
            self._current_heading = ""
        if tag == "form":
            self.public_markers.add("form")
        if tag == "a" and attr_map.get("href"):
            self.public_markers.add("links")
        if tag in {"button", "input", "select", "textarea"}:
            self.public_markers.add("interactive_controls")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"} and self._current_heading is not None:
            heading = _squash(self._current_heading)
            if heading and len(self.headings) < MAX_HEADINGS:
                self.headings.append(heading)
            self._current_heading = None
        while self._tag_stack:
            current = self._tag_stack.pop()
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        if not data or self._is_ignored_context():
            return
        text = _squash(data)
        if not text:
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self.title_parts.append(text)
            return
        if self._current_heading is not None:
            self._current_heading = f"{self._current_heading} {text}".strip()
        self.text_parts.append(text)

    def _is_ignored_context(self) -> bool:
        return any(tag in {"script", "style", "noscript", "svg"} for tag in self._tag_stack)


def _extract_html_signals(html: str) -> _ParsedHtml:
    parser = _SignalHtmlParser()
    parser.feed(html)
    visible_text = _squash(" ".join(parser.text_parts))[:MAX_TEXT_CHARS] or None
    return _ParsedHtml(
        page_title=_squash(" ".join(parser.title_parts)) or None,
        meta_description=parser.meta_description,
        headings=parser.headings,
        visible_text=visible_text,
        public_markers=sorted(parser.public_markers),
    )


def _validate_public_url(url: str | None) -> tuple[str | None, str | None]:
    value = _clean(url)
    if not value:
        return None, "website_missing_url"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None, "website_unsupported_scheme"
    if not parsed.hostname:
        return None, "website_missing_host"
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return None, "website_private_host"
    if _host_is_private_ip(host):
        return None, "website_private_host"
    if _resolved_host_is_private(host):
        return None, "website_private_host"
    return value, None


def _host_is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return _is_private_address(ip)


def _resolved_host_is_private(host: str) -> bool:
    try:
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for entry in addr_info:
        address = entry[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if _is_private_address(ip):
            return True
    return False


def _is_private_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _error_signal(error: str) -> str:
    return {
        "website_missing_url": "Website URL is missing.",
        "website_unsupported_scheme": "Website URL must use http or https.",
        "website_missing_host": "Website URL host is missing.",
        "website_private_host": "Website URL points to localhost, a private host, or an internal IP address.",
    }.get(error, "Website URL could not be inspected.")


def _squash(value: str | None) -> str:
    return " ".join((value or "").split())


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
