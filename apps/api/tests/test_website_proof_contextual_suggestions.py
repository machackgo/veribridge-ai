"""Website Proof V1.0.1 — contextual analysis suggestions (Bug 5).

GitHub/source-code guidance must be contextual, never universal:

* a generic Website Proof (research, operations, walking through a public
  website) is never told it is "missing" a GitHub repository — absence of
  GitHub evidence is not absence of skill;
* code/software-oriented claims, code-evidence-class skills, and recordings of
  the student's own locally-running app keep the GitHub guidance;
* an explicitly provided repository keeps its "was not visited"/"run analysis"
  follow-ups regardless of the claimed skill mix.

Also pins the website finalization ownership boundary used by the V1.0.1
completion flow (attach requires an owned proof AND an owned project).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.extension_proof_workflow_analysis_service import (
    _build_suggestions,
    _determine_missing_evidence,
    _has_software_oriented_claim,
    _is_software_oriented_skill,
)
from app.services.canonical_evidence_service import (
    CanonicalEvidenceNotFoundError,
    finalize_proof_evidence,
)

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER = "00000000-0000-0000-0000-00000000beef"


# ── Software-oriented skill classification ───────────────────────────────────


def test_software_oriented_classification_matches_code_skills_only() -> None:
    for skill in [
        "React", "JavaScript", "TypeScript", "Python", "FastAPI",
        "Full Stack Development", "Web Development", "Open Source",
        "REST API Design", "SQL",
    ]:
        assert _is_software_oriented_skill(skill), skill
    for skill in [
        "Research", "Information Literacy", "Technical Writing",
        "Customer Operations", "Rapid Prototyping", "Data Entry",
        "Logistics", "Marketing Strategy", "",
    ]:
        assert not _is_software_oriented_skill(skill), skill
    assert _has_software_oriented_claim(["Research", "React"]) is True
    assert _has_software_oriented_claim(["Research", "Marketing Strategy"]) is False


# ── Missing evidence ─────────────────────────────────────────────────────────


def _missing(claimed: list[str], *, url_type: str = "public_url", github_url: str | None = None,
             weakly: list[str] | None = None, skill_obs: dict[str, str] | None = None) -> list[str]:
    return _determine_missing_evidence(
        claimed,
        [],  # supported
        weakly or [],
        url_type,
        github_url,
        ["https://en.wikipedia.org/wiki/Alan_Turing"],
        skill_obs or {},
        supporting_visited_urls=[],
        frame_ocr_evidence_summary={},
    )


def test_non_code_public_site_proof_is_not_missing_github() -> None:
    missing = _missing(["Research", "Information Literacy"])
    assert not any("github" in m.lower() for m in missing), missing


def test_code_oriented_claim_without_repo_still_flags_github() -> None:
    missing = _missing(["React", "JavaScript"])
    assert any("GitHub repository URL for source code evidence" in m for m in missing)


def test_code_evidence_class_skill_flags_github_even_when_claim_wording_is_soft() -> None:
    missing = _missing(
        ["Machine Learning"],
        weakly=["Machine Learning"],
        skill_obs={"Machine Learning": "requires_code_evidence"},
    )
    assert any("github" in m.lower() for m in missing)


def test_localhost_recording_keeps_github_guidance_for_any_claim() -> None:
    # A locally-running app is the student's own build — source guidance applies.
    missing = _missing(["Product Walkthrough"], url_type="localhost_url")
    assert any("GitHub repository URL for source code evidence" in m for m in missing)


def test_provided_but_unvisited_repo_note_is_kept_for_non_code_claims() -> None:
    missing = _missing(["Research"], github_url="https://github.com/acme/notes")
    assert any("GitHub repository was not visited" in m for m in missing)


# ── Student improvement suggestions ──────────────────────────────────────────


def _suggestions(supported: list[str], weakly: list[str], unsupported: list[str], *,
                 url_type: str = "public_url", github_url: str | None = None,
                 skill_obs: dict[str, str] | None = None) -> list[str]:
    return _build_suggestions(
        url_type,
        200.0,   # duration
        25, 12, 6,  # events / clicks / inputs
        supported,
        weakly,
        unsupported,
        github_url,
        skill_obs or {},
    )


def test_non_code_proof_gets_no_github_suggestion() -> None:
    suggestions = _suggestions(["Research"], [], [])
    assert not any("github" in s.lower() for s in suggestions), suggestions


def test_code_proof_without_repo_keeps_github_suggestion() -> None:
    suggestions = _suggestions(["React"], [], [])
    assert any("Add a GitHub repository URL" in s for s in suggestions)


def test_code_evidence_class_weak_skill_keeps_specific_repo_suggestion() -> None:
    suggestions = _suggestions(
        [], ["FastAPI"], [],
        skill_obs={"FastAPI": "requires_code_evidence"},
    )
    assert any("require repository analysis" in s for s in suggestions)


def test_localhost_proof_keeps_github_suggestion_even_for_non_code_claims() -> None:
    suggestions = _suggestions(["Product Walkthrough"], [], [], url_type="localhost_url")
    assert any("Add a GitHub repository URL" in s for s in suggestions)


# ── Website finalization ownership boundary (completion flow) ────────────────


def _mem_website_proof(store: dict, *, user_id: str = USER_ID) -> str:
    proof_id = str(uuid4())
    store.setdefault("extension_proof_sessions", {})[proof_id] = {
        "id": proof_id,
        "user_id": user_id,
        "skill_evidence_id": str(uuid4()),
        "status": "completed",
        "website_url": "https://en.wikipedia.org/",
        "claimed_skills": ["Research"],
        "proof_objective": "Demonstrate the research workflow",
        "metadata": {},
        "created_at": "2026-08-20T10:00:00+00:00",
        "updated_at": "2026-08-20T10:10:00+00:00",
    }
    return proof_id


def _mem_project(store: dict, *, user_id: str) -> str:
    project_id = str(uuid4())
    store.setdefault("vbr_projects", {})[project_id] = {
        "id": project_id,
        "user_id": user_id,
        "title": "Owned Project",
        "repo_url": "https://github.com/veribridge/veribridge",
        "repo_full_name": "veribridge/veribridge",
        "status": "draft",
        "metadata": {"claimed_skills": ["Research"], "attached_proofs": {}},
    }
    return project_id


def test_website_proof_cannot_attach_to_another_students_project() -> None:
    store: dict = {}
    proof_id = _mem_website_proof(store, user_id=USER_ID)
    foreign_project = _mem_project(store, user_id=OTHER_USER)
    with pytest.raises(CanonicalEvidenceNotFoundError):
        finalize_proof_evidence(
            store,
            user_id=USER_ID,
            proof_type="website",
            proof_id=proof_id,
            project_id=foreign_project,
        )


def test_another_student_cannot_attach_someone_elses_website_proof() -> None:
    store: dict = {}
    proof_id = _mem_website_proof(store, user_id=OTHER_USER)
    own_project = _mem_project(store, user_id=USER_ID)
    with pytest.raises(CanonicalEvidenceNotFoundError):
        finalize_proof_evidence(
            store,
            user_id=USER_ID,
            proof_type="website",
            proof_id=proof_id,
            project_id=own_project,
        )
