"""Passport Profile service — owner CRUD + recruiter-safe public projection.

The passport profile (migration 062) is the ONE canonical source of candidate
identity for the Work Passport surfaces: the student edits it at
``/student/vbr/passport/profile``, the private passport header previews it, and
the public passport serves it live at read time (evidence/report content stays
publication-versioned; identity is always current).

Safety model:
  * every field is optional; the public projection omits empty fields —
    placeholders are never invented
  * publish-sensitive fields are gated by per-field visibility toggles
    (work authorization is opt-in / off by default)
  * link fields are validated https URLs (github/linkedin host-pinned) so the
    public surface can never emit javascript:/data: or signed/tokenized URLs
  * free text is scrubbed downstream by the existing public-safety layer
    (scrub + fail-closed unsafe-field scan) before anything is served publicly
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

_TABLE = "passport_profiles"

# Field length caps (characters) for student-authored text.
_TEXT_LIMITS = {
    "full_name": 120,
    "preferred_name": 120,
    "pronunciation": 160,
    "headline": 160,
    "bio": 700,
    "institution": 160,
    "degree": 120,
    "location": 120,
    "work_authorization_note": 200,
}

_URL_FIELDS = ("github_url", "linkedin_url", "portfolio_url")
_URL_MAX_LEN = 300
# Host pinning for the two well-known link fields. The portfolio link may point
# anywhere, but must still be a plain https URL.
_URL_ALLOWED_HOSTS = {
    "github_url": ("github.com",),
    "linkedin_url": ("linkedin.com",),
}

_ROLE_AREAS_MAX = 6
_ROLE_AREA_LEN = 80

_GRAD_YEAR_MIN = 1980
_GRAD_YEAR_MAX = 2100

_AVAILABILITY_LABELS = {
    "seeking_internship": "Seeking internship",
    "seeking_full_time": "Seeking full-time roles",
    "open_to_opportunities": "Open to opportunities",
}

# Query-string params that mark a tokenized/signed URL — never publishable.
_UNSAFE_URL_QUERY_RE = re.compile(
    r"[?&](token|signature|sig|expires|se|sv|x-amz-[a-z-]+)=", re.IGNORECASE
)

_TEXT_FIELDS = tuple(_TEXT_LIMITS.keys())
_BOOL_FIELDS = (
    "show_location",
    "show_availability",
    "show_links",
    "show_work_authorization",
)

_ALL_COLUMNS = (
    *_TEXT_FIELDS,
    *_URL_FIELDS,
    "graduation_year",
    "role_areas",
    "availability",
    *_BOOL_FIELDS,
)

_BOOL_DEFAULTS = {
    "show_location": True,
    "show_availability": True,
    "show_links": True,
    "show_work_authorization": False,
}


class PassportProfileValidationError(ValueError):
    """A field failed validation; ``field`` + human message for a 422."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _now() -> str:
    return datetime.now(UTC).isoformat()


def availability_label(value: Any) -> str | None:
    """Recruiter-facing label for a stored availability value, else ``None``."""
    return _AVAILABILITY_LABELS.get(str(value or "").strip())


