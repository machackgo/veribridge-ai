"""Tests for the Cross-Proof Linking Engine (Step 3).

The linker reads Step 2's uniform ``NormalizedEvidenceArtifact`` set and connects
artifacts that describe the SAME work (project / repo / endpoint / function /
explanation) into a :class:`LinkedProofChain`. It is purely deterministic — no
LLM, no source-table reads.

Invariants under test:

* Positive links — precise GitHub + Website runtime for the same project/skill;
  GitHub endpoint code + a Project Defense that explains the same endpoint.
* Documents corroborate only (they join via project signal, never become primary).
* False-positive prevention — the same generic skill across two different projects
  never merges; generic-word overlap alone never links.
* Public-safe output leaks no private ids / metadata / raw payloads.
* Chain ids are deterministic and stable for the same evidence set.

Most tests build artifacts directly for precise control over the matching signals;
the final test exercises the full Skill Report → synthesis → linker pipeline.
"""

from __future__ import annotations

import hashlib
from itertools import permutations
from uuid import uuid4

from app.services.cross_proof_linking_service import (
    LinkedProofChain,
    link_proof_chains,
)
from app.services.evidence_normalization_service import (
    SOURCE_DEFENSE,
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    SOURCE_WEBSITE,
    STRENGTH_CORROBORATION,
    STRENGTH_PRECISE_CODE,
    STRENGTH_RUNTIME,
    STRENGTH_SELF_EXPLANATION,
    NormalizedEvidenceArtifact,
)
from app.services.proof_synthesis_agent_service import build_skill_proof_synthesis

from tests.test_vbr_project_defense import (
    USER_ID,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_workflow_analysis,
)


# ── Artifact builders (already-safe normalized shape) ─────────────────────────


def _opaque_ev_id(source_type: str, source_id: str) -> str:
    """Opaque ``ev_…`` id (mirrors the real normalizer — never embeds source_id)."""
    digest = hashlib.sha1(f"{source_type}:{source_id}".encode()).hexdigest()[:16]
    return f"ev_{source_type}_{digest}"


def _github_code(
    *,
    project_id: str | None = "p1",
    project_title: str | None = "Boston Smart Accident Rerouting",
    skill: str = "Python",
    function_name: str = "predict",
    file_path: str = "app/api/routes.py",
    repo: str | None = "octocat/boston-rerouting",
    summary: str = "Implements the risk prediction handler.",
    source_id: str = "gh-1",
) -> NormalizedEvidenceArtifact:
    meta: dict = {"function_name": function_name, "file_path": file_path}
    if repo:
        meta["repo_url"] = f"https://github.com/{repo}"
        meta["github_line_url"] = f"https://github.com/{repo}/blob/main/{file_path}#L10-L20"
    return NormalizedEvidenceArtifact(
        evidence_id=_opaque_ev_id(SOURCE_GITHUB, source_id),
        source_type=SOURCE_GITHUB,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title=project_title,
        source_id=source_id,
        source_label="GitHub Proof",
        exact_location=f"{file_path} · {function_name}()",
        safe_summary=summary,
        proof_strength=STRENGTH_PRECISE_CODE,
        public_safe=True,
        metadata=meta,
    )


def _website(
    *,
    project_id: str | None = "p1",
    project_title: str | None = "Boston Smart Accident Rerouting",
    skill: str = "Python",
    summary: str = "Live workflow runs the rerouting demo end to end.",
    source_id: str = "w-1",
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_opaque_ev_id(SOURCE_WEBSITE, source_id),
        source_type=SOURCE_WEBSITE,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title=project_title,
        source_id=source_id,
        source_label="Website Proof",
        exact_location="demo.example.com",
        safe_summary=summary,
        proof_strength=STRENGTH_RUNTIME,
        public_safe=True,
        metadata={"public_url": "https://demo.example.com"},
    )


def _defense(
    *,
    project_id: str | None = None,
    project_title: str | None = None,
    skill: str = "Python",
    summary: str = "The candidate explained how the /predict endpoint returns a risk score.",
    source_id: str = "d-1",
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_opaque_ev_id(SOURCE_DEFENSE, source_id),
        source_type=SOURCE_DEFENSE,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title=project_title,
        source_id=source_id,
        source_label="Project Defense",
        exact_location="overall explanation",
        safe_summary=summary,
        proof_strength=STRENGTH_SELF_EXPLANATION,
        public_safe=False,
        metadata={},
    )


