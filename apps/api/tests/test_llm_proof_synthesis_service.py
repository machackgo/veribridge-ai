"""Tests for the LLM Synthesis Layer (Step 4).

The synthesis layer takes Step 3's already-linked, deterministic
:class:`LinkedProofChain` and produces recruiter-readable :class:`SynthesisClaim`\\s.
It is fenced in hard: every claim must cite real evidence ids from the chain, the
LLM can only ever *weaken* the deterministic tier (never promote past Steps 2/3),
documents stay corroboration-only, no string can leak private data, and if the LLM
is unavailable / invalid / unsafe a deterministic rule-based synthesis is returned.

The LLM is injected as a simple ``llm_fn`` callable, so NO test ever touches the
network — every "LLM" here is a local mock returning a canned string.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from uuid import uuid4

import pytest

import app.services.llm_proof_synthesis_service as llm_mod
from app.core.config import settings
from app.services.cross_proof_linking_service import link_proof_chains
from app.services.evidence_normalization_service import (
    SOURCE_DEFENSE,
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    SOURCE_WEBSITE,
    STRENGTH_CORROBORATION,
    STRENGTH_PRECISE_CODE,
    STRENGTH_REPO_LEVEL,
    STRENGTH_RUNTIME,
    STRENGTH_SELF_EXPLANATION,
    NormalizedEvidenceArtifact,
)
from app.services.llm_proof_synthesis_service import (
    TIER_CORROBORATED,
    TIER_NEEDS_REVIEW,
    TIER_STRONG,
    TIER_SUPPORTING,
    _TIER_RANK,
    _resolve_llm_fn,
    _resolved_concurrency,
    _safe_text,
    synthesize_chain,
    synthesize_linked_chains,
    synthesize_linked_chains_async,
)
from app.services.proof_synthesis_agent_service import build_skill_proof_synthesis

from tests.test_vbr_project_defense import (
    USER_ID,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_workflow_analysis,
)


# ── Hermetic guard ────────────────────────────────────────────────────────────
#
# The shared, autouse ``_hermetic_llm_synthesis`` fixture in ``tests/conftest.py``
# already makes EVERY backend test offline: it forces the synthesis layer disabled
# and neutralises the provider builders so no production path can reach a real
# provider, even when a developer ``.env`` enables synthesis. We capture the REAL
# builders here (at import time, before that fixture runs) so the provider tests
# below can opt back in explicitly — restoring the genuine ``local_openai`` /
# Anthropic resolution and pairing it with a FAKE httpx client / unconfigured creds,
# so they stay hermetic while exercising the real provider code path.

_REAL_LOCAL_OPENAI_LLM_FN = llm_mod._local_openai_llm_fn
_REAL_ANTHROPIC_LLM_FN = llm_mod._anthropic_llm_fn


# ── Artifact builders (already-safe normalized shape) ─────────────────────────


def _ev_id(source_type: str, source_id: str) -> str:
    digest = hashlib.sha1(f"{source_type}:{source_id}".encode()).hexdigest()[:16]
    return f"ev_{source_type}_{digest}"


def _github_code(
    *,
    project_id: str | None = "p1",
    project_title: str | None = "Boston Smart Accident Rerouting",
    skill: str = "Python",
    summary: str = "Implements the risk prediction handler.",
    source_id: str = "gh-1",
    public_safe: bool = True,
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_ev_id(SOURCE_GITHUB, source_id),
        source_type=SOURCE_GITHUB,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name="API design",
        project_id=project_id,
        project_title=project_title,
        source_id=source_id,
        source_label="GitHub Proof",
        exact_location="app/api/routes.py · predict()",
        safe_summary=summary,
        proof_strength=STRENGTH_PRECISE_CODE,
        public_safe=public_safe,
        metadata={
            "function_name": "predict",
            "file_path": "app/api/routes.py",
            "repo_url": "https://github.com/octocat/boston-rerouting",
            "github_line_url": "https://github.com/octocat/boston-rerouting/blob/main/app/api/routes.py#L10-L20",
        },
    )


def _repo_github(
    *, project_id: str | None = "p1", skill: str = "Python", source_id: str = "gh-r"
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_ev_id(SOURCE_GITHUB, source_id),
        source_type=SOURCE_GITHUB,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title="Boston Smart Accident Rerouting",
        source_id=source_id,
        source_label="GitHub Proof",
        exact_location="repo-level",
        safe_summary="Repository references the skill.",
        proof_strength=STRENGTH_REPO_LEVEL,
        public_safe=True,
        metadata={"repo_url": "https://github.com/octocat/boston-rerouting"},
    )


def _website(
    *, project_id: str | None = "p1", skill: str = "Python", source_id: str = "w-1"
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_ev_id(SOURCE_WEBSITE, source_id),
        source_type=SOURCE_WEBSITE,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title="Boston Smart Accident Rerouting",
        source_id=source_id,
        source_label="Website Proof",
        exact_location="demo.example.com",
        safe_summary="Live workflow runs the rerouting demo end to end.",
        proof_strength=STRENGTH_RUNTIME,
        public_safe=True,
        metadata={"public_url": "https://demo.example.com"},
    )


def _defense(
    *, project_id: str | None = "p1", skill: str = "Python", source_id: str = "d-1"
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_ev_id(SOURCE_DEFENSE, source_id),
        source_type=SOURCE_DEFENSE,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title="Boston Smart Accident Rerouting",
        source_id=source_id,
        source_label="Project Defense",
        exact_location="overall explanation",
        safe_summary="The candidate explained how the /predict endpoint returns a risk score.",
        proof_strength=STRENGTH_SELF_EXPLANATION,
        public_safe=False,
        metadata={},
    )


def _document(
    *, project_id: str | None = "p1", skill: str = "Python", source_id: str = "doc-1"
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_ev_id(SOURCE_DOCUMENT, source_id),
        source_type=SOURCE_DOCUMENT,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title="Boston Smart Accident Rerouting",
        source_id=source_id,
        source_label="Document Proof",
        exact_location="Page 2 · Methods",
        safe_summary="Report section describes the prediction pipeline.",
        proof_strength=STRENGTH_CORROBORATION,
        public_safe=False,
        metadata={"citation": "Page 2 · Methods"},
    )


def _strong_chain():
    """A precise-code + website + defense chain (deterministic ceiling STRONG)."""
    chains = link_proof_chains([_github_code(), _website(), _defense()])
    assert len(chains) == 1
    return chains[0]


def _llm(text: str):
    """A mock ``llm_fn`` that always returns ``text`` (never the network)."""

    def _fn(system_prompt: str, user_message: str) -> str:
        return text

    return _fn


def _llm_json(claims: list[dict], overall_summary: str = "Synthesized.") -> str:
    return json.dumps({"claims": claims, "overall_summary": overall_summary})


# ── 1. Valid LLM JSON with real evidence ids is accepted ──────────────────────


def test_valid_llm_json_is_accepted() -> None:
    chain = _strong_chain()
    gh = _ev_id(SOURCE_GITHUB, "gh-1")
    web = _ev_id(SOURCE_WEBSITE, "w-1")
    raw = _llm_json(
        [
            {
                "claim": "Precise GitHub code plus a live workflow show the prediction skill.",
                "supporting_evidence_ids": [gh, web],
                "why_connected": "Same project and repository.",
                "limitations": ["Single project only."],
                "qualitative_tier": TIER_STRONG,
            }
        ]
    )
    result = synthesize_chain(chain, llm_fn=_llm(raw))
    assert result.source == "llm"
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert set(claim.supporting_evidence_ids) == {gh, web}
    assert claim.qualitative_tier == TIER_STRONG
    assert "GitHub" in claim.claim


# ── 2. Unknown evidence ids are stripped / dropped ────────────────────────────


def test_unknown_evidence_ids_are_rejected() -> None:
    chain = _strong_chain()
    gh = _ev_id(SOURCE_GITHUB, "gh-1")
    raw = _llm_json(
        [
            {
                # One real id + one invented id → keep the real, strip the fake,
                # and downgrade (a claim that cited an invented id can't read strong).
                "claim": "Mixed citation claim.",
                "supporting_evidence_ids": [gh, "ev_github_FAKEFAKEFAKE"],
                "why_connected": "x",
                "limitations": [],
                "qualitative_tier": TIER_STRONG,
            },
            {
                # Only invented ids → dropped entirely.
                "claim": "Wholly fabricated claim.",
                "supporting_evidence_ids": ["ev_website_NOPE"],
                "why_connected": "x",
                "limitations": [],
                "qualitative_tier": TIER_STRONG,
            },
        ]
    )
    result = synthesize_chain(chain, llm_fn=_llm(raw))
    assert len(result.claims) == 1, "fabricated-only claim is dropped"
    claim = result.claims[0]
    assert claim.supporting_evidence_ids == (gh,), "invented id stripped"
    assert claim.qualitative_tier == TIER_NEEDS_REVIEW, "downgraded for citing a fake id"
    # No invented id leaks anywhere in the serialized output.
    assert "FAKEFAKEFAKE" not in str(result.to_dict())
    assert "NOPE" not in str(result.to_dict())


# ── 3. Unsafe strings in LLM output are scrubbed ──────────────────────────────


def test_unsafe_strings_are_scrubbed() -> None:
    chain = _strong_chain()
    gh = _ev_id(SOURCE_GITHUB, "gh-1")
    raw = _llm_json(
        [
            {
                "claim": (
                    "See https://abc.supabase.co/storage/v1/object/sign/vbr/x?token=secret "
                    "and contact student@example.com — token=ghp_DEADBEEF — "
                    "stored at /Users/alice/proj/data.csv. This skill is fully verified."
                ),
                "supporting_evidence_ids": [gh],
                "why_connected": "Bearer abctoken123 explains the link.",
                "limitations": ["file:///Users/alice/secret.pdf"],
                "qualitative_tier": TIER_CORROBORATED,
            }
        ]
    )
    result = synthesize_chain(chain, llm_fn=_llm(raw))
    blob = json.dumps(result.public_view())
    for needle in (
        "supabase.co",
        "token=secret",
        "ghp_DEADBEEF",
        "student@example.com",
        "/Users/alice",
        "abctoken123",
    ):
        assert needle not in blob, f"sensitive fragment leaked: {needle}"
    # The over-claim "fully verified" is neutralised.
    assert "fully verified" not in blob.lower()


# ── 4. Invalid JSON falls back safely ─────────────────────────────────────────


def test_invalid_json_falls_back() -> None:
    chain = _strong_chain()
    result = synthesize_chain(chain, llm_fn=_llm("this is not json at all"))
    assert result.source == "deterministic"
    assert result.claims, "fallback still produces claims"


def test_llm_raising_falls_back() -> None:
    chain = _strong_chain()

    def _boom(system_prompt: str, user_message: str) -> str:
        raise RuntimeError("provider exploded")

    result = synthesize_chain(chain, llm_fn=_boom)
    assert result.source == "deterministic"
    assert result.claims


# ── 5. LLM unavailable falls back safely ──────────────────────────────────────


def test_llm_unavailable_falls_back() -> None:
    chain = _strong_chain()
    # llm_fn returns None → unavailable. Default (no creds) resolves to None too.
    result = synthesize_chain(chain, llm_fn=lambda s, u: None)
    assert result.source == "deterministic"
    assert result.claims
    # No creds in the test env → the default path is also deterministic, no network.
    default_result = synthesize_chain(chain)
    assert default_result.source == "deterministic"


# ── 6. Document-only chain can never become strong implementation proof ───────


def test_document_only_chain_cannot_be_strongly_corroborated() -> None:
    chains = link_proof_chains([_document()])
    assert len(chains) == 1
    chain = chains[0]
    gh_doc = _ev_id(SOURCE_DOCUMENT, "doc-1")

    # Even if the LLM tries to assert a strong implementation claim, the tier is
    # clamped to the deterministic ceiling (Needs review for a document-only chain).
    raw = _llm_json(
        [
            {
                "claim": "The implementation is demonstrated and the skill is fully verified.",
                "supporting_evidence_ids": [gh_doc],
                "why_connected": "doc",
                "limitations": [],
                "qualitative_tier": TIER_STRONG,
            }
        ]
    )
    result = synthesize_chain(chain, llm_fn=_llm(raw))
    for claim in result.claims:
        assert _TIER_RANK[claim.qualitative_tier] >= _TIER_RANK[TIER_NEEDS_REVIEW]
        assert claim.qualitative_tier not in (TIER_STRONG, TIER_CORROBORATED)

    # Deterministic fallback for the same chain is corroboration-only too.
    fallback = synthesize_chain(chain, llm_fn=lambda s, u: None)
    assert fallback.claims
    for claim in fallback.claims:
        assert claim.qualitative_tier not in (TIER_STRONG, TIER_CORROBORATED)
        assert "corroborat" in claim.claim.lower()


# ── 7. Precise code + website + defense yields a stronger tier than repo-only ──


def test_precise_multi_source_is_stronger_than_repo_only() -> None:
    strong = synthesize_chain(_strong_chain(), llm_fn=lambda s, u: None)
    strongest_tier = min(_TIER_RANK[c.qualitative_tier] for c in strong.claims)
    assert strongest_tier == _TIER_RANK[TIER_STRONG]

    repo_chains = link_proof_chains([_repo_github()])
    repo_only = synthesize_chain(repo_chains[0], llm_fn=lambda s, u: None)
    repo_best = min(_TIER_RANK[c.qualitative_tier] for c in repo_only.claims)
    assert repo_best > strongest_tier, "repo-level evidence is weaker than precise multi-source"


# ── 8. Deterministic fallback is fully deterministic ──────────────────────────


def test_fallback_is_deterministic() -> None:
    chain = _strong_chain()
    a = synthesize_chain(chain, llm_fn=lambda s, u: None)
    b = synthesize_chain(chain, llm_fn=lambda s, u: None)
    assert a.to_dict() == b.to_dict()


# ── 9. Public output does not leak sensitive / private fields ─────────────────


def test_public_output_does_not_leak_private_fields() -> None:
    chain = _strong_chain()
    result = synthesize_chain(chain, llm_fn=lambda s, u: None)
    public = result.public_view()
    blob = json.dumps(public).lower()
    # No private ids, source ids, project ids, or raw metadata in the public view.
    for needle in ("source_id", "project_id", "metadata", "repo_url", "github_line_url"):
        assert needle not in blob
    # Only public-safe claims survive the public projection; the defense (public_safe
    # False) must not contribute a publicly-shown claim citing its private evidence.
    defense_ev = _ev_id(SOURCE_DEFENSE, "d-1")
    for claim in public["claims"]:
        assert defense_ev not in claim["supporting_evidence_ids"]


# ── 10. Proof Synthesis Agent embeds synthesis without breaking old fields ────


def _strong_seeded_github(mem_store: dict, skill: str = "Python") -> str:
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


def test_proof_synthesis_agent_includes_llm_synthesis() -> None:
    mem_store: dict = {}
    pipeline_db: dict = {}
    gh_id = _strong_seeded_github(mem_store, "Python")
    session_id = _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo="octocat/Hello-World",
        attached={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")

    # Backward compatible — every prior key is still present.
    for key in ("proof_chains", "unlinked_supporting_evidence", "linked_proof_chains"):
        assert key in report
    # New: the LLM synthesis layer output (deterministic in tests — no creds/network).
    assert "llm_synthesis" in report
    assert isinstance(report["llm_synthesis"], list)
    for syn in report["llm_synthesis"]:
        assert syn["source"] == "deterministic"
        assert syn["chain_id"]
        # Every cited id is a real linked-evidence id from some chain.
        all_ids = {
            ev for c in report["linked_proof_chains"] for ev in c["linked_evidence_ids"]
        }
        for claim in syn["claims"]:
            for ev in claim["supporting_evidence_ids"]:
                assert ev in all_ids

    # The synthesis output never leaks raw/private payloads.
    serialized = json.dumps(report["llm_synthesis"]).lower()
    for needle in ("analysis_snapshot", "raw_dump", "/storage/v1/object", "supabase.co"):
        assert needle not in serialized


# ──────────────────────────────────────────────────────────────────────────────
# Provider-agnostic synthesis (Step 4 — local Qwen / OpenAI-compatible support).
#
# Every provider call is mocked: the local_openai provider is exercised through a
# FAKE httpx.Client (no real Ollama / vLLM / LM Studio / OpenAI / Anthropic call is
# ever made), and the concurrency/order/fallback paths use injected ``llm_fn``s.
# ──────────────────────────────────────────────────────────────────────────────


def _chain_for(i: int):
    """A distinct precise-code chain (its own project → its own chain_id)."""
    chains = link_proof_chains(
        [
            _github_code(
                project_id=f"p{i}",
                project_title=f"Project {i}",
                source_id=f"gh-{i}",
            )
        ]
    )
    assert len(chains) == 1
    return chains[0]


def _citing_llm(system_prompt: str, user_message: str) -> str:
    """A mock provider that cites a REAL evidence id parsed from the safe prompt.

    The prompt only ever carries already-safe public fields, so reading
    ``valid_evidence_ids`` from it is exactly what a real provider would do.
    """
    payload = json.loads(user_message.split("\n\n", 1)[1])
    ids = payload["valid_evidence_ids"]
    return _llm_json(
        [
            {
                "claim": "Synthesized claim over linked evidence.",
                "supporting_evidence_ids": ids[:1],
                "why_connected": "Same project.",
                "limitations": [],
                "qualitative_tier": TIER_NEEDS_REVIEW,
            }
        ]
    )


# ── Fake OpenAI-compatible HTTP layer (no real network) ───────────────────────


class _FakeResp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _openai_resp(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _install_fake_httpx(monkeypatch, responses: list, calls: list | None = None) -> list:
    """Replace httpx.Client with a fake that pops queued responses (or raises)."""
    import httpx

    recorded = calls if calls is not None else []

    class _FakeClient:
        def __init__(self, *a, **k) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a) -> bool:
            return False

        def post(self, url, json=None, headers=None):
            recorded.append({"url": url, "json": json, "headers": headers})
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return recorded


def _enable_local(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(settings, "llm_synthesis_enabled", True)
    monkeypatch.setattr(settings, "llm_synthesis_provider", "local_openai")
    monkeypatch.setattr(settings, "local_llm_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(settings, "local_llm_model", "qwen3:14b")
    # Explicit opt-in: restore the REAL local_openai builder that the shared conftest
    # guard neutralises. Every caller pairs this with ``_install_fake_httpx`` below,
    # so the genuine provider code path runs but never makes a real network call.
    monkeypatch.setattr(llm_mod, "_local_openai_llm_fn", _REAL_LOCAL_OPENAI_LLM_FN)
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)


# ── 11. local_openai provider accepts valid mocked JSON ───────────────────────


def test_local_openai_provider_accepts_valid_json(monkeypatch) -> None:
    chain = _strong_chain()
    gh = _ev_id(SOURCE_GITHUB, "gh-1")
    content = _llm_json(
        [
            {
                "claim": "Precise GitHub code demonstrates the prediction skill.",
                "supporting_evidence_ids": [gh],
                "why_connected": "Same project.",
                "limitations": [],
                "qualitative_tier": TIER_CORROBORATED,
            }
        ]
    )
    _enable_local(monkeypatch)
    calls = _install_fake_httpx(monkeypatch, [_FakeResp(200, _openai_resp(content))])

    # llm_fn=None → the configured local_openai provider is resolved and called.
    result = synthesize_chain(chain)
    assert result.source == "llm"
    assert result.claims
    assert calls[0]["url"] == "http://localhost:11434/v1/chat/completions"
    assert calls[0]["json"]["model"] == "qwen3:14b"
    assert calls[0]["json"]["temperature"] == 0


# ── 12. local provider retries once without response_format on a 400 ──────────


def test_local_openai_provider_retries_without_response_format(monkeypatch) -> None:
    chain = _strong_chain()
    gh = _ev_id(SOURCE_GITHUB, "gh-1")
    content = _llm_json(
        [
            {
                "claim": "Code demonstrates the skill.",
                "supporting_evidence_ids": [gh],
                "why_connected": "x",
                "limitations": [],
                "qualitative_tier": TIER_CORROBORATED,
            }
        ]
    )
    _enable_local(monkeypatch)
    calls = _install_fake_httpx(
        monkeypatch,
        [_FakeResp(400, {}), _FakeResp(200, _openai_resp(content))],
    )
    result = synthesize_chain(chain)
    assert result.source == "llm"
    assert len(calls) == 2, "first call (with response_format) then a retry"
    assert "response_format" in calls[0]["json"]
    assert "response_format" not in calls[1]["json"], "retry drops response_format"


# ── 13. local provider failure / timeout falls back safely ────────────────────


def test_local_openai_provider_failure_falls_back(monkeypatch) -> None:
    chain = _strong_chain()
    _enable_local(monkeypatch)
    _install_fake_httpx(monkeypatch, [TimeoutError("provider timed out")])
    result = synthesize_chain(chain)
    assert result.source == "deterministic"
    assert result.claims


# ── 14. local provider invalid JSON content falls back safely ─────────────────


def test_local_openai_provider_invalid_json_falls_back(monkeypatch) -> None:
    chain = _strong_chain()
    _enable_local(monkeypatch)
    _install_fake_httpx(
        monkeypatch, [_FakeResp(200, _openai_resp("definitely not json"))]
    )
    result = synthesize_chain(chain)
    assert result.source == "deterministic"
    assert result.claims


# ── 15. provider disabled uses deterministic fallback only ────────────────────


def test_provider_disabled_uses_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_synthesis_enabled", True)
    monkeypatch.setattr(settings, "llm_synthesis_provider", "disabled")
    assert _resolve_llm_fn() is None
    result = synthesize_chain(_strong_chain())
    assert result.source == "deterministic"
    assert result.claims


# ── 16. Anthropic stays optional and is never required by default ─────────────


def test_anthropic_is_optional_and_not_default(monkeypatch) -> None:
    # Exercise the REAL anthropic builder (the shared conftest guard neutralises it
    # by default) so this proves genuine resolution, not the guard's stub.
    monkeypatch.setattr(llm_mod, "_anthropic_llm_fn", _REAL_ANTHROPIC_LLM_FN)

    # Default settings → layer disabled → deterministic only, no provider resolved.
    monkeypatch.setattr(settings, "llm_synthesis_enabled", False)
    assert _resolve_llm_fn() is None

    # Even if anthropic is explicitly selected, it is only used when ALSO configured
    # (ANTHROPIC_API_KEY + AI_REVIEWER_MODEL). Unconfigured → None (no network).
    monkeypatch.setattr(settings, "llm_synthesis_enabled", True)
    monkeypatch.setattr(settings, "llm_synthesis_provider", "anthropic")
    monkeypatch.setattr(settings, "ai_reviewer_model", "")
    assert _resolve_llm_fn() is None


# ── 17. concurrency defaults to 1 and respects configuration ──────────────────


def test_concurrency_defaults_to_one_and_is_configurable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_synthesis_max_concurrency", 1)
    assert _resolved_concurrency() == 1
    monkeypatch.setattr(settings, "llm_synthesis_max_concurrency", 4)
    assert _resolved_concurrency() == 4
    # An invalid value degrades safely to the conservative default of 1.
    monkeypatch.setattr(settings, "llm_synthesis_max_concurrency", "oops")
    assert _resolved_concurrency() == 1


# ── 18. bounded parallel synthesis preserves input order ──────────────────────


def test_parallel_synthesis_preserves_output_order() -> None:
    chains = [_chain_for(i) for i in range(5)]
    results = asyncio.run(
        synthesize_linked_chains_async(chains, llm_fn=_citing_llm, concurrency=4)
    )
    assert [r.chain_id for r in results] == [c.chain_id for c in chains]
    assert all(r.source == "llm" for r in results)


# ── 19. concurrency limit is respected (mocked slow provider) ─────────────────


class _ConcurrencyProbe:
    """A slow mock provider that records the peak number of concurrent calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current = 0
        self.max_seen = 0

    def __call__(self, system_prompt: str, user_message: str) -> None:
        with self._lock:
            self._current += 1
            self.max_seen = max(self.max_seen, self._current)
        time.sleep(0.05)
        with self._lock:
            self._current -= 1
        return None  # → deterministic fallback; we only measure concurrency here


