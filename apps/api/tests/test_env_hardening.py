"""Startup / environment hardening (P6) and log token redaction (N6).

* ENVIRONMENT is normalised and allow-listed; ``is_production`` is the single
  production check.
* Startup guards: a Render process must be production; production must not
  enable the demo-user fallback; production CORS must be explicit (non-empty,
  no wildcard, no localhost / loopback).
* The debug router is not mounted in production.
* Report tokens are redacted from uvicorn access logs and app request logs.

No real credentials are read; Settings are built from explicit dicts.
"""

from __future__ import annotations

import logging

import pydantic
import pytest
from fastapi.testclient import TestClient

from app.core import config as cfg
from app.core.config import Settings
from app.core.log_redaction import (
    REDACTED,
    ReportTokenRedactionFilter,
    install_report_token_redaction,
    redact_report_tokens,
)

_PROD_ORIGINS = "https://veribridgeai.com,https://www.veribridgeai.com"


def _settings(**overrides: str) -> Settings:
    return Settings.model_validate(
        {
            "ENVIRONMENT": "test",
            "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
            "SUPABASE_URL": "https://example.supabase.co",
            "RENDER": "",
            "ENABLE_DEMO_USER_FALLBACK": "false",
            **overrides,
        }
    )


def _prod(**overrides: str) -> Settings:
    return _settings(ENVIRONMENT="production", CORS_ALLOWED_ORIGINS=_PROD_ORIGINS, **overrides)


# ── ENVIRONMENT normalisation ────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["production", "Production", " production ", "PRODUCTION\n"])
def test_environment_production_variants_normalise(raw: str) -> None:
    s = _settings(ENVIRONMENT=raw, CORS_ALLOWED_ORIGINS=_PROD_ORIGINS)
    assert s.environment == "production"
    assert s.is_production is True


@pytest.mark.parametrize("raw", ["development", "Test", " staging "])
def test_environment_non_production_values(raw: str) -> None:
    s = _settings(ENVIRONMENT=raw)
    assert s.environment == raw.strip().lower()
    assert s.is_production is False


@pytest.mark.parametrize("raw", ["prod", "live", "", "production-eu"])
def test_environment_unknown_value_rejected(raw: str) -> None:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        _settings(ENVIRONMENT=raw, CORS_ALLOWED_ORIGINS=_PROD_ORIGINS)
    assert "ENVIRONMENT must be one of" in str(exc_info.value)


