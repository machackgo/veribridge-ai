from __future__ import annotations

from app.services import live_website_check_service as live_service
from app.services.live_website_check_service import LiveWebsiteCheckService
from app.services.url_classification_service import classify_website_url


def test_public_url_classified_as_live_public() -> None:
    result = classify_website_url("https://open-meteo.com/")
    assert result.is_public_live_url is True
    assert result.hostname == "open-meteo.com"


def test_localhost_url_classified_not_applicable() -> None:
    result = classify_website_url("http://localhost:3000")
    assert result.is_local_or_private is True
    assert result.classification == "local_private"


def test_loopback_ip_classified_not_applicable() -> None:
    result = classify_website_url("http://127.0.0.1:5173")
    assert result.is_local_or_private is True
    assert result.classification == "local_private"


def test_private_lan_ip_classified_not_applicable() -> None:
    result = classify_website_url("http://192.168.1.20:3000")
    assert result.is_local_or_private is True
    assert result.classification == "local_private"


def test_live_check_skips_local_private_urls_without_failure() -> None:
    store: dict = {}
    row = LiveWebsiteCheckService(store).run_check("u1", "s1", "http://localhost:3000")
    assert row["status"] == "not_applicable"
    assert row["confidence"] == "not_applicable"
    assert row["is_reachable"] is False
    assert row["status_code"] is None
    assert "public live website check is not applicable" in row["recruiter_summary"].lower()
    assert row["error_message"] is None


def test_public_live_check_still_runs_and_persists_reachable(monkeypatch) -> None:
    def fake_perform_check(url: str) -> dict:
        return {
            "status": "complete",
            "website_url": url,
            "final_url": None,
            "status_code": 200,
            "response_time_ms": 123,
            "content_type": "text/html",
            "page_title": "Open-Meteo",
            "is_reachable": True,
            "confidence": "high",
            "risk_flags": [],
            "recruiter_summary": "Website is reachable and returned HTTP 200.",
            "error_message": None,
            "checked_at": "2026-06-05T00:00:00+00:00",
        }

    monkeypatch.setattr(live_service, "_perform_check", fake_perform_check)
    store: dict = {}
    row = LiveWebsiteCheckService(store).run_check("u1", "s1", "https://open-meteo.com/")
    assert row["status"] == "complete"
    assert row["is_reachable"] is True
    assert row["status_code"] == 200
