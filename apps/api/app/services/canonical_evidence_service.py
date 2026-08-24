"""Canonical evidence graph relationship writes.

Read paths remain backward-compatible with legacy source tables, while every
new confirmation is persisted with provenance and immediately becomes visible
to Passport/project/skill reports through the same explicit session metadata.
No title/skill inference is ever written as a direct relationship.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.github_python_evidence_focus import (
    classify_code_block_purpose,
    grade_evidence,
    is_countable_code_purpose,
    is_strong_grade,
)


class CanonicalEvidenceNotFoundError(LookupError):
    pass


class CanonicalEvidenceConflictError(RuntimeError):
    """The proof already has a conflicting canonical project relationship."""


class CanonicalEvidencePreconditionError(RuntimeError):
    """The owned proof is not yet eligible for a direct project relationship."""


class CanonicalEvidencePersistenceError(RuntimeError):
    """The normalized relationship table exists but could not be written."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _owned_row(db: Any, table: str, row_id: str, user_id: str, *, user_key: str) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.get(table, {}).get(row_id)
        if not row or str(row.get(user_key) or "") != str(user_id):
            raise CanonicalEvidenceNotFoundError(row_id)
        return row
    response = (
        db.table(table)
        .select("*")
        .eq("id", row_id)
        .eq(user_key, user_id)
        .maybe_single()
        .execute()
    )
    row = getattr(response, "data", None) if response is not None else None
    if not row:
        raise CanonicalEvidenceNotFoundError(row_id)
    return row


def _retained_website_artifacts(
    db: Any, *, proof_id: str, user_id: str
) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        return [
            row
            for row in db.get("proof_artifacts", {}).values()
            if str(row.get("owner_user_id") or "") == str(user_id)
            and row.get("proof_type") == "website"
            and row.get("artifact_type") == "website_replay_video"
            and str(row.get("proof_id") or "") == str(proof_id)
            and row.get("retained") is True
        ]
    response = (
        db.table("proof_artifacts")
        .select("*")
        .eq("owner_user_id", user_id)
        .eq("proof_type", "website")
        .eq("artifact_type", "website_replay_video")
        .eq("proof_id", proof_id)
        .eq("retained", True)
        .execute()
    )
    return list(getattr(response, "data", []) or [])


def _missing_relationship_table(exc: Exception) -> bool:
    message = str(exc).lower()
    return "proof_project_relationships" in message and (
        "pgrst205" in message or "could not find the table" in message
    )


def _relationship_rows(
    db: Any, *, proof_id: str, user_id: str
) -> list[dict[str, Any]] | None:
    """Return normalized rows, or ``None`` only on a pre-058 database."""
    if isinstance(db, dict):
        return [
            row
            for row in db.get("proof_project_relationships", {}).values()
            if str(row.get("owner_user_id") or "") == str(user_id)
            and row.get("proof_type") == "website"
            and str(row.get("proof_id") or "") == str(proof_id)
        ]
    try:
        response = (
            db.table("proof_project_relationships")
            .select("*")
            .eq("owner_user_id", user_id)
            .eq("proof_type", "website")
            .eq("proof_id", proof_id)
            .execute()
        )
    except Exception as exc:
        if _missing_relationship_table(exc):
            return None
        raise CanonicalEvidencePersistenceError(
            "Could not inspect the canonical proof relationship."
        ) from exc
    return list(getattr(response, "data", []) or [])