def _document(
    *,
    project_id: str | None = "p1",
    project_title: str | None = "Boston Smart Accident Rerouting",
    skill: str = "Python",
    summary: str = "Report section describes the prediction pipeline.",
    source_id: str = "doc-1",
) -> NormalizedEvidenceArtifact:
    return NormalizedEvidenceArtifact(
        evidence_id=_opaque_ev_id(SOURCE_DOCUMENT, source_id),
        source_type=SOURCE_DOCUMENT,
        skill_name=skill,
        canonical_skill_name=skill,
        subskill_name=None,
        project_id=project_id,
        project_title=project_title,
        source_id=source_id,
        source_label="Document Proof",
        exact_location="Page 2 · Methods",
        safe_summary=summary,
        proof_strength=STRENGTH_CORROBORATION,
        public_safe=False,
        metadata={"corroborates": "GitHub implementation", "citation": "Page 2 · Methods"},
    )


def _chain_with(chains: list[LinkedProofChain], evidence_id: str) -> LinkedProofChain:
    return next(c for c in chains if evidence_id in c.linked_evidence_ids)


# ── 1. Precise GitHub links with Website workflow for same project + skill ─────


def test_links_precise_github_with_website_for_same_project() -> None:
    chains = link_proof_chains([_github_code(), _website()])
    assert len(chains) == 1, "same project_id + repo + skill → ONE chain"
    chain = chains[0]
    assert chain.source_types_present == (SOURCE_GITHUB, SOURCE_WEBSITE)
    # Precise GitHub code is the primary implementation proof, not the website.
    assert chain.primary_source_type == SOURCE_GITHUB
    assert chain.proof_strength_summary["has_precise_code"] is True
    assert chain.proof_strength_summary["has_runtime_behavior"] is True
    assert any("project" in r.lower() for r in chain.connection_reasons)


# ── 2. GitHub endpoint code links with a Defense that names the same endpoint ──


def test_links_github_endpoint_with_defense_mentioning_same_endpoint() -> None:
    # No shared project / repo — isolate the structural-endpoint link path.
    github = _github_code(
        project_id=None,
        project_title=None,
        repo=None,
        function_name="predict",
        summary="Risk endpoint handler.",
        source_id="gh-ep",
    )
    defense = _defense(project_id=None, project_title=None, source_id="d-ep")
    chains = link_proof_chains([github, defense])
    assert len(chains) == 1, "shared structural endpoint 'predict' → ONE chain"
    chain = chains[0]
    assert set(chain.source_types_present) == {SOURCE_GITHUB, SOURCE_DEFENSE}
    assert chain.primary_source_type == SOURCE_GITHUB  # code, not the explanation
    assert any("predict" in r.lower() for r in chain.connection_reasons)


# ── 3. Documents corroborate only — join via project, never become primary ─────


def test_document_links_only_as_corroboration() -> None:
    chains = link_proof_chains([_github_code(), _document()])
    assert len(chains) == 1
    chain = chains[0]
    assert SOURCE_DOCUMENT in chain.source_types_present
    # The document joined the chain but is NEVER the primary implementation proof.
    assert chain.primary_source_type == SOURCE_GITHUB
    assert chain.proof_strength_summary["corroborating_document_count"] == 1
    assert any("corroborate" in limit.lower() for limit in chain.limitations)


def test_document_does_not_link_by_free_text_token_alone() -> None:
    # A document that shares only a free-text word (no project signal) must NOT
    # be pulled into the code chain — documents corroborate by attachment only.
    github = _github_code(project_id="pA", project_title=None, repo=None, source_id="gh-x")
    document = _document(project_id=None, project_title=None, source_id="doc-x")
    chains = link_proof_chains([github, document])
    assert len(chains) == 2, "unattached document stays separate from the code chain"


# ── 4. Same generic skill across two DIFFERENT projects must not merge ─────────


