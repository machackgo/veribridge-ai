"""Tests for the Evidence Normalization Engine (Step 2).

The engine collapses every proof surface's already-safe, differently-shaped
evidence into ONE uniform internal model (``NormalizedEvidenceArtifact``) the
Proof Synthesis Agent (and later the cross-proof linker) can consume directly.

Invariants under test:

* GitHub precise line-level code → ``precise_code``; a repo-level row is the
  ``repo_level`` *fallback only* and is never promoted.
* Website → ``runtime_behavior``, Defense → ``self_explanation``,
  Video → ``supporting_moment``, Skill Graph → ``aggregated``.
* Documents are ALWAYS ``corroboration`` + ``public_safe == False`` — never
  primary proof.
* The public-safe projection strips the private ``source_id`` and all internal
  ``metadata`` (no raw transcript/document/DOM/provider JSON/storage path/signed
  URL/private id), keeping only safe summary fields + a genuinely public URL.
* Skill names are canonicalised by reusing the shared skill-normalization logic.

All in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.evidence_normalization_service import (
    SOURCE_DEFENSE,
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    SOURCE_SKILL_GRAPH,
    SOURCE_VIDEO,
    SOURCE_WEBSITE,
    STRENGTH_AGGREGATED,
    STRENGTH_CORROBORATION,
    STRENGTH_PRECISE_CODE,
    STRENGTH_REPO_LEVEL,
    STRENGTH_RUNTIME,
    STRENGTH_SELF_EXPLANATION,
    STRENGTH_SUPPORTING_MOMENT,
    NormalizedEvidenceArtifact,
    has_precise_code,
    has_source,
    normalize_chain,
    normalize_document_correlation,
    normalize_report_item,
    normalize_skill_report,
)
from app.services.proof_synthesis_agent_service import build_skill_proof_synthesis

from tests.test_vbr_project_defense import (
    USER_ID,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_workflow_analysis,
)

_SESSIONS_TABLE = "vbr_verification_sessions"


# ── Builders for already-safe report items / chains ───────────────────────────


def _gh_code_item(**over) -> dict:
    item = {
        "proof_type": "GitHub Proof",
        "source_id": "gh-1",
        "skill_name": "ml",
        "safe_summary": "Trains the model and exposes a predict route.",
        "safe_location": "api.py · predict()",
        "public_safe": True,
        "attached_project_ids": ["p1"],
        "limitation": "Repository evidence supports this skill.",
        "display_mode": "code_line",
        "has_precise_line_evidence": True,
        "file_path": "api.py",
        "line_start": 252,
        "line_end": 255,
        "function_name": "predict",
        "github_line_url": "https://github.com/octocat/Hello-World/blob/main/api.py#L252-L255",
        "repo_url": "https://github.com/octocat/Hello-World",
        "subskill_name": "Model serving",
        "selection_reason": "API endpoint decorator",
    }
    item.update(over)
    return item


def _gh_repo_item(**over) -> dict:
    item = {
        "proof_type": "GitHub Proof",
        "source_id": "gh-2",
        "skill_name": "Python",
        "safe_summary": "Repository inspected for Python.",
        "safe_location": "repo-level",
        "public_safe": True,
        "attached_project_ids": ["p1"],
        "limitation": "Repository-level evidence only.",
        "display_mode": "repo_level",
        "has_precise_line_evidence": False,
    }
    item.update(over)
    return item


# ── 1. GitHub precise code → precise_code, canonical skill, safe metadata ──────


def test_github_precise_code_normalizes_to_precise_code() -> None:
    art = normalize_report_item(_gh_code_item(), project_title="Boston")
    assert art is not None
    assert art.source_type == SOURCE_GITHUB
    assert art.proof_strength == STRENGTH_PRECISE_CODE
    # Reuses shared skill normalization: "ml" → "Machine Learning".
    assert art.skill_name == "ml"
    assert art.canonical_skill_name == "Machine Learning"
    assert art.subskill_name == "Model serving"
    assert art.exact_location == "api.py · predict()"
    assert art.project_title == "Boston"
    # Safe locators land in internal metadata.
    assert art.metadata["file_path"] == "api.py"
    assert art.metadata["selection_reason"] == "API endpoint decorator"
    assert art.source_label == "GitHub Proof"


# ── 2. GitHub repo-level stays the fallback (never promoted) ───────────────────


def test_github_repo_level_is_fallback_only() -> None:
    art = normalize_report_item(_gh_repo_item())
    assert art is not None
    assert art.proof_strength == STRENGTH_REPO_LEVEL
    assert not has_precise_code([art])


# ── 3. Website / Defense / Video / Skill Graph strengths ──────────────────────


@pytest.mark.parametrize(
    ("proof_type", "source_type", "strength", "extra"),
    [
        ("Website Proof", SOURCE_WEBSITE, STRENGTH_RUNTIME, {"public_url": "https://demo.example.com"}),
        ("Project Defense", SOURCE_DEFENSE, STRENGTH_SELF_EXPLANATION, {}),
        ("Video Evidence", SOURCE_VIDEO, STRENGTH_SUPPORTING_MOMENT, {"timestamp_label": "01:20"}),
        ("Skill Graph", SOURCE_SKILL_GRAPH, STRENGTH_AGGREGATED, {}),
    ],
)
def test_non_github_source_strengths(proof_type, source_type, strength, extra) -> None:
    item = {
        "proof_type": proof_type,
        "source_id": "s-1",
        "skill_name": "Python",
        "safe_summary": "summary",
        "safe_location": "loc",
        "public_safe": False,
        "attached_project_ids": [],
        "limitation": "lim",
        **extra,
    }
    art = normalize_report_item(item)
    assert art is not None
    assert art.source_type == source_type
    assert art.proof_strength == strength


# ── 4. Document is corroboration-only and never public ────────────────────────


def test_document_correlation_is_corroboration_only() -> None:
    card = {
        "source_id": "doc-1",
        "document_title": "Boston Report",
        "page_number": 2,
        "citation": "Page 2 · Methods",
        "corroborates": "GitHub implementation",
        "correlation_confidence": "title/project match",
        "reason": "Describes the prediction pipeline.",
        "limitation": "Document supports but does not prove implementation.",
    }
    art = normalize_document_correlation(card, skill_name="ml", project_title="Boston")
    assert art.source_type == SOURCE_DOCUMENT
    assert art.proof_strength == STRENGTH_CORROBORATION
    assert art.public_safe is False
    assert art.canonical_skill_name == "Machine Learning"
    assert art.exact_location == "Page 2 · Methods"
    assert art.metadata["corroborates"] == "GitHub implementation"


# ── 5. Unrecognised / document report item returns None ───────────────────────


def test_unrecognised_report_item_returns_none() -> None:
    assert normalize_report_item({"proof_type": "Document Proof", "source_id": "d"}) is None
    assert normalize_report_item({"proof_type": "Mystery", "source_id": "x"}) is None


# ── 6. Public-safe projection strips private id + internal metadata ────────────

_FORBIDDEN = ("gh-1", "secret_token", "/storage/v1/object", "raw_dump", "analysis_snapshot")


def test_public_view_strips_private_id_and_metadata() -> None:
    art = normalize_report_item(_gh_code_item(source_id="gh-1"))
    assert art is not None
    public = art.public_view()
    # No private source id, no internal metadata bag.
    assert "source_id" not in public
    assert "metadata" not in public
    # A genuinely public github line URL survives for deep-linking.
    assert public["public_url"].startswith("https://github.com/")
    serialized = str(public).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in serialized


def test_document_public_view_exposes_no_url() -> None:
    art = normalize_document_correlation(
        {"source_id": "doc-9", "reason": "x", "citation": "Page 1", "page_number": 1}
    )
    public = art.public_view()
    assert public["public_url"] is None
    assert "source_id" not in public


# ── 6b. Hostile upstream: public_view re-scrubs retained public strings ────────
#
# The retained public fields (safe_summary, exact_location, limitations) are
# meant to be already-safe, but a hostile upstream item could smuggle a token /
# signed URL / storage or local path into them. public_view() must defensively
# re-scrub every retained string so none of these survive into a public report.

# Secret markers that must NEVER appear in public output, one per threat class.
_HOSTILE_SECRETS = (
    "eyJSECRETaccessAAA",  # access_token value
    "rtSECRETrefreshBBB",  # refresh_token value
    "sigSECRETsignedCCC",  # signed-URL query token
    "vbr/sessions/SECRETsessionDDD",  # Supabase storage path
    "s3SECRETbucketEEE",  # S3/GCS URL host/key
    "SECRETlocalFFF",  # /Users/... local path leaf
    "SECRETfileGGG",  # file:/// path leaf
    "SECRETcallbackHHH",  # localhost/private callback path
)


def _hostile_artifact(**over) -> NormalizedEvidenceArtifact:
    base = dict(
        evidence_id="ev_test_hostile",
        source_type=SOURCE_GITHUB,
        skill_name="Python",
        canonical_skill_name="Python",
        subskill_name=None,
        project_id="p1",
        project_title="Boston",
        source_id="gh-secret-1",
        source_label="GitHub Proof",
        exact_location="/Users/victim/Movies/SECRETlocalFFF.mov",
        safe_summary=(
            "Calls https://proj.s3.amazonaws.com/s3SECRETbucketEEE with "
            "access_token=eyJSECRETaccessAAA refresh_token=rtSECRETrefreshBBB "
            "and a signed URL https://proj.supabase.co/storage/v1/object/sign/x"
            "?token=sigSECRETsignedCCC"
        ),
        proof_strength=STRENGTH_PRECISE_CODE,
        public_safe=True,
        limitations=(
            "Stored at vbr/sessions/SECRETsessionDDD/raw.mp4",
            "Callback http://localhost:8000/admin/SECRETcallbackHHH",
            "Backup file:///Users/victim/SECRETfileGGG",
        ),
        metadata={
            "file_path": "/Users/victim/SECRETlocalFFF.py",
            "github_line_url": "https://github.com/octocat/Hello-World/blob/main/api.py#L1-L2",
        },
    )
    base.update(over)
    return NormalizedEvidenceArtifact(**base)


def test_public_view_scrubs_hostile_secrets_from_retained_fields() -> None:
    public = _hostile_artifact().public_view()
    serialized = str(public).lower()
    for secret in _HOSTILE_SECRETS:
        assert secret.lower() not in serialized, secret

    # The retained fields are present but redacted (the marker is gone).
    assert "secret" not in public["safe_summary"].lower()
    assert "secret" not in (public["exact_location"] or "").lower()
    for lim in public["limitations"]:
        assert "secret" not in lim.lower()

    # The private source_id and the internal metadata bag never reach public output.
    assert "source_id" not in public
    assert "metadata" not in public
    assert "gh-secret-1" not in serialized

    # A genuinely public github line URL still survives for deep-linking.
    assert public["public_url"].startswith("https://github.com/")


def test_public_view_scrubs_every_limitation_in_a_list() -> None:
    art = _hostile_artifact(
        safe_summary="ok",
        exact_location="api.py",
        limitations=(
            "token=eyJSECRETaccessAAA",
            "path /Users/victim/SECRETfileGGG",
            "see https://proj.supabase.co/storage/v1/object/sign/x?token=sigSECRETsignedCCC",
        ),
    )
    public = art.public_view()
    assert len(public["limitations"]) == 3
    joined = " ".join(public["limitations"]).lower()
    for secret in ("eyJSECRETaccessAAA", "SECRETfileGGG", "sigSECRETsignedCCC"):
        assert secret.lower() not in joined, secret


def test_public_view_is_deterministic_under_hostile_input() -> None:
    art = _hostile_artifact()
    assert art.public_view() == art.public_view()


def test_hostile_public_view_through_normalizer_pipeline() -> None:
    # Even when the secrets enter through the real normalize_report_item path
    # (Vault item → artifact → public_view), the public projection stays clean.
    item = _gh_code_item(
        source_id="gh-secret-2",
        safe_summary="leak access_token=eyJSECRETaccessAAA via https://x.s3.amazonaws.com/s3SECRETbucketEEE",
        safe_location="/Users/victim/SECRETlocalFFF.py",
        limitation="stored at vbr/sessions/SECRETsessionDDD/raw.mp4",
    )
    art = normalize_report_item(item)
    assert art is not None
    serialized = str(art.public_view()).lower()
    for secret in ("eyJSECRETaccessAAA", "s3SECRETbucketEEE", "SECRETlocalFFF", "SECRETsessionDDD"):
        assert secret.lower() not in serialized, secret
    assert "gh-secret-2" not in serialized


# ── 7. Chain-level normalization preserves strong-first ordering ──────────────


def test_normalize_chain_orders_and_covers_all_sources() -> None:
    chain = {
        "project_id": "p1",
        "project_title": "Boston",
        "github_evidence": [_gh_code_item()],
        "website_evidence": [
            {
                "proof_type": "Website Proof",
                "source_id": "w-1",
                "skill_name": "ml",
                "safe_summary": "live workflow",
                "safe_location": "demo.example.com",
                "public_safe": True,
                "public_url": "https://demo.example.com",
            }
        ],
        "defense_evidence": [
            {
                "proof_type": "Project Defense",
                "source_id": "d-1",
                "skill_name": "ml",
                "safe_summary": "explained",
                "safe_location": "overall explanation",
                "public_safe": False,
            }
        ],
        "document_correlations": [
            {"source_id": "doc-1", "reason": "supports", "citation": "Page 2"}
        ],
    }
    arts = normalize_chain(chain, "ml")
    types = [a.source_type for a in arts]
    # GitHub → Website → Defense → Document order; document is last (corroboration).
    assert types == [SOURCE_GITHUB, SOURCE_WEBSITE, SOURCE_DEFENSE, SOURCE_DOCUMENT]
    assert has_precise_code(arts)
    assert has_source(arts, SOURCE_WEBSITE)
    assert all(a.project_id == "p1" for a in arts)
    # Every artifact carries a distinct, non-leaking evidence id.
    ids = [a.evidence_id for a in arts]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("ev_") for i in ids)


# ── 8. End-to-end: report normalization + agent attaches normalized_evidence ──


def _strong_github(mem_store: dict, skill: str = "Python") -> str:
    return _seed_github_proof(
        mem_store,
        detected_skills=[skill],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": skill,
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        },
    )


def _seed_project(mem_store: dict, *, title: str, repo: str, attached: dict) -> str:
    pid = str(uuid4())
    mem_store.setdefault("vbr_projects", {})[pid] = {
        "id": pid,
        "user_id": USER_ID,
        "title": title,
        "repo_full_name": repo,
        "repo_url": f"https://github.com/{repo}",
        "metadata": {"attached_proofs": attached},
        "created_at": "2026-01-01T00:00:00Z",
    }
    return pid


def test_report_normalization_and_agent_integration() -> None:
    mem_store: dict = {}
    pipeline_db: dict = {}
    gh_id = _strong_github(mem_store, "Python")
    doc_id = _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Report"},
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "prediction API", "page_number": 2}
        ],
    )
    session_id = _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )
    pid = _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo="octocat/Hello-World",
        attached={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [{"document_evidence_id": doc_id}],
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")

    # The agent attaches the uniform normalized set to each chain.
    chain = next(c for c in report["proof_chains"] if c.get("project_id") == pid)
    assert chain["normalized_evidence"], "chain carries normalized artifacts"
    strengths = {a["proof_strength"] for a in chain["normalized_evidence"]}
    assert STRENGTH_PRECISE_CODE in strengths
    assert STRENGTH_RUNTIME in strengths
    assert STRENGTH_CORROBORATION in strengths

    # Whole-report normalization yields one uniform list across the chain.
    arts = normalize_skill_report(report)
    assert has_precise_code(arts)
    assert has_source(arts, SOURCE_WEBSITE)
    assert has_source(arts, SOURCE_DOCUMENT)
    # Documents never become public, even end-to-end.
    docs = [a for a in arts if a.source_type == SOURCE_DOCUMENT]
    assert docs and all(d.public_safe is False for d in docs)
