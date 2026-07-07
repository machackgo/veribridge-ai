"""Public Safety / Recruiter Sharing Layer — the centralized public projection.

Steps 2–6 each grew their own ``public_view()`` and the public route builders
(:mod:`vbr_public_project_report`, :mod:`vbr_work_passport_service`) each grew a
local score-scrub + unsafe-field gate. The safety rules were therefore correct
but *scattered*: there was no single module a public/recruiter surface could call
to say "project this internal object into something safe to share". This module
is that single source of truth.

It does two things, both **fail-closed**:

1. **Scrub + scan** — :func:`scrub_public_payload` recursively strips
   score / ranking / rating / percentile / "fully verified" language and email
   addresses from every string in a built public payload, and
   :func:`contains_unsafe_fields` rejects the *whole* payload if any field still
   smells private (storage path, signed URL, token, raw/metadata/source_id key,
   local ``/Users/…`` path, ``file://`` URL, email, …). :func:`enforce_public_safe`
   composes them: scrub, then refuse to serve anything that still trips the scan.

2. **Explicit public projections** — ``public_safe_*`` functions turn the
   internal ``to_dict()`` shapes of Steps 2–6 (normalized evidence artifacts,
   linked proof chains, synthesis claims/results, stale/reanalysis markers, and a
   whole Work-Passport skill-report payload) into recruiter-safe dicts. Each one
   is a **whitelist**: it builds a brand-new dict containing only allowed keys,
   re-scrubs every retained string, drops every private ``source_id`` /
   ``project_id`` / ``metadata`` / raw-payload field, and gates any outbound URL
   through :func:`~app.services.safe_public_url.is_safe_public_url`. A field that
   is unknown, unsafe, or not explicitly allowed is **omitted**, never echoed.

Nothing here calls an LLM; every transform is deterministic (pure regex /
dict-whitelisting), so it is safe to run synchronously on any request path.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.project_defense_evidence_chips import _sanitize_transcript_text
from app.services.safe_public_url import safe_public_url
# Low-level, already-trusted primitives (single source of the regexes). Importing
# them here (rather than re-implementing) keeps one definition of "score-style
# fragment" / "unsafe field" so the central service can never drift from the
# route builders that have shipped with these rules.
from app.services.vbr_public_project_report import (
    _contains_unsafe_fields as _base_contains_unsafe_fields,
    _scrub_text as _scrub_score_fragments,
)
from app.services.llm_proof_synthesis_service import (
    _scrub_score_rank_language,
    TIER_STRONG,
    TIER_CORROBORATED,
    TIER_SUPPORTING,
    TIER_NEEDS_REVIEW,
    TIER_INSUFFICIENT,
)
# Single source of truth for the enum-like labels Steps 2–4 mint. Reusing the
# real constants (rather than re-spelling the strings) keeps the public-safe
# allowlists below from silently drifting from the producers — a label the
# backend stops emitting, or starts emitting, is reflected here automatically.
from app.services.evidence_normalization_service import (
    SOURCE_GITHUB,
    SOURCE_WEBSITE,
    SOURCE_DOCUMENT,
    SOURCE_DEFENSE,
    SOURCE_VIDEO,
    SOURCE_SKILL_GRAPH,
    STRENGTH_PRECISE_CODE,
    STRENGTH_RUNTIME,
    STRENGTH_SELF_EXPLANATION,
    STRENGTH_SUPPORTING_MOMENT,
    STRENGTH_REPO_LEVEL,
    STRENGTH_AGGREGATED,
    STRENGTH_CORROBORATION,
)
from app.services.website_skill_proof_focus import (
    ALLOWED_WEBSITE_EVIDENCE_CHIPS,
    ALLOWED_WEBSITE_PURPOSE_KEYS,
    ALLOWED_WEBSITE_RELEVANCE_KEYS,
    describe_website_purpose,
    describe_website_skill_relevance,
    public_screenshot_access_label,
    website_behavior_claim,
    website_corroboration_note,
    website_verification_mode_label,
    website_verification_mode_note,
    VERIFICATION_MODE_LIVE,
    VERIFICATION_MODE_RECORDED,
)
from app.services.proof_synthesis_agent_service import (
    PROOF_GITHUB,
    PROOF_WEBSITE,
    PROOF_DOCUMENT,
    PROOF_DEFENSE,
    PROOF_VIDEO,
    PROOF_SKILL_GRAPH,
)

__all__ = [
    "PublicReportUnsafeError",
    "scrub_public_text",
    "scrub_public_payload",
    "contains_unsafe_fields",
    "enforce_public_safe",
    "public_safe_skill_name",
    "public_safe_evidence_artifact",
    "public_safe_linked_chain",
    "public_safe_synthesis_claim",
    "public_safe_synthesis_result",
    "public_safe_stale_marker",
    "public_safe_skill_report",
    "public_safe_document_inspection_card",
    "defense_privacy_is_clean",
    "public_safe_defense_analysis",
    "public_safe_defense_answer_evidence",
    "DEFENSE_PRIVACY_HIDDEN_MESSAGE",
    "DEFENSE_ANSWER_WITHHELD_MESSAGE",
]

_TEXT_LIMIT = 400

# Email addresses are not caught by the canonical sensitive-data scrubber (they
# are not paths / tokens / URLs), so the public layer redacts them explicitly.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Approved opaque public id formats — the deterministic, non-leaking hashes minted
# by Steps 2–4: ``ev_<source>_<hex>`` (evidence), ``chain_<hex>`` (linked chain),
# ``claim_<hex>`` (synthesis claim). The hash bodies are lower-case hex of bounded
# length, so a raw UUID, email, ``/Users/…`` path, provider/source id, student or
# project id, or any arbitrary string is rejected — only an approved opaque id is
# ever echoed into a public citation / reference. (Mirrors the ``ev_``/``chain_``/
# ``claim_`` minting in evidence_normalization / cross_proof_linking /
# llm_proof_synthesis.)
_PUBLIC_EVIDENCE_ID_RE = re.compile(r"^ev_[a-z0-9]{2,32}_[0-9a-f]{6,40}$")
_PUBLIC_CHAIN_ID_RE = re.compile(r"^chain_[0-9a-f]{6,40}$")
_PUBLIC_CLAIM_ID_RE = re.compile(r"^claim_[0-9a-f]{6,40}$")

# Non-http(s) URI schemes the canonical scrubber (which only redacts ``http(s)``
# URLs and local paths) can leave behind — ``file://`` / ``blob:`` / ``data:`` /
# ``javascript:`` must never reach a recruiter-facing free-text field. ``data:``
# requires a real ``type/subtype`` body so the English word "data:" is untouched.
_DANGEROUS_URI_RE = re.compile(
    r"\b(?:file|blob|javascript|vbscript|ftp)://?\S*|\bdata:[\w.+-]+/[\w.+-]+\S*",
    re.IGNORECASE,
)

# ── Secret / credential material ──────────────────────────────────────────────
# Credential-bearing ``name=value`` / ``name: value`` tokens (api_key, token,
# client_secret, AWS/Azure/GCP signing params, …). The canonical scrubber only
# redacts *whole* http(s) URLs + local paths, so a bare ``api_key=sk-…`` smuggled
# into prose, or a *secret query string* hung off an otherwise-public URL, would
# otherwise survive. Matched case-insensitively; the value run stops at
# whitespace / ``&`` / quotes / angle brackets so only the secret itself (never the
# surrounding prose) is redacted.
_SECRET_KEY_NAMES = (
    r"api[_-]?keys?|access[_-]?tokens?|refresh[_-]?tokens?|id[_-]?tokens?|"
    r"auth[_-]?tokens?|bearer[_-]?tokens?|session[_-]?tokens?|csrf[_-]?tokens?|"
    r"client[_-]?secrets?|secret[_-]?keys?|service[_-]?role[_-]?keys?|"
    r"private[_-]?keys?|anon[_-]?keys?|secrets?|passwords?|passwd|pwd|tokens?|"
    r"signatures?|sig|x-amz-[\w-]+|x-goog-[\w-]+|goog-[\w-]+|keys?"
)
_SECRET_KV_RE = re.compile(
    rf"(?i)(?<![\w-])(?:{_SECRET_KEY_NAMES})\s*[=:]\s*[^\s&\"'<>]+"
)

# A standalone ``Bearer <token>`` / ``Authorization: Bearer <token>`` credential.
# The token run requires ≥6 chars so the bare English word "bearer" is untouched.
_BEARER_RE = re.compile(r"(?i)(?:authorization\s*:\s*)?\bbearer\s+[\w.\-~+/=]{6,}")

# GitHub personal-access / OAuth / app tokens (``ghp_…`` / ``gho_…`` / ``ghs_…`` /
# ``github_pat_…``) are self-identifying credentials that carry no ``key=value``
# shape, so the key=value matcher above never sees them.
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b|\bgithub_pat_[A-Za-z0-9_]{8,}\b")

# Relative storage paths (``uploads/user-123/report.pdf``) are neither absolute
# ``/Users/…`` paths, storage URLs, nor credentials, so no other matcher catches
# them. Two path segments are required (so prose like "uploads/downloads" is left
# alone), and the lookbehind skips ``…/uploads/…`` inside a legitimately public
# http(s) URL path — those are gated by the safe-url checks instead.
_RELATIVE_STORAGE_PATH_RE = re.compile(
    r"(?<![\w/])uploads?/[\w.@%-]+/[^\s\"'<>]+", re.IGNORECASE
)

# Any http(s) URL — used to strip a secret-bearing query string while keeping the
# safe base, and to scan for secret query params in the fail-closed gate.
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+", re.IGNORECASE)


def _strip_secret_query(match: re.Match[str]) -> str:
    """Drop a URL's *entire* query string when it carries credential params.

    The base (scheme + host + path) is preserved verbatim; whether that base is a
    genuinely public URL is judged elsewhere (the fail-closed scan / safe-url
    gate). The point here is only that ``…?token=secret`` never survives.
    """
    url = match.group(0)
    base, sep, query = url.partition("?")
    if sep and _SECRET_KV_RE.search(query):
        return base
    return url


def _redact_secrets(text: str) -> str:
    """Strip credential material from a string while leaving safe prose + URLs.

    In order: drop any secret-bearing query string off an http(s) URL (keeping the
    safe base), redact ``Bearer …`` credentials, then redact any remaining bare
    ``api_key=…`` / ``token=…`` / ``client_secret=…`` / signing-param token.
    """
    out = _URL_RE.sub(_strip_secret_query, text)
    out = _BEARER_RE.sub("[redacted]", out)
    out = _SECRET_KV_RE.sub("[redacted]", out)
    out = _GITHUB_TOKEN_RE.sub("[redacted]", out)
    out = _RELATIVE_STORAGE_PATH_RE.sub("[redacted]", out)
    return out


# A token that is *only* a redaction marker carries no human-readable signal, so a
# skill / project label that scrubs down to this is omitted entirely.
_REDACTION_MARKER = "redacted"

# Identifier-shaped tokens (bare UUIDs, hex blobs, ``prefix_<long-hex>`` private
# ids) are NOT redacted by the canonical scrubber — yet a raw ``user_…`` /
# ``project_…`` id or a bare UUID is exactly what must never ride out on a public
# skill label. Mirrors the matchers in ``proof_reanalysis_service``.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_BARE_HEX_ID_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
_PREFIXED_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*[_-][0-9a-fA-F]{12,}$")
# Known private-id prefixes whose suffix is a long *alphanumeric* (not just hex)
# blob — e.g. ``user_1234567890ghijkl`` / ``project_ABCXYZ1234567890``. The hex
# matcher above misses these (``g``/``h``/… are not hex), so a raw ``user_…`` /
# ``project_…`` / ``student_…`` / ``artifact_…`` / ``source_…`` / ``provider_…`` /
# ``report_…`` identifier could otherwise ride out on a public/private identity
# header. Matched case-insensitively; the suffix must be ≥12 alphanumerics so
# short human labels ("MS AI", "Machine Learning") are never caught.
_PRIVATE_ID_PREFIXES = (
    "user",
    "project",
    "student",
    "artifact",
    "source",
    "provider",
    "report",
)
_PREFIXED_ALNUM_ID_RE = re.compile(
    r"^(?:" + "|".join(_PRIVATE_ID_PREFIXES) + r")[_-][A-Za-z0-9]{12,}$",
    re.IGNORECASE,
)
_TOKEN_TRIM = " \t\r\n.,;:!?()[]{}<>\"'`"


class PublicReportUnsafeError(RuntimeError):
    """Raised by :func:`enforce_public_safe` when a payload still trips the scan.

    Routes catch this and convert it to their own fail-closed ``404`` so a
    questionable payload is never served — the same posture the inline gates in
    the route builders already use.
    """


# ── Text scrubbing ────────────────────────────────────────────────────────────


def _fragment_scrub(text: str) -> str:
    """Remove score / rank / rating / percentile / over-claim wording + emails.

    URL/path *preserving*: it never redacts ``http(s)`` links, so a legitimately
    public ``deployed_url`` survives a recursive whole-payload pass. Leaking
    paths/tokens/URLs is handled by the fail-closed :func:`contains_unsafe_fields`
    scan, not by mangling the value.
    """
    out = _scrub_score_fragments(text)  # X/100, X%, "trust score", "fully verified", rank #N
    out = _scrub_score_rank_language(out)  # rating, "N stars", "out of N", percentile
    out = _EMAIL_RE.sub("[redacted]", out)
    out = _redact_secrets(out)  # api_key=…/token=…/client_secret=…/Bearer …/?token=…
    return out


def scrub_public_text(value: Any, *, limit: int = _TEXT_LIMIT) -> str:
    """Fully scrub a single recruiter-facing free-text string.

    Applies, in order: score/rank/rating/percentile + over-claim removal, email
    redaction, then the canonical sensitive-data scrubber (storage paths, signed
    URLs, tokens, local ``/Users/…`` / ``file://`` paths, private media paths) and
    a length bound. Use for an evidence summary / claim / limitation — i.e. a
    field that should contain prose, never a raw outbound link (those go through
    :func:`~app.services.safe_public_url.safe_public_url`). Deterministic.
    """
    text = _fragment_scrub(str(value or ""))
    text = _sanitize_transcript_text(text)
    # Strip any non-http(s) scheme the canonical scrubber leaves behind (it only
    # redacts http(s) URLs + local paths), e.g. a leftover ``file://`` prefix after
    # the local-path body was redacted, or a ``blob:`` / ``data:`` / ``javascript:``.
    text = _DANGEROUS_URI_RE.sub("[redacted]", text)
    text = text.strip()
    return text[:limit].rstrip() if len(text) > limit else text


def _scrub_text_or_none(value: Any) -> str | None:
    """Scrub a free-text field, returning ``None`` when nothing survives."""
    if value is None:
        return None
    scrubbed = scrub_public_text(value)
    return scrubbed or None


def scrub_public_payload(value: Any) -> Any:
    """Recursively scrub score-style / rank / email fragments from a payload.

    Walks dicts / lists / strings, scrubbing each string with the URL-preserving
    :func:`_fragment_scrub` so any safe ``deployed_url`` survives. Keys are never
    altered, so the downstream :func:`contains_unsafe_fields` scan still sees the
    original structure. This is the recruiter-facing analogue of the route
    builders' ``_scrub_public_report`` — strengthened with rank/rating/percentile
    and email scrubbing.
    """
    if isinstance(value, str):
        return _fragment_scrub(value)
    if isinstance(value, dict):
        return {key: scrub_public_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_public_payload(item) for item in value]
    return value


# ── Unsafe-field scan (fail-closed) ───────────────────────────────────────────

# Private/internal keys that must NEVER appear in a public payload, in addition
# to the storage/token/path/id keys the route builders already reject. Normalized
# to lower-case-alnum (underscores stripped) before comparison.
_EXTRA_UNSAFE_KEYS = {
    "sourceid",
    "metadata",
    "rawmetadata",
    "rawpayload",
    "rawdata",
    "rawresponse",
    "providerresponse",
    "providerpayload",
    "providerjson",
    "providermodel",
    "providername",
    "modelconfig",
    "refreshtoken",
    "idtoken",
    "authtoken",
    "apikey",
    "apisecret",
    "secret",
    "secretkey",
    "clientsecret",
    "servicerolekey",
    "anonkey",
    "privatemediapath",
    "mediapath",
    "screenshotpath",
    "framepath",
    "framepayload",
    "domhtml",
    "domsnapshot",
    "ocrtext",
    "rawtranscript",
    "providerconfig",
}

# Extra unsafe substrings to reject on (lower-cased value match), layered on top
# of the base scanner's storage/signed-url patterns.
_EXTRA_UNSAFE_VALUE_SUBSTRINGS = (
    "/users/",
    "/home/",
    "file://",
    "data:",
    "blob:",
    "refresh_token",
    "access_token",
    "service_role",
    "-----begin",  # PEM private key blocks
)


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum() or ch == "_")


def _contains_extra_unsafe(value: Any) -> bool:
    """Strengthening scan: extra private keys + value patterns + raw emails."""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = _normalize_key(str(key))
            compact = normalized.replace("_", "")
            if normalized in _EXTRA_UNSAFE_KEYS or compact in _EXTRA_UNSAFE_KEYS:
                return True
            if _contains_extra_unsafe(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_extra_unsafe(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        if any(fragment in lowered for fragment in _EXTRA_UNSAFE_VALUE_SUBSTRINGS):
            return True
        if _EMAIL_RE.search(value):
            return True
        return False
    return False


def _contains_secret_material(value: Any) -> bool:
    """Fail-closed scan for credential material the scrubber may have missed.

    Catches bare ``api_key=…`` / ``token=…`` / ``client_secret=…`` / signing-param
    tokens, ``Bearer …`` credentials, and any http(s) URL whose *query string*
    carries a secret param (``?token=…`` / ``&X-Amz-Signature=…``). Defence in
    depth behind :func:`_redact_secrets`: even if a secret reaches the gate in a
    shape the scrubber did not rewrite, the payload is refused rather than served.
    """
    if isinstance(value, dict):
        return any(_contains_secret_material(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret_material(item) for item in value)
    if isinstance(value, str):
        if _SECRET_KV_RE.search(value) or _BEARER_RE.search(value):
            return True
        if _GITHUB_TOKEN_RE.search(value) or _RELATIVE_STORAGE_PATH_RE.search(value):
            return True
        for match in _URL_RE.finditer(value):
            _, sep, query = match.group(0).partition("?")
            if sep and _SECRET_KV_RE.search(query):
                return True
        return False
    return False


def contains_unsafe_fields(value: Any) -> bool:
    """``True`` when ``value`` still contains anything unsafe to publish.

    A strict superset of the route builders' ``_contains_unsafe_fields``: it adds
    private ``source_id`` / ``metadata`` / raw-payload / provider-config keys,
    extra value patterns (``/Users/…``, ``file://``, ``data:``/``blob:``, raw
    ``refresh_token`` / ``access_token`` / ``service_role`` mentions, PEM key
    blocks), raw email addresses, and credential material (``api_key=…`` /
    ``token=…`` / ``client_secret=…`` / ``Bearer …`` / secret-bearing URL query
    strings). Used fail-closed: a public surface refuses to serve a payload for
    which this returns ``True``.
    """
    return (
        _base_contains_unsafe_fields(value)
        or _contains_extra_unsafe(value)
        or _contains_secret_material(value)
    )


def enforce_public_safe(payload: Any) -> Any:
    """Scrub a built public payload, then refuse it if it still trips the scan.

    Returns the scrubbed payload when it is safe; raises
    :class:`PublicReportUnsafeError` otherwise so the caller can convert it into
    its own fail-closed ``404`` (never leaking *why* it was rejected).
    """
    scrubbed = scrub_public_payload(payload)
    if contains_unsafe_fields(scrubbed):
        raise PublicReportUnsafeError("public payload failed the unsafe-field scan")
    return scrubbed


# ── Small typed helpers ───────────────────────────────────────────────────────


def _looks_like_private_identifier(token: str) -> bool:
    candidate = token.strip(_TOKEN_TRIM)
    if not candidate:
        return False
    return bool(
        _UUID_RE.match(candidate)
        or _BARE_HEX_ID_RE.match(candidate)
        or _PREFIXED_ID_RE.match(candidate)
        or _PREFIXED_ALNUM_ID_RE.match(candidate)
    )


def public_safe_skill_name(value: Any) -> str | None:
    """Scrub an untrusted skill / project label before it reaches a public view.

    A skill name is meant to be a short human label ("Python", "FastAPI") but it
    is derived from upstream artifact data, so it is treated as untrusted here: we
    redact emails + sensitive fragments, then drop any token shaped like a bare
    UUID / hex blob / ``prefix_<hex>`` private id. Returns ``None`` when nothing
    human-readable survives (e.g. the label was *only* a private id).
    """
    if not value:
        return None
    scrubbed = scrub_public_text(value, limit=160)
    if not scrubbed:
        return None
    kept = [
        tok
        for tok in scrubbed.split()
        if not _looks_like_private_identifier(tok)
        and tok.strip(_TOKEN_TRIM).lower() != _REDACTION_MARKER
    ]
    cleaned = " ".join(kept).strip()
    return cleaned or None


def _is_public_safe_evidence_id(value: Any) -> bool:
    """``True`` only for an approved opaque ``ev_<source>_<hex>`` evidence id."""
    return isinstance(value, str) and bool(_PUBLIC_EVIDENCE_ID_RE.match(value))


def _is_public_safe_chain_id(value: Any) -> bool:
    """``True`` only for an approved opaque ``chain_<hex>`` chain id."""
    return isinstance(value, str) and bool(_PUBLIC_CHAIN_ID_RE.match(value))


def _is_public_safe_claim_id(value: Any) -> bool:
    """``True`` only for an approved opaque ``claim_<hex>`` claim id."""
    return isinstance(value, str) and bool(_PUBLIC_CLAIM_ID_RE.match(value))


def _public_id(value: Any, validator: Any) -> str | None:
    """Echo an identifier only when it matches an approved opaque format.

    Any raw UUID, email, path-like / provider / source / student / project id, or
    arbitrary string fails ``validator`` and is omitted (``None``) so it never
    rides out on a public citation / reference.
    """
    return value if validator(value) else None


def _safe_evidence_ids(value: Any) -> list[str]:
    """Keep only approved opaque ``ev_…`` evidence-id hashes from a citation list.

    Invalid / private citation ids (raw UUIDs, source ids, arbitrary strings) are
    dropped — the citation chip is omitted rather than echoed.
    """
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if _is_public_safe_evidence_id(v)]


def _scrub_str_list(value: Any) -> list[str]:
    """Scrub each string in a list, dropping any that scrub to empty."""
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        scrubbed = _scrub_text_or_none(item)
        if scrubbed:
            out.append(scrubbed)
    return out


def _safe_url(value: Any) -> str | None:
    """Return ``value`` only when it is a genuinely public http(s) URL."""
    return safe_public_url(value)


def _safe_scalar(value: Any) -> Any:
    """Pass through a safe scalar (bool/int/float), scrubbing any string."""
    if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
        return value
    return _scrub_text_or_none(value)


# ── Enum-like field allowlists (STRICTER than generic scrubbing) ──────────────
# Several public fields — ``source`` / ``source_type`` / ``proof_strength`` /
# ``qualitative_tier`` / ``proof_type`` / ``source_types_present`` /
# ``primary_source_type`` — are *assumed* by recruiter surfaces to be short,
# known enum labels. But each is ultimately derived from upstream artifact data,
# so a hostile or buggy producer could put ``api_key=sk-private`` / ``token=…`` /
# ``client_secret=…``, a signed URL, an email, or a raw UUID where a label
# belongs. Generic scrubbing wouldn't fully neutralise every such value, so these
# fields are held to a STRICT allowlist: a value is echoed ONLY when it exactly
# matches a known backend label; anything unknown is replaced with a neutral
# fallback (or omitted), never passed through raw.
_ALLOWED_SOURCE_TYPES = frozenset(
    {
        SOURCE_GITHUB,
        SOURCE_WEBSITE,
        SOURCE_DOCUMENT,
        SOURCE_DEFENSE,
        SOURCE_VIDEO,
        SOURCE_SKILL_GRAPH,
    }
)
# Neutral label for an unknown source — a known-safe word, never the raw value.
_SOURCE_TYPE_FALLBACK = "other"

_ALLOWED_PROOF_STRENGTHS = frozenset(
    {
        STRENGTH_PRECISE_CODE,
        STRENGTH_RUNTIME,
        STRENGTH_SELF_EXPLANATION,
        STRENGTH_SUPPORTING_MOMENT,
        STRENGTH_REPO_LEVEL,
        STRENGTH_AGGREGATED,
        STRENGTH_CORROBORATION,
    }
)
_PROOF_STRENGTH_FALLBACK = "unknown"

_ALLOWED_QUALITATIVE_TIERS = frozenset(
    {
        TIER_STRONG,
        TIER_CORROBORATED,
        TIER_SUPPORTING,
        TIER_NEEDS_REVIEW,
        TIER_INSUFFICIENT,
    }
)
# Neutral, never-inflating tier for an unknown value ("Needs review" rather than a
# corroborated/strong claim the original value can't be trusted to justify).
_QUALITATIVE_TIER_FALLBACK = TIER_NEEDS_REVIEW

# Synthesis provenance is deterministic-or-llm; an unknown value falls back to the
# conservative "deterministic" label rather than echoing the raw string.
_ALLOWED_SYNTHESIS_SOURCES = frozenset({"deterministic", "llm"})
_SYNTHESIS_SOURCE_FALLBACK = "deterministic"

# Display-label proof types for unlinked cards ("GitHub Proof", …).
_ALLOWED_PROOF_TYPES = frozenset(
    {
        PROOF_GITHUB,
        PROOF_WEBSITE,
        PROOF_DOCUMENT,
        PROOF_DEFENSE,
        PROOF_VIDEO,
        PROOF_SKILL_GRAPH,
    }
)
_PROOF_TYPE_FALLBACK = "Other"


def _safe_enum(value: Any, allowed: frozenset[str], fallback: str) -> str:
    """Echo an enum-like value only on an EXACT allowlist match, else the fallback.

    The defining property: an unknown / unsafe value (``api_key=sk-…``, a signed
    URL, an email, a raw UUID, any arbitrary string) is NEVER returned — it is
    replaced with ``fallback``, a known-safe neutral label. Stricter than the
    generic scrubber, which only redacts *recognised* secret shapes.
    """
    return value if isinstance(value, str) and value in allowed else fallback


def _safe_enum_or_none(value: Any, allowed: frozenset[str]) -> str | None:
    """Like :func:`_safe_enum` but OMIT (``None``) an unknown value.

    Used where the field is legitimately nullable (e.g. a document-only chain has
    no ``primary_source_type``), so an unknown value collapses to ``None`` rather
    than to a misleading neutral label.
    """
    return value if isinstance(value, str) and value in allowed else None


def _safe_enum_list(value: Any, allowed: frozenset[str]) -> list[str]:
    """Filter a list to known enum labels, dedup (order-preserving), drop the rest.

    Each item must exactly match the allowlist; unknown / unsafe entries
    (``token=private``, UUIDs, arbitrary strings) are dropped. Returns ``[]`` when
    nothing valid remains.
    """
    if not isinstance(value, (list, tuple)):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item in allowed and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ── Step 2 — normalized evidence artifact ─────────────────────────────────────


def public_safe_evidence_artifact(item: dict[str, Any]) -> dict[str, Any]:
    """Project a normalized evidence artifact dict to a recruiter-safe dict.

    Whitelist only. Drops the private ``source_id`` and the internal ``metadata``
    bag entirely, scrubs every retained string, gates ``public_url`` through the
    safe-public-url helper, scrubs the (untrusted) skill / project labels, and
    echoes ``evidence_id`` only when it is an approved opaque ``ev_…`` id (a raw
    UUID / source id / path / arbitrary string is omitted as ``None``).
    """
    if not isinstance(item, dict):
        return {}
    # Website semantic proof: only KEYS from the closed vocabularies survive
    # (fail-closed — anything else becomes None) and the public labels are
    # DERIVED from those vocabularies here, never echoed from the payload. The
    # relevance label interpolates only the already-scrubbed skill name.
    safe_skill = public_safe_skill_name(item.get("canonical_skill_name"))
    purpose_key = str(item.get("website_purpose_key") or "") or None
    if purpose_key not in ALLOWED_WEBSITE_PURPOSE_KEYS:
        purpose_key = None
    relevance_key = str(item.get("website_skill_relevance_key") or "") or None
    if relevance_key not in ALLOWED_WEBSITE_RELEVANCE_KEYS:
        relevance_key = None
    projected = {
        "evidence_id": _public_id(item.get("evidence_id"), _is_public_safe_evidence_id),
        "source_type": _safe_enum(
            item.get("source_type"), _ALLOWED_SOURCE_TYPES, _SOURCE_TYPE_FALLBACK
        ),
        "source_label": _scrub_text_or_none(item.get("source_label")) or "",
        "canonical_skill_name": safe_skill,
        "subskill_name": public_safe_skill_name(item.get("subskill_name")),
        "project_title": public_safe_skill_name(item.get("project_title")),
        "exact_location": _scrub_text_or_none(item.get("exact_location")),
        "safe_summary": scrub_public_text(item.get("safe_summary")),
        "proof_strength": _safe_enum(
            item.get("proof_strength"), _ALLOWED_PROOF_STRENGTHS, _PROOF_STRENGTH_FALLBACK
        ),
        "public_safe": bool(item.get("public_safe")),
        "limitations": _scrub_str_list(item.get("limitations")),
        "public_url": _safe_url(item.get("public_url")),
    }
    # Website fields appear ONLY when a validated closed-vocabulary key exists —
    # non-website artifacts never grow website-shaped keys.
    if purpose_key:
        projected["website_purpose_key"] = purpose_key
        projected["website_purpose_label"] = describe_website_purpose(purpose_key)
        # Recruiter-first behaviour claim — DERIVED from the validated purpose
        # key's closed vocabulary at projection time, never echoed from payload.
        projected["website_behavior_claim"] = website_behavior_claim(purpose_key)
    if relevance_key:
        projected["website_skill_relevance_key"] = relevance_key
        projected["website_skill_relevance_label"] = describe_website_skill_relevance(
            relevance_key, safe_skill
        )
    # Website evidence-card extras: basis chips filtered against the closed chip
    # vocabulary (a smuggled chip string is dropped) and the screenshot access
    # label re-coerced for the public surface — never a preview URL, and any
    # preview-shaped label collapses to the permission-gated status.
    chips = [
        str(c)
        for c in (item.get("website_evidence_chips") or [])
        if str(c) in ALLOWED_WEBSITE_EVIDENCE_CHIPS
    ]
    if chips:
        projected["website_evidence_chips"] = chips
    if purpose_key or chips:
        available = bool(item.get("website_screenshot_available"))
        projected["website_screenshot_available"] = available
        projected["website_screenshot_access_label"] = public_screenshot_access_label(
            item.get("website_screenshot_access_label"), screenshot_available=available
        )
        # Recruiter verification mode — DERIVED here from whether a revalidated
        # safe public URL survived (``projected["public_url"]``); never echoed
        # from the payload. A local/private host is stripped by ``_safe_url`` and
        # so always projects as recorded-replay-only. Copy is closed vocabulary.
        mode = (
            VERIFICATION_MODE_LIVE
            if projected.get("public_url")
            else VERIFICATION_MODE_RECORDED
        )
        projected["website_verification_mode"] = mode
        projected["website_verification_mode_label"] = website_verification_mode_label(mode)
        projected["website_verification_note"] = website_verification_mode_note(mode)
        projected["website_deployment_recommended"] = mode == VERIFICATION_MODE_RECORDED
        # Cross-proof corroboration: BOOLEANS only, with the public note
        # RE-DERIVED from those booleans through the closed fragments — any
        # note text in the payload is ignored, never echoed.
        gh = bool(item.get("website_corroborates_github"))
        dfn = bool(item.get("website_corroborates_defense"))
        doc = bool(item.get("website_corroborates_document"))
        if gh or dfn or doc:
            projected["website_corroborates_github"] = gh
            projected["website_corroborates_defense"] = dfn
            projected["website_corroborates_document"] = doc
            projected["website_corroboration_note"] = website_corroboration_note(
                has_github=gh, has_defense=dfn, has_document=doc
            )
    return projected


# ── Step 3 — linked proof chain ───────────────────────────────────────────────


# The documented, recruiter-safe fields of a proof-strength summary (Step 3's
# ``_strength_summary`` in cross_proof_linking_service). A STRICT allowlist:
# any other key — e.g. a smuggled ``owner`` carrying a UUID — is dropped, never
# echoed. ``label`` is scrubbed prose, ``strengths_present`` a known-label list,
# the ``has_*`` / ``repo_level_only`` fields booleans, and
# ``corroborating_document_count`` a non-negative int.
_STRENGTH_SUMMARY_BOOL_FIELDS = (
    "has_precise_code",
    "has_runtime_behavior",
    "has_self_explanation",
    "has_supporting_moment",
    "repo_level_only",
)

# The known qualitative strength labels Step 2 mints (evidence_normalization /
# workflow_sequence_analysis). ``strengths_present`` may contain ONLY these — any
# other string (a UUID, an email, an arbitrary value) is scrubbed out.
_KNOWN_STRENGTH_LABELS = {
    "precise_code",
    "runtime_behavior",
    "self_explanation",
    "supporting_moment",
    "repo_level",
    "aggregated",
    "corroboration",
    "insufficient",
}


def _safe_strength_labels(value: Any) -> list[str]:
    """Keep only known qualitative strength labels from a list (drop the rest)."""
    if not isinstance(value, (list, tuple)):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip().lower() in _KNOWN_STRENGTH_LABELS
    ]


def _safe_count(value: Any) -> int:
    """Coerce to a safe non-negative int; anything else (bool/str/None) → 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value >= 0 else 0


def _safe_strength_summary(value: Any) -> dict[str, Any]:
    """Project a proof-strength summary through a STRICT allowlist.

    Only the documented qualitative fields survive; every other key (e.g. a
    smuggled ``owner`` carrying a UUID under an innocent-looking name) is dropped
    rather than passed through. ``label`` is scrubbed prose, ``strengths_present``
    keeps only known strength labels, the ``has_*`` / ``repo_level_only`` fields
    stay booleans, and ``corroborating_document_count`` is coerced to a safe
    non-negative int.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}

    label = _scrub_text_or_none(value.get("label"))
    if label:
        out["label"] = label

    if "strengths_present" in value:
        out["strengths_present"] = _safe_strength_labels(value.get("strengths_present"))

    for field in _STRENGTH_SUMMARY_BOOL_FIELDS:
        if field in value:
            out[field] = bool(value.get(field))

    if "corroborating_document_count" in value:
        out["corroborating_document_count"] = _safe_count(
            value.get("corroborating_document_count")
        )

    return out


def public_safe_linked_chain(chain: dict[str, Any]) -> dict[str, Any]:
    """Project a linked proof chain dict to a recruiter-safe dict.

    Drops the private ``project_id``; echoes ``chain_id`` only when it is an
    approved opaque ``chain_…`` id (else ``None``); keeps only approved ``ev_…``
    ids in ``linked_evidence_ids``; scrubs every connection reason, label, and
    limitation; and projects each member artifact through
    :func:`public_safe_evidence_artifact`, dropping any member whose
    ``public_safe`` is not truthy (fail-closed).
    """
    if not isinstance(chain, dict):
        return {}
    return {
        "chain_id": _public_id(chain.get("chain_id"), _is_public_safe_chain_id),
        "project_title": public_safe_skill_name(chain.get("project_title")),
        "canonical_skill_name": public_safe_skill_name(chain.get("canonical_skill_name")),
        "chain_label": _scrub_text_or_none(chain.get("chain_label")) or "",
        "linked_evidence_ids": _safe_evidence_ids(chain.get("linked_evidence_ids")),
        "source_types_present": _safe_enum_list(
            chain.get("source_types_present"), _ALLOWED_SOURCE_TYPES
        ),
        "primary_source_type": _safe_enum_or_none(
            chain.get("primary_source_type"), _ALLOWED_SOURCE_TYPES
        ),
        "connection_reasons": _scrub_str_list(chain.get("connection_reasons")),
        "proof_strength_summary": _safe_strength_summary(chain.get("proof_strength_summary")),
        "limitations": _scrub_str_list(chain.get("limitations")),
        "public_safe": bool(chain.get("public_safe")),
        "evidence": [
            public_safe_evidence_artifact(e)
            for e in (chain.get("evidence") or [])
            if isinstance(e, dict) and e.get("public_safe")
        ],
    }


# ── Step 4 — synthesis claim / result ─────────────────────────────────────────


def public_safe_synthesis_claim(claim: dict[str, Any]) -> dict[str, Any]:
    """Project one synthesis claim to a recruiter-safe dict (cited ids only)."""
    if not isinstance(claim, dict):
        return {}
    return {
        "claim_id": _public_id(claim.get("claim_id"), _is_public_safe_claim_id),
        "claim": scrub_public_text(claim.get("claim")),
        "supporting_evidence_ids": _safe_evidence_ids(claim.get("supporting_evidence_ids")),
        "why_connected": scrub_public_text(claim.get("why_connected")),
        "limitations": _scrub_str_list(claim.get("limitations")),
        "qualitative_tier": _safe_enum(
            claim.get("qualitative_tier"),
            _ALLOWED_QUALITATIVE_TIERS,
            _QUALITATIVE_TIER_FALLBACK,
        ),
        "public_safe": bool(claim.get("public_safe")),
    }


def _safe_synthesis_claims(value: Any) -> list[dict[str, Any]]:
    """Project + filter synthesis claims for a public result.

    A claim is kept only when it is itself marked ``public_safe`` AND retains at
    least one valid public evidence citation after strict ID validation. A claim
    whose every ``supporting_evidence_id`` was rejected (raw UUID / source id /
    arbitrary string) is dropped — an unsupported public claim, asserting a skill
    with no citation a recruiter could trace, is never shown.
    """
    if not isinstance(value, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for claim in value:
        if not isinstance(claim, dict) or not claim.get("public_safe"):
            continue
        projected = public_safe_synthesis_claim(claim)
        if not projected.get("supporting_evidence_ids"):
            continue
        out.append(projected)
    return out


_NO_PUBLIC_SYNTHESIS_SUMMARY = (
    "No public-safe synthesis claims are available for this proof chain."
)
_NO_PUBLIC_SYNTHESIS_LIMITATION = (
    "Public-safe cited synthesis claims were unavailable, so no overall summary "
    "is shown for this proof chain."
)


def public_safe_synthesis_result(result: dict[str, Any]) -> dict[str, Any]:
    """Project one chain's synthesis result to a recruiter-safe dict.

    Drops any private project id, scrubs the prose, and keeps only the claims that
    are themselves marked public-safe AND still carry at least one valid public
    evidence citation after ID validation (claims left without any citation are
    dropped via :func:`_safe_synthesis_claims`).

    When *every* claim is dropped, the original ``overall_summary`` is **not**
    exposed: it can restate the same unsupported assertion as the dropped claims
    without a single public citation a recruiter could trace. In that case the
    summary is replaced with neutral language and a limitation is appended
    explaining that public-safe cited claims were unavailable. When at least one
    valid cited claim remains, the scrubbed summary is retained as before.
    """
    if not isinstance(result, dict):
        return {}
    claims = _safe_synthesis_claims(result.get("claims"))
    limitations = _scrub_str_list(result.get("limitations"))
    if claims:
        overall_summary = scrub_public_text(result.get("overall_summary"))
    else:
        # No public-safe cited claim survived — never surface the original prose,
        # which may assert a skill with no traceable public evidence.
        overall_summary = _NO_PUBLIC_SYNTHESIS_SUMMARY
        if _NO_PUBLIC_SYNTHESIS_LIMITATION not in limitations:
            limitations.append(_NO_PUBLIC_SYNTHESIS_LIMITATION)
    return {
        "chain_id": _public_id(result.get("chain_id"), _is_public_safe_chain_id),
        "canonical_skill_name": public_safe_skill_name(result.get("canonical_skill_name")),
        "project_title": public_safe_skill_name(result.get("project_title")),
        "claims": claims,
        "overall_summary": overall_summary,
        "limitations": limitations,
        "public_safe": bool(result.get("public_safe")),
        "source": _safe_enum(
            result.get("source"), _ALLOWED_SYNTHESIS_SOURCES, _SYNTHESIS_SOURCE_FALLBACK
        ),
    }


# ── Step 6 — stale / reanalysis marker ────────────────────────────────────────


def public_safe_stale_marker(marker: dict[str, Any]) -> dict[str, Any] | None:
    """Project one stale-evidence marker to a recruiter-safe dict (or omit it).

    Fail-closed: a marker explicitly flagged ``public_safe=False`` is omitted
    entirely (returns ``None``) so a not-for-public marker never rides out on a
    recruiter surface. Otherwise drops the private ``project_id``, scrubs the
    (untrusted) skill name, validates ``evidence_id`` to an approved opaque id,
    and scrubs the reason / recommended-action prose.
    """
    if not isinstance(marker, dict):
        return None
    if marker.get("public_safe") is False:
        return None
    return {
        "evidence_id": _public_id(marker.get("evidence_id"), _is_public_safe_evidence_id),
        "reason": scrub_public_text(marker.get("reason")),
        "recommended_action": scrub_public_text(marker.get("recommended_action")),
        "source_type": _safe_enum(
            marker.get("source_type"), _ALLOWED_SOURCE_TYPES, _SOURCE_TYPE_FALLBACK
        ),
        "skill_name": public_safe_skill_name(marker.get("skill_name")),
    }


# ── Work Passport skill-report payload ────────────────────────────────────────


# Known evidence-source names allowed as public ``source_coverage`` keys. An
# arbitrary key — an email, a UUID, or any private identifier used as a map key —
# is dropped rather than echoed (matched case-insensitively via ``_normalize_key``
# so the producer's capitalised "GitHub"/"Website"/… still pass).
_ALLOWED_SOURCE_COVERAGE_KEYS = {
    "github",
    "website",
    "document",
    "defense",
    "video",
    "skill_graph",
    "other",
}


def _safe_source_coverage(value: Any) -> dict[str, bool]:
    """Whitelist known evidence-source coverage keys; booleans-only values.

    Only the known source names survive; any other key (a private identifier or
    email smuggled in as a key) is dropped, and every value is coerced to a plain
    boolean so a raw string / dict can never ride out under a coverage key.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, bool] = {}
    for key, present in value.items():
        if _normalize_key(str(key)) in _ALLOWED_SOURCE_COVERAGE_KEYS:
            out[str(key)] = bool(present)
    return out


