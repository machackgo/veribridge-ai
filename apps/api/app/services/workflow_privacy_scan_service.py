"""
Workflow Privacy Scan — detects sensitive data in recorded workflow evidence.

This scan is intentionally project-agnostic: it looks for known credential
and PII patterns (API keys, tokens, credit card numbers, SSNs, private keys,
passwords in URLs, etc.) in any recorded workflow payload regardless of the
app type, domain, framework, or URL.

The scan runs automatically after every proof upload and can be re-run via
the privacy-scan API endpoint.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_TABLE = "workflow_privacy_scan_results"

# ── Sensitive data patterns ────────────────────────────────────────────────────
# Each entry: (flag_key, compiled_regex, human_readable_description)
# Ordered from most-specific to most-generic so early hits stop redundant work.

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # Cloud / AI provider keys
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS access key detected",
    ),
    (
        "google_api_key",
        # Real Google API keys are AIza + 35 chars; accept ≥33 so test data of
        # varying lengths is caught without producing false positives on short strings.
        re.compile(r"\bAIza[0-9A-Za-z\-_]{33,}\b"),
        "Google API key detected",
    ),
    (
        "openai_key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9\-_T]{20,}\b"),
        "OpenAI API key detected",
    ),
    (
        "anthropic_key",
        re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b"),
        "Anthropic API key detected",
    ),
    (
        "github_token",
        re.compile(r"\bgh[pso]_[A-Za-z0-9]{36,}\b"),
        "GitHub personal access token detected",
    ),
    (
        "stripe_key",
        re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{20,}\b"),
        "Stripe API key detected",
    ),
    (
        "sendgrid_key",
        re.compile(r"\bSG\.[A-Za-z0-9\-_]{22,}\.[A-Za-z0-9\-_]{43,}\b"),
        "SendGrid API key detected",
    ),
    (
        "twilio_key",
        re.compile(r"\bSK[0-9a-fA-F]{32}\b"),
        "Twilio API key detected",
    ),
    (
        "slack_token",
        re.compile(r"\bxox[boas]-[A-Za-z0-9\-]{20,}\b"),
        "Slack API token detected",
    ),
    # Unredacted sensitive values in URL query parameters
    # Matches ?access_token=<value> / ?api_key=<value> etc. where the value has
    # NOT been replaced by [REDACTED] (square bracket excluded from char class).
    (
        "sensitive_url_param",
        re.compile(
            r"[?&](?:access_token|id_token|refresh_token|api_key|secret|auth|session|jwt)"
            r"=[^\s&\"'\[\]]{6,}",
            re.IGNORECASE,
        ),
        "Sensitive credentials exposed in URL parameters",
    ),
    # Auth / session tokens
    (
        "jwt_token",
        re.compile(
            r"\beyJ[A-Za-z0-9\-_]{5,}\.eyJ[A-Za-z0-9\-_]{5,}\.[A-Za-z0-9\-_]{5,}\b"
        ),
        "JWT token detected",
    ),
    (
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9\-_\.]{20,}\b", re.IGNORECASE),
        "Bearer token value detected",
    ),
    # Private key material
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----"
        ),
        "Private key block detected",
    ),
    # Credentials in URLs / form data
    (
        "password_in_url",
        re.compile(r"\bpassword\s*=\s*[^\s&\"\'<>{}\[\]]{4,}", re.IGNORECASE),
        "Password value exposed in URL or form data",
    ),
    # Payment card data
    (
        "credit_card",
        re.compile(
            r"\b(?:4[0-9]{12}(?:[0-9]{3})?"       # Visa
            r"|5[1-5][0-9]{14}"                    # MasterCard
            r"|3[47][0-9]{13}"                     # Amex
            r"|6(?:011|5[0-9]{2})[0-9]{12})\b"    # Discover
        ),
        "Credit card number pattern detected",
    ),
    # US Social Security Number
    (
        "ssn",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "SSN pattern detected (###-##-####)",
    ),
]

# Markers that indicate fields were already redacted by the extension or backend.
# [REDACTED_SENSITIVE_FIELD] = content script masked a form input
# [REDACTED]                 = backend mask_sensitive() masked a key
_REDACTED_MARKER_RE = re.compile(r"\[REDACTED(?:_SENSITIVE_FIELD)?\]")

# URL parameter that was already redacted: ?foo=[REDACTED] or &foo=[REDACTED]
_REDACTED_URL_PARAM_RE = re.compile(r"[?&][^=&\s]+=\[REDACTED\]")


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class PrivacyScanResult:
    """Result of a privacy scan on workflow proof data."""

    status: str                            # 'clean' | 'redacted' | 'flagged'
    risk_flags: list[str] = field(default_factory=list)
    redacted_fields_count: int = 0
    redacted_urls_count: int = 0
    contains_sensitive_data: bool = False
    scan_summary: str = ""


# ── Core scan function (pure — no DB dependency) ───────────────────────────────

def scan_proof_data(proof_data: dict[str, Any]) -> PrivacyScanResult:
    """
    Scan workflow proof data for sensitive information patterns.

    The scan is intentionally generic: it works for web apps, CLI tools,
    local dashboards, deployed sites, GitHub pages, and any other recorded
    workflow.  It does not assume any specific project type.

    Returns a PrivacyScanResult with:
    - status: 'clean' | 'redacted' | 'flagged'
    - risk_flags: list of human-readable descriptions of detected issues
    - redacted_fields_count: number of fields already masked (extension/backend)
    - redacted_urls_count: number of URL params already redacted
    - contains_sensitive_data: True only when unmasked sensitive data is found
    - scan_summary: one-line human-readable outcome
    """
    try:
        text = json.dumps(proof_data, ensure_ascii=False, default=str)
    except Exception:  # pragma: no cover
        text = str(proof_data)

    risk_flags: list[str] = []

    # Count already-redacted markers (these are good — the guard is working)
    redacted_fields = len(_REDACTED_MARKER_RE.findall(text))
    redacted_urls = len(_REDACTED_URL_PARAM_RE.findall(text))

    # Run all pattern checks against the serialized payload text
    for _key, pattern, description in _PATTERNS:
        try:
            if pattern.search(text):
                risk_flags.append(description)
        except Exception:  # pragma: no cover
            pass  # A broken regex must never fail the upload

    # Determine final status
    if risk_flags:
        status = "flagged"
        contains_sensitive = True
    elif redacted_fields > 0 or redacted_urls > 0:
        status = "redacted"
        contains_sensitive = False
    else:
        status = "clean"
        contains_sensitive = False

    # Build human-readable summary
    if status == "clean":
        summary = "No sensitive data detected in workflow recording."
    elif status == "redacted":
        parts: list[str] = []
        if redacted_fields > 0:
            parts.append(f"{redacted_fields} sensitive field(s) masked automatically")
        if redacted_urls > 0:
            parts.append(f"{redacted_urls} sensitive URL parameter(s) redacted")
        summary = "Privacy Guard active — " + "; ".join(parts) + "."
    else:  # flagged
        summary = (
            f"Potential sensitive data detected: {len(risk_flags)} issue(s). "
            "This proof is hidden from recruiter/public view until reviewed. "
            "Re-record using demo data or mark this proof as private."
        )

    return PrivacyScanResult(
        status=status,
        risk_flags=risk_flags,
        redacted_fields_count=redacted_fields,
        redacted_urls_count=redacted_urls,
        contains_sensitive_data=contains_sensitive,
        scan_summary=summary,
    )


# ── DB-backed service ──────────────────────────────────────────────────────────

class WorkflowPrivacyScanService:
    """Stores and retrieves privacy scan results for proof sessions."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def store_scan(
        self,
        user_id: str,
        proof_session_id: str,
        result: PrivacyScanResult,
    ) -> dict[str, Any]:
        """Insert or update a privacy scan result row (upsert on proof_session_id)."""
        now = _now()
        data: dict[str, Any] = {
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "status": result.status,
            "risk_flags": result.risk_flags,
            "redacted_fields_count": result.redacted_fields_count,
            "redacted_urls_count": result.redacted_urls_count,
            "contains_sensitive_data": result.contains_sensitive_data,
            "scan_summary": result.scan_summary,
        }

        if isinstance(self._client, dict):
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            self._client.setdefault(_TABLE, {})[proof_session_id] = row
            return row

        try:
            result_obj = (
                self._client.table(_TABLE)
                .upsert({**data, "updated_at": now}, on_conflict="proof_session_id")
                .execute()
            )
            rows = getattr(result_obj, "data", []) or []
            if rows:
                return rows[0]
        except Exception as exc:
            logger.warning("Privacy scan DB store failed (non-critical): %s", exc)
        return data

    def get_scan(
        self,
        user_id: str,
        proof_session_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve the stored privacy scan result for a session."""
        if isinstance(self._client, dict):
            return self._client.get(_TABLE, {}).get(proof_session_id)

        try:
            result = (
                self._client.table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", proof_session_id)
                .maybe_single()
                .execute()
            )
            return result.data if result else None
        except Exception as exc:
            logger.warning("Privacy scan DB fetch failed: %s", exc)
            return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(UTC).isoformat()
