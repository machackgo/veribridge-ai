"""Website Evidence Discovery Service.

Scans a public website page and detects linked/embedded proof sources:
GitHub repos, video demos, PDFs, Google Docs/Drive, LinkedIn, deployed
apps, API docs, and images/screenshots.

Guardrails:
  - Only fetches public URLs (rejects localhost, private IP ranges).
  - String-based hostname check AND DNS pre-resolution: all resolved
    IP addresses are validated via ipaddress to cover private, loopback,
    link-local (169.254.x.x), multicast, and reserved ranges.
  - follow_redirects=False; each redirect Location is re-validated
    (including fresh DNS resolution) before following — prevents open
    redirectors from bouncing into internal networks.
  - Timeout + max bytes enforced to prevent resource exhaustion.
  - Does NOT store raw HTML.
  - Returns only public-safe metadata per discovered source.
  - Does NOT auto-submit discovered evidence; student chooses next action.
  - For JS-heavy sites with no static links, returns a clear limitation.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0
_MAX_HTML_BYTES = 500_000
_MAX_REDIRECTS = 5
_MAX_LINKS_PER_PAGE = 300  # cap to avoid huge pages
_DISCOVERY_VERSION = "website-evidence-discovery-v2"

# ── Evidence types ─────────────────────────────────────────────────────────────

EVIDENCE_TYPE_GITHUB      = "github_repository"
EVIDENCE_TYPE_VIDEO       = "video_demo"
EVIDENCE_TYPE_PDF         = "pdf_report"
EVIDENCE_TYPE_GOOGLE_DOC  = "google_doc"
EVIDENCE_TYPE_GOOGLE_DRIVE = "google_drive"
EVIDENCE_TYPE_LINKEDIN    = "linkedin"
EVIDENCE_TYPE_DEPLOYED_APP = "deployed_app"
EVIDENCE_TYPE_API_DOCS    = "api_docs"
EVIDENCE_TYPE_IMAGE       = "image_or_screenshot"
EVIDENCE_TYPE_UNKNOWN     = "unknown"

# ── SSRF-safe host guard ───────────────────────────────────────────────────────

def _ip_is_unsafe(addr_str: str) -> bool:
    """Return True if the IP address is in any non-public range.

    Covers: loopback, private (RFC 1918 + RFC 4193), link-local
    (169.254/16, fe80::/10), multicast, reserved, and unspecified.
    Using ipaddress avoids the fragile string-prefix approach.
    """
    try:
        addr = ipaddress.ip_address(addr_str)
    except ValueError:
        return True  # unparseable → reject
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local       # 169.254.x.x, fe80::/10
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified      # 0.0.0.0 / ::
    )


def _hostname_is_safe(hostname: str) -> tuple[bool, str | None]:
    """Check hostname via both string heuristics and DNS resolution.

    Returns (is_safe, error_code).  Rejects:
      - .local / .localhost TLDs (before DNS resolution)
      - any hostname that resolves to an unsafe IP (see _ip_is_unsafe)
      - hostnames that fail DNS resolution (unknown host = reject)

    Note: this performs a blocking DNS lookup on the calling thread.
    For a web API handler this is acceptable given the overall network
    I/O budget of the endpoint.
    """
    h = hostname.lower()

    # Fast-path: catch obvious local names before incurring a DNS round-trip.
    if h in {"localhost"} or h.endswith(".localhost") or h.endswith(".local"):
        return False, "private_host"

    # DNS pre-resolution: get all addresses and check each one.
    # This defeats hostnames like spoofed.evil.com → 127.0.0.1
    # AND catches 169.254.169.254 (cloud metadata) that string matching misses.
    try:
        results = socket.getaddrinfo(h, None)
    except socket.gaierror:
        # Could not resolve — refuse to proceed.
        return False, "dns_resolution_failed"

    for _family, _type, _proto, _canonname, sockaddr in results:
        addr_str = sockaddr[0]
        if _ip_is_unsafe(addr_str):
            logger.warning(
                "[EvidenceDiscovery] blocked private IP resolution: %s → %s",
                hostname, addr_str,
            )
            return False, "private_host"

    return True, None


def _validate_public_url(url: str | None) -> tuple[str | None, str | None]:
    """Return (normalized_url, error_string). error_string is None on success.

    Validates scheme, host presence, and calls _hostname_is_safe which
    performs both string heuristics and DNS pre-resolution.
    """
    if not url or not url.strip():
        return None, "missing_url"
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None, "unsupported_scheme"
    host = (parsed.hostname or "").lower()
    if not host:
        return None, "missing_host"

    safe, err = _hostname_is_safe(host)
    if not safe:
        return None, err

    return value, None


# ── Detected evidence dataclass ───────────────────────────────────────────────

@dataclass
class DiscoveredEvidenceItem:
    evidence_type: str
    url: str
    domain: str
    title: str | None
    confidence: float          # 0.0–1.0
    reason: str
    suggested_action: str
    raw_text: str | None = None  # anchor text / alt text — never raw HTML


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class WebsiteEvidenceDiscoveryResult:
    source_url: str
    final_url: str | None
    status_code: int | None
    page_title: str | None
    items: list[DiscoveredEvidenceItem] = field(default_factory=list)
    js_heavy_warning: bool = False
    limitation: str | None = None
    error: str | None = None
    version: str = _DISCOVERY_VERSION


# ── Detector functions ────────────────────────────────────────────────────────

_SUGGESTED_ACTIONS: dict[str, str] = {
    EVIDENCE_TYPE_GITHUB:      "Analyze GitHub Proof",
    EVIDENCE_TYPE_VIDEO:       "Analyze Demo Video",
    EVIDENCE_TYPE_PDF:         "Analyze PDF/Report",
    EVIDENCE_TYPE_GOOGLE_DOC:  "Review Google Doc",
    EVIDENCE_TYPE_GOOGLE_DRIVE: "Review Google Drive",
    EVIDENCE_TYPE_LINKEDIN:    "Add LinkedIn Proof",
    EVIDENCE_TYPE_DEPLOYED_APP: "Start Website Recording",
    EVIDENCE_TYPE_API_DOCS:    "Review API Docs",
    EVIDENCE_TYPE_IMAGE:       "Review Screenshot",
    EVIDENCE_TYPE_UNKNOWN:     "Explore Evidence",
}


def _classify_url(url: str, text: str | None = None) -> DiscoveredEvidenceItem | None:
    """Classify a single URL into an evidence type.  Returns None if not interesting."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    path_lower = path

    # ── GitHub / GitLab / Bitbucket ──────────────────────────────────────────
    if host in {"github.com", "www.github.com"}:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] not in {"features", "pricing", "about", "login", "join", "signup", "explore"}:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_GITHUB,
                url=url,
                domain=host,
                title=text or f"github.com/{parts[0]}/{parts[1]}",
                confidence=0.95,
                reason=f"GitHub repository link: {parsed.path.strip('/')}",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_GITHUB],
                raw_text=text,
            )
        # github.com profile
        if len(parts) == 1 and parts[0] not in {"features", "pricing", "about", "login", "join", "signup", "explore"}:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_GITHUB,
                url=url,
                domain=host,
                title=text or f"github.com/{parts[0]}",
                confidence=0.75,
                reason=f"GitHub profile link: /{parts[0]}",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_GITHUB],
                raw_text=text,
            )

    if host in {"gitlab.com", "www.gitlab.com", "bitbucket.org", "www.bitbucket.org"}:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_GITHUB,
                url=url,
                domain=host,
                title=text or f"{host}/{parts[0]}/{parts[1]}",
                confidence=0.90,
                reason=f"Code repository on {host}: {parsed.path.strip('/')}",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_GITHUB],
                raw_text=text,
            )

    # ── Video demos ──────────────────────────────────────────────────────────
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if "watch" in path_lower or "/embed/" in path_lower or "/shorts/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_VIDEO,
                url=url,
                domain="youtube.com",
                title=text or "YouTube video",
                confidence=0.95,
                reason="YouTube video link",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_VIDEO],
                raw_text=text,
            )
    if host in {"youtu.be"}:
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_VIDEO,
            url=url,
            domain="youtu.be",
            title=text or "YouTube video (short link)",
            confidence=0.95,
            reason="YouTube short link",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_VIDEO],
            raw_text=text,
        )
    if host in {"youtube-nocookie.com", "www.youtube-nocookie.com"}:
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_VIDEO,
            url=url,
            domain="youtube-nocookie.com",
            title=text or "Embedded YouTube video",
            confidence=0.90,
            reason="YouTube privacy-enhanced embed",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_VIDEO],
            raw_text=text,
        )
    if host in {"loom.com", "www.loom.com"}:
        if "/share/" in path_lower or "/embed/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_VIDEO,
                url=url,
                domain="loom.com",
                title=text or "Loom demo video",
                confidence=0.95,
                reason="Loom video link",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_VIDEO],
                raw_text=text,
            )
    if host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_VIDEO,
            url=url,
            domain="vimeo.com",
            title=text or "Vimeo video",
            confidence=0.92,
            reason="Vimeo video link",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_VIDEO],
            raw_text=text,
        )

    # ── LinkedIn ─────────────────────────────────────────────────────────────
    if host in {"linkedin.com", "www.linkedin.com"}:
        if "/in/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_LINKEDIN,
                url=url,
                domain="linkedin.com",
                title=text or "LinkedIn profile",
                confidence=0.95,
                reason="LinkedIn personal profile link",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_LINKEDIN],
                raw_text=text,
            )
        if "/posts/" in path_lower or "/pulse/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_LINKEDIN,
                url=url,
                domain="linkedin.com",
                title=text or "LinkedIn post",
                confidence=0.90,
                reason="LinkedIn post or article",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_LINKEDIN],
                raw_text=text,
            )
        if "/company/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_LINKEDIN,
                url=url,
                domain="linkedin.com",
                title=text or "LinkedIn company page",
                confidence=0.85,
                reason="LinkedIn company page",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_LINKEDIN],
                raw_text=text,
            )

    # ── Google Docs / Drive ──────────────────────────────────────────────────
    if host in {"docs.google.com"}:
        if "/document/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_GOOGLE_DOC,
                url=url,
                domain="docs.google.com",
                title=text or "Google Doc",
                confidence=0.95,
                reason="Google Docs document link",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_GOOGLE_DOC],
                raw_text=text,
            )
        if "/presentation/" in path_lower or "/present/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_GOOGLE_DOC,
                url=url,
                domain="docs.google.com",
                title=text or "Google Slides presentation",
                confidence=0.95,
                reason="Google Slides presentation link",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_GOOGLE_DOC],
                raw_text=text,
            )
        if "/spreadsheets/" in path_lower:
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_GOOGLE_DOC,
                url=url,
                domain="docs.google.com",
                title=text or "Google Sheets spreadsheet",
                confidence=0.95,
                reason="Google Sheets link",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_GOOGLE_DOC],
                raw_text=text,
            )
    if host in {"drive.google.com", "www.drive.google.com"}:
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_GOOGLE_DRIVE,
            url=url,
            domain="drive.google.com",
            title=text or "Google Drive file",
            confidence=0.90,
            reason="Google Drive link",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_GOOGLE_DRIVE],
            raw_text=text,
        )

    # ── PDF / Research reports ────────────────────────────────────────────────
    if path_lower.endswith(".pdf"):
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_PDF,
            url=url,
            domain=host,
            title=text or _path_filename(parsed.path),
            confidence=0.95,
            reason="Direct PDF link",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_PDF],
            raw_text=text,
        )
    if host in {"arxiv.org", "www.arxiv.org"} and ("/abs/" in path_lower or "/pdf/" in path_lower):
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_PDF,
            url=url,
            domain="arxiv.org",
            title=text or "ArXiv paper",
            confidence=0.92,
            reason="ArXiv research paper link",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_PDF],
            raw_text=text,
        )
    if host in {"overleaf.com", "www.overleaf.com"}:
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_PDF,
            url=url,
            domain="overleaf.com",
            title=text or "Overleaf document",
            confidence=0.88,
            reason="Overleaf LaTeX document link",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_PDF],
            raw_text=text,
        )

    # ── API Docs / OpenAPI / Swagger ─────────────────────────────────────────
    _api_doc_patterns = (
        "/swagger", "/redoc", "/api/docs", "/api-docs", "/openapi",
        "/docs/api", "/developer", "/apidocs", "/api-reference",
    )
    if any(pattern in path_lower for pattern in _api_doc_patterns):
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_API_DOCS,
            url=url,
            domain=host,
            title=text or "API documentation",
            confidence=0.85,
            reason=f"API documentation path detected ({_first_match(path_lower, _api_doc_patterns)})",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_API_DOCS],
            raw_text=text,
        )
    if path_lower.endswith(("swagger.json", "swagger.yaml", "openapi.json", "openapi.yaml")):
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_API_DOCS,
            url=url,
            domain=host,
            title=text or "OpenAPI spec",
            confidence=0.92,
            reason="OpenAPI/Swagger spec file",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_API_DOCS],
            raw_text=text,
        )
    if host in {"readme.com", "stoplight.io", "redocly.com", "apidocjs.com"}:
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_API_DOCS,
            url=url,
            domain=host,
            title=text or "API documentation",
            confidence=0.88,
            reason=f"API documentation hosting service: {host}",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_API_DOCS],
            raw_text=text,
        )

    # ── Deployed apps (well-known hosting domains) ────────────────────────────
    _DEPLOY_HOSTS = (
        ".vercel.app", ".netlify.app", ".herokuapp.com", ".fly.dev",
        ".railway.app", ".onrender.com", ".pages.dev", ".github.io",
        ".surge.sh", ".glitch.me", ".repl.co", ".replit.dev",
        ".azurewebsites.net", ".azurestaticapps.net",
        ".cloudflareapps.com", ".workers.dev",
        ".firebaseapp.com", ".web.app",
    )
    for suffix in _DEPLOY_HOSTS:
        if host.endswith(suffix):
            return DiscoveredEvidenceItem(
                evidence_type=EVIDENCE_TYPE_DEPLOYED_APP,
                url=url,
                domain=host,
                title=text or f"Deployed app ({host})",
                confidence=0.88,
                reason=f"Deployed app on {suffix.lstrip('.')} platform",
                suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_DEPLOYED_APP],
                raw_text=text,
            )

    # ── Images / screenshots ─────────────────────────────────────────────────
    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
    if any(path_lower.endswith(ext) for ext in _IMAGE_EXTS):
        return DiscoveredEvidenceItem(
            evidence_type=EVIDENCE_TYPE_IMAGE,
            url=url,
            domain=host,
            title=text or _path_filename(parsed.path),
            confidence=0.80,
            reason=f"Image file ({_path_ext(path_lower)})",
            suggested_action=_SUGGESTED_ACTIONS[EVIDENCE_TYPE_IMAGE],
            raw_text=text,
        )

    return None