def _public_unlinked_card(card: dict[str, Any]) -> dict[str, Any]:
    """Project one unlinked supporting-evidence card to a safe dict (no source_id)."""
    if not isinstance(card, dict):
        return {}
    return {
        "proof_type": _safe_enum(
            card.get("proof_type"), _ALLOWED_PROOF_TYPES, _PROOF_TYPE_FALLBACK
        ),
        "title": public_safe_skill_name(card.get("title")) or "",
        "safe_summary": scrub_public_text(card.get("safe_summary")),
        "safe_location": _scrub_text_or_none(card.get("safe_location")),
        "corroborates": _scrub_text_or_none(card.get("corroborates")) or "",
        "limitation": _scrub_text_or_none(card.get("limitation")) or "",
    }


def public_safe_skill_report(report: dict[str, Any]) -> dict[str, Any]:
    """Project a Work-Passport skill-report payload to a recruiter-safe shape.

    The internal skill report (``collect_skill_report`` /
    ``synthesize_skill_report``) carries rich, project-anchored ``proof_chains``
    plus the Step 3 ``linked_proof_chains`` and Step 4 ``llm_synthesis``. The
    public projection exposes ONLY:

    * the (scrubbed) skill name and synthesis summary,
    * the boolean ``source_coverage`` map (no counts/scores),
    * the linked proof chains marked ``public_safe`` (via
      :func:`public_safe_linked_chain`),
    * the synthesis results marked ``public_safe`` (via
      :func:`public_safe_synthesis_result`),
    * a capped, safe ``unlinked_supporting_evidence`` bucket, and
    * scrubbed limitations.

    Fail-closed: any linked chain or synthesis result whose ``public_safe`` is not
    truthy is dropped here (synthesis *claims* and nested *evidence* are likewise
    dropped by their projections), so a section becomes a safe empty list rather
    than leaking an unsafe item. The rich internal ``proof_chains`` (which still
    carry private source_ids and raw per-source fields) are intentionally
    dropped — the linked chains are the public, citation-safe representation. The
    result is run through :func:`enforce_public_safe` so it fail-closes on
    anything that slips through.
    """
    if not isinstance(report, dict):
        return {}

    safe_coverage = _safe_source_coverage(report.get("source_coverage"))

    unlinked = report.get("unlinked_supporting_evidence") or {}
    unlinked_items = unlinked.get("items") if isinstance(unlinked, dict) else None

    projected = {
        "skill": public_safe_skill_name(report.get("skill")),
        "synthesis_summary": scrub_public_text(report.get("synthesis_summary")),
        "source_coverage": safe_coverage,
        "linked_proof_chains": [
            public_safe_linked_chain(c)
            for c in (report.get("linked_proof_chains") or [])
            if isinstance(c, dict) and c.get("public_safe")
        ],
        "synthesis": [
            public_safe_synthesis_result(s)
            for s in (report.get("llm_synthesis") or [])
            if isinstance(s, dict) and s.get("public_safe")
        ],
        "unlinked_supporting_evidence": {
            "items": [
                _public_unlinked_card(card)
                for card in (unlinked_items or [])
                if isinstance(card, dict)
            ],
            "count": int(unlinked.get("count", 0) or 0) if isinstance(unlinked, dict) else 0,
            "more_count": int(unlinked.get("more_count", 0) or 0)
            if isinstance(unlinked, dict)
            else 0,
        },
        "limitations": _scrub_str_list(report.get("limitations")),
    }
    return enforce_public_safe(projected)


