"""Redact public report tokens from log output.

Public VBR report tokens are bearer secrets that travel in URL paths
(``/api/v1/public/vbr/reports/<token>`` and ``.../legacy-reports/<token>``).
Uvicorn's access log records every request path, so without redaction anyone
with log access could open any shared report. This filter rewrites the token
path segment to ``<redacted>`` in the log record before it is formatted.

It is attached to the uvicorn loggers and to the handlers of the root and
uvicorn loggers (so records propagated from ``app.*`` loggers are covered
too). Installation is idempotent.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "<redacted>"

_TOKEN_PATH_RE = re.compile(r"(/public/vbr/(?:reports|legacy-reports)/)[^/?#\s\"']+")

_REDACTED_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error", "app.main")


def redact_report_tokens(text: str) -> str:
    """Replace report-token path segments in ``text`` with ``<redacted>``."""
    return _TOKEN_PATH_RE.sub(rf"\g<1>{REDACTED}", text)


def _redact_value(value: Any) -> Any:
    return redact_report_tokens(value) if isinstance(value, str) else value


class ReportTokenRedactionFilter(logging.Filter):
    """Rewrites report tokens in a record's message and arguments in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_report_tokens(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact_value(a) for a in args)
        elif isinstance(args, Mapping):
            record.args = {k: _redact_value(v) for k, v in args.items()}
        return True


def _ensure_filter(target: logging.Filterer) -> None:
    if not any(isinstance(f, ReportTokenRedactionFilter) for f in target.filters):
        target.addFilter(ReportTokenRedactionFilter())


def install_report_token_redaction() -> None:
    """Attach the redaction filter to the request-logging loggers and to the
    handlers currently on the root / uvicorn loggers. Safe to call repeatedly."""
    for name in _REDACTED_LOGGERS:
        logger = logging.getLogger(name)
        _ensure_filter(logger)
        for handler in logger.handlers:
            _ensure_filter(handler)
    for handler in logging.getLogger().handlers:
        _ensure_filter(handler)


__all__ = [
    "REDACTED",
    "ReportTokenRedactionFilter",
    "install_report_token_redaction",
    "redact_report_tokens",
]
