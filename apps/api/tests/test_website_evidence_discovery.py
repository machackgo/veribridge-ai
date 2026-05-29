"""Tests for WebsiteEvidenceDiscoveryService.

Covers all detection types, URL validation, and edge cases.
These tests run without any network calls — the service is tested
using injected HTML strings via the internal helper functions.
"""

from __future__ import annotations

import pytest

from app.services.website_evidence_discovery_service import (
    WebsiteEvidenceDiscoveryService,
    _classify_url,
    _dedup,
    _is_private_host,
    _LinkExtractorParser,
    _make_absolute,
    _validate_public_url,
    EVIDENCE_TYPE_API_DOCS,
    EVIDENCE_TYPE_DEPLOYED_APP,
    EVIDENCE_TYPE_GITHUB,
    EVIDENCE_TYPE_GOOGLE_DOC,
    EVIDENCE_TYPE_GOOGLE_DRIVE,
    EVIDENCE_TYPE_IMAGE,
    EVIDENCE_TYPE_LINKEDIN,
    EVIDENCE_TYPE_PDF,
    EVIDENCE_TYPE_VIDEO,
)


# ── _validate_public_url ───────────────────────────────────────────────────────

def test_validate_public_url_ok():
    url, err = _validate_public_url("https://example.com/portfolio")
    assert err is None
    assert url == "https://example.com/portfolio"

def test_validate_public_url_missing():
    _, err = _validate_public_url(None)
    assert err == "missing_url"
    _, err2 = _validate_public_url("   ")
    assert err2 == "missing_url"

def test_validate_public_url_unsupported_scheme():
    _, err = _validate_public_url("ftp://example.com")
    assert err == "unsupported_scheme"

def test_validate_public_url_private_localhost():
    _, err = _validate_public_url("http://localhost:3000")
    assert err == "private_host"

def test_validate_public_url_private_ip():
    _, err = _validate_public_url("http://192.168.1.1/app")
    assert err == "private_host"

def test_validate_public_url_private_10_range():
    _, err = _validate_public_url("http://10.0.0.5/dashboard")
    assert err == "private_host"

def test_validate_public_url_missing_host():
    _, err = _validate_public_url("https://")
    assert err == "missing_host"


# ── _is_private_host ──────────────────────────────────────────────────────────

def test_is_private_host_localhost():
    assert _is_private_host("localhost") is True

def test_is_private_host_local_subdomain():
    assert _is_private_host("myapp.local") is True

def test_is_private_host_public():
    assert _is_private_host("github.com") is False
    assert _is_private_host("example.vercel.app") is False


# ── _classify_url — GitHub ─────────────────────────────────────────────────────

def test_classify_github_repo():
    item = _classify_url("https://github.com/johndoe/my-ml-project")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GITHUB
    assert item.confidence >= 0.9

def test_classify_github_profile():
    item = _classify_url("https://github.com/johndoe")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GITHUB

def test_classify_gitlab_repo():
    item = _classify_url("https://gitlab.com/johndoe/project")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GITHUB

def test_classify_bitbucket_repo():
    item = _classify_url("https://bitbucket.org/johndoe/repo")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GITHUB

def test_classify_github_homepage_ignored():
    # github.com/features is not a repo
    item = _classify_url("https://github.com/features")
    assert item is None or item.evidence_type != EVIDENCE_TYPE_GITHUB


# ── _classify_url — Video ──────────────────────────────────────────────────────

def test_classify_youtube_watch():
    item = _classify_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_VIDEO

def test_classify_youtu_be():
    item = _classify_url("https://youtu.be/dQw4w9WgXcQ")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_VIDEO