def test_same_skill_two_different_projects_do_not_merge() -> None:
    boston = _github_code(
        project_id="pA",
        project_title="Boston Smart Accident Rerouting",
        repo="octocat/boston-rerouting",
        function_name="predict",
        file_path="boston/routes.py",
        summary="Computes accident risk for rerouting.",
        source_id="gh-a",
    )
    weather = _github_code(
        project_id="pB",
        project_title="Coastal Weather Forecast Portal",
        repo="octocat/weather-portal",
        function_name="forecast",
        file_path="weather/views.py",
        summary="Renders the coastal weather forecast.",
        source_id="gh-b",
    )
    chains = link_proof_chains([boston, weather])
    assert len(chains) == 2, "same skill (Python) alone must NOT merge two projects"
    assert {c.project_id for c in chains} == {"pA", "pB"}


# ── 4b. Conflicting explicit project_id is a hard blocker for token linking ────


def test_shared_endpoint_does_not_merge_conflicting_project_ids() -> None:
    # Both artifacts expose the SAME structural endpoint ("/predict") and the SAME
    # canonical skill, but carry DIFFERENT explicit project_id values. A shared
    # structural token must never override conflicting project identity.
    project_a = _github_code(
        project_id="project-a",
        project_title=None,
        repo=None,
        function_name="predict",
        file_path="service_a/routes.py",
        summary="Project A exposes the /predict endpoint for risk scoring.",
        source_id="gh-pa",
    )
    project_b = _github_code(
        project_id="project-b",
        project_title=None,
        repo=None,
        function_name="predict",
        file_path="service_b/routes.py",
        summary="Project B exposes the /predict endpoint for its own model.",
        source_id="gh-pb",
    )
    chains = link_proof_chains([project_a, project_b])
    assert len(chains) == 2, "conflicting explicit project_id must block /predict union"
    assert {c.project_id for c in chains} == {"project-a", "project-b"}


def test_neutral_artifact_does_not_bridge_conflicting_project_ids() -> None:
    # A project_id-less Defense that names "/predict" must not transitively bridge
    # two artifacts whose explicit project_id values conflict.
    project_a = _github_code(
        project_id="project-a",
        project_title=None,
        repo=None,
        function_name="predict",
        file_path="service_a/routes.py",
        summary="Project A's /predict handler.",
        source_id="gh-na",
    )
    project_b = _github_code(
        project_id="project-b",
        project_title=None,
        repo=None,
        function_name="predict",
        file_path="service_b/routes.py",
        summary="Project B's /predict handler.",
        source_id="gh-nb",
    )
    neutral = _defense(project_id=None, project_title=None, source_id="d-bridge")
    chains = link_proof_chains([project_a, project_b, neutral])
    a_chain = _chain_with(chains, project_a.evidence_id)
    b_chain = _chain_with(chains, project_b.evidence_id)
    assert a_chain.chain_id != b_chain.chain_id, "neutral artifact must not bridge projects"
    assert project_b.evidence_id not in a_chain.linked_evidence_ids


def test_shared_endpoint_still_links_within_same_project_id() -> None:
    # Positive control: same explicit project_id + shared "/predict" structural
    # token still links (the blocker only fires on CONFLICTING project ids).
    code = _github_code(
        project_id="project-a",
        project_title=None,
        repo=None,
        function_name="predict",
        file_path="service_a/routes.py",
        summary="Project A's /predict handler.",
        source_id="gh-same1",
    )
    defense = _defense(
        project_id="project-a",
        project_title=None,
        summary="The candidate explained the /predict endpoint of this project.",
        source_id="d-same1",
    )
    chains = link_proof_chains([code, defense])
    assert len(chains) == 1, "same project_id + shared /predict must still link"
    assert set(chains[0].source_types_present) == {SOURCE_GITHUB, SOURCE_DEFENSE}