def test_is_production_survives_runtime_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests (and any runtime patch) bypass the field validator; the property
    must still normalise."""
    monkeypatch.setattr(cfg.settings, "environment", " Production ")
    assert cfg.settings.is_production is True


# ── RENDER marker ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("marker", ["true", "1", "TRUE", "yes"])
def test_render_marker_requires_production(marker: str) -> None:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        _settings(RENDER=marker, ENVIRONMENT="development")
    assert "RENDER is set" in str(exc_info.value)


@pytest.mark.parametrize("marker", ["", "0", "false", "off"])
def test_falsey_render_marker_ignored(marker: str) -> None:
    assert _settings(RENDER=marker, ENVIRONMENT="development").is_production is False


def test_render_marker_with_production_ok() -> None:
    assert _prod(RENDER="true").is_production is True


# ── Demo fallback ────────────────────────────────────────────────────────────


def test_demo_fallback_rejected_in_production() -> None:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        _prod(ENABLE_DEMO_USER_FALLBACK="true")
    assert "ENABLE_DEMO_USER_FALLBACK" in str(exc_info.value)


def test_demo_fallback_allowed_outside_production() -> None:
    assert _settings(ENABLE_DEMO_USER_FALLBACK="true").enable_demo_user_fallback is True


# ── CORS ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "origins",
    [
        "",
        " , ",
        "*",
        "https://veribridgeai.com,*",
        "https://*.veribridgeai.com",
        "https://veribridgeai.com,http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://LOCALHOST",
        "http://app.localhost:3000",
        "http://[::1]:3000",
        "http://0.0.0.0:8000",
        "null",
        "https://veribridgeai.com,NULL",
        "http://127.0.0.2",
        "http://127.255.255.254:3000",
        "http://[::ffff:127.0.0.1]",
        "http://10.0.0.5:3000",
        "http://172.16.0.1",
        "http://172.31.255.254",
        "http://192.168.1.23:3000",
        "http://169.254.169.254",
        "http://[fc00::1]",
        "http://[fd12:3456::1]:3000",
        "http://[fe80::1]",
    ],
)
def test_unsafe_production_cors_rejected(origins: str) -> None:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        _settings(ENVIRONMENT="production", CORS_ALLOWED_ORIGINS=origins)
    message = str(exc_info.value)
    assert "CORS" in message
    # Messages name the setting, never echo the configured origins.
    assert "localhost:3000" not in message and "127.0.0.1:3000" not in message


def test_explicit_production_cors_accepted() -> None:
    assert _prod().cors_origins == _PROD_ORIGINS.split(",")


@pytest.mark.parametrize("origin", ["http://172.15.0.1", "http://172.32.0.1", "https://8.8.8.8"])
def test_public_ip_origins_not_mistaken_for_private(origin: str) -> None:
    """Range boundaries: addresses just outside 172.16/12 and public IPs pass."""
    assert _settings(ENVIRONMENT="production", CORS_ALLOWED_ORIGINS=origin).cors_origins == [origin]


def test_localhost_cors_fine_outside_production() -> None:
    assert _settings(CORS_ALLOWED_ORIGINS="http://localhost:3000,*").cors_origins == [
        "http://localhost:3000",
        "*",
    ]


# ── Debug router ─────────────────────────────────────────────────────────────


def _route_paths(app) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def test_debug_router_absent_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setattr(cfg.settings, "environment", "production")
    app = create_app()
    paths = _route_paths(app)
    assert not any(p.startswith("/api/v1/debug") for p in paths)
    assert "/api/v1/health" in paths
    assert app.openapi_url is None  # docs stay off in production too
    client = TestClient(app)
    assert client.get("/api/v1/debug/config").status_code == 404
    assert client.post("/api/v1/debug/bootstrap-demo-user").status_code == 404


def test_debug_router_present_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setattr(cfg.settings, "environment", "development")
    paths = _route_paths(create_app())
    assert "/api/v1/debug/config" in paths
    assert "/api/v1/debug/bootstrap-demo-user" in paths


# ── N6: token redaction in logs ──────────────────────────────────────────────

_FAKE_TOKEN = "Zz9_fakeTokenForRedactionTest-0001"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"/api/v1/public/vbr/reports/{_FAKE_TOKEN}", f"/api/v1/public/vbr/reports/{REDACTED}"),
        (
            f"/api/v1/public/vbr/reports/{_FAKE_TOKEN}/view?x=1",
            f"/api/v1/public/vbr/reports/{REDACTED}/view?x=1",
        ),
        (
            f"/api/v1/public/vbr/legacy-reports/{_FAKE_TOKEN}",
            f"/api/v1/public/vbr/legacy-reports/{REDACTED}",
        ),
        ("/api/v1/public/passports/some-slug", "/api/v1/public/passports/some-slug"),
    ],
)
def test_redact_report_tokens(raw: str, expected: str) -> None:
    assert redact_report_tokens(raw) == expected


def test_uvicorn_access_log_record_is_redacted() -> None:
    """A record shaped exactly like uvicorn's access log line."""
    install_report_token_redaction()
    access = logging.getLogger("uvicorn.access")
    assert any(isinstance(f, ReportTokenRedactionFilter) for f in access.filters)

    handler = _ListHandler()
    access.addHandler(handler)
    old_level, access.level = access.level, logging.INFO
    try:
        access.info(
            '%s - "%s %s HTTP/%s" %d',
            "203.0.113.7:51000",
            "POST",
            f"/api/v1/public/vbr/reports/{_FAKE_TOKEN}/view",
            "1.1",
            200,
        )
    finally:
        access.removeHandler(handler)
        access.level = old_level
    assert len(handler.messages) == 1
    assert _FAKE_TOKEN not in handler.messages[0]
    assert f"/api/v1/public/vbr/reports/{REDACTED}/view" in handler.messages[0]


def test_app_request_log_through_root_handler_is_redacted() -> None:
    """Records from app.* loggers propagate to root; its handlers redact."""
    root = logging.getLogger()
    handler = _ListHandler()
    root.addHandler(handler)
    old_level = root.level
    root.setLevel(logging.INFO)
    try:
        install_report_token_redaction()
        logging.getLogger("app.some.module").warning(
            "Unhandled error on %s %s", "GET", f"/api/v1/public/vbr/legacy-reports/{_FAKE_TOKEN}"
        )
        logging.getLogger("app.main").warning(
            f"inline path /api/v1/public/vbr/reports/{_FAKE_TOKEN}"
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert len(handler.messages) == 2
    assert all(_FAKE_TOKEN not in m for m in handler.messages)


def test_install_is_idempotent() -> None:
    install_report_token_redaction()
    install_report_token_redaction()
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, ReportTokenRedactionFilter) for f in access.filters) == 1