def _path_filename(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else path


def _path_ext(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:] if dot >= 0 else ""


def _first_match(haystack: str, needles: tuple[str, ...]) -> str:
    for n in needles:
        if n in haystack:
            return n
    return ""


# ── HTML parser ────────────────────────────────────────────────────────────────

@dataclass
class _ExtractedLink:
    url: str
    text: str | None
    is_embed: bool = False   # from <iframe src>


class _LinkExtractorParser(HTMLParser):
    """Extract all hrefs (anchors) and embed sources (iframes, videos)."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self.links: list[_ExtractedLink] = []
        self._tag_stack: list[str] = []
        self._current_a_text: list[str] = []
        self._in_a = False
        self.page_title: str | None = None
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag)
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if tag == "a":
            href = attr_map.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                absolute = _make_absolute(href, self._base)
                if absolute and len(self.links) < _MAX_LINKS_PER_PAGE:
                    self.links.append(_ExtractedLink(url=absolute, text=None, is_embed=False))
                    self._in_a = True
                    self._current_a_text = []

        elif tag in {"iframe", "embed", "video", "source"}:
            src = attr_map.get("src", "")
            if src and not src.startswith(("data:", "blob:")):
                absolute = _make_absolute(src, self._base)
                if absolute and len(self.links) < _MAX_LINKS_PER_PAGE:
                    self.links.append(_ExtractedLink(url=absolute, text=None, is_embed=True))

        elif tag == "link":
            # Look for RSS/Atom — not currently classified but not excluded either
            pass

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_a:
            if self.links:
                text = " ".join(self._current_a_text).strip() or None
                self.links[-1] = _ExtractedLink(
                    url=self.links[-1].url, text=text, is_embed=self.links[-1].is_embed
                )
            self._in_a = False
            self._current_a_text = []
        if tag == "title" and self._title_parts:
            self.page_title = " ".join(self._title_parts).strip() or None
            self._title_parts = []
        while self._tag_stack:
            top = self._tag_stack.pop()
            if top == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._is_ignored():
            return
        text = data.strip()
        if not text:
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self._title_parts.append(text)
        elif self._in_a:
            self._current_a_text.append(text)

    def _is_ignored(self) -> bool:
        return any(t in {"script", "style", "noscript", "svg"} for t in self._tag_stack)


def _make_absolute(href: str, base: str) -> str | None:
    try:
        result = urljoin(base, href)
        parsed = urlparse(result)
        if parsed.scheme not in {"http", "https"}:
            return None
        return result
    except Exception:
        return None


# ── De-duplication ─────────────────────────────────────────────────────────────

def _dedup(items: list[DiscoveredEvidenceItem]) -> list[DiscoveredEvidenceItem]:
    """Remove exact URL duplicates; keep the highest-confidence entry."""
    seen: dict[str, DiscoveredEvidenceItem] = {}
    for item in items:
        key = item.url.rstrip("/")
        if key not in seen or item.confidence > seen[key].confidence:
            seen[key] = item
    return list(seen.values())


# ── Main service ───────────────────────────────────────────────────────────────

class WebsiteEvidenceDiscoveryService:
    """Scan a public website page and return discovered evidence sources."""

    def __init__(self, timeout_seconds: float = _TIMEOUT_SECONDS) -> None:
        self._timeout = timeout_seconds

    def discover(
        self,
        website_url: str,
        proof_session_id: str | None = None,
    ) -> WebsiteEvidenceDiscoveryResult:
        """Fetch website_url and return discovered evidence items.

        Always returns a result (never raises).  On error, result.error
        is set and items will be empty.
        """
        logger.info(
            "[EvidenceDiscovery] scan started url=%r session=%s",
            website_url[:80], proof_session_id or "(none)",
        )

        norm_url, err = _validate_public_url(website_url)
        if err:
            return WebsiteEvidenceDiscoveryResult(
                source_url=website_url,
                final_url=None,
                status_code=None,
                page_title=None,
                error=err,
                limitation=f"URL validation failed: {err}",
            )

        assert norm_url is not None
        try:
            # follow_redirects=False: we manually follow redirects so we can
            # re-validate each Location header before connecting to it.
            with httpx.Client(
                timeout=self._timeout,
                follow_redirects=False,
                headers={
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                    "User-Agent": "veribridge-ai-evidence-discovery/1",
                },
            ) as client:
                return self._fetch_with_redirect_guard(client, norm_url)
        except httpx.TimeoutException:
            return WebsiteEvidenceDiscoveryResult(
                source_url=website_url,
                final_url=None,
                status_code=None,
                page_title=None,
                error="fetch_timeout",
                limitation="Website request timed out. Evidence may exist but could not be discovered automatically.",
            )
        except httpx.HTTPError as exc:
            return WebsiteEvidenceDiscoveryResult(
                source_url=website_url,
                final_url=None,
                status_code=None,
                page_title=None,
                error="fetch_error",
                limitation=f"Network error fetching website: {type(exc).__name__}",
            )

    def _fetch_with_redirect_guard(
        self,
        client: httpx.Client,
        url: str,
    ) -> WebsiteEvidenceDiscoveryResult:
        """Follow redirects manually, re-validating every Location URL.

        Each hop's Location header is run through _validate_public_url
        (which includes a fresh DNS resolution) before the next request
        is sent.  This prevents open-redirect SSRF where a public host
        issues a 302 to an internal network address.
        """
        current_url = url
        for _hop in range(_MAX_REDIRECTS + 1):
            response = client.get(current_url)
            status_code = response.status_code

            if status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "").strip()
                if not location:
                    # Redirect with no Location — stop and process current response
                    break
                # Resolve relative Location against current URL
                next_url = urljoin(current_url, location)
                # Re-validate the redirect target (string + DNS)
                validated, err = _validate_public_url(next_url)
                if err or not validated:
                    logger.warning(
                        "[EvidenceDiscovery] blocked unsafe redirect: %s → %s (err=%s)",
                        current_url[:80], next_url[:80], err,
                    )
                    return WebsiteEvidenceDiscoveryResult(
                        source_url=url,
                        final_url=current_url,
                        status_code=status_code,
                        page_title=None,
                        error="unsafe_redirect",
                        limitation="Redirect target failed safety validation.",
                    )
                current_url = validated
                continue  # follow the validated redirect

            # Non-redirect response — hand off to classifier
            break

        return self._classify_response(response, url)

    def _classify_response(
        self,
        response: httpx.Response,
        source_url: str,
    ) -> WebsiteEvidenceDiscoveryResult:
        """Parse and classify an HTTP response that is the final hop."""
        final_url = str(response.url)
        status_code = response.status_code

        if status_code >= 400:
            return WebsiteEvidenceDiscoveryResult(
                source_url=source_url,
                final_url=final_url,
                status_code=status_code,
                page_title=None,
                error="http_error",
                limitation=f"Website returned HTTP {status_code}.",
            )

        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "xml" not in content_type:
            return WebsiteEvidenceDiscoveryResult(
                source_url=source_url,
                final_url=final_url,
                status_code=status_code,
                page_title=None,
                error="non_html_response",
                limitation=f"Website returned non-HTML content ({content_type.split(';')[0].strip()}).",
            )

        # Read body with size cap (non-streaming since httpx already fetched it)
        raw = response.content[:_MAX_HTML_BYTES]
        html = raw.decode("utf-8", errors="replace")

        parser = _LinkExtractorParser(base_url=final_url)
        parser.feed(html)

        raw_items: list[DiscoveredEvidenceItem] = []
        for link in parser.links:
            item = _classify_url(link.url, link.text)
            if item is not None:
                # Skip links that point back to the same host (self-references)
                try:
                    if urlparse(link.url).hostname == urlparse(final_url).hostname and \
                       item.evidence_type == EVIDENCE_TYPE_DEPLOYED_APP:
                        continue
                except Exception:
                    pass
                raw_items.append(item)

        items = _dedup(raw_items)

        # Sort: highest confidence first, then by type name for stable order
        items.sort(key=lambda x: (-x.confidence, x.evidence_type))

        # JS-heavy warning: no links discovered in static HTML
        js_heavy = len(parser.links) < 3 and not items
        limitation: str | None = None
        if js_heavy:
            limitation = (
                "This website appears to be JavaScript-rendered. Evidence links may not "
                "be present in static HTML. Use Website Recording to discover evidence "
                "during interactive browsing."
            )

        logger.info(
            "[EvidenceDiscovery] scan complete url=%r items=%d js_heavy=%s",
            source_url[:80], len(items), js_heavy,
        )

        return WebsiteEvidenceDiscoveryResult(
            source_url=source_url,
            final_url=final_url,
            status_code=status_code,
            page_title=parser.page_title,
            items=items,
            js_heavy_warning=js_heavy,
            limitation=limitation,
            error=None,
        )