def test_neutral_artifact_does_not_bridge_across_separate_token_buckets() -> None:
    # Component-wide blocker: a project_id-less Defense that names BOTH "/predict"
    # and "/classify" shares one structural token with project-a (via /predict) and
    # a DIFFERENT structural token with project-b (via /classify). Each token bucket
    # on its own sees only one explicit project_id (so no single-bucket conflict),
    # but transitively the neutral artifact would merge project-a ↔ project-b. The
    # connected-component blocker must keep them apart.
    project_a = _github_code(
        project_id="project-a",
        project_title=None,
        repo=None,
        function_name="predict",
        file_path="service_a/routes.py",
        skill="API Development",
        summary="Project A exposes the /predict endpoint.",
        source_id="gh-bridge-a",
    )
    project_b = _github_code(
        project_id="project-b",
        project_title=None,
        repo=None,
        function_name="classify",
        file_path="service_b/routes.py",
        skill="API Development",
        summary="Project B exposes the /classify endpoint.",
        source_id="gh-bridge-b",
    )
    neutral = _defense(
        project_id=None,
        project_title=None,
        skill="API Development",
        summary="The candidate explained both the /predict and the /classify endpoints.",
        source_id="d-bridge-both",
    )

    chains = link_proof_chains([project_a, project_b, neutral])

    a_chain = _chain_with(chains, project_a.evidence_id)
    b_chain = _chain_with(chains, project_b.evidence_id)
    # project-a and project-b must NOT collapse into one merged chain.
    assert a_chain.chain_id != b_chain.chain_id, "neutral must not bridge across token buckets"
    assert project_b.evidence_id not in a_chain.linked_evidence_ids
    assert project_a.evidence_id not in b_chain.linked_evidence_ids
    # No single chain contains both explicit projects.
    assert not any(
        project_a.evidence_id in c.linked_evidence_ids
        and project_b.evidence_id in c.linked_evidence_ids
        for c in chains
    ), "no chain may hold both conflicting projects"
    # The bridging artifact is dropped from structural linking, not arbitrarily
    # attached to one side.
    assert neutral.evidence_id not in a_chain.linked_evidence_ids
    assert neutral.evidence_id not in b_chain.linked_evidence_ids


def test_neutral_artifact_links_when_only_one_project_group_present() -> None:
    # Positive control for the blocker: a project_id-less Defense that names
    # "/predict" still links to the one explicit project that exposes /predict —
    # the bridge guard only drops it when >= 2 conflicting projects are reachable.
    project_a = _github_code(
        project_id="project-a",
        project_title=None,
        repo=None,
        function_name="predict",
        file_path="service_a/routes.py",
        skill="API Development",
        summary="Project A exposes the /predict endpoint.",
        source_id="gh-solo-a",
    )
    neutral = _defense(
        project_id=None,
        project_title=None,
        skill="API Development",
        summary="The candidate explained the /predict endpoint.",
        source_id="d-solo",
    )
    chains = link_proof_chains([project_a, neutral])
    assert len(chains) == 1, "project-less /predict attaches to the single matching project"
    assert set(chains[0].source_types_present) == {SOURCE_GITHUB, SOURCE_DEFENSE}


# ── 4c. Layer-1 project signals are order-independent under conflicting ids ─────


def _membership(chains: list[LinkedProofChain]) -> frozenset[frozenset[str]]:
    """Order-independent fingerprint of chain membership (set of id-sets)."""
    return frozenset(frozenset(c.linked_evidence_ids) for c in chains)


