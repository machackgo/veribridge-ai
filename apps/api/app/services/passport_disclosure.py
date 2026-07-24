"""Canonical granular Passport disclosure policy (migration 063).

The ONE place that decides what an anonymous recruiter may see of a
student's evidence. Every public serializer and media gate consults this
resolver — policy logic is never duplicated in endpoints.

Three passport modes (the ``vbr_work_passports.is_published`` master
switch stays authoritative above everything here):

* **Private** — ``is_published = false``. Every public surface fails
  closed; the rows managed here stay stored but dormant.
* **Public recruiter-safe** (``mode = 'recruiter_safe'``, the default) —
  fixed safe defaults identical to the pre-063 product behavior:
  summaries visible, public GitHub repository links allowed, raw
  artifacts private, downloads disabled, videos/transcripts hidden.
  Overrides are stored but NOT applied.
* **Public custom** (``mode = 'custom'``) — per-resource overrides apply,
  resolved hierarchically. In custom mode disclosure is authoritative for
  anonymous artifact access: it can both grant (a document preview the
  student opted in) and revoke (a previously public-safe video the
  student hid).

Deterministic inheritance rules:

* Passport Private overrides everything.
* A Hidden parent forces every descendant to be effectively Hidden:
  project → report → per-proof aspects; skill_group → skill →
  project_skill. A child can be more restrictive than its parent, never
  less restrictive than a Hidden ancestor.
* ``github_lines`` can be Viewable only while ``github_repo`` is
  Viewable; ``document_download`` only while the document is Viewable.
* Unknown resource types/values and lookup errors fail closed (Hidden).

Dict-mode (hermetic tests / dev fallback): when ``db`` is a plain dict
the tables live under their names keyed by row id, mirroring the other
passport services.
"""

from __future__ import annotations

import logging

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_POLICIES_TABLE = "passport_disclosure_policies"
_OVERRIDES_TABLE = "passport_disclosure_overrides"
_AUDIT_TABLE = "passport_disclosure_audit"
_PASSPORTS_TABLE = "vbr_work_passports"

MODE_RECRUITER_SAFE = "recruiter_safe"
MODE_CUSTOM = "custom"
MODES = frozenset({MODE_RECRUITER_SAFE, MODE_CUSTOM})

HIDDEN = "hidden"
SUMMARY = "summary"
VIEWABLE = "viewable"
DOWNLOADABLE = "downloadable"
VISIBLE = "visible"

_STRUCTURAL = frozenset({VISIBLE, HIDDEN})

# Closed vocabulary: resource type → the visibility states a student may
# configure for it. Must stay in sync with the migration-063 CHECK list.
RESOURCE_TYPES: dict[str, frozenset[str]] = {
    "project": _STRUCTURAL,
    "report": _STRUCTURAL,
    "skill_group": _STRUCTURAL,
    "skill": _STRUCTURAL,
    "project_skill": _STRUCTURAL,
    "github_repo": frozenset({HIDDEN, SUMMARY, VIEWABLE}),
    "github_lines": frozenset({HIDDEN, VIEWABLE}),
    "website_summary": _STRUCTURAL,
    "website_url": _STRUCTURAL,
    "website_frames": frozenset({HIDDEN, VIEWABLE}),
    "website_video": frozenset({HIDDEN, VIEWABLE}),
    "document": frozenset({HIDDEN, SUMMARY, VIEWABLE}),
    "document_download": frozenset({HIDDEN, DOWNLOADABLE}),
    "defense_summary": _STRUCTURAL,
    "defense_transcript": frozenset({HIDDEN, VIEWABLE}),
    "defense_video": frozenset({HIDDEN, VIEWABLE}),
    "video_summary": _STRUCTURAL,
    "video_full": frozenset({HIDDEN, VIEWABLE}),
}

# Recruiter-safe defaults — EXACTLY the pre-063 public behavior, so
# existing published passports keep their current availability after the
# migration. These are also the custom-mode fallback when no override
# exists for a node.
RECRUITER_SAFE_DEFAULTS: dict[str, str] = {
    "project": VISIBLE,
    "report": VISIBLE,
    "skill_group": VISIBLE,
    "skill": VISIBLE,
    "project_skill": VISIBLE,
    # Truth-gated elsewhere: a repo link still only renders when the repo
    # is actually public and the URL passes the safe-public-url gate.
    "github_repo": VIEWABLE,
    "github_lines": VIEWABLE,
    "website_summary": VISIBLE,
    "website_url": VISIBLE,
    "website_frames": HIDDEN,
    "website_video": HIDDEN,
    "document": SUMMARY,
    "document_download": HIDDEN,
    "defense_summary": VISIBLE,
    "defense_transcript": HIDDEN,
    "defense_video": HIDDEN,
    "video_summary": VISIBLE,
    "video_full": HIDDEN,
}