# Public replacement note shown on a Document Proof inspection card when the
# document is not intentionally share-safe — recruiters see the locator + reason,
# never the excerpt, and there is no download button.
_PUBLIC_DOC_PRIVATE_ACCESS_NOTE = (
    "Original document is private. Recruiters see verified excerpts and locators only."
)


def public_safe_document_inspection_card(card: Any) -> dict[str, Any] | None:
    """Project a Document Proof inspection card to a recruiter-safe shape, fail-closed.

    The private card (built by ``_build_document_inspection_card``) already avoids
    raw text / paths / signed URLs / internal ids. This projection additionally:

    * STRIPS ``safe_snippet`` unless the card is explicitly ``is_public_safe`` —
      recruiters otherwise see only the locator (page/section/citation/figure) and
      the why-supported reason, never the document excerpt;
    * DISABLES download — ``can_download_document`` is forced ``False`` and both
      URLs to ``None`` unless the card explicitly allows download AND carries a URL
      that survives :func:`safe_public_url`; when disabled the access note is
      replaced with a neutral "document is private" message;
    * scrubs every free-text field and echoes only the documented safe fields, so
      no internal id / path / provider JSON can ride out.

    Returns ``None`` for a ``None`` / non-dict card.
    """
    if not isinstance(card, dict):
        return None

    is_public_safe = bool(card.get("is_public_safe"))
    # Snippet is owner-only unless explicitly public-safe.
    safe_snippet = _scrub_text_or_none(card.get("safe_snippet")) if is_public_safe else None

    # Download stays closed unless BOTH explicit consent AND a genuinely safe URL.
    download_url = safe_public_url(card.get("document_download_url")) if card.get("can_download_document") else None
    open_url = safe_public_url(card.get("document_open_url")) if card.get("can_download_document") else None
    can_download = bool(card.get("can_download_document")) and bool(download_url or open_url)
    access_note = (
        _scrub_text_or_none(card.get("access_note")) or ""
        if can_download
        else _PUBLIC_DOC_PRIVATE_ACCESS_NOTE
    )

    # Skill-specific detail lists ARE recruiter-safe (bounded, normalized claims —
    # not the raw excerpt, which stays owner-only). Each entry is still scrubbed of
    # any path/URL/score fragment, dropped if nothing survives, and capped.
    def _public_detail_list(value: Any) -> list[str]:
        out: list[str] = []
        for entry in value if isinstance(value, list) else []:
            scrubbed = scrub_public_text(entry)
            if scrubbed and scrubbed not in out:
                out.append(scrubbed)
            if len(out) >= 5:
                break
        return out

    page = card.get("page_number")
    projected = {
        "title": scrub_public_text(card.get("title")),
        "source_type": _scrub_text_or_none(card.get("source_type")),
        "status": _scrub_text_or_none(card.get("status")),
        "matched_skill": public_safe_skill_name(card.get("matched_skill")),
        "project_title": public_safe_skill_name(card.get("project_title")),
        "evidence_role": scrub_public_text(card.get("evidence_role")) or "Supporting evidence",
        "page_number": page if isinstance(page, int) else None,
        "section_label": _scrub_text_or_none(card.get("section_label")),
        "citation_label": _scrub_text_or_none(card.get("citation_label")),
        "safe_snippet": safe_snippet,
        "figure_reference": _scrub_text_or_none(card.get("figure_reference")),
        "table_reference": _scrub_text_or_none(card.get("table_reference")),
        "diagram_reference": _scrub_text_or_none(card.get("diagram_reference")),
        "visual_or_table_summary": _scrub_text_or_none(card.get("visual_or_table_summary")),
        "why_supported": scrub_public_text(card.get("why_supported")),
        "corroborates": _scrub_text_or_none(card.get("corroborates")),
        "limitation": scrub_public_text(card.get("limitation")),
        "skill_specific_claims": _public_detail_list(card.get("skill_specific_claims")),
        "technical_details": _public_detail_list(card.get("technical_details")),
        "api_endpoints": _public_detail_list(card.get("api_endpoints")),
        "request_response_details": _public_detail_list(card.get("request_response_details")),
        "architecture_details": _public_detail_list(card.get("architecture_details")),
        "implementation_hints": _public_detail_list(card.get("implementation_hints")),
        "missing_detail_note": _scrub_text_or_none(card.get("missing_detail_note")),
        "has_skill_specific_details": bool(card.get("has_skill_specific_details")),
        "access_note": access_note,
        # Download stays disabled publicly; the label/note explain the private state.
        "document_access_label": _scrub_text_or_none(card.get("document_access_label"))
        if can_download
        else None,
        "document_access_note": access_note,
        "can_download_document": can_download,
        "document_download_url": download_url,
        "document_open_url": open_url,
        "is_public_safe": is_public_safe,
        "is_attached_to_project": bool(card.get("is_attached_to_project")),
    }
    return projected