def test_layer1_neutral_does_not_attach_to_conflicting_project_by_input_order() -> None:
    # A project-less neutral artifact shares the SAME distinctive project title AND
    # the SAME repository with TWO artifacts that carry CONFLICTING explicit
    # project_id values. Distinct function/file names keep this purely a Layer-1
    # (project-signal) case, isolated from structural-token linking. The neutral
    # artifact must not attach to project-a in one input order and project-b in
    # another — it is compatible with both conflicting groups, so it attaches to
    # neither, and chains stay identical across every permutation.
    shared_title = "Quantum Ledger Reconciliation Engine"
    shared_repo = "octocat/quantum-ledger"
    project_a = _github_code(
        project_id="project-a",
        project_title=shared_title,
        repo=shared_repo,
        function_name="alpha",
        file_path="service_a/alpha.py",
        summary="Project A module.",
        source_id="gh-l1-a",
    )
    project_b = _github_code(
        project_id="project-b",
        project_title=shared_title,
        repo=shared_repo,
        function_name="beta",
        file_path="service_b/beta.py",
        summary="Project B module.",
        source_id="gh-l1-b",
    )
    neutral = _github_code(
        project_id=None,
        project_title=shared_title,
        repo=shared_repo,
        function_name="gamma",
        file_path="service_c/gamma.py",
        summary="Neutral module sharing the title and repo.",
        source_id="gh-l1-neutral",
    )

    artifacts = [project_a, project_b, neutral]
    fingerprints: set[frozenset[frozenset[str]]] = set()
    neutral_partners: set[frozenset[str]] = set()
    for perm in permutations(artifacts):
        chains = link_proof_chains(list(perm))
        a_chain = _chain_with(chains, project_a.evidence_id)
        b_chain = _chain_with(chains, project_b.evidence_id)
        neutral_chain = _chain_with(chains, neutral.evidence_id)

        # project-a and project-b never collapse into one chain.
        assert a_chain.chain_id != b_chain.chain_id
        assert project_b.evidence_id not in a_chain.linked_evidence_ids
        assert project_a.evidence_id not in b_chain.linked_evidence_ids
        assert not any(
            project_a.evidence_id in c.linked_evidence_ids
            and project_b.evidence_id in c.linked_evidence_ids
            for c in chains
        ), "no chain may hold both conflicting projects"

        # The neutral artifact never arbitrarily attaches to either side.
        assert neutral.evidence_id not in a_chain.linked_evidence_ids
        assert neutral.evidence_id not in b_chain.linked_evidence_ids

        fingerprints.add(_membership(chains))
        neutral_partners.add(frozenset(neutral_chain.linked_evidence_ids))

    # Chain membership (and therefore chain_ids) is identical across every order.
    assert len(fingerprints) == 1, "chain membership must be order-independent"
    # The neutral artifact lands in exactly one stable group regardless of order
    # (never project-a's chain in one permutation and project-b's in another).
    assert neutral_partners == {frozenset({neutral.evidence_id})}


def test_layer1_neutral_attaches_when_only_one_project_group_present() -> None:
    # Positive control for the Layer-1 bridge guard: a project-less artifact that
    # shares the distinctive title + repo with only ONE explicit project group
    # still attaches to it — and does so identically across input orders.
    shared_title = "Quantum Ledger Reconciliation Engine"
    shared_repo = "octocat/quantum-ledger"
    project_a = _github_code(
        project_id="project-a",
        project_title=shared_title,
        repo=shared_repo,
        function_name="alpha",
        file_path="service_a/alpha.py",
        summary="Project A module.",
        source_id="gh-solo1-a",
    )
    neutral = _github_code(
        project_id=None,
        project_title=shared_title,
        repo=shared_repo,
        function_name="gamma",
        file_path="service_c/gamma.py",
        summary="Neutral module sharing the title and repo.",
        source_id="gh-solo1-neutral",
    )
    forward = link_proof_chains([project_a, neutral])
    reverse = link_proof_chains([neutral, project_a])
    assert len(forward) == 1, "single compatible project → neutral attaches via Layer 1"
    assert _membership(forward) == _membership(reverse)
    assert neutral.evidence_id in forward[0].linked_evidence_ids
    assert project_a.evidence_id in forward[0].linked_evidence_ids


def test_layer1_same_project_title_and_repo_still_link() -> None:
    # Same-project Layer-1 linking must keep working: two artifacts that share the
    # SAME explicit project_id (plus title + repo) stay one chain.
    code = _github_code(
        project_id="project-a",
        project_title="Quantum Ledger Reconciliation Engine",
        repo="octocat/quantum-ledger",
        function_name="alpha",
        file_path="service_a/alpha.py",
        summary="Project A code.",
        source_id="gh-sp-a",
    )
    website = _website(
        project_id="project-a",
        project_title="Quantum Ledger Reconciliation Engine",
        summary="Live demo of the project.",
        source_id="w-sp-a",
    )
    chains = link_proof_chains([code, website])
    assert len(chains) == 1, "same project_id + title still links via Layer 1"
    assert set(chains[0].source_types_present) == {SOURCE_GITHUB, SOURCE_WEBSITE}


# ── 5. Generic-word overlap alone must not link ───────────────────────────────