def confirm_project_relationship(
    db: Any,
    *,
    user_id: str,
    proof_type: str,
    proof_id: str,
    project_id: str,
) -> dict[str, Any]:
    """Confirm an owned proof→owned project edge and log its provenance.

    Website keeps its original precondition-heavy path below. Every other
    supported proof type flows through :func:`finalize_proof_evidence`, the ONE
    shared finalization boundary, and returns the same relationship descriptor.
    """
    if proof_type != "website":
        if proof_type not in SUPPORTED_PROOF_TYPES:
            raise ValueError(
                f"Unsupported proof type '{proof_type}'. Supported: {', '.join(SUPPORTED_PROOF_TYPES)}."
            )
        result = finalize_proof_evidence(
            db,
            user_id=user_id,
            proof_type=proof_type,
            proof_id=proof_id,
            project_id=project_id,
        )
        return result["project_relationship"]
    session = _owned_row(
        db, "extension_proof_sessions", proof_id, user_id, user_key="user_id"
    )
    project = _owned_row(db, "vbr_projects", project_id, user_id, user_key="user_id")
    if str(session.get("status") or "").lower() != "completed":
        raise CanonicalEvidencePreconditionError(
            "Only a completed Website Proof can be attached to a project."
        )

    artifacts = _retained_website_artifacts(db, proof_id=proof_id, user_id=user_id)
    if not artifacts:
        raise CanonicalEvidencePreconditionError(
            "A retained Website Proof replay is required before project attachment."
        )

    previous = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    previous_project_id = str(previous.get("project_id") or "")
    previous_state = str(
        previous.get("project_relationship_state")
        or ("directly_linked" if previous_project_id else "vault_only")
    )
    if previous_project_id and previous_project_id != str(project_id):
        raise CanonicalEvidenceConflictError(
            "This Website Proof already belongs to a different project."
        )

    for artifact in artifacts:
        artifact_project_id = str(artifact.get("project_id") or "")
        if artifact_project_id and artifact_project_id != str(project_id):
            raise CanonicalEvidenceConflictError(
                "The retained Website Proof replay already belongs to a different project."
            )

    relationship_rows = _relationship_rows(db, proof_id=proof_id, user_id=user_id)
    if relationship_rows is not None:
        conflicting_direct = next(
            (
                row
                for row in relationship_rows
                if row.get("relationship_state") == "directly_linked"
                and str(row.get("project_id") or "") != str(project_id)
            ),
            None,
        )
        if conflicting_direct:
            raise CanonicalEvidenceConflictError(
                "This Website Proof already has a direct relationship to another project."
            )

    confirmed_at = str(previous.get("project_link_confirmed_at") or _now())
    metadata = {
        **previous,
        "project_id": project_id,
        "project_relationship_state": "directly_linked",
        "project_link_source": "user_confirmation",
        "project_link_confirmed_at": confirmed_at,
    }
    relationship = {
        "owner_user_id": user_id,
        "proof_type": "website",
        "proof_id": proof_id,
        "project_id": project_id,
        "relationship_state": "directly_linked",
        "match_method": "user_confirmation",
        "confirmed_by_user": True,
        "provenance": {
            "source": "student_confirmation",
            "previous_project_id": previous.get("project_id"),
            "previous_relationship_state": previous_state,
        },
    }

    if isinstance(db, dict):
        if relationship_rows is not None:
            existing = next(
                (
                    row
                    for row in relationship_rows
                    if str(row.get("project_id") or "") == str(project_id)
                ),
                None,
            ) or next(
                (
                    row
                    for row in relationship_rows
                    if row.get("relationship_state") == "vault_only"
                    and not row.get("project_id")
                ),
                None,
            )
            if existing is not None:
                preserved_provenance = (
                    existing.get("provenance")
                    if existing.get("relationship_state") == "directly_linked"
                    and str(existing.get("project_id") or "") == str(project_id)
                    else None
                )
                existing.update(
                    {
                        **relationship,
                        "provenance": preserved_provenance or relationship["provenance"],
                        "updated_at": _now(),
                    }
                )
            else:
                key = f"website:{proof_id}:{project_id}"
                db.setdefault("proof_project_relationships", {})[key] = {
                    "id": key,
                    **relationship,
                    "created_at": _now(),
                    "updated_at": _now(),
                }
        session["metadata"] = metadata
        session["updated_at"] = _now()
        for artifact in artifacts:
            artifact["project_id"] = project_id
            artifact["updated_at"] = _now()
    else:
        if relationship_rows is not None:
            existing = next(
                (
                    row
                    for row in relationship_rows
                    if str(row.get("project_id") or "") == str(project_id)
                ),
                None,
            ) or next(
                (
                    row
                    for row in relationship_rows
                    if row.get("relationship_state") == "vault_only"
                    and not row.get("project_id")
                ),
                None,
            )
            try:
                if existing:
                    preserved_provenance = (
                        existing.get("provenance")
                        if existing.get("relationship_state") == "directly_linked"
                        and str(existing.get("project_id") or "") == str(project_id)
                        else None
                    )
                    (
                        db.table("proof_project_relationships")
                        .update(
                            {
                                **relationship,
                                "provenance": preserved_provenance
                                or relationship["provenance"],
                                "updated_at": _now(),
                            }
                        )
                        .eq("id", existing["id"])
                        .execute()
                    )
                else:
                    db.table("proof_project_relationships").insert(relationship).execute()
            except Exception as exc:
                raise CanonicalEvidencePersistenceError(
                    "Could not persist the canonical proof relationship."
                ) from exc
        (
            db.table("extension_proof_sessions")
            .update({"metadata": metadata, "updated_at": _now()})
            .eq("id", proof_id)
            .eq("user_id", user_id)
            .execute()
        )
        (
            db.table("proof_artifacts")
            .update({"project_id": project_id, "updated_at": _now()})
            .eq("owner_user_id", user_id)
            .eq("proof_type", "website")
            .eq("proof_id", proof_id)
            .execute()
        )
    return {
        "state": "directly_linked",
        "project_id": project_id,
        "project_title": str(project.get("title") or "Project"),
        "match_method": "user_confirmation",
        "counted": True,
        "confirmed_by_user": True,
        "reasons": ["The student confirmed this Website Proof belongs to the selected project."],
        "action_label": None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Shared finalization boundary — the ONE service every proof type flows through
# before it may count for a project, a skill claim, or a report.
#
#   authenticated owner → owned project → owned proof → retained artifact →
#   analysis → normalized evidence → proof-project relationship →
#   project-skill claims → claim-evidence links → report eligibility
#
# No step is inferred from titles/skill text; every edge written here comes from
# an explicit owner action or a deterministic stored source id. Reads/reports
# derive their views on demand from these rows plus the legacy metadata, so
# there is no separate cache to invalidate — finalization is immediately
# visible to Passport / Project Report / Skill Report.
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED_PROOF_TYPES = ("github", "website", "document", "project_defense", "video")

# Document evidence-object block types that carry a real, source-native locator
# (beyond "the text somewhere mentions the skill"). Paragraphs still qualify
# when they sit under a real section heading or carry a page number.
_STRONG_DOC_BLOCK_TYPES = frozenset(
    {
        "table", "chart", "graph", "image", "screenshot", "architecture_diagram",
        "code_block", "metric_result", "caption", "list", "equation", "mixed_region",
    }
)
_NON_LOCATOR_SECTIONS = frozenset({"", "normal", "body text", "default", "default paragraph font"})


def document_evidence_object_has_locator(obj: dict[str, Any]) -> bool:
    """True when one stored document evidence object cites an exact source
    location (page / figure reference / typed block / real section heading)."""
    if obj.get("page_number") is not None:
        return True
    if str(obj.get("figure_reference") or "").strip():
        return True
    if str(obj.get("block_type") or "").strip().lower() in _STRONG_DOC_BLOCK_TYPES:
        return True
    section = str(obj.get("section_label") or "").strip().lower()
    return section not in _NON_LOCATOR_SECTIONS


def _owned_project(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    return _owned_row(db, "vbr_projects", project_id, user_id, user_key="user_id")


def _website_finalization_state(
    db: Any, *, user_id: str, proof_id: str, project_id: str
) -> tuple[bool, str | None]:
    """Read the durable finalization marker for one exact Website Proof edge."""
    session = _owned_row(
        db, "extension_proof_sessions", proof_id, user_id, user_key="user_id"
    )
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    finalized_at = str(metadata.get("canonical_finalized_at") or "") or None
    finalized_project_id = str(metadata.get("canonical_finalized_project_id") or "")
    return bool(finalized_at and finalized_project_id == str(project_id)), finalized_at


def _mark_website_finalized(
    db: Any,
    *,
    user_id: str,
    proof_id: str,
    project_id: str,
    existing_finalized_at: str | None,
) -> str:
    """Persist a reload/login-stable marker after all canonical writes succeed."""
    session = _owned_row(
        db, "extension_proof_sessions", proof_id, user_id, user_key="user_id"
    )
    previous = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    finalized_at = existing_finalized_at or _now()
    metadata = {
        **previous,
        "canonical_finalized_at": finalized_at,
        "canonical_finalized_project_id": str(project_id),
        "canonical_finalization_service": "finalize_proof_evidence",
    }
    updated_at = _now()
    if isinstance(db, dict):
        session["metadata"] = metadata
        session["updated_at"] = updated_at
        return finalized_at
    try:
        response = (
            db.table("extension_proof_sessions")
            .update({"metadata": metadata, "updated_at": updated_at})
            .eq("id", proof_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not (getattr(response, "data", []) or []):
            raise CanonicalEvidenceNotFoundError(proof_id)
    except CanonicalEvidenceNotFoundError:
        raise
    except Exception as exc:
        raise CanonicalEvidencePersistenceError(
            "Could not persist the Website Proof finalization state."
        ) from exc
    return finalized_at


def _merge_website_claimed_skills_into_project(
    db: Any,
    *,
    project: dict[str, Any],
    session: dict[str, Any],
) -> None:
    """Carry the student's explicit Website Proof skill claims onto the project.

    Project Report and Work Passport map runtime proof only to skills claimed on
    that project.  Website Proof creation stores those explicit selections on
    the proof session, so dropping them at finalization makes analyzed evidence
    appear merely project-level on downstream surfaces.  Merge them
    idempotently; analyzer-derived supported skills are deliberately excluded.
    """
    metadata = project.get("metadata") if isinstance(project.get("metadata"), dict) else {}
    existing = [str(s).strip() for s in (metadata.get("claimed_skills") or []) if str(s).strip()]
    selected = [str(s).strip() for s in (session.get("claimed_skills") or []) if str(s).strip()]
    merged: list[str] = []
    seen: set[str] = set()
    for skill in [*existing, *selected]:
        key = _norm_skill(skill)
        if key and key not in seen:
            seen.add(key)
            merged.append(skill)
    if merged == existing:
        return
    updated = {**metadata, "claimed_skills": merged}
    now = _now()
    if isinstance(db, dict):
        project["metadata"] = updated
        project["updated_at"] = now
        return
    try:
        response = (
            db.table("vbr_projects")
            .update({"metadata": updated, "updated_at": now})
            .eq("id", project["id"])
            .eq("user_id", project["user_id"])
            .execute()
        )
        if not (getattr(response, "data", []) or []):
            raise CanonicalEvidenceNotFoundError(str(project.get("id") or ""))
        project["metadata"] = updated
        project["updated_at"] = now
    except CanonicalEvidenceNotFoundError:
        raise
    except Exception as exc:
        raise CanonicalEvidencePersistenceError(
            "Could not persist the Website Proof's claimed skills on the selected project."
        ) from exc


def _norm_skill(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _table_rows(db: Any, table: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort equality-filtered read (dict-mode + Supabase)."""
    try:
        if isinstance(db, dict):
            out = []
            for row in db.get(table, {}).values():
                if all(str(row.get(k) or "") == str(v) for k, v in filters.items()):
                    out.append(row)
            return out
        query = db.table(table).select("*")
        for key, value in filters.items():
            query = query.eq(key, value)
        response = query.execute()
        return list(getattr(response, "data", []) or [])
    except Exception:
        return []


def _upsert_relationship_row(
    db: Any,
    *,
    user_id: str,
    proof_type: str,
    proof_id: str,
    project_id: str,
    match_method: str,
    provenance: dict[str, Any],
) -> None:
    """Idempotent directly-linked relationship write (best-effort pre-058)."""
    relationship = {
        "owner_user_id": user_id,
        "proof_type": proof_type,
        "proof_id": proof_id,
        "project_id": project_id,
        "relationship_state": "directly_linked",
        "match_method": match_method,
        "confirmed_by_user": True,
        "provenance": provenance,
    }
    try:
        existing = [
            row
            for row in _table_rows(
                db,
                "proof_project_relationships",
                {"owner_user_id": user_id, "proof_type": proof_type, "proof_id": proof_id},
            )
        ]
        same = next((r for r in existing if str(r.get("project_id") or "") == str(project_id)), None)
        vault = next(
            (r for r in existing if r.get("relationship_state") == "vault_only" and not r.get("project_id")),
            None,
        )
        if isinstance(db, dict):
            target = same or vault
            if target is not None:
                if not (
                    target.get("relationship_state") == "directly_linked"
                    and str(target.get("project_id") or "") == str(project_id)
                ):
                    target.update({**relationship, "updated_at": _now()})
            else:
                key = f"{proof_type}:{proof_id}:{project_id}"
                db.setdefault("proof_project_relationships", {})[key] = {
                    "id": key,
                    **relationship,
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            return
        target = same or vault
        if target is not None:
            if not (
                target.get("relationship_state") == "directly_linked"
                and str(target.get("project_id") or "") == str(project_id)
            ):
                (
                    db.table("proof_project_relationships")
                    .update({**relationship, "updated_at": _now()})
                    .eq("id", target["id"])
                    .execute()
                )
        else:
            db.table("proof_project_relationships").insert(relationship).execute()
    except Exception as exc:
        if _missing_relationship_table(exc):
            return  # pre-058 database: metadata edges stay authoritative
        raise CanonicalEvidencePersistenceError(
            "Could not persist the canonical proof relationship."
        ) from exc


def _conflicting_direct_relationship(
    db: Any, *, user_id: str, proof_type: str, proof_id: str, project_id: str
) -> dict[str, Any] | None:
    for row in _table_rows(
        db,
        "proof_project_relationships",
        {"owner_user_id": user_id, "proof_type": proof_type, "proof_id": proof_id},
    ):
        if (
            row.get("relationship_state") == "directly_linked"
            and str(row.get("project_id") or "") != str(project_id)
        ):
            return row
    return None


def _downgrade_identity_invalid_relationship(db: Any, row: dict[str, Any]) -> None:
    """Downgrade a provably-wrong directly_linked edge to ``mismatched_project``.

    A legacy relationship recorded before the repository-identity write gate can
    attach a GitHub proof to a project whose own declared repository contradicts
    the proof's repository. Such an edge is excluded by every canonical read
    path already; downgrading it (state ``mismatched_project``, the 058 schema's
    state for exactly this) stops it from permanently blocking the proof's REAL
    project at the finalization boundary while keeping the row for audit.
    """
    patch = {
        "relationship_state": "mismatched_project",
        "confirmed_by_user": False,
        "provenance": {
            **(row.get("provenance") if isinstance(row.get("provenance"), dict) else {}),
            "downgraded_reason": "repo_identity_conflict",
            "downgraded_at": _now(),
        },
        "updated_at": _now(),
    }
    if isinstance(db, dict):
        row.update(patch)
        return
    db.table("proof_project_relationships").update(patch).eq("id", row["id"]).execute()


def _stamp_artifact_project(
    db: Any, *, user_id: str, proof_type: str, proof_id: str, project_id: str
) -> list[str]:
    """Set project_id on this proof's retained artifacts; conflict fails closed."""
    artifact_ids: list[str] = []
    rows = [
        row
        for row in _table_rows(
            db,
            "proof_artifacts",
            {"owner_user_id": user_id, "proof_type": proof_type, "proof_id": proof_id},
        )
    ]
    for row in rows:
        current = str(row.get("project_id") or "")
        if current and current != str(project_id):
            raise CanonicalEvidenceConflictError(
                "A retained artifact for this proof already belongs to a different project."
            )
    if isinstance(db, dict):
        for row in rows:
            row["project_id"] = project_id
            row["updated_at"] = _now()
            artifact_ids.append(str(row.get("id") or ""))
        return artifact_ids
    try:
        (
            db.table("proof_artifacts")
            .update({"project_id": project_id, "updated_at": _now()})
            .eq("owner_user_id", user_id)
            .eq("proof_type", proof_type)
            .eq("proof_id", proof_id)
            .execute()
        )
    except Exception:  # pragma: no cover - artifact table availability is additive
        pass
    return [str(row.get("id") or "") for row in rows]


def _upsert_skill_claims_and_links(
    db: Any,
    *,
    project: dict[str, Any],
    proof_type: str,
    proof_id: str,
    supported_skills: list[str],
    pending_skills: list[str],
    context_skills: list[str],
    citation_type: str,
    counted_quality: str,
    link_reason: str,
    pending_reason: str,
) -> tuple[int, int]:
    """Upsert vbr_project_skill_claims + vbr_claim_evidence_links (idempotent).

    Returns ``(claim_link_count, counted_link_count)``. Claims are only ever
    upgraded (claimed → partially_demonstrated/demonstrated); this function
    never downgrades a claim another proof already supported. On a pre-058
    database the write is skipped silently — reports keep deriving the same
    facts from source rows.
    """
    project_id = str(project.get("id") or "")
    project_title = str(project.get("title") or "Project")
    entries: list[tuple[str, str, str, str]] = []  # (skill, status, quality, reason)
    for skill in supported_skills:
        entries.append((skill, "counted", counted_quality, link_reason))
    for skill in pending_skills:
        entries.append((skill, "pending", "insufficient", pending_reason))
    for skill in context_skills:
        entries.append((skill, "excluded", "context", pending_reason))
    if not entries:
        return (0, 0)

    def _claim_rows() -> list[dict[str, Any]]:
        return _table_rows(db, "vbr_project_skill_claims", {"project_id": project_id})

    try:
        existing_claims = {
            _norm_skill(row.get("skill_key") or row.get("skill_name")): row
            for row in _claim_rows()
        }
        link_count = 0
        counted_count = 0
        for skill, status, quality, reason in entries:
            key = _norm_skill(skill)
            if not key:
                continue
            claim = existing_claims.get(key)
            desired_status = (
                "demonstrated"
                if status == "counted" and quality == "primary"
                else "partially_demonstrated"
                if status == "counted"
                else "not_assessed"
            )
            if claim is None:
                claim = {
                    "project_id": project_id,
                    "skill_key": key,
                    "skill_name": str(skill).strip(),
                    # PROJECT-scoped by construction: the sentence asserts what
                    # the project's artifacts show, never who built it.
                    # Candidate attribution is a separate claim with its own
                    # evidence bar (see candidate_attribution_service).
                    "claim_text": f"{str(skill).strip()} is demonstrated in the project {project_title}.",
                    "claim_state": "claimed",
                    "evidence_status": desired_status if status == "counted" else "not_assessed",
                }
                if isinstance(db, dict):
                    claim_id = f"claim:{project_id}:{key}"
                    claim = {"id": claim_id, **claim, "created_at": _now(), "updated_at": _now()}
                    db.setdefault("vbr_project_skill_claims", {})[claim_id] = claim
                else:
                    response = db.table("vbr_project_skill_claims").insert(claim).execute()
                    rows = list(getattr(response, "data", []) or [])
                    claim = rows[0] if rows else claim
                existing_claims[key] = claim
            elif status == "counted":
                ladder = ["not_assessed", "insufficient_evidence", "partially_demonstrated", "demonstrated"]
                current = str(claim.get("evidence_status") or "not_assessed")
                if ladder.index(desired_status) > (
                    ladder.index(current) if current in ladder else 0
                ):
                    if isinstance(db, dict):
                        claim["evidence_status"] = desired_status
                        claim["updated_at"] = _now()
                    else:
                        (
                            db.table("vbr_project_skill_claims")
                            .update({"evidence_status": desired_status, "updated_at": _now()})
                            .eq("id", claim["id"])
                            .execute()
                        )

            claim_id = str(claim.get("id") or "")
            if not claim_id:
                continue
            link = {
                "project_skill_claim_id": claim_id,
                "proof_type": proof_type,
                "proof_id": proof_id,
                "citation_type": citation_type,
                "link_status": status if status in ("counted", "pending", "excluded") else "pending",
                "evidence_quality": quality,
                "link_reason": reason,
                "limitations": [],
            }
            existing_links = [
                row
                for row in _table_rows(
                    db,
                    "vbr_claim_evidence_links",
                    {
                        "project_skill_claim_id": claim_id,
                        "proof_type": proof_type,
                        "proof_id": proof_id,
                        "citation_type": citation_type,
                    },
                )
            ]
            if existing_links:
                link_count += 1
                counted_count += 1 if existing_links[0].get("link_status") == "counted" else 0
                continue
            if isinstance(db, dict):
                link_id = f"link:{claim_id}:{proof_type}:{proof_id}:{citation_type}"
                db.setdefault("vbr_claim_evidence_links", {})[link_id] = {
                    "id": link_id,
                    **link,
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            else:
                db.table("vbr_claim_evidence_links").insert(link).execute()
            link_count += 1
            counted_count += 1 if status == "counted" else 0
        return (link_count, counted_count)
    except Exception as exc:
        message = str(exc).lower()
        if "vbr_project_skill_claims" in message or "vbr_claim_evidence_links" in message:
            return (0, 0)  # pre-058 database
        raise CanonicalEvidencePersistenceError(
            "Could not persist project-skill claims / claim-evidence links."
        ) from exc


def _relationship_descriptor(project: dict[str, Any], match_method: str, reason: str) -> dict[str, Any]:
    return {
        "state": "directly_linked",
        "project_id": str(project.get("id") or ""),
        "project_title": str(project.get("title") or "Project"),
        "match_method": match_method,
        "counted": True,
        "confirmed_by_user": True,
        "reasons": [reason],
        "action_label": None,
    }


def finalize_proof_evidence(
    db: Any,
    *,
    user_id: str,
    proof_type: str,
    proof_id: str,
    project_id: str,
    pipeline_db: Any = None,
) -> dict[str, Any]:
    """Finalize one owned proof against one owned project.

    Validates owner → project → proof → artifact → analysis ownership, persists
    the proof-project relationship (legacy metadata + normalized 058 rows),
    stamps retained artifacts, upserts project-skill claims and claim-evidence
    links for the skills this proof's stored analysis actually supports, and
    returns an explicit, honest finalization result. Idempotent: repeating it
    changes nothing and reports the same counts.
    """
    if proof_type not in SUPPORTED_PROOF_TYPES:
        raise ValueError(
            f"Unsupported proof type '{proof_type}'. Supported: {', '.join(SUPPORTED_PROOF_TYPES)}."
        )
    project = _owned_project(db, project_id, user_id)
    already_finalized = False
    existing_finalized_at: str | None = None
    if proof_type == "website":
        already_finalized, existing_finalized_at = _website_finalization_state(
            db,
            user_id=user_id,
            proof_id=proof_id,
            project_id=project_id,
        )
    warnings: list[str] = []
    claimed = [
        str(s).strip()
        for s in ((project.get("metadata") or {}).get("claimed_skills") or [])
        if str(s).strip()
    ]

    if proof_type == "website":
        website_session = _owned_row(
            db, "extension_proof_sessions", proof_id, user_id, user_key="user_id"
        )
        relationship = confirm_project_relationship(
            db, user_id=user_id, proof_type="website", proof_id=proof_id, project_id=project_id
        )
        analysis_rows = [
            row
            for row in _table_rows(
                db, "workflow_analysis_results", {"user_id": user_id, "proof_session_id": proof_id}
            )
        ]
        supported = sorted(
            {
                str(skill).strip()
                for row in analysis_rows
                for skill in (row.get("supported_skills") or [])
                if str(skill).strip()
            }
        )
        evidence_item_count = len(analysis_rows)
        if not analysis_rows:
            warnings.append("No completed Website analysis was found; skill links stay pending.")
        artifact_ids = _stamp_artifact_project(
            db, user_id=user_id, proof_type="website", proof_id=proof_id, project_id=project_id
        )
        link_count, counted_links = _upsert_skill_claims_and_links(
            db,
            project=project,
            proof_type="website",
            proof_id=proof_id,
            supported_skills=supported,
            pending_skills=[] if analysis_rows else claimed,
            context_skills=[],
            citation_type="website_workflow",
            counted_quality="supporting",
            link_reason="The recorded workflow demonstrates this skill at runtime (identity-validated at read time).",
            pending_reason="Website analysis has not mapped this claimed skill yet.",
        )
        # Canonical Website Proof finalization is also the write boundary for
        # the student's Skill Graph.  The dedicated sync endpoint remains
        # useful for repair/replay, but requiring the client to make a second
        # best-effort request left successfully finalized proofs absent from
        # skill_evidence_pipelines.  Run the idempotent sync here so a single
        # Save action cannot report success with a stale Skill Graph.
        if pipeline_db is not None and analysis_rows and supported:
            from app.services.website_proof_artifact_sync_service import (
                WebsiteProofArtifactSyncService,
            )

            sync_result = WebsiteProofArtifactSyncService(
                db=db,
                pipeline_db=pipeline_db,
            ).sync(user_id=user_id, proof_session_id=proof_id)
            if sync_result.errors:
                raise CanonicalEvidencePersistenceError(
                    "Could not sync the finalized Website Proof to the Skill Graph: "
                    + "; ".join(sync_result.errors)
                )
        _merge_website_claimed_skills_into_project(
            db,
            project=project,
            session=website_session,
        )
    elif proof_type == "document":
        from app.services.optional_evidence_service import OptionalEvidenceService

        submission = OptionalEvidenceService(db).get_by_id(user_id=user_id, evidence_id=proof_id)
        if submission is None:
            raise CanonicalEvidenceNotFoundError(proof_id)
        if str(submission.get("status") or "") not in ("analyzed", "needs_review"):
            raise CanonicalEvidencePreconditionError(
                "Only an analyzed document can be attached to a project."
            )
        conflict = _conflicting_direct_relationship(
            db, user_id=user_id, proof_type="document", proof_id=proof_id, project_id=project_id
        )
        if conflict is None:
            for other in _table_rows(db, "vbr_projects", {"user_id": user_id}):
                if str(other.get("id") or "") == str(project_id):
                    continue
                attached = ((other.get("metadata") or {}).get("attached_proofs") or {})
                for doc in attached.get("documents") or []:
                    if str((doc or {}).get("document_evidence_id") or "") == str(proof_id):
                        conflict = other
                        break
        if conflict is not None:
            raise CanonicalEvidenceConflictError(
                "This document is already attached to a different project."
            )
        # Merge the safe document summary into the project's attached proofs —
        # the SAME canonical edge the existing attach flow writes.
        from app.services.vbr_project_defense import attach_proofs_to_project

        class _AttachShim:
            github_proof_id = None
            website_proof_session_ids: list[str] = []
            skill_pipeline_ids: list[str] = []
            document_evidence_ids = [proof_id]

        attach_proofs_to_project(db, pipeline_db, user_id, project, _AttachShim())
        _upsert_relationship_row(
            db,
            user_id=user_id,
            proof_type="document",
            proof_id=proof_id,
            project_id=project_id,
            match_method="user_confirmation",
            provenance={"source": "document_attach_finalization"},
        )
        artifact_ids = _stamp_artifact_project(
            db, user_id=user_id, proof_type="document", proof_id=proof_id, project_id=project_id
        )
        objects = [o for o in (submission.get("evidence_objects") or []) if isinstance(o, dict)]
        evidence_item_count = len(objects)
        supported_set: dict[str, bool] = {}
        for obj in objects:
            skill = str(obj.get("skill_name") or "").strip()
            if not skill:
                continue
            has_locator = document_evidence_object_has_locator(obj)
            supported_set[skill] = supported_set.get(skill, False) or has_locator
        supported = sorted(s for s, ok in supported_set.items() if ok)
        keyword_only = sorted(s for s, ok in supported_set.items() if not ok)
        if keyword_only:
            warnings.append(
                "Skills mentioned only as keywords (no page/section/block locator) are not counted: "
                + ", ".join(keyword_only[:8])
                + "."
            )
        relationship = _relationship_descriptor(
            project,
            "user_confirmation",
            "The student confirmed this document belongs to the selected project.",
        )
        link_count, counted_links = _upsert_skill_claims_and_links(
            db,
            project=project,
            proof_type="document",
            proof_id=proof_id,
            supported_skills=supported,
            pending_skills=[],
            context_skills=keyword_only,
            citation_type="document_block",
            counted_quality="supporting",
            link_reason="The document cites this skill at an exact page/section/block locator.",
            pending_reason="The document mentions this skill without an exact source locator; it stays context-only.",
        )
    elif proof_type == "github":
        rows = _table_rows(db, "github_proof_submissions", {"id": proof_id, "user_id": user_id})
        if not rows:
            raise CanonicalEvidenceNotFoundError(proof_id)
        proof = rows[0]
        # Repository-identity integrity gate: a GitHub Proof may only be
        # finalized against a project whose declared repository it matches.
        # Without this, attaching proof A while typing project repo B silently
        # records a contradictory edge that leaks an unrelated repository into
        # the project's defense/report/passport views.
        from app.services.canonical_project_evidence import (
            github_identity_conflict,
            project_repo_identity,
        )

        if github_identity_conflict(project_repo_identity(project), proof.get("repo_url")):
            raise CanonicalEvidencePreconditionError(
                "This GitHub Proof's repository does not match the selected project's "
                "repository. Attach the GitHub Proof for the project's own repository, "
                "or select/create the project that matches this proof."
            )
        conflict = _conflicting_direct_relationship(
            db, user_id=user_id, proof_type="github", proof_id=proof_id, project_id=project_id
        )
        if conflict is not None:
            # A legacy directly_linked edge that contradicts ITS OWN project's
            # repository identity (recorded before the identity write gate) is
            # provably wrong — downgrade it instead of letting it permanently
            # block this proof's real project.
            conflict_project_rows = _table_rows(
                db, "vbr_projects", {"id": str(conflict.get("project_id") or ""), "user_id": user_id}
            )
            conflict_project = conflict_project_rows[0] if conflict_project_rows else {}
            if github_identity_conflict(
                project_repo_identity(conflict_project), proof.get("repo_url")
            ):
                _downgrade_identity_invalid_relationship(db, conflict)
                conflict = None
        if conflict is not None:
            raise CanonicalEvidenceConflictError(
                "This GitHub Proof already has a direct relationship to another project."
            )
        from app.services.vbr_project_defense import attach_proofs_to_project

        class _GitHubShim:
            github_proof_id = proof_id
            website_proof_session_ids: list[str] = []
            skill_pipeline_ids: list[str] = []
            document_evidence_ids: list[str] = []

        attach_proofs_to_project(db, pipeline_db, user_id, project, _GitHubShim())
        _upsert_relationship_row(
            db,
            user_id=user_id,
            proof_type="github",
            proof_id=proof_id,
            project_id=project_id,
            match_method="user_confirmation",
            provenance={"source": "github_attach_finalization"},
        )
        artifact_ids = _stamp_artifact_project(
            db, user_id=user_id, proof_type="github", proof_id=proof_id, project_id=project_id
        )
        snapshot = proof.get("analysis_snapshot") if isinstance(proof.get("analysis_snapshot"), dict) else {}
        line_level = [
            item
            for item in (snapshot.get("skill_code_evidence") or [])
            if isinstance(item, dict) and item.get("file_path") and item.get("line_start")
        ]
        evidence_item_count = len(line_level)
        # Countability contract at the canonical write path: a skill claim may
        # only be linked as COUNTED when at least one of its line-level items
        # validates as a strong code body with a concretely resolved purpose.
        # A line item whose snippet grades weak (imports / docstring / config /
        # sliced fragment) or whose purpose cannot be determined stays context.
        supported_set: set[str] = set()
        unvalidated_set: set[str] = set()
        for item in line_level:
            item_skill = str(item.get("skill") or "").strip()
            if not item_skill:
                continue
            item_grade = grade_evidence(
                file_path=str(item.get("file_path") or "") or None,
                code_snippet=str(item.get("code_snippet") or "") or None,
                selection_reason=str(item.get("reason") or "") or None,
                line_start=item.get("line_start"),
                line_end=item.get("line_end"),
            )
            item_purpose = classify_code_block_purpose(
                grade=item_grade,
                code_snippet=str(item.get("code_snippet") or "") or None,
                file_path=str(item.get("file_path") or "") or None,
            )
            if is_strong_grade(item_grade) and is_countable_code_purpose(item_purpose):
                supported_set.add(item_skill)
            else:
                unvalidated_set.add(item_skill)
        supported = sorted(supported_set)
        unvalidated_only = sorted(unvalidated_set - supported_set)
        if unvalidated_only:
            warnings.append(
                "Line-level items whose code body or purpose could not be validated "
                "stay context-only: " + ", ".join(unvalidated_only[:8]) + "."
            )
        detected_only = sorted(
            (
                {
                    str(s).strip()
                    for s in (proof.get("detected_skills") or [])
                    if str(s).strip() and str(s).strip() not in supported
                }
                | set(unvalidated_only)
            )
        )
        if detected_only:
            warnings.append(
                "Repo-level detected skills without validated line evidence stay context-only: "
                + ", ".join(detected_only[:8])
                + "."
            )
        relationship = _relationship_descriptor(
            project,
            "user_confirmation",
            "The student confirmed this GitHub Proof belongs to the selected project.",
        )
        link_count, counted_links = _upsert_skill_claims_and_links(
            db,
            project=project,
            proof_type="github",
            proof_id=proof_id,
            supported_skills=supported,
            pending_skills=[],
            context_skills=detected_only,
            citation_type="github_code_lines",
            counted_quality="primary",
            link_reason="Validated line-level code evidence supports this skill.",
            pending_reason="Detected at repository level only — context, not implementation proof.",
        )
    elif proof_type == "project_defense":
        sessions = _table_rows(db, "vbr_verification_sessions", {"id": proof_id})
        if not sessions:
            raise CanonicalEvidenceNotFoundError(proof_id)
        session = sessions[0]
        session_project = str(session.get("project_id") or "")
        # Ownership is transitive through the owned project the session was
        # created for; a session belonging to a different project is rejected.
        if session_project != str(project_id):
            raise CanonicalEvidenceConflictError(
                "This defense session belongs to a different project."
            )
        _upsert_relationship_row(
            db,
            user_id=user_id,
            proof_type="project_defense",
            proof_id=proof_id,
            project_id=project_id,
            match_method="explicit_project_id",
            provenance={"source": "defense_session_project_binding"},
        )
        artifact_ids = _stamp_artifact_project(
            db, user_id=user_id, proof_type="project_defense", proof_id=proof_id, project_id=project_id
        )
        telemetry = session.get("telemetry") if isinstance(session.get("telemetry"), dict) else {}
        analysis = telemetry.get("project_defense_analysis")
        analyzed_skills: list[str] = []
        if isinstance(analysis, dict):
            analyzed_skills = sorted(
                {
                    str(s).strip()
                    for s in (analysis.get("skills_explained_well") or [])
                    if str(s).strip()
                }
            )
        evidence_item_count = len(analyzed_skills)
        pending = [] if isinstance(analysis, dict) else claimed
        if not isinstance(analysis, dict):
            warnings.append(
                "Defense captured but not yet analyzed — it is visible, never counted, until Q/A analysis runs."
            )
        relationship = _relationship_descriptor(
            project,
            "explicit_project_id",
            "This defense session was created for this project.",
        )
        link_count, counted_links = _upsert_skill_claims_and_links(
            db,
            project=project,
            proof_type="project_defense",
            proof_id=proof_id,
            supported_skills=analyzed_skills,
            pending_skills=pending,
            context_skills=[],
            citation_type="defense_answer",
            counted_quality="supporting",
            link_reason="An analyzed defense answer explains this skill in the student's own words.",
            pending_reason="Defense analysis is pending; answers are not counted as skill evidence yet.",
        )
    else:  # video
        rows = _table_rows(db, "video_proofs", {"id": proof_id, "user_id": user_id})
        if not rows:
            raise CanonicalEvidenceNotFoundError(proof_id)
        video = rows[0]
        current_project = str(video.get("project_id") or "")
        if current_project and current_project != str(project_id):
            raise CanonicalEvidenceConflictError(
                "This Video Proof already belongs to a different project."
            )
        _upsert_relationship_row(
            db,
            user_id=user_id,
            proof_type="video",
            proof_id=proof_id,
            project_id=project_id,
            match_method="user_confirmation",
            provenance={"source": "video_attach_finalization"},
        )
        if isinstance(db, dict):
            video["project_id"] = project_id
            video["updated_at"] = _now()
        else:
            (
                db.table("video_proofs")
                .update({"project_id": project_id, "updated_at": _now()})
                .eq("id", proof_id)
                .eq("user_id", user_id)
                .execute()
            )
        artifact_ids = _stamp_artifact_project(
            db, user_id=user_id, proof_type="video", proof_id=proof_id, project_id=project_id
        )
        evidence_item_count = 1
        # A demo video is a citation layer, never an independent proof source —
        # it must not create counted claim links of its own.
        video_skills = sorted(
            {str(s).strip() for s in (video.get("claimed_skills") or []) if str(s).strip()}
        )
        warnings.append(
            "Video evidence is a citation layer (timestamps into a recording); it never counts as an "
            "independent proof source."
        )
        relationship = _relationship_descriptor(
            project,
            "user_confirmation",
            "The student confirmed this Video Proof belongs to the selected project.",
        )
        link_count, counted_links = _upsert_skill_claims_and_links(
            db,
            project=project,
            proof_type="video",
            proof_id=proof_id,
            supported_skills=[],
            pending_skills=[],
            context_skills=video_skills,
            citation_type="video_timestamp",
            counted_quality="context",
            link_reason="",
            pending_reason="A demo video shows behaviour but does not by itself verify a skill.",
        )

    supported_count = counted_links
    unsupported_count = max(0, len({_norm_skill(s) for s in claimed}) - supported_count) if claimed else 0
    if counted_links > 0:
        eligibility = "report_ready"
    elif evidence_item_count > 0 or link_count > 0:
        eligibility = "skill_mapped" if link_count > 0 else "project_attached"
    else:
        eligibility = "project_attached"
    finalized_at: str | None = None
    if proof_type == "website":
        finalized_at = _mark_website_finalized(
            db,
            user_id=user_id,
            proof_id=proof_id,
            project_id=project_id,
            existing_finalized_at=existing_finalized_at if already_finalized else None,
        )
    return {
        "proof_id": proof_id,
        "proof_type": proof_type,
        "project_id": str(project_id),
        "project_relationship": relationship,
        "evidence_item_count": evidence_item_count,
        "supported_skill_count": supported_count,
        "unsupported_skill_count": unsupported_count,
        "claim_link_count": link_count,
        "artifact_ids": artifact_ids,
        "report_eligibility": eligibility,
        "warnings": warnings,
        "failure_category": None,
        "already_finalized": already_finalized,
        "finalized_at": finalized_at,
    }


__all__ = [
    "CanonicalEvidenceConflictError",
    "CanonicalEvidenceNotFoundError",
    "CanonicalEvidencePersistenceError",
    "CanonicalEvidencePreconditionError",
    "SUPPORTED_PROOF_TYPES",
    "confirm_project_relationship",
    "document_evidence_object_has_locator",
    "finalize_proof_evidence",
]