# ── Project Defense analysis (privacy fail-closed) ────────────────────────────
#
# A Project Defense analysis is built from the student's spoken/written
# transcript. Even after the numeric scores are mapped to qualitative labels for
# the report, its ``transcript_summary`` is composed from the *first sentence of
# the raw transcript* — so it can carry whatever private data (SSNs, addresses,
# secrets) the student happened to say. When the transcript's privacy review does
# NOT come back clean, none of that transcript-derived text may reach a public
# recruiter surface. This is the single fail-closed projection every public
# builder must route a defense analysis through, so a flagged transcript can
# never leak its summary / first sentence / answer text again.

# Public replacement wording shown when a Project Defense happened but its answer
# content is withheld because privacy review did not pass. Carries NO
# transcript-derived text of any kind.
DEFENSE_PRIVACY_HIDDEN_MESSAGE = (
    "Project Defense was completed, but answer content is hidden from the public "
    "report because privacy review did not pass."
)

# Explicit boolean flags a producer may set to mark a defense analysis as
# privacy-sensitive / hidden even when the status string is absent. Any truthy one
# forces the fail-closed path.
_DEFENSE_PRIVACY_UNSAFE_FLAGS = (
    "privacy_flagged",
    "sensitive",
    "sensitive_data",
    "contains_sensitive_data",
    "hidden",
    "is_hidden",
    "transcript_hidden",
    "privacy_hidden",
)