def test_create_app_installs_redaction() -> None:
    from app.main import create_app

    access = logging.getLogger("uvicorn.access")
    access.filters = [f for f in access.filters if not isinstance(f, ReportTokenRedactionFilter)]
    create_app()
    assert any(isinstance(f, ReportTokenRedactionFilter) for f in access.filters)



# ── N6 follow-up: httpx URLs, passport access tokens, tracebacks ─────────────


def _capture(logger_name: str, level: int = logging.INFO):
    """Context manager: a filtered capture handler on ``logger_name``."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        logger = logging.getLogger(logger_name)
        handler = _ListHandler()
        handler.addFilter(ReportTokenRedactionFilter())
        old_level, old_propagate = logger.level, logger.propagate
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
        try:
            yield handler
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
            logger.propagate = old_propagate

    return _cm()


def test_httpx_request_url_with_postgrest_token_filter_is_redacted() -> None:
    """Reproduces the leak: httpx logs the Supabase URL (an httpx.URL object,
    not a str) carrying ``public_report_token=eq.<token>`` at INFO."""
    import httpx

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    url = (
        "https://example.supabase.co/rest/v1/vbr_projects"
        f"?select=%2A&public_report_token=eq.{_FAKE_TOKEN}&limit=1"
    )
    with _capture("httpx") as handler, httpx.Client(transport=transport) as http:
        http.get(url)
        http.get(f"https://example.supabase.co/rest/v1/grants?access_token=eq.{_FAKE_TOKEN}")
    assert len(handler.messages) == 2, handler.messages
    assert all(_FAKE_TOKEN not in m for m in handler.messages)
    assert f"public_report_token=eq.{REDACTED}" in handler.messages[0]
    assert "limit=1" in handler.messages[0]


def test_httpx_and_httpcore_quieted_by_create_app() -> None:
    from app.main import create_app

    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.NOTSET)
    create_app()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level == logging.WARNING


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/public/access/{_FAKE_TOKEN}/evidence",
        f"/api/v1/public/access/{_FAKE_TOKEN}/skill-evidence-timeline",
        f"/api/v1/public/access/{_FAKE_TOKEN}",
    ],
)
def test_passport_access_token_path_is_redacted(path: str) -> None:
    with _capture("app.some.module") as handler:
        logging.getLogger("app.some.module").info("GET %s", path)
    assert _FAKE_TOKEN not in handler.messages[0]
    assert f"/public/access/{REDACTED}" in handler.messages[0]


def test_non_string_arg_is_redacted() -> None:
    class _Url:
        def __str__(self) -> str:
            return f"https://api.example.test/api/v1/public/vbr/reports/{_FAKE_TOKEN}"

    with _capture("app.some.module") as handler:
        logging.getLogger("app.some.module").info("calling %s", _Url())
    assert _FAKE_TOKEN not in handler.messages[0]


def test_exception_traceback_is_redacted() -> None:
    with _capture("app.some.module") as handler:
        try:
            raise RuntimeError(
                f"lookup failed for /api/v1/public/vbr/reports/{_FAKE_TOKEN} "
                f"(public_report_token=eq.{_FAKE_TOKEN})"
            )
        except RuntimeError:
            logging.getLogger("app.some.module").exception("unhandled")
    (message,) = handler.messages
    assert "Traceback" in message and "RuntimeError" in message
    assert _FAKE_TOKEN not in message


def test_uvicorn_access_formatter_still_works_after_redaction() -> None:
    """uvicorn's AccessFormatter unpacks record.args as a 5-tuple, so the
    filter must keep that shape on the access logger."""
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.7:51000", "GET", f"/api/v1/public/access/{_FAKE_TOKEN}/export", "1.1", 200),
        None,
    )
    assert ReportTokenRedactionFilter().filter(record)
    formatted = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    ).format(record)
    assert _FAKE_TOKEN not in formatted
    assert f"/api/v1/public/access/{REDACTED}/export" in formatted
    assert "200" in formatted
