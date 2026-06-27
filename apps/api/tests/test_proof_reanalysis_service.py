"""Tests for the Backfill / Reanalysis service (Step 6).

The reanalysis service is the EXPLICIT, controlled counterpart to the read-time
Steps 2–4 pipeline: it walks a student's already-safe proofs and re-runs
normalization (Step 2) → linking (Step 3) → optional synthesis (Step 4) over
them, reporting what would be (or was) regenerated. It must:

* preserve old precise GitHub code as ``precise_code`` and keep a repo-level
  fallback weaker (and flag it stale);
* keep documents corroboration-only;
* normalize website / defense evidence from safe summaries only (never raw
  DOM / OCR / provider JSON / transcript dumps);
* rebuild linked proof chains with the Step-3 linker;
* run the Step-4 LLM layer ONLY when ``include_llm_synthesis`` is true (and never
  call an LLM otherwise);
* mark stale/weak evidence with a safe reason + recommended action;
* never leak storage paths / signed URLs / private ids / raw payloads;
* be idempotent (repeated dry-runs → stable counts).

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.evidence_normalization_service import (
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    STRENGTH_CORROBORATION,
    STRENGTH_PRECISE_CODE,
    STRENGTH_REPO_LEVEL,
    normalize_skill_report,
)
from app.services.proof_reanalysis_service import (
    ProofReanalysisRequest,
    StaleEvidenceMarker,
    reanalyze_student_proofs,
)
from app.services.student_proof_vault_service import collect_skill_report

from tests.test_vbr_project_defense import (
    USER_ID,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_workflow_analysis,
)

_SESSIONS_TABLE = "vbr_verification_sessions"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


# ── Seed helpers (mirror test_proof_synthesis_agent_service) ──────────────────


def _seed_project(
    mem_store: dict,
    *,
    title: str,
    repo_full_name: str | None = None,
    attached_proofs: dict | None = None,
) -> str:
    pid = str(uuid4())
    mem_store.setdefault("vbr_projects", {})[pid] = {
        "id": pid,
        "user_id": USER_ID,
        "title": title,
        "repo_full_name": repo_full_name,
        "repo_url": f"https://github.com/{repo_full_name}" if repo_full_name else None,
        "metadata": {"attached_proofs": attached_proofs or {}},
        "created_at": "2026-01-01T00:00:00Z",
    }
    return pid


def _seed_defense_session(
    mem_store: dict,
    *,
    project_id: str,
    skills_explained: list[str],
    summary: str = "The candidate clearly explained how the prediction route works.",
) -> str:
    session_id = str(uuid4())
    mem_store.setdefault(_SESSIONS_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": USER_ID,
        "project_id": project_id,
        "attempt_no": 1,
        "telemetry": {
            "project_defense_analysis": {
                "skills_explained_well": skills_explained,
                "skills_mentioned": [],
                "recruiter_summary": summary,
            }
        },
        "created_at": "2026-01-01T00:00:00Z",
    }
    return session_id


def _strong_github(mem_store: dict, skill: str = "Python") -> str:
    """Precise, line-level GitHub code evidence (preserved as ``precise_code``)."""
    return _seed_github_proof(
        mem_store,
        detected_skills=[skill],
        analysis_snapshot={
            "raw_dump": "should-never-leak",
            "skill_code_evidence": [
                {
                    "skill": skill,
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ],
        },
    )


def _weak_github(mem_store: dict, skill: str = "Python") -> str:
    """Import-only GitHub evidence → repo-level fallback (no precise line)."""
    return _seed_github_proof(
        mem_store,
        detected_skills=[skill],
        analysis_snapshot={
            "raw_dump": "should-never-leak",
            "skill_code_evidence": [
                {
                    "skill": skill,
                    "file_path": "api.py",
                    "line_start": 6,
                    "line_end": 9,
                    "code_snippet": "import sys\nimport io",
                }
            ],
        },
    )


def _strong_project(mem_store: dict, gh_id: str, *, title: str = "Boston Smart Rerouting") -> str:
    return _seed_project(
        mem_store,
        title=title,
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": gh_id}},
    )


# ── 1. Dry-run returns expected counts and persists nothing ───────────────────


def test_dry_run_reports_counts_and_does_not_persist(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    pid = _strong_project(mem_store, gh_id)

    # Snapshot the seeded source rows (the dict-DB read path may create empty
    # bucket keys for tables it queries — that is not persistence by reanalysis;
    # what must stay untouched is the actual seeded proof/project DATA).
    gh_before = dict(mem_store["github_proof_submissions"][gh_id])
    project_before = dict(mem_store["vbr_projects"][pid])

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)

    assert result.dry_run is True
    assert result.normalized_evidence_count >= 1
    assert result.linked_chain_count >= 1
    assert result.processed_proof_counts.get(SOURCE_GITHUB, 0) >= 1
    # The dry-run mutated none of the seeded source rows.
    assert mem_store["github_proof_submissions"][gh_id] == gh_before
    assert mem_store["vbr_projects"][pid] == project_before


# ── 2. Old GitHub precise line evidence is preserved ──────────────────────────


def test_precise_github_line_evidence_is_preserved(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    _strong_project(mem_store, gh_id)

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    artifacts = normalize_skill_report(report)
    github = [a for a in artifacts if a.source_type == SOURCE_GITHUB]
    assert any(a.proof_strength == STRENGTH_PRECISE_CODE for a in github), (
        "precise, line-level GitHub code must stay precise_code after reanalysis"
    )

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    # Precise code is healthy → not flagged stale.
    assert all(m.source_type != SOURCE_GITHUB for m in result.stale_evidence) or all(
        "repository-level" not in m.reason for m in result.stale_evidence
    )


# ── 3. Repo-level fallback stays weaker than precise code, and is flagged ──────


def test_repo_level_fallback_is_weaker_and_flagged_stale(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _weak_github(mem_store, "Python")
    _strong_project(mem_store, gh_id)

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    github = [a for a in normalize_skill_report(report) if a.source_type == SOURCE_GITHUB]
    assert github and all(a.proof_strength == STRENGTH_REPO_LEVEL for a in github)
    assert all(a.proof_strength != STRENGTH_PRECISE_CODE for a in github)

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    assert result.stale_evidence_count >= 1
    repo_markers = [m for m in result.stale_evidence if m.source_type == SOURCE_GITHUB]
    assert repo_markers, "repo-level GitHub fallback must be flagged stale"
    assert "repository-level" in repo_markers[0].reason
    assert repo_markers[0].recommended_action


# ── 4. Document evidence stays corroboration-only ─────────────────────────────


def test_document_evidence_stays_corroboration_only(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    doc_id = _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Report"},
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "prediction API", "page_number": 2}
        ],
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [{"document_evidence_id": doc_id}],
        },
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    docs = [a for a in normalize_skill_report(report) if a.source_type == SOURCE_DOCUMENT]
    assert docs, "document evidence should be present"
    assert all(a.proof_strength == STRENGTH_CORROBORATION for a in docs)
    assert all(a.public_safe is False for a in docs)

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    # Documents are corroboration-only by design — never flagged as stale evidence.
    assert all(m.source_type != SOURCE_DOCUMENT for m in result.stale_evidence)


# ── 5. Website evidence normalized from safe summaries; no raw DOM/OCR/JSON ────


def test_website_evidence_is_safe_summary_only(mem_store: dict, pipeline_db: dict) -> None:
    session_id = _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Python"],
        # Hostile raw fields that must never reach normalized output.
        raw_dom="<html>secret_dom_dump</html>",
        ocr_text="secret_ocr_dump",
        provider_payload={"raw": "secret_provider_json"},
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"website_proofs": [{"proof_session_id": session_id}]},
    )

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    blob = str(result.to_dict()).lower()
    for needle in ("secret_dom_dump", "secret_ocr_dump", "secret_provider_json", "raw_dom"):
        assert needle.lower() not in blob, f"website reanalysis leaked {needle!r}"


# ── 6. Defense/video evidence uses safe summary, not raw transcript ───────────


def test_defense_evidence_uses_safe_summary(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    pid = _strong_project(mem_store, gh_id)
    _seed_defense_session(
        mem_store,
        project_id=pid,
        skills_explained=["Python"],
        summary="The candidate explained the prediction route clearly.",
    )
    # Smuggle a raw transcript dump into the session telemetry.
    session = next(iter(mem_store[_SESSIONS_TABLE].values()))
    session["telemetry"]["raw_transcript"] = "RAW_TRANSCRIPT_SHOULD_NEVER_LEAK"

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    assert "raw_transcript_should_never_leak" not in str(result.to_dict()).lower()


# ── 7. Reanalysis rebuilds linked proof chains (Step 3) ───────────────────────


def test_reanalysis_rebuilds_linked_chains(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    session_id = _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    # GitHub + Website for one project link into at least one chain.
    assert result.linked_chain_count >= 1
    assert result.processed_proof_counts.get(SOURCE_GITHUB, 0) >= 1


# ── 8. include_llm_synthesis=false never calls the LLM ────────────────────────


def test_no_llm_synthesis_by_default(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    _strong_project(mem_store, gh_id)

    calls: list[tuple[str, str]] = []

    def _spy(system_prompt: str, user_message: str) -> str | None:
        calls.append((system_prompt, user_message))
        return None

    req = ProofReanalysisRequest(
        student_id=USER_ID, skill_name="python", include_llm_synthesis=False, dry_run=True
    )
    result = reanalyze_student_proofs(mem_store, pipeline_db, req, llm_fn=_spy)
    assert calls == [], "LLM provider must not be called when synthesis is disabled"
    assert result.synthesis_count == 0


# ── 9. include_llm_synthesis=true uses Step 4 with the mocked provider only ────


def test_llm_synthesis_uses_mocked_provider(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    _strong_project(mem_store, gh_id)

    calls: list[tuple[str, str]] = []

    def _mock_llm(system_prompt: str, user_message: str) -> str | None:
        calls.append((system_prompt, user_message))
        # Return invalid JSON → Step 4 falls back deterministically (still safe).
        return "not json"

    req = ProofReanalysisRequest(
        student_id=USER_ID, skill_name="python", include_llm_synthesis=True, dry_run=True
    )
    result = reanalyze_student_proofs(mem_store, pipeline_db, req, llm_fn=_mock_llm)
    assert calls, "the injected provider must be used when synthesis is enabled"
    assert result.synthesis_count >= 1


# ── 10. Stale/weak evidence carries a safe reason + recommended action ────────


def test_stale_marker_has_safe_reason_and_action(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _weak_github(mem_store, "Python")
    _strong_project(mem_store, gh_id)

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    assert result.stale_evidence_count >= 1
    for marker in result.stale_evidence:
        assert marker.evidence_id.startswith("ev_")
        assert marker.reason.strip()
        assert marker.recommended_action.strip()
        # No numeric score / ranking language in the safe reason.
        assert "/100" not in marker.reason


# ── 11. Public-safe result leaks no paths / urls / ids / raw payloads ─────────

_FORBIDDEN = (
    "should-never-leak",
    "secret_token",
    "raw_dump",
    "analysis_snapshot",
    "/storage/v1/object",
    "supabase.co/storage",
    USER_ID,
)


def test_public_safe_result_does_not_leak(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    pid = _strong_project(mem_store, gh_id)
    _seed_document_evidence(
        mem_store, evidence_objects=[{"skill_name": "Python", "confidence": "high", "snippet": "ok"}]
    )
    _seed_workflow_analysis(mem_store, supported_skills=["Python"])

    req = ProofReanalysisRequest(student_id=USER_ID, project_id=pid, dry_run=True)
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    public = result.public_view()
    # The public projection drops student_id and project_id entirely.
    assert "student_id" not in public
    assert "project_id" not in public
    serialized = str(public).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in serialized, f"public result leaked {needle!r}"
    assert "/100" not in serialized
    assert result.public_safe is True


# ── 12. Idempotent repeated dry-runs produce stable counts ────────────────────


def test_repeated_dry_runs_are_idempotent(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    session_id = _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    req = ProofReanalysisRequest(student_id=USER_ID, skill_name="python", dry_run=True)
    first = reanalyze_student_proofs(mem_store, pipeline_db, req)
    second = reanalyze_student_proofs(mem_store, pipeline_db, req)
    assert first.run_id == second.run_id
    assert first.normalized_evidence_count == second.normalized_evidence_count
    assert first.linked_chain_count == second.linked_chain_count
    assert first.stale_evidence_count == second.stale_evidence_count
    assert first.processed_proof_counts == second.processed_proof_counts


# ── 13. Proof-type + project scoping (skips out-of-scope evidence) ────────────


def test_proof_type_scope_filters_and_counts_skips(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    session_id = _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    # Only reanalyze GitHub proofs → website evidence is skipped, not processed.
    req = ProofReanalysisRequest(
        student_id=USER_ID, skill_name="python", proof_types=(SOURCE_GITHUB,), dry_run=True
    )
    result = reanalyze_student_proofs(mem_store, pipeline_db, req)
    assert result.processed_proof_counts.get(SOURCE_GITHUB, 0) >= 1
    assert SOURCE_DOCUMENT not in result.processed_proof_counts
    assert "website" not in result.processed_proof_counts
    assert result.skipped_items >= 1


# ── 14. Authenticated endpoint prevents cross-user reanalysis ─────────────────

_OTHER_USER_ID = "00000000-0000-0000-0000-0000000000ff"


def test_endpoint_prevents_cross_user_reanalysis(mem_store: dict, pipeline_db: dict) -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user_id, get_db, get_pipeline_db
    from app.main import app

    # Seed proofs owned by USER_ID only.
    gh_id = _strong_github(mem_store, "Python")
    _strong_project(mem_store, gh_id)

    # Authenticate as a DIFFERENT user who owns no proofs.
    app.dependency_overrides[get_current_user_id] = lambda: _OTHER_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/student/vbr/passport/reanalyze",
            json={"skill_name": "python", "dry_run": True},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # The other user owns no Python proofs, so nothing is normalized for them —
        # they can never reanalyze USER_ID's proofs.
        assert data["normalized_evidence_count"] == 0
        assert data["linked_chain_count"] == 0
        assert data["processed_proof_counts"] == {}
        # Public projection never echoes a private student/project id.
        assert "student_id" not in data
        assert "project_id" not in data
    finally:
        app.dependency_overrides.clear()


# ── 15. include_llm_synthesis gate: false → 0 provider calls, true → 1 (Step 4) ─


def test_synthesis_gate_controls_provider_calls(monkeypatch, mem_store: dict, pipeline_db: dict) -> None:
    """The Step-6 LLM gate is the ONLY thing that may resolve/call a provider.

    Even with a provider configured in the env (simulated by patching the
    resolver), include_llm_synthesis=False must produce ZERO provider calls — the
    synthesis-free ``collect_skill_report`` path must never reach Step 4. With the
    gate enabled, the provider is called exactly through the explicit Step-6 gate.
    """
    import app.services.llm_proof_synthesis_service as llm_mod

    gh_id = _strong_github(mem_store, "Python")
    _strong_project(mem_store, gh_id)

    provider_calls: list[tuple[str, str]] = []

    def _spy_provider(system_prompt: str, user_message: str) -> str | None:
        provider_calls.append((system_prompt, user_message))
        return None

    # Simulate a configured provider (local_openai / Anthropic) being available.
    monkeypatch.setattr(llm_mod, "_resolve_llm_fn", lambda: _spy_provider)

    # Synthesis OFF and NO injected llm_fn → the provider must never be resolved
    # or called, even though collect_skill_report runs over real proofs.
    off = ProofReanalysisRequest(
        student_id=USER_ID, skill_name="python", include_llm_synthesis=False, dry_run=True
    )
    off_result = reanalyze_student_proofs(mem_store, pipeline_db, off)
    assert provider_calls == [], "synthesis disabled must produce zero provider calls"
    assert off_result.synthesis_count == 0

    # Synthesis ON and NO injected llm_fn → exactly the explicit Step-6 gate calls
    # the configured provider (collection still makes none).
    on = ProofReanalysisRequest(
        student_id=USER_ID, skill_name="python", include_llm_synthesis=True, dry_run=True
    )
    on_result = reanalyze_student_proofs(mem_store, pipeline_db, on)
    assert provider_calls, "synthesis enabled must call the configured provider via Step 4"
    assert on_result.synthesis_count >= 1


# ── 16. Stale marker public_view scrubs a hostile, private-looking skill_name ──


@pytest.mark.parametrize(
    "hostile_skill",
    [
        "attacker@example.com",
        "Bearer sk-secret-token",
        "/Users/victim/secrets/key.pem",
        "https://project.supabase.co/storage/v1/object/sign/abc?token=xyz",
    ],
)
def test_stale_marker_public_view_scrubs_skill_name(hostile_skill: str) -> None:
    marker = StaleEvidenceMarker(
        evidence_id="ev_deadbeefdeadbeef",
        reason="GitHub evidence is repository-level only.",
        recommended_action="Reanalyze this repository.",
        source_type=SOURCE_GITHUB,
        project_id="private-project-id",
        skill_name=hostile_skill,
    )
    public = marker.public_view()
    serialized = str(public).lower()
    # The private/hostile skill string never reaches the public projection.
    for needle in ("attacker@example.com", "sk-secret-token", "/users/victim", "supabase.co/storage", "token=xyz"):
        assert needle not in serialized, f"public_view leaked {needle!r}"
    assert "@" not in str(public.get("skill_name") or "")
    # The private project_id is still dropped entirely.
    assert "project_id" not in public


# ── 17. Bare UUID / private-id-shaped skill names are redacted on public_view ──


@pytest.mark.parametrize(
    "hostile_skill",
    [
        # Canonical and de-hyphenated UUIDs.
        "550e8400-e29b-41d4-a716-446655440000",
        "550e8400e29b41d4a716446655440000",
        "550E8400-E29B-41D4-A716-446655440000",
        # `<prefix>_<long-hex>` private ids.
        "user_1234567890abcdef",
        "project_1234567890abcdef",
        "artifact_1234567890abcdef",
        "ev_1234567890abcdef",
        # Hyphen-separated private id variant.
        "user-1234567890abcdef",
        # Wrapped / punctuated so a trailing token can't smuggle the id through.
        "(550e8400-e29b-41d4-a716-446655440000)",
    ],
)
def test_stale_marker_public_view_redacts_identifier_skill_name(hostile_skill: str) -> None:
    marker = StaleEvidenceMarker(
        evidence_id="ev_deadbeefdeadbeef",
        reason="GitHub evidence is repository-level only.",
        recommended_action="Reanalyze this repository.",
        source_type=SOURCE_GITHUB,
        project_id="private-project-id",
        skill_name=hostile_skill,
    )
    public = marker.public_view()
    # A skill name that is *only* a private id leaves nothing human-readable, so it
    # must be omitted entirely (None) rather than echoed back on a public surface.
    assert public["skill_name"] is None, f"identifier-shaped skill leaked: {public['skill_name']!r}"
    # And the raw id never appears anywhere in the serialized public projection.
    needle = hostile_skill.strip("()").lower()
    assert needle not in str(public).lower(), f"public_view leaked id {needle!r}"


# ── 18. Normal human skill names survive the public projection intact ─────────


@pytest.mark.parametrize(
    "human_skill",
    ["Python", "API Development", "Machine Learning", "React", "FastAPI", "Data Visualization"],
)
def test_stale_marker_public_view_keeps_human_skill_name(human_skill: str) -> None:
    marker = StaleEvidenceMarker(
        evidence_id="ev_deadbeefdeadbeef",
        reason="Aggregated skill-graph evidence only.",
        recommended_action="Attach a concrete proof.",
        source_type=SOURCE_GITHUB,
        project_id="private-project-id",
        skill_name=human_skill,
    )
    public = marker.public_view()
    assert public["skill_name"] == human_skill, "normal human skill names must stay intact"


# ── 19. A human skill mixed with a private id keeps only the human part ────────


def test_stale_marker_public_view_keeps_human_part_drops_id() -> None:
    marker = StaleEvidenceMarker(
        evidence_id="ev_deadbeefdeadbeef",
        reason="GitHub evidence is repository-level only.",
        recommended_action="Reanalyze this repository.",
        source_type=SOURCE_GITHUB,
        project_id="private-project-id",
        skill_name="Python user_1234567890abcdef",
    )
    public = marker.public_view()
    assert public["skill_name"] == "Python"
    assert "1234567890abcdef" not in str(public).lower()