# The ONLY explicit statuses that mark a Project Defense transcript as safe to
# share publicly. Everything else — a non-clean status ("flagged" / "redacted" /
# "sensitive" / …), an unrecognized string, an empty / ``None`` status, or a
# missing status key — is fail-closed to NOT shareable. This is the allowlist that
# closes the fail-open gap where a legacy or malformed analysis with no explicit
# status could publish its transcript-derived sensitive summary. (The transcript
# scanner only ever emits "clean" / "redacted" / "flagged"; only "clean" is safe —
# a "redacted" scan means sensitive data was present in the raw transcript the
# summary is built from.)
_DEFENSE_PRIVACY_CLEAN_STATUSES = frozenset({"clean"})

# Fixed, neutral status echoed on a WITHHELD public defense projection. The raw /
# internal ``privacy_scan_status`` is NEVER copied into public output (it could
# carry arbitrary or hostile producer text); the public surface only ever sees
# this single allowlisted value.
_DEFENSE_PRIVACY_WITHHELD_STATUS = "withheld"


def defense_privacy_is_clean(analysis: Any) -> bool:
    """``True`` only when a Project Defense analysis EXPLICITLY passed privacy review.

    Fail-closed: the ``privacy_scan_status`` must be present AND an exact match for
    an allowlisted clean status (:data:`_DEFENSE_PRIVACY_CLEAN_STATUSES`). A status
    that is missing, ``None``, empty, or unrecognized (e.g. ``"flagged"`` /
    ``"redacted"`` / ``"sensitive"`` / ``"needs_review"`` / an arbitrary string) is
    treated as NOT shareable, as is any truthy privacy / sensitive / hidden flag.
    This closes the fail-open gap where a legacy or malformed analysis carrying no
    explicit status could publish its transcript-derived summary.

    A ``None`` / non-dict analysis is **not** clean: it is a missing/malformed
    analysis object, which carries NO explicit clean/shareable status. Returning
    ``False`` here fails closed so that any orphaned transcript-derived artifacts
    (Project Defense / Video evidence chips and traces) that exist WITHOUT a clean
    analysis object are withheld by the caller — only an explicit clean analysis
    may unlock them.
    """
    if not isinstance(analysis, dict):
        return False
    raw_status = analysis.get("privacy_scan_status")
    status = raw_status.strip().lower() if isinstance(raw_status, str) else ""
    if status not in _DEFENSE_PRIVACY_CLEAN_STATUSES:
        return False
    if any(analysis.get(flag) for flag in _DEFENSE_PRIVACY_UNSAFE_FLAGS):
        return False
    return True