def test_concurrency_limit_is_respected() -> None:
    chains = [_chain_for(i) for i in range(6)]

    probe2 = _ConcurrencyProbe()
    asyncio.run(
        synthesize_linked_chains_async(chains, llm_fn=probe2, concurrency=2)
    )
    assert 1 <= probe2.max_seen <= 2, "concurrency 2 is never exceeded"

    probe1 = _ConcurrencyProbe()
    asyncio.run(
        synthesize_linked_chains_async(chains, llm_fn=probe1, concurrency=1)
    )
    assert probe1.max_seen == 1, "concurrency 1 runs strictly serially"


# ── 20. one failed chain falls back without failing the whole run ─────────────


def test_one_failed_chain_does_not_abort_run() -> None:
    chains = [_chain_for(i) for i in range(3)]

    def _fn(system_prompt: str, user_message: str) -> str:
        if '"Project 1"' in user_message:
            raise RuntimeError("provider exploded for this chain only")
        return _citing_llm(system_prompt, user_message)

    results = asyncio.run(
        synthesize_linked_chains_async(chains, llm_fn=_fn, concurrency=3)
    )
    assert len(results) == 3
    by_id = {r.chain_id: r for r in results}
    failed = by_id[chains[1].chain_id]
    assert failed.source == "deterministic", "the failing chain fell back"
    assert failed.claims, "fallback still produced claims for it"
    others = [r for r in results if r.chain_id != chains[1].chain_id]
    assert others and all(r.source == "llm" for r in others), "other chains unaffected"