# Per-project proof aspects (resource_key = the project uuid).
PROJECT_ASPECTS = frozenset(
    {
        "github_repo",
        "github_lines",
        "website_summary",
        "website_url",
        "website_frames",
        "website_video",
        "defense_summary",
        "defense_transcript",
        "defense_video",
        "video_summary",
        "video_full",
    }
)

# proof_artifacts.artifact_type → the disclosure aspect that governs
# anonymous access to it (view). Download is separately gated.
ARTIFACT_TYPE_ASPECT: dict[str, str] = {
    "website_replay_video": "website_video",
    "website_frame": "website_frames",
    "document_original": "document",
    "document_redacted": "document",
    "defense_transcript": "defense_transcript",
    "defense_video": "defense_video",
    "defense_audio": "defense_video",
    "video_proof_original": "video_full",
    "video_proof_frame": "video_full",
    "video_proof_transcript": "video_full",
}

__all__ = [
    "MODES",
    "MODE_CUSTOM",
    "MODE_RECRUITER_SAFE",
    "HIDDEN",
    "SUMMARY",
    "VIEWABLE",
    "DOWNLOADABLE",
    "VISIBLE",
    "RESOURCE_TYPES",
    "RECRUITER_SAFE_DEFAULTS",
    "PROJECT_ASPECTS",
    "EffectiveDisclosure",
    "DisclosureValidationError",
    "project_skill_key",
    "artifact_action_allowed",
    "video_proof_public_access",
    "get_policy",
    "list_overrides",
    "set_disclosure_mode",
    "apply_disclosure_overrides",
    "load_effective_disclosure",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def project_skill_key(project_id: Any, skill_slug: str) -> str:
    """Canonical ``project_skill`` resource key: ``"<project_uuid>:<slug>"``."""
    return f"{project_id}:{skill_slug}"


class DisclosureValidationError(ValueError):
    """A disclosure write carried an unknown resource type / visibility."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


# ── Row access (dict-mode + Supabase) ─────────────────────────────────────────


def _policy_row(db: Any, user_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_POLICIES_TABLE, {}).values()
                if str(row.get("user_id")) == str(user_id)
            ),
            None,
        )
    result = (
        db.table(_POLICIES_TABLE)
        .select("*")
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _default_policy(user_id: str) -> dict[str, Any]:
    return {
        "id": None,
        "user_id": str(user_id),
        "mode": MODE_RECRUITER_SAFE,
        "disclosure_version": 1,
    }


def get_policy(db: Any, user_id: str) -> dict[str, Any]:
    """The user's policy row, or the recruiter-safe default when absent.

    Never creates a row — reads must stay side-effect free (public request
    paths call this). Lookup errors fail closed to the safe default.
    """
    try:
        row = _policy_row(db, user_id)
    except Exception:  # pragma: no cover - defensive
        logger.warning("[Disclosure] Policy lookup failed; using recruiter-safe default.")
        row = None
    if not isinstance(row, dict):
        return _default_policy(user_id)
    mode = row.get("mode")
    if mode not in MODES:
        # Unknown mode value (future migration drift) → safest known mode.
        row = dict(row)
        row["mode"] = MODE_RECRUITER_SAFE
    return row


def _ensure_policy(db: Any, user_id: str) -> dict[str, Any]:
    row = _policy_row(db, user_id)
    if isinstance(row, dict):
        return row
    new_row = {
        "id": str(uuid4()),
        "user_id": str(user_id),
        "mode": MODE_RECRUITER_SAFE,
        "disclosure_version": 1,
        "created_at": _now(),
        "updated_at": _now(),
    }
    if isinstance(db, dict):
        db.setdefault(_POLICIES_TABLE, {})[new_row["id"]] = new_row
        return new_row
    result = db.table(_POLICIES_TABLE).insert(new_row).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else new_row


def _update_policy(db: Any, policy_id: str, updates: dict[str, Any]) -> None:
    if isinstance(db, dict):
        row = db.setdefault(_POLICIES_TABLE, {}).get(policy_id)
        if row is not None:
            row.update(updates)
        return
    db.table(_POLICIES_TABLE).update(updates).eq("id", policy_id).execute()


def list_overrides(db: Any, user_id: str) -> dict[tuple[str, str], str]:
    """All stored overrides as ``{(resource_type, resource_key): visibility}``.

    Unknown types/values are dropped on read (fail closed), never served.
    """
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_OVERRIDES_TABLE, {}).values()
            if str(row.get("user_id")) == str(user_id)
        ]
    else:
        result = (
            db.table(_OVERRIDES_TABLE)
            .select("resource_type,resource_key,visibility")
            .eq("user_id", str(user_id))
            .execute()
        )
        rows = getattr(result, "data", []) or []

    overrides: dict[tuple[str, str], str] = {}
    for row in rows:
        rtype = str(row.get("resource_type") or "")
        key = str(row.get("resource_key") or "")
        visibility = str(row.get("visibility") or "")
        allowed = RESOURCE_TYPES.get(rtype)
        if not key or allowed is None or visibility not in allowed:
            continue
        overrides[(rtype, key)] = visibility
    return overrides


def _find_override_row(db: Any, user_id: str, rtype: str, key: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_OVERRIDES_TABLE, {}).values()
                if str(row.get("user_id")) == str(user_id)
                and row.get("resource_type") == rtype
                and row.get("resource_key") == key
            ),
            None,
        )
    result = (
        db.table(_OVERRIDES_TABLE)
        .select("*")
        .eq("user_id", str(user_id))
        .eq("resource_type", rtype)
        .eq("resource_key", key)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _write_audit(
    db: Any,
    *,
    user_id: str,
    changed_by: str,
    rtype: str,
    key: str,
    previous: str | None,
    new: str | None,
    version: int,
) -> None:
    row = {
        "id": str(uuid4()),
        "user_id": str(user_id),
        "changed_by_user_id": str(changed_by),
        "resource_type": rtype,
        "resource_key": key,
        "previous_visibility": previous,
        "new_visibility": new,
        "disclosure_version": version,
        "changed_at": _now(),
    }
    try:
        if isinstance(db, dict):
            db.setdefault(_AUDIT_TABLE, {})[row["id"]] = row
        else:
            db.table(_AUDIT_TABLE).insert(row).execute()
    except Exception:  # pragma: no cover - audit is best-effort, never blocks
        logger.warning("[Disclosure] Audit write failed (non-fatal).")


# ── Owner writes ──────────────────────────────────────────────────────────────


def set_disclosure_mode(db: Any, user_id: str, mode: str) -> dict[str, Any]:
    """Switch between recruiter-safe and custom. Bumps ``disclosure_version``."""
    if mode not in MODES:
        raise DisclosureValidationError("mode", f"Unknown disclosure mode: {mode!r}")
    policy = _ensure_policy(db, user_id)
    previous = policy.get("mode")
    if previous == mode:
        return policy
    version = int(policy.get("disclosure_version") or 1) + 1
    updates = {"mode": mode, "disclosure_version": version, "updated_at": _now()}
    _update_policy(db, str(policy["id"]), updates)
    policy = {**policy, **updates}
    _write_audit(
        db,
        user_id=user_id,
        changed_by=user_id,
        rtype="passport_mode",
        key="passport",
        previous=str(previous),
        new=mode,
        version=version,
    )
    logger.info("[Disclosure] Mode for user %s → %s (v%d)", user_id, mode, version)
    return policy


def apply_disclosure_overrides(
    db: Any, user_id: str, changes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Batch upsert/clear overrides. One version bump per batch.

    Each change is ``{resource_type, resource_key, visibility}``;
    ``visibility = None`` clears the override so the node reverts to its
    inherited default. Every change is validated against the closed
    vocabulary before ANY write happens, then audited row by row.
    """
    validated: list[tuple[str, str, str | None]] = []
    for change in changes:
        rtype = str(change.get("resource_type") or "")
        key = str(change.get("resource_key") or "").strip()
        visibility = change.get("visibility")
        allowed = RESOURCE_TYPES.get(rtype)
        if allowed is None:
            raise DisclosureValidationError(
                "resource_type", f"Unknown resource type: {rtype!r}"
            )
        if not key or len(key) > 300:
            raise DisclosureValidationError("resource_key", "Invalid resource key.")
        if visibility is not None:
            visibility = str(visibility)
            if visibility not in allowed:
                raise DisclosureValidationError(
                    "visibility",
                    f"{visibility!r} is not a valid state for {rtype} "
                    f"(allowed: {', '.join(sorted(allowed))}).",
                )
        validated.append((rtype, key, visibility))

    policy = _ensure_policy(db, user_id)
    version = int(policy.get("disclosure_version") or 1) + 1

    for rtype, key, visibility in validated:
        existing = _find_override_row(db, user_id, rtype, key)
        previous = existing.get("visibility") if isinstance(existing, dict) else None
        if visibility is None:
            if existing is None:
                continue
            if isinstance(db, dict):
                db.setdefault(_OVERRIDES_TABLE, {}).pop(str(existing.get("id")), None)
            else:
                db.table(_OVERRIDES_TABLE).delete().eq("id", str(existing["id"])).execute()
        elif existing is None:
            row = {
                "id": str(uuid4()),
                "user_id": str(user_id),
                "resource_type": rtype,
                "resource_key": key,
                "visibility": visibility,
                "created_at": _now(),
                "updated_at": _now(),
            }
            if isinstance(db, dict):
                db.setdefault(_OVERRIDES_TABLE, {})[row["id"]] = row
            else:
                db.table(_OVERRIDES_TABLE).insert(row).execute()
        else:
            if previous == visibility:
                continue
            updates = {"visibility": visibility, "updated_at": _now()}
            if isinstance(db, dict):
                existing.update(updates)
            else:
                db.table(_OVERRIDES_TABLE).update(updates).eq(
                    "id", str(existing["id"])
                ).execute()
        _write_audit(
            db,
            user_id=user_id,
            changed_by=user_id,
            rtype=rtype,
            key=key,
            previous=previous,
            new=visibility,
            version=version,
        )

    updates = {"disclosure_version": version, "updated_at": _now()}
    _update_policy(db, str(policy["id"]), updates)
    return {**policy, **updates}


def clear_disclosure_overrides(db: Any, user_id: str) -> dict[str, Any]:
    """Delete every stored override (reset to recommended defaults).

    The mode is left as-is (a custom-mode passport resets to the recruiter-safe
    DEFAULTS while staying in custom mode, ready for new overrides). One audit
    row records the bulk reset; the version bump revokes cached access.
    """
    policy = _ensure_policy(db, user_id)
    version = int(policy.get("disclosure_version") or 1) + 1

    if isinstance(db, dict):
        table = db.setdefault(_OVERRIDES_TABLE, {})
        removed = [
            row_id
            for row_id, row in list(table.items())
            if str(row.get("user_id")) == str(user_id)
        ]
        for row_id in removed:
            table.pop(row_id, None)
    else:
        db.table(_OVERRIDES_TABLE).delete().eq("user_id", str(user_id)).execute()

    _write_audit(
        db,
        user_id=user_id,
        changed_by=user_id,
        rtype="bulk_reset",
        key="all_overrides",
        previous=None,
        new=None,
        version=version,
    )
    updates = {"disclosure_version": version, "updated_at": _now()}
    _update_policy(db, str(policy["id"]), updates)
    logger.info("[Disclosure] Overrides cleared for user %s (v%d)", user_id, version)
    return {**policy, **updates}


# ── Effective resolution ──────────────────────────────────────────────────────


class EffectiveDisclosure:
    """Immutable per-request view of one owner's effective disclosure.

    Loaded once (policy + overrides + passport publish state), then every
    question is answered from memory — deterministic and side-effect free.
    All answers fail closed when the passport is not public.
    """

    def __init__(
        self,
        *,
        user_id: str,
        passport_public: bool,
        mode: str,
        disclosure_version: int,
        overrides: dict[tuple[str, str], str],
    ) -> None:
        self.user_id = str(user_id)
        self.passport_public = bool(passport_public)
        self.mode = mode if mode in MODES else MODE_RECRUITER_SAFE
        self.disclosure_version = int(disclosure_version or 1)
        self._overrides = dict(overrides)

    # -- configured (what the student set, before inheritance) ---------------

    def configured(self, rtype: str, key: str) -> str | None:
        """The stored override for a node, or None when inherited."""
        return self._overrides.get((rtype, str(key)))

    def _resolved(self, rtype: str, key: str) -> str:
        """Override in custom mode, else the recruiter-safe default."""
        if self.mode == MODE_CUSTOM:
            configured = self._overrides.get((rtype, str(key)))
            if configured is not None:
                return configured
        return RECRUITER_SAFE_DEFAULTS.get(rtype, HIDDEN)

    # -- hierarchy: passport → project → report → aspect ---------------------

    def project_visible(self, project_id: Any) -> bool:
        if not self.passport_public:
            return False
        return self._resolved("project", str(project_id)) != HIDDEN

    def report_visible(self, project_id: Any) -> bool:
        """The project's public report — Hidden project forces Hidden report."""
        if not self.project_visible(project_id):
            return False
        return self._resolved("report", str(project_id)) != HIDDEN

    def project_card_visible(self, project_id: Any) -> bool:
        """A featured passport card exists only when project AND report are
        visible — the card's whole purpose is the report link, so a hidden
        report never renders a dead card."""
        return self.report_visible(project_id)

    def aspect(self, project_id: Any, rtype: str) -> str:
        """Effective state of a per-project proof aspect (fail-closed).

        Hidden ancestors force Hidden. Dependent aspects degrade with
        their parent: exact code lines require a viewable repository;
        website URL/frames/video require the website proof itself to be
        present; the defense transcript/video require the defense summary.
        """
        if rtype not in PROJECT_ASPECTS:
            return HIDDEN
        if not self.report_visible(project_id):
            return HIDDEN
        resolved = self._resolved(rtype, str(project_id))

        if rtype == "github_lines":
            if self.aspect(project_id, "github_repo") != VIEWABLE:
                return HIDDEN
        elif rtype in {"website_url", "website_frames", "website_video"}:
            if self.aspect(project_id, "website_summary") == HIDDEN:
                return HIDDEN
        elif rtype in {"defense_transcript", "defense_video"}:
            if self.aspect(project_id, "defense_summary") == HIDDEN:
                return HIDDEN
        elif rtype == "video_full":
            if self.aspect(project_id, "video_summary") == HIDDEN:
                return HIDDEN
        return resolved

    # -- documents (per-document keys) ---------------------------------------

    def document_state(self, project_id: Any, document_key: str) -> str:
        """hidden | summary | viewable for ONE document of a visible report."""
        if not self.report_visible(project_id):
            return HIDDEN
        return self._resolved("document", str(document_key))

    def document_downloadable(self, project_id: Any, document_key: str) -> bool:
        """Download is a separate grant on top of a viewable document."""
        if self.document_state(project_id, document_key) != VIEWABLE:
            return False
        return self._resolved("document_download", str(document_key)) == DOWNLOADABLE

    # -- skills: group → skill → project_skill -------------------------------

    def skill_group_visible(self, category: str) -> bool:
        if not self.passport_public:
            return False
        return self._resolved("skill_group", str(category)) != HIDDEN

    def skill_visible(self, category: str, slug: str) -> bool:
        if not self.skill_group_visible(category):
            return False
        return self._resolved("skill", str(slug)) != HIDDEN

    def project_skill_visible(self, project_id: Any, category: str, slug: str) -> bool:
        """One skill claim inside one project — hidden if the skill, its
        group, the project, or the report is hidden."""
        if not self.skill_visible(category, slug):
            return False
        if not self.report_visible(project_id):
            return False
        return (
            self._resolved("project_skill", project_skill_key(project_id, slug)) != HIDDEN
        )

    # -- anonymous artifact access (media gates) ------------------------------

    def artifact_access(self, artifact: dict[str, Any]) -> str:
        """'none' | 'view' | 'download' for an anonymous caller.

        Only meaningful in custom mode — recruiter-safe mode returns
        'none' so the pre-063 retention policy (``can_access_artifact``)
        stays the sole authority there.
        """
        if not self.passport_public or self.mode != MODE_CUSTOM:
            return "none"
        artifact_type = str(artifact.get("artifact_type") or "")
        aspect = ARTIFACT_TYPE_ASPECT.get(artifact_type)
        if aspect is None:
            return "none"
        project_id = artifact.get("project_id")
        if not project_id:
            return "none"
        if aspect == "document":
            document_key = str(artifact.get("proof_id") or "")
            if not document_key:
                return "none"
            state = self.document_state(project_id, document_key)
            if state != VIEWABLE:
                return "none"
            if self.document_downloadable(project_id, document_key):
                return "download"
            return "view"
        if self.aspect(project_id, aspect) == VIEWABLE:
            return "view"
        return "none"

    def custom_mode_revokes(self, artifact: dict[str, Any]) -> bool:
        """True when custom mode explicitly hides this artifact's aspect —
        used to REVOKE anonymous access an artifact row's own retention
        policy (e.g. ``public_safe``) would otherwise allow. In
        recruiter-safe mode nothing is revoked (pre-063 behavior)."""
        if self.mode != MODE_CUSTOM:
            return False
        return self.artifact_access(artifact) == "none" and str(
            artifact.get("artifact_type") or ""
        ) in ARTIFACT_TYPE_ASPECT


def artifact_action_allowed(
    db: Any,
    artifact: dict[str, Any],
    caller_user_id: str | None,
    *,
    caller_is_privileged: bool = False,
    action: str = "view",
) -> bool:
    """THE access decision for a retained artifact under granular disclosure.

    Composes the migration-056 retention policy with the migration-063
    disclosure policy — the single gate every artifact route calls:

    * owner → full access, always (privacy settings never lock the student
      out of their own evidence);
    * privileged non-owner (recruiter/admin/reviewer) → the retention
      consent flow stays authoritative, unchanged;
    * anonymous / plain non-owner student, artifact type governed by a
      disclosure aspect → requires a PUBLIC passport; then custom mode is
      fully authoritative (it can grant view/download the retention policy
      would deny, and revoke access it would allow), while recruiter-safe
      mode keeps the legacy ``public_safe`` behavior with downloads denied;
    * anything unmapped falls back to the retention policy alone.
    """
    from app.services.proof_artifact_service import can_access_artifact

    if not artifact.get("retained", False):
        return False
    owner = str(artifact.get("owner_user_id") or "")
    if caller_user_id is not None and str(caller_user_id) == owner:
        return True
    if caller_is_privileged:
        return can_access_artifact(artifact, caller_user_id, caller_is_privileged=True)

    mapped = str(artifact.get("artifact_type") or "") in ARTIFACT_TYPE_ASPECT
    if not mapped:
        return can_access_artifact(artifact, caller_user_id, caller_is_privileged=False)

    disclosure = load_effective_disclosure(db, owner)
    if not disclosure.passport_public:
        return False
    if disclosure.mode == MODE_CUSTOM:
        access = disclosure.artifact_access(artifact)
        if action == "download":
            return access == "download"
        return access != "none"
    # Recruiter-safe: pre-063 behavior for viewing, downloads never granted
    # to a non-owner without an explicit custom-mode grant.
    if action == "download":
        return False
    return can_access_artifact(artifact, caller_user_id, caller_is_privileged=False)


def video_proof_public_access(db: Any, proof: dict[str, Any]) -> bool:
    """Non-owner access decision for a first-class Video Proof row.

    Mirrors :func:`artifact_action_allowed` for the ``video_proofs`` table
    (detail / transcript / frames routes): requires a public passport;
    custom mode requires the project's ``video_full`` aspect to be
    Viewable; recruiter-safe mode keeps the legacy ``public_safe`` flag.
    """
    owner = str(proof.get("user_id") or "")
    disclosure = load_effective_disclosure(db, owner)
    if not disclosure.passport_public:
        return False
    if disclosure.mode == MODE_CUSTOM:
        project_id = proof.get("project_id")
        if not project_id:
            return False
        return disclosure.aspect(project_id, "video_full") == VIEWABLE
    return bool(proof.get("public_safe", False))


def load_effective_disclosure(
    db: Any,
    user_id: Any,
    *,
    passport_public: bool | None = None,
) -> EffectiveDisclosure:
    """Load one owner's effective disclosure. Fails closed on any error.

    ``passport_public`` may be passed when the caller already resolved the
    passport row (public builders do); otherwise it is looked up here.
    """
    uid = str(user_id or "")
    if not uid:
        return EffectiveDisclosure(
            user_id="",
            passport_public=False,
            mode=MODE_RECRUITER_SAFE,
            disclosure_version=1,
            overrides={},
        )

    if passport_public is None:
        # Local import to avoid a cycle (passport_visibility is leaf-level).
        from app.services.passport_visibility import owner_passport_is_public

        passport_public = owner_passport_is_public(db, uid)

    try:
        policy = get_policy(db, uid)
        overrides = list_overrides(db, uid)
    except Exception:  # pragma: no cover - defensive
        logger.warning("[Disclosure] Load failed; failing closed to recruiter-safe.")
        policy = _default_policy(uid)
        overrides = {}

    return EffectiveDisclosure(
        user_id=uid,
        passport_public=bool(passport_public),
        mode=str(policy.get("mode") or MODE_RECRUITER_SAFE),
        disclosure_version=int(policy.get("disclosure_version") or 1),
        overrides=overrides,
    )