# Neutral qualitative label used for every assessment field when the defense is
# withheld — nothing about the flagged transcript's analysis is exposed.
_DEFENSE_HIDDEN_LABEL = "Not assessed"


def public_safe_defense_analysis(analysis: Any) -> dict[str, Any] | None:
    """Project a Project Defense analysis to a recruiter-safe dict, fail-closed.

    When the privacy review is not clean (see :func:`defense_privacy_is_clean`),
    ALL transcript-derived content — ``transcript_summary`` (built from the raw
    transcript's first sentence), recruiter / answer summaries, skill lists, risk
    flags, and every qualitative label derived from the flagged transcript — is
    dropped. The free-text fields are replaced with a single fixed placeholder
    that names no answer content, the list fields are emptied, and the labels are
    reset to a neutral value. When the review is clean, the analysis dict is
    returned unchanged so the caller's normal scrub + fail-closed gate handles it
    as before.

    The returned shape only ever uses the documented report-safe defense fields
    (matching ``VBRReportProjectDefenseAnalysis``) so it slots straight into the
    public report response without leaking or introducing unexpected keys. The raw
    internal ``privacy_scan_status`` is NEVER echoed publicly — the withheld
    projection always reports the fixed, neutral
    :data:`_DEFENSE_PRIVACY_WITHHELD_STATUS` so arbitrary / hostile producer status
    text can never ride out on the public surface.

    Returns ``None`` for a ``None`` / non-dict analysis (no defense to show).
    """
    if not isinstance(analysis, dict):
        return None
    if defense_privacy_is_clean(analysis):
        return analysis
    return {
        # transcript_summary is REPLACED with safe placeholder wording — it must
        # never carry the raw transcript's first sentence for a flagged defense.
        "transcript_summary": DEFENSE_PRIVACY_HIDDEN_MESSAGE,
        "skills_mentioned": [],
        "skills_explained_well": [],
        "skills_missing_from_explanation": [],
        "overall_assessment": _DEFENSE_HIDDEN_LABEL,
        "explanation_clarity": _DEFENSE_HIDDEN_LABEL,
        "ownership_signal": _DEFENSE_HIDDEN_LABEL,
        "technical_depth": _DEFENSE_HIDDEN_LABEL,
        "consistency_with_evidence": _DEFENSE_HIDDEN_LABEL,
        "risk_flags": [],
        "recruiter_summary": DEFENSE_PRIVACY_HIDDEN_MESSAGE,
        "recommended_improvements": [],
        # Fixed neutral value — never the raw/internal status string.
        "privacy_scan_status": _DEFENSE_PRIVACY_WITHHELD_STATUS,
    }