# ── 21. sync orchestrator falls back per-chain when the layer is disabled ──────


def test_sync_disabled_uses_fallback_for_all_chains(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_synthesis_enabled", False)
    chains = [_chain_for(i) for i in range(3)]
    results = synthesize_linked_chains(chains)
    assert len(results) == 3
    assert all(r.source == "deterministic" and r.claims for r in results)
    assert [r.chain_id for r in results] == [c.chain_id for c in chains]


# ── 22. max chains per run caps LLM usage; overflow stays deterministic ───────


def test_max_chains_per_run_caps_llm_usage() -> None:
    chains = [_chain_for(i) for i in range(3)]
    results = asyncio.run(
        synthesize_linked_chains_async(
            chains, llm_fn=_citing_llm, concurrency=2, max_chains=1
        )
    )
    assert len(results) == 3
    assert results[0].source == "llm", "first chain used the LLM"
    assert all(r.source == "deterministic" for r in results[1:]), "overflow is deterministic"
    assert all(r.claims for r in results), "every chain still produced a synthesis"


# ── 23. per-run cache dedupes an identical chain (one provider call) ──────────


def test_per_run_cache_dedupes_identical_chains() -> None:
    chain = _strong_chain()
    calls: list[int] = []

    def _fn(system_prompt: str, user_message: str) -> str:
        calls.append(1)
        return _citing_llm(system_prompt, user_message)

    # Same chain twice; concurrency 1 so the first result is cached before the second.
    results = asyncio.run(
        synthesize_linked_chains_async([chain, chain], llm_fn=_fn, concurrency=1)
    )
    assert len(results) == 2
    assert results[0].chain_id == results[1].chain_id
    assert len(calls) == 1, "the duplicate chain was served from the per-run cache"


# ── 24. cited-evidence tier clamp: document-only citation inside a STRONG chain ─
#       can never become Strongly corroborated (must-fix 1) ────────────────────


def _mixed_strong_chain_with_document():
    """precise code + website + document → chain ceiling STRONG, but a document
    is present so a claim citing ONLY the document must be clamped to the document's
    strength, never to the chain's strong ceiling."""
    chains = link_proof_chains([_github_code(), _website(), _document()])
    assert len(chains) == 1, "shared project links these into one chain"
    return chains[0]


def test_document_only_citation_in_strong_chain_cannot_be_strong() -> None:
    chain = _mixed_strong_chain_with_document()
    doc = _ev_id(SOURCE_DOCUMENT, "doc-1")
    gh = _ev_id(SOURCE_GITHUB, "gh-1")
    # Sanity: the chain really does carry strong (precise-code) evidence too.
    assert gh in chain.linked_evidence_ids and doc in chain.linked_evidence_ids

    raw = _llm_json(
        [
            {
                # The LLM cites ONLY the document but asks for the strongest tier.
                "claim": "The implementation is demonstrated by the attached report.",
                "supporting_evidence_ids": [doc],
                "why_connected": "doc",
                "limitations": [],
                "qualitative_tier": TIER_STRONG,
            }
        ]
    )
    result = synthesize_chain(chain, llm_fn=_llm(raw))
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.supporting_evidence_ids == (doc,)
    # Clamped to the cited document's strength — never strong/corroborated, even
    # though the WHOLE chain ceiling is Strongly corroborated.
    assert claim.qualitative_tier not in (TIER_STRONG, TIER_CORROBORATED)
    assert _TIER_RANK[claim.qualitative_tier] >= _TIER_RANK[TIER_SUPPORTING]

    # A claim that DOES cite the precise GitHub code may still reach the strong tier.
    raw_strong = _llm_json(
        [
            {
                "claim": "Precise GitHub code plus a live workflow show the skill.",
                "supporting_evidence_ids": [gh, _ev_id(SOURCE_WEBSITE, "w-1")],
                "why_connected": "Same project.",
                "limitations": [],
                "qualitative_tier": TIER_STRONG,
            }
        ]
    )
    strong_result = synthesize_chain(chain, llm_fn=_llm(raw_strong))
    assert strong_result.claims[0].qualitative_tier == TIER_STRONG


def test_repo_level_only_citation_stays_weaker_than_precise() -> None:
    """A claim citing only repo-level fallback stays weaker than precise code."""
    chains = link_proof_chains([_github_code(), _repo_github(source_id="gh-r")])
    assert len(chains) == 1
    chain = chains[0]
    repo = _ev_id(SOURCE_GITHUB, "gh-r")
    raw = _llm_json(
        [
            {
                "claim": "Repository-level evidence references the skill.",
                "supporting_evidence_ids": [repo],
                "why_connected": "same repo",
                "limitations": [],
                "qualitative_tier": TIER_STRONG,
            }
        ]
    )
    result = synthesize_chain(chain, llm_fn=_llm(raw))
    assert _TIER_RANK[result.claims[0].qualitative_tier] > _TIER_RANK[TIER_STRONG]


# ── 25. score / ranking / rating / percentile language is scrubbed (must-fix 2) ─


def test_score_and_ranking_language_is_scrubbed() -> None:
    chain = _strong_chain()
    gh = _ev_id(SOURCE_GITHUB, "gh-1")
    raw = _llm_json(
        [
            {
                "claim": (
                    "This candidate earned a trust score 98 and a verification "
                    "score 92, ranked #1 overall, rated 9.8 out of 10, 4.9 stars, "
                    "in the top 1% — a 98/100 result and 98th percentile."
                ),
                "supporting_evidence_ids": [gh],
                "why_connected": "Ranked #1 and 9.8 out of 10 across reviewers.",
                "limitations": ["Only a 4.9 stars sample so far."],
                "qualitative_tier": TIER_CORROBORATED,
            }
        ],
        overall_summary="Overall trust score 98, ranked #1, 9.8 out of 10.",
    )
    result = synthesize_chain(chain, llm_fn=_llm(raw))
    blob = json.dumps(result.public_view()).lower()
    for needle in (
        "trust score 98",
        "verification score 92",
        "ranked #1",
        "rank #1",
        "9.8 out of 10",
        "98/100",
        "4.9 stars",
        "top 1%",
        "percentile",
    ):
        assert needle not in blob, f"score/ranking fragment leaked: {needle}"
    # Line numbers / harmless technical numbers are NOT clobbered by the scrubber.
    assert _safe_text("See app/api/routes.py line 252 for predict().").find("252") != -1


# ── 26. production integration uses the CONCURRENT orchestrator (must-fix 3) ────


def test_production_integration_uses_concurrent_orchestrator(monkeypatch) -> None:
    import app.services.llm_proof_synthesis_service as llm_mod

    called = {"async": 0}
    real_async = llm_mod.synthesize_linked_chains_async

    async def _spy_async(chains, **kwargs):
        called["async"] += 1
        return await real_async(chains, **kwargs)

    # The bounded wrapper (used in production) resolves this name as a module global
    # at call time, so patching it here proves production drives the concurrent path.
    monkeypatch.setattr(llm_mod, "synthesize_linked_chains_async", _spy_async)

    mem_store: dict = {}
    pipeline_db: dict = {}
    gh_id = _strong_seeded_github(mem_store, "Python")
    session_id = _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo="octocat/Hello-World",
        attached={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")

    assert called["async"] >= 1, "production integration must use the concurrent orchestrator"
    assert isinstance(report["llm_synthesis"], list)
    # Deterministic in tests (layer disabled by the hermetic fixture).
    for syn in report["llm_synthesis"]:
        assert syn["source"] == "deterministic"


def test_bounded_orchestrator_runs_inside_a_running_loop() -> None:
    """The sync bounded wrapper is safe even when a loop is already running."""
    from app.services.llm_proof_synthesis_service import synthesize_linked_chains_bounded

    chains = [_chain_for(i) for i in range(3)]

    async def _from_async():
        # Calling the sync wrapper from inside a live loop must not raise
        # "asyncio.run() cannot be called from a running event loop".
        return synthesize_linked_chains_bounded(chains, llm_fn=_citing_llm)

    results = asyncio.run(_from_async())
    assert [r.chain_id for r in results] == [c.chain_id for c in chains]
    assert all(r.source == "llm" for r in results)


# ── 27. shared hermeticity guard: production path never calls a real provider ───
#        even when a developer .env would enable synthesis (Codex must-fix) ──────


def test_production_path_makes_no_real_provider_call_when_env_enables(monkeypatch) -> None:
    """Even with a developer ``.env`` that turns the LLM layer ON, the production
    synthesis path (the proof-synthesis agent — shared by VBR reports and the work
    passport) must never make a real provider/network call.

    The shared autouse ``_hermetic_llm_synthesis`` guard in ``conftest.py`` keeps
    every backend suite hermetic; here we PROVE its defense-in-depth holds by
    configuring synthesis ON exactly as a leaked dev ``.env`` would (enabled +
    ``local_openai`` + a real-looking base url), WITHOUT opting back into the real
    provider builder. A spy ``httpx.Client`` records (and rejects) any construction,
    so any real synthesis network attempt would fail the test loudly.
    """
    import httpx

    constructed: list = []

    class _SpyClient:  # pragma: no cover - only constructed if the guard regresses
        def __init__(self, *args, **kwargs):
            constructed.append((args, kwargs))
            raise RuntimeError(
                "real network call attempted from the synthesis provider path "
                "despite the shared hermeticity guard"
            )

    monkeypatch.setattr(httpx, "Client", _SpyClient)

    # Simulate a developer .env flipping the layer on (overrides the conftest disable).
    # We deliberately do NOT restore the real provider builder, so the guard alone
    # must keep this hermetic.
    monkeypatch.setattr(settings, "llm_synthesis_enabled", True)
    monkeypatch.setattr(settings, "llm_synthesis_provider", "local_openai")
    monkeypatch.setattr(settings, "local_llm_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(settings, "local_llm_model", "qwen3:14b")

    # The configured provider still resolves to the deterministic fallback (None).
    assert _resolve_llm_fn() is None

    mem_store: dict = {}
    pipeline_db: dict = {}
    gh_id = _strong_seeded_github(mem_store, "Python")
    session_id = _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo="octocat/Hello-World",
        attached={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")

    assert constructed == [], "synthesis path must not construct a real httpx client"
    assert isinstance(report["llm_synthesis"], list) and report["llm_synthesis"]
    for syn in report["llm_synthesis"]:
        assert syn["source"] == "deterministic"
