"""Tests for the Apple Wallet Passport Pass (owner-only, feature-flag gated).

  ``GET /api/v1/student/vbr/wallet/apple/availability``  — readiness booleans
  ``GET /api/v1/student/vbr/wallet/apple/pass-json``     — dev preview mapping
  ``GET /api/v1/student/vbr/wallet/apple/pass.pkpass``   — signed pass (gated)

Covers:
  - pass.json maps the safe public-passport fields (name / role / education /
    verified project count / top skills / proof sources / back fields)
  - the barcode message is EXACTLY the existing revocable ``/b/{code}`` short
    URL, iso-8859-1 encoded, and the same Beam link is created/reused (never a
    second sharing URL)
  - pass.json carries NO private data: no user id, no beam link id, no slug
    leakage beyond the public link, no storage/token/path markers
  - serialNumber is stable per user and not a raw internal id
  - an unpublished passport gets the same 409 the Beam Card gets
  - the ``.pkpass`` endpoint is honestly gated: flag off → 404 not_enabled;
    flag on without identifiers/certs → 503 not_configured (no crash, no fake
    unsigned bundle)
  - availability reports enabled ONLY when flag + identifiers + real signing
    files are all present, and never leaks paths

All storage is in-memory (dict mode). No network / Apple certificates needed.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.core.config import settings
from app.main import app

USER_ID = "11111111-1111-1111-1111-111111111111"

PASS_JSON_PATH = "/api/v1/student/vbr/wallet/apple/pass-json"
PKPASS_PATH = "/api/v1/student/vbr/wallet/apple/pass.pkpass"
AVAILABILITY_PATH = "/api/v1/student/vbr/wallet/apple/availability"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def wallet_identifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "apple_pass_type_identifier", "pass.com.veribridgeai.passport")
    monkeypatch.setattr(settings, "apple_team_identifier", "TEAM123456")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _publish_passport(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/publish", json={})


def _beam_link(client: TestClient) -> dict:
    return client.post("/api/v1/student/vbr/beam/links", json={}).json()


# ── pass.json builder (Phase C/D) ─────────────────────────────────────────────

def test_pass_json_requires_published_passport(client: TestClient) -> None:
    res = client.get(PASS_JSON_PATH)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "beam_passport_not_published"


def test_pass_json_maps_safe_fields(client: TestClient, wallet_identifiers: None) -> None:
    _publish_passport(client)
    res = client.get(PASS_JSON_PATH)
    assert res.status_code == 200
    pass_json = res.json()

    assert pass_json["formatVersion"] == 1
    assert pass_json["passTypeIdentifier"] == "pass.com.veribridgeai.passport"
    assert pass_json["teamIdentifier"] == "TEAM123456"
    assert pass_json["organizationName"] == "VeriBridge AI"
    assert pass_json["description"] == "VeriBridge Work Passport"
    assert pass_json["logoText"] == "VeriBridge"

    generic = pass_json["generic"]
    (header,) = generic["headerFields"]
    assert header["label"] == "VERIFIED"
    assert "PROJECT" in header["value"]

    (primary,) = generic["primaryFields"]
    assert primary["label"] == "NAME"
    assert primary["value"].strip()

    role = generic["secondaryFields"][0]
    assert role["label"] == "ROLE"
    assert role["value"].strip()

    labels = [f["label"] for f in generic["auxiliaryFields"]]
    assert labels == ["TOP SKILLS", "PROOF SOURCES"]

    back_labels = [f["label"] for f in generic["backFields"]]
    assert "Public-safe proof summary" in back_labels
    assert "Private evidence protected" in back_labels
    assert "Open the live public Passport to inspect proof" in back_labels


def test_pass_barcode_uses_existing_beam_short_link(client: TestClient) -> None:
    _publish_passport(client)
    link = _beam_link(client)

    pass_json = client.get(PASS_JSON_PATH).json()
    (barcode,) = pass_json["barcodes"]
    assert barcode["format"] == "PKBarcodeFormatQR"
    assert barcode["messageEncoding"] == "iso-8859-1"
    assert barcode["message"].endswith(f"/b/{link['code']}")
    assert barcode["altText"] == barcode["message"]
    # The message is a resolvable absolute-or-relative /b/{code} URL, never /p/.
    assert "/p/" not in barcode["message"]


def test_pass_reuses_the_active_beam_link_instead_of_minting(client: TestClient, mem_store: dict) -> None:
    _publish_passport(client)
    first = client.get(PASS_JSON_PATH).json()
    second = client.get(PASS_JSON_PATH).json()
    assert first["barcodes"][0]["message"] == second["barcodes"][0]["message"]
    # Exactly one link exists — the pass never mints a parallel sharing URL.
    assert len(mem_store.get("beam_links", {})) == 1
    # And the Beam Card reuses the SAME code the pass QR carries.
    link = _beam_link(client)
    assert first["barcodes"][0]["message"].endswith(f"/b/{link['code']}")


def test_pass_json_excludes_private_data(client: TestClient, mem_store: dict) -> None:
    _publish_passport(client)
    link = _beam_link(client)
    res = client.get(PASS_JSON_PATH)
    body = json.dumps(res.json()).lower()

    assert USER_ID not in body
    assert link["id"].lower() not in body
    for marker in ("supabase", "x-amz", "/object/sign/", "file://", "storage_path", "access_token"):
        assert marker not in body
    # No numeric-score leakage on the pass (the honest "never numeric scores"
    # copy is allowed; a score VALUE like "score: 87" / "87/100" is not).
    assert re.search(r"score[s]?\s*[:=]\s*\d", body) is None
    assert re.search(r"\b\d+\s*/\s*100\b", body) is None


def test_serial_number_is_stable_and_not_an_internal_id(client: TestClient) -> None:
    _publish_passport(client)
    first = client.get(PASS_JSON_PATH).json()["serialNumber"]
    second = client.get(PASS_JSON_PATH).json()["serialNumber"]
    assert first == second
    assert first.startswith("vbr-")
    assert USER_ID not in first


# ── .pkpass gating (Phase E) ──────────────────────────────────────────────────

def test_pkpass_is_404_when_feature_flag_is_off(client: TestClient) -> None:
    _publish_passport(client)
    assert settings.apple_wallet_enabled is False  # repo default
    res = client.get(PKPASS_PATH)
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "apple_wallet_not_enabled"


def test_pkpass_missing_identifiers_is_clear_config_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish_passport(client)
    monkeypatch.setattr(settings, "apple_wallet_enabled", True)
    res = client.get(PKPASS_PATH)
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "apple_wallet_not_configured"


def test_pkpass_missing_cert_files_is_clear_config_error(
    client: TestClient, wallet_identifiers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish_passport(client)
    monkeypatch.setattr(settings, "apple_wallet_enabled", True)
    monkeypatch.setattr(settings, "apple_wallet_cert_path", "/nonexistent/pass-cert.pem")
    monkeypatch.setattr(settings, "apple_wallet_key_path", "/nonexistent/pass-key.pem")
    monkeypatch.setattr(settings, "apple_wallet_wwdr_cert_path", "/nonexistent/wwdr.pem")
    res = client.get(PKPASS_PATH)
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["code"] == "apple_wallet_not_configured"
    # The error must never echo filesystem paths back to the caller.
    assert "/nonexistent" not in json.dumps(detail)


def test_pkpass_never_returns_unsigned_success_without_certs(
    client: TestClient, wallet_identifiers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish_passport(client)
    monkeypatch.setattr(settings, "apple_wallet_enabled", True)
    res = client.get(PKPASS_PATH)
    assert res.status_code != 200
    assert res.headers.get("content-type", "") != "application/vnd.apple.pkpass"


# ── Availability (drives the frontend button) ─────────────────────────────────

def test_availability_disabled_by_default(client: TestClient) -> None:
    res = client.get(AVAILABILITY_PATH)
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    assert body["feature_flag"] is False
    assert set(body) == {"enabled", "feature_flag", "identifiers_configured", "signing_ready"}


def test_availability_requires_flag_identifiers_and_real_files(
    client: TestClient, wallet_identifiers: None, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "apple_wallet_enabled", True)

    # Paths set but files absent → still not enabled (the button must not show).
    monkeypatch.setattr(settings, "apple_wallet_cert_path", str(tmp_path / "missing-cert.pem"))
    monkeypatch.setattr(settings, "apple_wallet_key_path", str(tmp_path / "missing-key.pem"))
    monkeypatch.setattr(settings, "apple_wallet_wwdr_cert_path", str(tmp_path / "missing-wwdr.pem"))
    body = client.get(AVAILABILITY_PATH).json()
    assert body["enabled"] is False
    assert body["signing_ready"] is False

    # All three files present → enabled flips true.
    for name in ("cert.pem", "key.pem", "wwdr.pem"):
        (tmp_path / name).write_text("placeholder pem for availability check")
    monkeypatch.setattr(settings, "apple_wallet_cert_path", str(tmp_path / "cert.pem"))
    monkeypatch.setattr(settings, "apple_wallet_key_path", str(tmp_path / "key.pem"))
    monkeypatch.setattr(settings, "apple_wallet_wwdr_cert_path", str(tmp_path / "wwdr.pem"))
    body = client.get(AVAILABILITY_PATH).json()
    assert body["enabled"] is True
    assert body["signing_ready"] is True


def test_availability_never_leaks_paths(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "apple_wallet_cert_path", "/secret/mount/pass-cert.pem")
    body = json.dumps(client.get(AVAILABILITY_PATH).json())
    assert "/secret/mount" not in body