def _clean_text(field: str, value: Any) -> str | None:
    """Normalize student text: strip, collapse inner newlines for single-line
    fields, enforce the length cap. Empty → ``None`` (field cleared)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if field != "bio":
        text = " ".join(text.split())
    limit = _TEXT_LIMITS[field]
    if len(text) > limit:
        raise PassportProfileValidationError(
            field, f"Must be {limit} characters or fewer."
        )
    return text


def _clean_url(field: str, value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if len(raw) > _URL_MAX_LEN:
        raise PassportProfileValidationError(field, "Link is too long.")
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise PassportProfileValidationError(field, "Link must start with https://")
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        raise PassportProfileValidationError(field, "Link must include a valid domain.")
    if parsed.username or parsed.password:
        raise PassportProfileValidationError(field, "Link must not embed credentials.")
    if _UNSAFE_URL_QUERY_RE.search(raw):
        raise PassportProfileValidationError(
            field, "Link must not contain access tokens or signatures."
        )
    allowed = _URL_ALLOWED_HOSTS.get(field)
    if allowed and not any(host == a or host.endswith(f".{a}") for a in allowed):
        raise PassportProfileValidationError(
            field, f"Link must be on {allowed[0]}."
        )
    return raw


def _clean_graduation_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise PassportProfileValidationError(
            "graduation_year", "Graduation year must be a number."
        ) from None
    if not (_GRAD_YEAR_MIN <= year <= _GRAD_YEAR_MAX):
        raise PassportProfileValidationError(
            "graduation_year",
            f"Graduation year must be between {_GRAD_YEAR_MIN} and {_GRAD_YEAR_MAX}.",
        )
    return year


def _clean_role_areas(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PassportProfileValidationError("role_areas", "Must be a list of role areas.")
    cleaned: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        if len(text) > _ROLE_AREA_LEN:
            raise PassportProfileValidationError(
                "role_areas", f"Each role area must be {_ROLE_AREA_LEN} characters or fewer."
            )
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > _ROLE_AREAS_MAX:
        raise PassportProfileValidationError(
            "role_areas", f"Choose at most {_ROLE_AREAS_MAX} role areas."
        )
    return cleaned


def _clean_availability(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text not in _AVAILABILITY_LABELS:
        raise PassportProfileValidationError(
            "availability",
            "Availability must be one of: " + ", ".join(sorted(_AVAILABILITY_LABELS)),
        )
    return text


def validate_profile_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize an owner update payload (only provided keys).

    Returns the cleaned column→value map ready to persist. Raises
    :class:`PassportProfileValidationError` on the first invalid field.
    """
    cleaned: dict[str, Any] = {}
    for field, value in updates.items():
        if field in _TEXT_LIMITS:
            cleaned[field] = _clean_text(field, value)
        elif field in _URL_FIELDS:
            cleaned[field] = _clean_url(field, value)
        elif field == "graduation_year":
            cleaned[field] = _clean_graduation_year(value)
        elif field == "role_areas":
            cleaned[field] = _clean_role_areas(value)
        elif field == "availability":
            cleaned[field] = _clean_availability(value)
        elif field in _BOOL_FIELDS:
            if value is not None:
                cleaned[field] = bool(value)
        # Unknown keys are ignored (schema already forbids extras).
    return cleaned


# ── Persistence ───────────────────────────────────────────────────────────────