# ── Project Defense Answer Evidence (privacy fail-closed) ─────────────────────
#
# Claim-level answer evidence objects (``defense_answer_evidence_service``) are
# built from the SAME transcript the defense analysis is built from: their
# ``safe_answer_summary`` is answer-derived text. They may therefore reach a
# public recruiter surface only when the defense analysis EXPLICITLY passed
# privacy review (:func:`defense_privacy_is_clean`) AND the individual object is
# marked shareable. Everything else fails closed to a fixed withheld card that
# carries no answer-derived text, no internal IDs, and no raw status strings.

# Fixed public wording for a withheld answer evidence card. Names no answer
# content and no reason beyond the privacy review outcome.
DEFENSE_ANSWER_WITHHELD_MESSAGE = (
    "This Project Defense answer is hidden from the public report because "
    "privacy review did not pass."
)

_ANSWER_WITHHELD_STATUS = "Withheld for privacy"

# Bound the public list so a hostile/inflated telemetry blob cannot balloon the
# public payload.
_MAX_PUBLIC_ANSWER_EVIDENCE = 12

# Taxonomy allowlists — public cards only ever echo these fixed vocabulary
# values, never arbitrary producer strings.
_ALLOWED_QUESTION_KINDS = frozenset(
    {
        "architecture_explanation",
        "implementation_explanation",
        "contribution_explanation",
        "skill_explanation",
        "website_behavior_explanation",
        "document_explanation",
        "challenge_debugging",
        "tradeoff_decision",
        "evaluation_result",
        "improvement_next_step",
        "unknown_or_generic",
    }
)
_ALLOWED_CLAIM_TYPES = frozenset(
    {
        "project_architecture",
        "personal_contribution",
        "skill_understanding",
        "implementation_reasoning",
        "runtime_behavior_explanation",
        "document_claim_explanation",
        "challenge_resolution",
        "tradeoff_reasoning",
        "evaluation_interpretation",
        "future_improvement",
    }
)
_ALLOWED_EVIDENCE_ROLES = frozenset(
    {
        "candidate_explanation",
        "implementation_explanation_context",
        "runtime_behavior_explanation_context",
        "document_corroboration_context",
        "process_reflection",
        "challenge_tradeoff_context",
        "generic_project_context",
        "insufficient_or_generic",
    }
)
_ALLOWED_ANSWER_STATUSES = frozenset(
    {
        "Explained with evidence",
        "Partially explained",
        "Generic explanation",
        "Not explained",
        "Needs review",
        _ANSWER_WITHHELD_STATUS,
    }
)
# Fixed basis-chip vocabulary (see ``defense_answer_evidence_service``).
_ALLOWED_BASIS_CHIPS = frozenset(
    {
        "Targeted question",
        "Candidate answer",
        "Project skill claim",
        "Attached GitHub proof",
        "Attached Website proof",
        "Attached Document proof",
        "Challenge/tradeoff explanation",
        "Privacy-safe summary",
    }
)


