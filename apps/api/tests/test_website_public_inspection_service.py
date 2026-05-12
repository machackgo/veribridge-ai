"""Tests for safe public website inspection."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.website_public_inspection_service import WebsitePublicInspectionService


class _FakeStreamResponse:
    def __init__(
        self,
        status_code: int,
        body: bytes,
        headers: dict[str, str] | None = None,
        url: str = "https://example.com/final",
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers or {"content-type": "text/html"}
        self.url = url

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def iter_bytes(self):
        yield self._body


class _FakeWebsiteClient:
    response: _FakeStreamResponse | Exception

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_FakeWebsiteClient":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def stream(self, method: str, url: str) -> _FakeStreamResponse:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _public_dns(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.website_public_inspection_service.socket.getaddrinfo",
        lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))],
    )


def test_inspect_public_website_extracts_title_meta_headings_and_text(monkeypatch) -> None:
    _public_dns(monkeypatch)
    html = b"""
    <html>
      <head>
        <title>FastAPI Accident Risk Dashboard</title>
        <meta name="description" content="A FastAPI and React demo for route risk scoring">
      </head>
      <body>
        <h1>FastAPI route risk scoring</h1>
        <p>Built with FastAPI APIs and deployed as a public dashboard.</p>
        <form><input name="origin"><button>Run</button></form>
      </body>
    </html>
    """
    _FakeWebsiteClient.response = _FakeStreamResponse(200, html)
    monkeypatch.setattr("app.services.website_public_inspection_service.httpx.Client", _FakeWebsiteClient)

    result = WebsitePublicInspectionService().inspect_url("https://example.com")

    assert result.inspection_used is True
    assert result.final_url == "https://example.com/final"
    assert result.status_code == 200
    assert result.page_title == "FastAPI Accident Risk Dashboard"
    assert result.meta_description == "A FastAPI and React demo for route risk scoring"
    assert result.headings == ["FastAPI route risk scoring"]
    assert "FastAPI APIs" in (result.visible_text or "")
    assert "form" in result.public_markers
    assert "interactive_controls" in result.public_markers


def test_inspect_localhost_is_rejected() -> None:
    result = WebsitePublicInspectionService().inspect_url("http://localhost:3000")

    assert result.inspection_used is False
    assert result.error == "website_private_host"
    assert any("localhost" in signal for signal in result.missing_signals)


def test_inspect_private_ip_is_rejected() -> None:
    result = WebsitePublicInspectionService().inspect_url("http://10.0.0.5")

    assert result.inspection_used is False
    assert result.error == "website_private_host"


def test_inspect_timeout_returns_safe_failure(monkeypatch) -> None:
    _public_dns(monkeypatch)
    _FakeWebsiteClient.response = httpx.TimeoutException("timed out")
    monkeypatch.setattr("app.services.website_public_inspection_service.httpx.Client", _FakeWebsiteClient)

    result = WebsitePublicInspectionService().inspect_url("https://example.com")

    assert result.inspection_used is False
    assert result.error == "website_timeout"
    assert any("timed out" in signal for signal in result.missing_signals)


def test_inspect_non_html_response_returns_safe_failure(monkeypatch) -> None:
    _public_dns(monkeypatch)
    _FakeWebsiteClient.response = _FakeStreamResponse(
        200,
        b'{"ok": true}',
        headers={"content-type": "application/json"},
    )
    monkeypatch.setattr("app.services.website_public_inspection_service.httpx.Client", _FakeWebsiteClient)

    result = WebsitePublicInspectionService().inspect_url("https://example.com")

    assert result.inspection_used is False
    assert result.error == "website_non_html_response"
    assert any("not HTML" in signal for signal in result.missing_signals)