def _fetch_row(db: Any, user_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                r
                for r in db.setdefault(_TABLE, {}).values()
                if str(r.get("user_id")) == str(user_id)
            ),
            None,
        )
    result = (
        db.table(_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _row_to_profile(row: dict[str, Any] | None) -> dict[str, Any]:
    """Stored row → owner-view profile dict (defaults when no row exists)."""
    row = row or {}
    profile: dict[str, Any] = {}
    for field in _TEXT_FIELDS + _URL_FIELDS + ("availability",):
        value = row.get(field)
        profile[field] = str(value).strip() if isinstance(value, str) and value.strip() else None
    grad = row.get("graduation_year")
    profile["graduation_year"] = grad if isinstance(grad, int) and grad > 0 else None
    roles = row.get("role_areas")
    profile["role_areas"] = [str(r) for r in roles] if isinstance(roles, list) else []
    for field, default in _BOOL_DEFAULTS.items():
        value = row.get(field)
        profile[field] = bool(value) if isinstance(value, bool) else default
    profile["updated_at"] = row.get("updated_at")
    return profile


def get_passport_profile_row(db: Any, user_id: str) -> dict[str, Any] | None:
    """The raw stored row for the owner, or ``None``. Best-effort: a lookup
    problem returns ``None`` so callers degrade gracefully."""
    try:
        return _fetch_row(db, user_id)
    except Exception:  # pragma: no cover - profile context is optional
        return None


def get_passport_profile(db: Any, user_id: str) -> dict[str, Any]:
    """Owner view: stored profile (or defaults) + ``has_profile``."""
    row = get_passport_profile_row(db, user_id)
    return {"profile": _row_to_profile(row), "has_profile": row is not None}


def upsert_passport_profile(
    db: Any, user_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Validate + persist an owner update; returns the fresh owner view.

    Only the provided keys are written (PATCH semantics — an omitted field is
    left unchanged; an explicit ``null``/empty value clears it).
    """
    cleaned = validate_profile_updates(updates)
    now = _now()
    if isinstance(db, dict):
        table = db.setdefault(_TABLE, {})
        row = next(
            (r for r in table.values() if str(r.get("user_id")) == str(user_id)),
            None,
        )
        if row is None:
            row = {"id": f"pp_{len(table) + 1}", "user_id": str(user_id), "created_at": now}
            table[row["id"]] = row
        row.update(cleaned)
        row["updated_at"] = now
        return {"profile": _row_to_profile(row), "has_profile": True}

    existing = _fetch_row(db, user_id)
    payload = {**cleaned, "updated_at": now}
    if existing is None:
        payload["user_id"] = str(user_id)
        db.table(_TABLE).insert(payload).execute()
    else:
        db.table(_TABLE).update(payload).eq("user_id", user_id).execute()
    return get_passport_profile(db, user_id)


# ── Editor context (prefill + photo) ─────────────────────────────────────────

_STUDENT_PROFILES_TABLE = "student_profiles"
_ONBOARDING_TABLE = "student_onboarding_profiles"


def _fetch_one(db: Any, table: str, user_id: str, columns: str) -> dict[str, Any]:
    try:
        if isinstance(db, dict):
            row = next(
                (
                    r
                    for r in db.setdefault(table, {}).values()
                    if str(r.get("user_id")) == str(user_id)
                ),
                None,
            )
        else:
            result = (
                db.table(table).select(columns).eq("user_id", user_id).limit(1).execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - prefill is best-effort context
        return {}
    return row if isinstance(row, dict) else {}


def build_prefill(db: Any, user_id: str) -> dict[str, Any]:
    """Best-effort editor prefill from existing account data.

    Reads only recruiter-safe fields from ``student_profiles`` (the legacy
    editable profile) so a returning student doesn't retype what the product
    already knows. Never invented — empty when nothing is stored.
    """
    student = _fetch_one(
        db,
        _STUDENT_PROFILES_TABLE,
        user_id,
        "full_name,headline,school_name,degree,major,graduation_year,location,links",
    )
    links = student.get("links") if isinstance(student.get("links"), dict) else {}
    degree = str(student.get("degree") or "").strip()
    major = str(student.get("major") or "").strip()
    degree_line = " in ".join([p for p in (degree, major) if p]) or None
    grad = student.get("graduation_year")
    prefill = {
        "full_name": str(student.get("full_name") or "").strip() or None,
        "headline": str(student.get("headline") or "").strip() or None,
        "institution": str(student.get("school_name") or "").strip() or None,
        "degree": degree_line,
        "graduation_year": grad if isinstance(grad, int) and grad > 0 else None,
        "location": str(student.get("location") or "").strip() or None,
        "github_url": str(links.get("github_url") or "").strip() or None,
        "linkedin_url": str(links.get("linkedin_url") or "").strip() or None,
    }
    return {k: v for k, v in prefill.items() if v is not None}


def lookup_avatar_url(db: Any, user_id: str) -> str | None:
    """The stored passport photo URL (migration-054 path), if any."""
    row = _fetch_one(db, _ONBOARDING_TABLE, user_id, "avatar_url")
    value = str(row.get("avatar_url") or "").strip()
    return value or None


def get_editor_context(db: Any, user_id: str) -> dict[str, Any]:
    """Full owner editor payload: profile + has_profile + photo + prefill."""
    view = get_passport_profile(db, user_id)
    view["avatar_url"] = lookup_avatar_url(db, user_id)
    view["prefill"] = build_prefill(db, user_id)
    return view


# ── Recruiter-safe public projection ─────────────────────────────────────────


def public_passport_profile(db: Any, user_id: str) -> dict[str, Any]:
    """Visibility-filtered identity fields for the PUBLIC passport builder.

    Returns only fields the student has filled in AND allowed to show; empty
    fields are omitted (``None``) so the public surface renders nothing for
    them. The caller still runs every value through the public-safety scrub +
    fail-closed scan before serving.
    """
    row = get_passport_profile_row(db, user_id)
    if not row:
        return {}
    profile = _row_to_profile(row)
    public: dict[str, Any] = {
        "full_name": profile["full_name"],
        "preferred_name": profile["preferred_name"],
        "pronunciation": profile["pronunciation"],
        "headline": profile["headline"],
        "bio": profile["bio"],
        "institution": profile["institution"],
        "degree": profile["degree"],
        "graduation_year": profile["graduation_year"],
        "role_areas": profile["role_areas"],
    }
    if profile["show_location"]:
        public["location"] = profile["location"]
    if profile["show_availability"]:
        public["availability"] = profile["availability"]
        public["availability_label"] = availability_label(profile["availability"])
    if profile["show_links"]:
        public["github_url"] = profile["github_url"]
        public["linkedin_url"] = profile["linkedin_url"]
        public["portfolio_url"] = profile["portfolio_url"]
    if profile["show_work_authorization"]:
        public["work_authorization_note"] = profile["work_authorization_note"]
    return {k: v for k, v in public.items() if v not in (None, "", [])}