def test_classify_youtube_embed():
    item = _classify_url("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_VIDEO

def test_classify_loom_share():
    item = _classify_url("https://www.loom.com/share/abc123def456")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_VIDEO

def test_classify_loom_embed():
    item = _classify_url("https://www.loom.com/embed/abc123def456")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_VIDEO

def test_classify_vimeo():
    item = _classify_url("https://vimeo.com/123456789")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_VIDEO


# ── _classify_url — PDF / Reports ─────────────────────────────────────────────

def test_classify_pdf_link():
    item = _classify_url("https://example.com/reports/analysis.pdf")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_PDF

def test_classify_arxiv():
    item = _classify_url("https://arxiv.org/abs/2301.00001")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_PDF

def test_classify_arxiv_pdf():
    item = _classify_url("https://arxiv.org/pdf/2301.00001")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_PDF

def test_classify_overleaf():
    item = _classify_url("https://www.overleaf.com/project/abc123")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_PDF


# ── _classify_url — Google Docs / Drive ──────────────────────────────────────

def test_classify_google_doc():
    item = _classify_url("https://docs.google.com/document/d/abc123/edit")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GOOGLE_DOC

def test_classify_google_slides():
    item = _classify_url("https://docs.google.com/presentation/d/abc123/edit")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GOOGLE_DOC

def test_classify_google_sheets():
    item = _classify_url("https://docs.google.com/spreadsheets/d/abc123/edit")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GOOGLE_DOC

def test_classify_google_drive():
    item = _classify_url("https://drive.google.com/file/d/abc123/view")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_GOOGLE_DRIVE


# ── _classify_url — LinkedIn ──────────────────────────────────────────────────

def test_classify_linkedin_profile():
    item = _classify_url("https://www.linkedin.com/in/johndoe")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_LINKEDIN

def test_classify_linkedin_post():
    item = _classify_url("https://www.linkedin.com/posts/johndoe_activity-123456789")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_LINKEDIN

def test_classify_linkedin_company():
    item = _classify_url("https://www.linkedin.com/company/acme-corp")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_LINKEDIN


# ── _classify_url — Deployed apps ─────────────────────────────────────────────

def test_classify_vercel_app():
    item = _classify_url("https://my-ml-dashboard.vercel.app")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_DEPLOYED_APP

def test_classify_netlify_app():
    item = _classify_url("https://awesome-project.netlify.app")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_DEPLOYED_APP

def test_classify_github_pages():
    item = _classify_url("https://johndoe.github.io/portfolio")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_DEPLOYED_APP

def test_classify_fly_dev():
    item = _classify_url("https://my-api.fly.dev")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_DEPLOYED_APP

def test_classify_render():
    item = _classify_url("https://my-backend.onrender.com")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_DEPLOYED_APP


# ── _classify_url — API docs ──────────────────────────────────────────────────

def test_classify_swagger_path():
    item = _classify_url("https://api.example.com/swagger")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_API_DOCS

def test_classify_redoc_path():
    item = _classify_url("https://api.example.com/redoc")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_API_DOCS

def test_classify_openapi_json():
    item = _classify_url("https://api.example.com/openapi.json")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_API_DOCS

def test_classify_openapi_yaml():
    item = _classify_url("https://api.example.com/openapi.yaml")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_API_DOCS

def test_classify_api_docs_path():
    item = _classify_url("https://example.com/api/docs")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_API_DOCS

def test_classify_readme_io():
    item = _classify_url("https://readme.com/docs/my-project")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_API_DOCS


# ── _classify_url — Images / screenshots ──────────────────────────────────────

def test_classify_png():
    item = _classify_url("https://example.com/screenshots/demo.png")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_IMAGE

def test_classify_jpg():
    item = _classify_url("https://example.com/results/chart.jpg")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_IMAGE

def test_classify_webp():
    item = _classify_url("https://example.com/demo.webp")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_IMAGE

def test_classify_svg():
    item = _classify_url("https://example.com/diagram.svg")
    assert item is not None
    assert item.evidence_type == EVIDENCE_TYPE_IMAGE


# ── _classify_url — Non-evidence URLs ────────────────────────────────────────

def test_classify_plain_page_returns_none():
    item = _classify_url("https://example.com/about")
    assert item is None

def test_classify_css_returns_none():
    item = _classify_url("https://example.com/styles.css")
    assert item is None


# ── _dedup ─────────────────────────────────────────────────────────────────────

def test_dedup_removes_exact_duplicates():
    from app.services.website_evidence_discovery_service import DiscoveredEvidenceItem
    a = DiscoveredEvidenceItem(
        evidence_type=EVIDENCE_TYPE_GITHUB, url="https://github.com/a/b",
        domain="github.com", title="a/b", confidence=0.95,
        reason="test", suggested_action="Analyze GitHub Proof",
    )
    b = DiscoveredEvidenceItem(
        evidence_type=EVIDENCE_TYPE_GITHUB, url="https://github.com/a/b",
        domain="github.com", title="a/b", confidence=0.90,
        reason="test", suggested_action="Analyze GitHub Proof",
    )
    result = _dedup([a, b])
    assert len(result) == 1
    assert result[0].confidence == 0.95  # kept highest


# ── _LinkExtractorParser ──────────────────────────────────────────────────────

def test_link_extractor_parses_anchors():
    html = '<html><body><a href="https://github.com/user/repo">My Project</a></body></html>'
    parser = _LinkExtractorParser(base_url="https://example.com")
    parser.feed(html)
    assert len(parser.links) == 1
    assert parser.links[0].url == "https://github.com/user/repo"
    assert parser.links[0].text == "My Project"

def test_link_extractor_resolves_relative_links():
    html = '<html><body><a href="/about">About</a></body></html>'
    parser = _LinkExtractorParser(base_url="https://example.com")
    parser.feed(html)
    assert parser.links[0].url == "https://example.com/about"

def test_link_extractor_ignores_javascript_links():
    html = '<html><body><a href="javascript:void(0)">Click</a></body></html>'
    parser = _LinkExtractorParser(base_url="https://example.com")
    parser.feed(html)
    assert len(parser.links) == 0

def test_link_extractor_captures_iframe_src():
    html = '<html><body><iframe src="https://www.youtube.com/embed/abc"></iframe></body></html>'
    parser = _LinkExtractorParser(base_url="https://example.com")
    parser.feed(html)
    assert any("youtube" in lnk.url for lnk in parser.links)

def test_link_extractor_captures_page_title():
    html = "<html><head><title>My Portfolio</title></head><body></body></html>"
    parser = _LinkExtractorParser(base_url="https://example.com")
    parser.feed(html)
    assert parser.page_title == "My Portfolio"


# ── _make_absolute ─────────────────────────────────────────────────────────────

def test_make_absolute_already_absolute():
    assert _make_absolute("https://github.com/user/repo", "https://example.com") == "https://github.com/user/repo"

def test_make_absolute_relative():
    result = _make_absolute("/projects/demo.pdf", "https://example.com/portfolio")
    assert result == "https://example.com/projects/demo.pdf"

def test_make_absolute_non_http_returns_none():
    assert _make_absolute("data:image/png;base64,abc", "https://example.com") is None


# ── Integration: classify from HTML ───────────────────────────────────────────

def test_classify_from_portfolio_html():
    """End-to-end test using a mock HTML page with multiple evidence types."""
    html = """
    <html>
    <head><title>Jane's Portfolio</title></head>
    <body>
      <a href="https://github.com/janedoe/ml-dashboard">GitHub Repo</a>
      <a href="https://www.youtube.com/watch?v=abc123">Demo Video</a>
      <a href="https://docs.google.com/document/d/xyz/edit">Project Report</a>
      <a href="https://www.linkedin.com/in/janedoe">LinkedIn</a>
      <a href="/reports/final-analysis.pdf">PDF Report</a>
      <a href="https://ml-dashboard.vercel.app">Live Demo</a>
      <a href="https://api.ml-dashboard.vercel.app/swagger">API Docs</a>
      <a href="https://example.com/screenshots/demo.png">Screenshot</a>
      <iframe src="https://www.loom.com/embed/demo123"></iframe>
    </body>
    </html>
    """
    parser = _LinkExtractorParser(base_url="https://janedoe.dev")
    parser.feed(html)
    assert parser.page_title == "Jane's Portfolio"
    assert len(parser.links) >= 9

    items = []
    for link in parser.links:
        item = _classify_url(link.url, link.text)
        if item:
            items.append(item)

    types_found = {item.evidence_type for item in items}
    assert EVIDENCE_TYPE_GITHUB in types_found
    assert EVIDENCE_TYPE_VIDEO in types_found
    assert EVIDENCE_TYPE_GOOGLE_DOC in types_found
    assert EVIDENCE_TYPE_LINKEDIN in types_found
    assert EVIDENCE_TYPE_PDF in types_found
    assert EVIDENCE_TYPE_DEPLOYED_APP in types_found
    assert EVIDENCE_TYPE_API_DOCS in types_found
    assert EVIDENCE_TYPE_IMAGE in types_found


# ── Service: validate rejects private URLs ────────────────────────────────────

def test_service_rejects_localhost():
    svc = WebsiteEvidenceDiscoveryService()
    result = svc.discover("http://localhost:3000")
    assert result.error == "private_host"
    assert result.items == []

def test_service_rejects_missing_url():
    svc = WebsiteEvidenceDiscoveryService()
    result = svc.discover("")
    assert result.error is not None
    assert result.items == []

def test_service_rejects_private_ip():
    svc = WebsiteEvidenceDiscoveryService()
    result = svc.discover("http://192.168.0.1/api")
    assert result.error == "private_host"


# ── Service: fetch timeout/failure handled gracefully ─────────────────────────

def test_service_handles_timeout(monkeypatch):
    """Service catches httpx.TimeoutException and returns graceful result."""
    import httpx

    class _FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def stream(self, *a, **kw):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(
        "app.services.website_evidence_discovery_service.httpx.Client",
        lambda **kw: _FakeClient(),
    )
    svc = WebsiteEvidenceDiscoveryService()
    result = svc.discover("https://example.com")
    assert result.error == "fetch_timeout"
    assert result.items == []
    assert result.limitation is not None


def test_service_handles_network_error(monkeypatch):
    """Service catches httpx.HTTPError and returns graceful result."""
    import httpx

    class _FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def stream(self, *a, **kw):
            raise httpx.NetworkError("connection refused")

    monkeypatch.setattr(
        "app.services.website_evidence_discovery_service.httpx.Client",
        lambda **kw: _FakeClient(),
    )
    svc = WebsiteEvidenceDiscoveryService()
    result = svc.discover("https://example.com")
    assert result.error == "fetch_error"


# ── JS-heavy detection ────────────────────────────────────────────────────────

def test_js_heavy_warning_when_no_links(monkeypatch):
    """Sites with no discoverable links trigger js_heavy_warning."""
    import httpx
    from io import BytesIO

    class _FakeResponse:
        status_code = 200
        url = "https://spa-app.com"
        headers = {"content-type": "text/html"}
        def iter_bytes(self):
            yield b"<html><body><div id='root'></div></body></html>"

    class _FakeStream:
        def __enter__(self):
            return _FakeResponse()
        def __exit__(self, *a):
            pass

    class _FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def stream(self, *a, **kw):
            return _FakeStream()

    monkeypatch.setattr(
        "app.services.website_evidence_discovery_service.httpx.Client",
        lambda **kw: _FakeClient(),
    )
    svc = WebsiteEvidenceDiscoveryService()
    result = svc.discover("https://spa-app.com")
    assert result.js_heavy_warning is True
    assert result.limitation is not None
    assert "JavaScript" in result.limitation or "Recording" in result.limitation
