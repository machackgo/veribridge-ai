"""Redact bearer tokens from log output.

Public VBR report tokens and passport access-grant tokens are bearer secrets.
They show up in three places that reach the logs:

* request paths: ``/api/v1/public/vbr/reports/<token>``,
  ``.../public/vbr/legacy-reports/<token>`` and ``.../public/access/<token>``
  (uvicorn's access log, the app's unhandled-error log);
* PostgREST query strings the Supabase client sends through httpx, e.g.
  ``?public_report_token=eq.<token>`` (httpx logs every request URL at INFO;
  ``app.main`` also raises the httpx/httpcore loggers to WARNING);
* exception text and tracebacks that embed either of the above.

``ReportTokenRedactionFilter`` rewrites all of them to ``<redacted>`` before a
record is formatted. It is attached to the relevant loggers and to the
handlers of the root and uvicorn loggers, so records that propagate from
``app.*`` loggers are covered too. Installation is idempotent.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "<redacted>"

_PATH_TOKEN_RE = re.compile(
    r"(/public/(?:vbr/(?:reports|legacy-reports)|access)/)[^/?#&\s\"']+"
)
_QUERY_TOKEN_RE = re.compile(
    r"((?:public_report_token|public_token|access_token(?:_hash)?)=eq\.)[^&\s\"']+"
)

_REDACTED_LOGGERS = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "app.main",
    "httpx",
    "httpcore",
)

# uvicorn's AccessFormatter unpacks ``record.args`` as a fixed 5-tuple, so
# records on this logger keep their args (each one redacted) instead of being
# collapsed into a pre-formatted message.
_TUPLE_ARGS_LOGGERS = frozenset({"uvicorn.access"})

_PLAIN_FORMATTER = logging.Formatter()


def redact_report_tokens(text: str) -> str:
    """Replace bearer-token path segments and token query filters in ``text``."""
    return _QUERY_TOKEN_RE.sub(rf"\g<1>{REDACTED}", _PATH_TOKEN_RE.sub(rf"\g<1>{REDACTED}", text))


def _redact_arg(value: Any) -> Any:
    if isinstance(value, str):
        return redact_report_tokens(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    # Non-string objects (e.g. httpx.URL): replace with the redacted string
    # form only when that form actually carries a token.
    try:
        text = str(value)
    except Exception:
        return value
    redacted = redact_report_tokens(text)
    return redacted if redacted != text else value


class ReportTokenRedactionFilter(logging.Filter):
    """Rewrites tokens in a record's message, args, exception and stack text."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name in _TUPLE_ARGS_LOGGERS and isinstance(record.args, tuple):
            if isinstance(record.msg, str):
                record.msg = redact_report_tokens(record.msg)
            record.args = tuple(_redact_arg(a) for a in record.args)
        else:
            try:
                message = record.getMessage()
            except Exception:
                message = None  # malformed record: let logging report it as usual
            if message is not None:
                record.msg = redact_report_tokens(message)
                record.args = None

        if record.exc_info and not record.exc_text:
            # Pre-render the traceback so Formatter.format reuses the redacted
            # text instead of formatting the raw exception later.
            record.exc_text = _PLAIN_FORMATTER.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_report_tokens(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_report_tokens(record.stack_info)
        return True


def _ensure_filter(target: logging.Filterer) -> None:
    if not any(isinstance(f, ReportTokenRedactionFilter) for f in target.filters):
        target.addFilter(ReportTokenRedactionFilter())


def install_report_token_redaction() -> None:
    """Attach the redaction filter to the request-logging loggers and to the
    handlers currently on them and on the root logger. Safe to call repeatedly."""
    for name in _REDACTED_LOGGERS:
        logger = logging.getLogger(name)
        _ensure_filter(logger)
        for handler in logger.handlers:
            _ensure_filter(handler)
    for handler in logging.getLogger().handlers:
        _ensure_filter(handler)


def quiet_http_client_loggers() -> None:
    """httpx logs every request URL (incl. PostgREST token filters) at INFO."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


__all__ = [
    "REDACTED",
    "ReportTokenRedactionFilter",
    "install_report_token_redaction",
    "quiet_http_client_loggers",
    "redact_report_tokens",
]