def test_generic_keyword_overlap_alone_does_not_link() -> None:
    # Two unrelated artifacts whose ONLY shared words are generic (app/page/model/
    # data/api/code) and no project/repo signal.
    a = _github_code(
        project_id=None,
        project_title=None,
        repo=None,
        function_name="main",
        file_path="app/index.py",
        summary="The app page renders the model data via the api code.",
        source_id="gh-g1",
    )
    b = _github_code(
        project_id=None,
        project_title=None,
        repo=None,
        function_name="main",
        file_path="app/index.py",
        summary="Another app page loads model data through the api code.",
        source_id="gh-g2",
    )
    chains = link_proof_chains([a, b])
    assert len(chains) == 2, "generic words (app/page/model/data/api/code) must not link"


# ── 6. Public-safe output leaks no private fields ─────────────────────────────

_FORBIDDEN = (
    "gh-1",
    "w-1",
    "doc-1",
    "p1",
    "source_id",
    "secret_token",
    "/storage/v1/object",
    "supabase.co/storage",
)


def test_public_view_does_not_leak_private_fields() -> None:
    chains = link_proof_chains([_github_code(), _website(), _document()])
    chain = chains[0]
    public = chain.public_view()
    serialized = str(public).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in serialized, f"linked chain leaked {needle!r}"
    # Private project_id is dropped; safe evidence-id hashes are retained for Step 4.
    assert "project_id" not in public
    assert public["linked_evidence_ids"], "safe evidence ids survive for citation"
    assert all(eid.startswith("ev_") for eid in public["linked_evidence_ids"])
    # Member projections are the artifact public views (no source_id / metadata).
    for ev in public["evidence"]:
        assert "source_id" not in ev
        assert "metadata" not in ev


def test_public_view_scrubs_hostile_strings() -> None:
    hostile = _github_code(
        summary=(
            "Calls https://proj.supabase.co/storage/v1/object/sign/x?token=sigSECRET "
            "with access_token=eyJSECRET"
        ),
        source_id="gh-hostile",
    )
    chains = link_proof_chains([hostile, _website()])
    serialized = str(chains[0].public_view()).lower()
    for secret in ("sigsecret", "eyjsecret", "/storage/v1/object"):
        assert secret not in serialized, secret


# ── 7. Deterministic, stable chain ids ────────────────────────────────────────


def test_chain_ids_are_stable_for_same_evidence_set() -> None:
    arts = [_github_code(), _website(), _document()]
    first = link_proof_chains(arts)
    # Re-run with the SAME artifacts in a DIFFERENT order — ids must be identical.
    second = link_proof_chains(list(reversed(arts)))
    assert [c.chain_id for c in first] == [c.chain_id for c in second]
    assert first[0].chain_id.startswith("chain_")
    # The full chain projection is deterministic too.
    assert first[0].to_dict() == second[0].to_dict()


def test_transitive_links_collapse_into_one_chain() -> None:
    # GitHub↔Website by project; GitHub↔Defense by endpoint → all one chain.
    github = _github_code(function_name="predict", source_id="gh-t")
    website = _website(source_id="w-t")
    defense = _defense(project_id=None, project_title=None, source_id="d-t")
    chains = link_proof_chains([github, website, defense])
    assert len(chains) == 1
    assert set(chains[0].source_types_present) == {
        SOURCE_GITHUB,
        SOURCE_WEBSITE,
        SOURCE_DEFENSE,
    }


# ── 8. End-to-end through the Proof Synthesis Agent pipeline ───────────────────


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


def test_synthesis_pipeline_emits_linked_proof_chains() -> None:
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

    # Backward compatible: original synthesis keys still present.
    assert "proof_chains" in report and "unlinked_supporting_evidence" in report
    # New: the linker attaches connected proof chains to the synthesis output.
    linked = report["linked_proof_chains"]
    assert linked, "synthesis output carries linked proof chains"
    chain = next(c for c in linked if c.get("project_id") == pid)
    assert SOURCE_GITHUB in chain["source_types_present"]
    assert SOURCE_WEBSITE in chain["source_types_present"]
    assert chain["primary_source_type"] == SOURCE_GITHUB
    assert chain["linked_evidence_ids"]

    # The linked chain output never leaks raw/private payloads.
    serialized = str(linked).lower()
    for needle in ("analysis_snapshot", "raw_dump", "/storage/v1/object"):
        assert needle not in serialized