def _withheld_answer_evidence_card(item: dict[str, Any], index: int) -> dict[str, Any]:
    """Fixed, neutral public card for one withheld answer evidence object.

    Keeps only the deterministic, non-transcript-derived structure (a stable
    safe id and the question kind, which comes from the generated question's
    ``target_ref`` — never from the answer). Everything answer-derived is
    dropped; free text is the fixed withheld message.
    """
    kind = str(item.get("question_kind") or "")
    return {
        "evidence_id_safe": f"defense-answer-{index}",
        "question_kind": kind if kind in _ALLOWED_QUESTION_KINDS else "unknown_or_generic",
        "question_text": None,
        "target_ref_label_safe": None,
        "mapped_skill": None,
        "claim_type": "project_architecture",
        "answer_purpose": "unknown_or_generic",
        "evidence_role": "insufficient_or_generic",
        "qualitative_status": _ANSWER_WITHHELD_STATUS,
        "safe_answer_summary": DEFENSE_ANSWER_WITHHELD_MESSAGE,
        "evidence_basis_chips": [],
        "corroborates_github": False,
        "corroborates_website": False,
        "corroborates_document": False,
        "limitation": DEFENSE_ANSWER_WITHHELD_MESSAGE,
        # Fixed neutral value — never the raw/internal status string.
        "privacy_status": _DEFENSE_PRIVACY_WITHHELD_STATUS,
    }


def _safe_vocab(value: Any, allowed: frozenset[str], fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else fallback


# Deterministic public wording per question kind. The public surface NEVER
# echoes the candidate's answer text — not even sanitized (the same rule that
# strips ``answer_excerpt`` from public evidence traces). A public card only
# ever *describes* the explanation and its corroboration.
_PUBLIC_ANSWER_KIND_WORDING: dict[str, str] = {
    "architecture_explanation": "The candidate explained the project architecture in their own words.",
    "implementation_explanation": (
        "The candidate explained the implementation approach behind this claim in a targeted defense answer."
    ),
    "contribution_explanation": "The candidate described their personal contribution in their own words.",
    "skill_explanation": "The candidate explained this claimed skill in a targeted defense answer.",
    "website_behavior_explanation": (
        "The candidate explained the live website behavior in a targeted defense answer."
    ),
    "document_explanation": (
        "The candidate explained the attached document's claim in a targeted defense answer."
    ),
    "challenge_debugging": "The candidate explained a technical challenge and how they addressed it.",
    "tradeoff_decision": "The candidate explained a design tradeoff decision in their own words.",
    "evaluation_result": "The candidate explained the project's evaluation results in their own words.",
    "improvement_next_step": "The candidate described what they would improve next.",
    "unknown_or_generic": "The candidate provided a general project explanation.",
}

_PUBLIC_ANSWER_GENERIC_WORDING = (
    "The answer was generic, so it is treated as project context only."
)


def _public_answer_summary(
    kind: str,
    mapped_skill: str | None,
    status: str,
    corroborates_github: bool,
    corroborates_website: bool,
    corroborates_document: bool,
) -> str:
    """Fixed, derived public summary for one clean answer evidence card.

    Composed ONLY from the deterministic taxonomy + corroboration flags — no
    transcript/answer-derived text ever reaches this string.
    """
    parts: list[str] = []
    base = _PUBLIC_ANSWER_KIND_WORDING.get(kind, _PUBLIC_ANSWER_KIND_WORDING["unknown_or_generic"])
    if mapped_skill and kind == "skill_explanation":
        base = f"The candidate explained their {mapped_skill} skill claim in a targeted defense answer."
    parts.append(base)
    if status in ("Generic explanation", "Not explained"):
        parts.append(_PUBLIC_ANSWER_GENERIC_WORDING)
    if corroborates_github:
        parts.append("GitHub proof for the same project is attached and corroborates this explanation.")
    if corroborates_website:
        parts.append("Website proof shows the observed runtime workflow for the same project.")
    if corroborates_document:
        parts.append("Document proof corroborates the related project claim.")
    return " ".join(parts)


def public_safe_defense_answer_evidence(
    items: Any, analysis: Any
) -> list[dict[str, Any]]:
    """Project Defense Answer Evidence to recruiter-safe cards, fail-closed.

    ``items`` is the stored ``telemetry.defense_answer_evidence`` list;
    ``analysis`` is the (raw) defense analysis whose ``privacy_scan_status``
    gates the whole session. A card's answer-derived content is published ONLY
    when the session analysis is explicitly clean (:func:`defense_privacy_is_clean`)
    AND the object itself is marked ``public_shareable`` with a clean
    ``privacy_status``. Any other object — flagged, contradicted, malformed,
    legacy (no status), or attached to a missing/unclean analysis — is replaced
    with a fixed withheld card (:func:`_withheld_answer_evidence_card`).

    Public cards never carry ``question_id`` or any internal ID; enum-ish
    fields are allowlisted to the fixed taxonomy; free text is scrubbed through
    :func:`scrub_public_text`. The deterministic ``question_text`` (generated
    template wording, not transcript-derived) is kept only on a clean card.
    """
    if not isinstance(items, list) or not items:
        return []

    session_clean = defense_privacy_is_clean(analysis)

    out: list[dict[str, Any]] = []
    for index, item in enumerate(items[:_MAX_PUBLIC_ANSWER_EVIDENCE], start=1):
        if not isinstance(item, dict):
            continue
        item_status = str(item.get("privacy_status") or "").strip().lower()
        shareable = (
            session_clean
            and bool(item.get("public_shareable"))
            and item_status in _DEFENSE_PRIVACY_CLEAN_STATUSES
            and not item.get("contradiction_flag")
        )
        if not shareable:
            out.append(_withheld_answer_evidence_card(item, index))
            continue

        mapped_skill = _scrub_text_or_none(item.get("mapped_skill"))
        question_kind = _safe_vocab(
            item.get("question_kind"), _ALLOWED_QUESTION_KINDS, "unknown_or_generic"
        )
        qualitative_status = _safe_vocab(
            item.get("qualitative_status"), _ALLOWED_ANSWER_STATUSES, "Not explained"
        )
        corroborates_github = bool(item.get("corroborates_github"))
        corroborates_website = bool(item.get("corroborates_website"))
        corroborates_document = bool(item.get("corroborates_document"))
        out.append(
            {
                "evidence_id_safe": f"defense-answer-{index}",
                "question_kind": question_kind,
                "question_text": _scrub_text_or_none(item.get("question_text")),
                "target_ref_label_safe": _scrub_text_or_none(item.get("target_ref_label_safe")),
                "mapped_skill": mapped_skill,
                "claim_type": _safe_vocab(
                    item.get("claim_type"), _ALLOWED_CLAIM_TYPES, "project_architecture"
                ),
                "answer_purpose": _safe_vocab(
                    item.get("answer_purpose"), _ALLOWED_QUESTION_KINDS, "unknown_or_generic"
                ),
                "evidence_role": _safe_vocab(
                    item.get("evidence_role"), _ALLOWED_EVIDENCE_ROLES, "insufficient_or_generic"
                ),
                "qualitative_status": qualitative_status,
                # Derived description only — the candidate's answer text (even
                # sanitized) is never echoed on the public surface.
                "safe_answer_summary": _public_answer_summary(
                    question_kind,
                    mapped_skill,
                    qualitative_status,
                    corroborates_github,
                    corroborates_website,
                    corroborates_document,
                ),
                "evidence_basis_chips": [
                    chip
                    for chip in (item.get("evidence_basis_chips") or [])
                    if isinstance(chip, str) and chip in _ALLOWED_BASIS_CHIPS
                ],
                "corroborates_github": corroborates_github,
                "corroborates_website": corroborates_website,
                "corroborates_document": corroborates_document,
                "limitation": scrub_public_text(item.get("limitation")),
                "privacy_status": "clean",
            }
        )
    return out
