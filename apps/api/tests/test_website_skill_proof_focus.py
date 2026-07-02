"""Tests for the Website semantic proof layer (purpose / skill relevance / honesty).

Covers:

* the deterministic closed-vocabulary purpose classifier (chat / prediction /
  form / upload / dashboard / availability / unknown — from already-safe text);
* per-skill-family relevance recomputation (React direct vs ML/GenAI *product
  behaviour context* vs DevOps conservative availability vs backend API context);
* honest limitations (a website UI never proves ML training / LLM internals /
  CI-CD internals by itself);
* Skill Report integration: website purpose/relevance fields on report items,
  the connected-chain ``website_connection_note``, and the honest gap when no
  Website Proof maps to the skill;
* public projection: only closed-vocabulary keys/derived labels ride out — raw
  DOM/OCR/visual summaries and bogus keys never do.

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

from app.schemas.vbr_student_report import SkillReportEvidenceItem
from app.services.evidence_normalization_service import normalize_report_item
from app.services.public_report_safety_service import public_safe_evidence_artifact
from app.services.student_proof_vault_service import collect_skill_report
from app.services.website_skill_proof_focus import (
    ALLOWED_WEBSITE_EVIDENCE_CHIPS,
    ALLOWED_WEBSITE_PURPOSE_KEYS,
    ALLOWED_WEBSITE_RELEVANCE_KEYS,
    attach_website_corroboration,
    build_website_evidence_card,
    classify_website_purpose,
    classify_website_skill_relevance,
    derive_website_evidence_chips,
    describe_website_purpose,
    describe_website_skill_relevance,
    is_direct_website_relevance,
    public_screenshot_access_label,
    website_behavior_claim,
    website_chain_connection_note,
    website_corroboration_note,
    website_limitation_for,
    website_purpose_summary,
    website_skill_relevance_summary,
)

from tests.test_student_proof_vault import _seed_project, mem_store, pipeline_db  # noqa: F401
from tests.test_vbr_project_defense import (
    USER_ID,
    _seed_github_proof,
    _seed_workflow_analysis,
)


# ── Purpose classification (closed vocabulary, deterministic) ─────────────────


def test_purpose_chat_prompt_interface() -> None:
    key = classify_website_purpose(
        workflow_summary="The student typed a prompt into the chat box and a reply appeared."
    )
    assert key == "chat_prompt_interface"


def test_purpose_prediction_result_display_beats_generic_form() -> None:
    key = classify_website_purpose(
        workflow_summary=(
            "Accident details were entered into the form and a crash-risk prediction "
            "was displayed in the results panel."
        )
    )
    assert key == "prediction_result_display"


def test_purpose_interactive_form_flow() -> None:
    key = classify_website_purpose(
        workflow_summary="The user filled in the input fields and submitted the form."
    )
    assert key == "interactive_form_flow"


def test_purpose_file_upload_flow() -> None:
    key = classify_website_purpose(workflow_steps=["Upload a CSV file", "View parsed rows"])
    assert key == "file_upload_flow"


def test_purpose_dashboard_and_charts() -> None:
    assert classify_website_purpose(dom_summary="An analytics dashboard with KPI tiles") == "dashboard_view"
    assert classify_website_purpose(visual_summary="A bar chart plotting monthly totals") == "data_visualization"


def test_purpose_availability_floor_when_only_live_check() -> None:
    key = classify_website_purpose(live_check={"is_reachable": True})
    assert key == "deployed_availability"


def test_purpose_availability_floor_for_unclassifiable_narrative() -> None:
    # A safe narrative that matches no product pattern is still an observed
    # deployment — never silently promoted to a product flow.
    key = classify_website_purpose(workflow_summary="A working deployment was inspected.")
    assert key == "deployed_availability"


def test_purpose_fails_closed_to_unknown() -> None:
    assert classify_website_purpose() == "unknown_needs_review"


def test_purpose_labels_fail_closed_on_bogus_key() -> None:
    assert describe_website_purpose("totally_bogus") == "Unknown / needs review"
    assert website_purpose_summary(None)
    for key in ALLOWED_WEBSITE_PURPOSE_KEYS:
        assert describe_website_purpose(key)
        assert website_purpose_summary(key)


# ── Skill relevance (recomputed per selected skill, conservative) ─────────────


def test_ml_skill_prediction_ui_is_product_context_never_direct() -> None:
    key = classify_website_skill_relevance("prediction_result_display", skill="Machine Learning")
    assert key == "ml_product_context"
    assert not is_direct_website_relevance(key)
    label = describe_website_skill_relevance(key, "Machine Learning")
    assert "not Machine Learning implementation proof" in label
    assert "model training" in website_limitation_for(key)


def test_react_skill_interactive_ui_is_direct_frontend_evidence() -> None:
    key = classify_website_skill_relevance("prediction_result_display", skill="React")
    assert key == "direct_frontend_evidence"
    assert is_direct_website_relevance(key)
    assert "Direct React evidence" in describe_website_skill_relevance(key, "React")


def test_react_skill_landing_page_is_supporting_frontend_evidence() -> None:
    key = classify_website_skill_relevance("landing_overview", skill="React")
    assert key == "supporting_frontend_evidence"


def test_genai_skill_chat_ui_is_product_context_not_implementation() -> None:
    key = classify_website_skill_relevance("chat_prompt_interface", skill="Generative AI")
    assert key == "genai_product_context"
    assert "LLM/RAG implementation internals" in website_limitation_for(key)
    summary = website_skill_relevance_summary(key, "Generative AI")
    assert "does not" in summary and "prove" in summary


def test_devops_skill_is_always_conservative_deployment_availability() -> None:
    for purpose in ("prediction_result_display", "interactive_form_flow", "navigation_layout"):
        key = classify_website_skill_relevance(purpose, skill="Docker & Kubernetes")
        assert key == "deployment_availability_evidence"
    assert "Docker/Kubernetes/CI-CD internals" in website_limitation_for(
        "deployment_availability_evidence"
    )


def test_backend_skill_request_result_flow_is_api_behavior_context() -> None:
    key = classify_website_skill_relevance("api_backed_interaction", skill="FastAPI")
    assert key == "api_behavior_context"
    assert "server-side implementation" in website_limitation_for(key)


def test_dataviz_skill_charts_are_direct_dataviz_evidence() -> None:
    key = classify_website_skill_relevance("data_visualization", skill="Data Visualization")
    assert key == "data_visualization_evidence"
    assert is_direct_website_relevance(key)


def test_documentation_and_availability_floors_apply_to_every_family() -> None:
    for skill in ("React", "Machine Learning", "Generative AI", "FastAPI", "Quantum Wizardry"):
        assert (
            classify_website_skill_relevance("documentation_static", skill=skill)
            == "documentation_context"
        )
        assert (
            classify_website_skill_relevance("deployed_availability", skill=skill)
            == "deployment_availability_evidence"
        )


def test_unknown_purpose_or_bogus_key_fails_closed_to_needs_review() -> None:
    assert classify_website_skill_relevance("unknown_needs_review", skill="React") == "unknown_needs_review"
    assert classify_website_skill_relevance("bogus_key", skill="React") == "unknown_needs_review"
    assert "needs review" in describe_website_skill_relevance("bogus", "React").lower()


def test_every_relevance_key_has_label_summary_and_limitation() -> None:
    for key in ALLOWED_WEBSITE_RELEVANCE_KEYS:
        assert describe_website_skill_relevance(key, "React")
        assert website_skill_relevance_summary(key, "React")
        assert website_limitation_for(key)


# ── Connected chain note ──────────────────────────────────────────────────────


def test_chain_connection_note_mentions_each_companion_source() -> None:
    note = website_chain_connection_note(has_github=True, has_defense=True, has_document=True)
    assert note is not None
    assert "website demonstrates" in note
    assert "GitHub code shows the implementation" in note
    assert "Project Defense" in note
    assert "documents corroborate" in note


def test_chain_connection_note_is_none_with_no_companion_source() -> None:
    assert website_chain_connection_note(has_github=False, has_defense=False, has_document=False) is None


# ── Skill Report integration ──────────────────────────────────────────────────


_PREDICTION_WORKFLOW = (
    "Accident details were entered into the form and a crash-risk prediction "
    "was displayed in the results panel."
)


def test_attached_website_proof_joins_chain_with_purpose_and_note(
    mem_store: dict, pipeline_db: dict
) -> None:
    sid = _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Machine Learning"],
        workflow_summary=_PREDICTION_WORKFLOW,
    )
    gh_id = _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {"skill": "Machine Learning", "file_path": "train.py", "line_start": 10, "line_end": 20}
            ]
        },
    )
    pid = _seed_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": sid}],
        },
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if p["project_id"] == pid)
    assert chain["website_evidence"], "attached website proof must join the project chain"
    web = chain["website_evidence"][0]
    assert web["website_purpose_key"] == "prediction_result_display"
    assert web["website_purpose_label"] == "Prediction / result display"
    assert web["website_skill_relevance_key"] == "ml_product_context"
    # The chain explains how the website connects to the GitHub implementation.
    assert chain["website_connection_note"]
    assert "GitHub code shows the implementation" in chain["website_connection_note"]


def test_same_website_session_reads_differently_per_selected_skill(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Machine Learning", "React"],
        workflow_summary=_PREDICTION_WORKFLOW,
    )

    ml = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    ml_web = ml["website"][0]
    assert ml_web["website_skill_relevance_key"] == "ml_product_context"
    assert "not Machine Learning implementation proof" in ml_web["website_skill_relevance_label"]
    assert "model training" in ml_web["limitation"]

    react = collect_skill_report(mem_store, pipeline_db, USER_ID, "react")
    react_web = react["website"][0]
    assert react_web["website_skill_relevance_key"] == "direct_frontend_evidence"
    assert "Direct React evidence" in react_web["website_skill_relevance_label"]


def test_deployed_url_supports_devops_skill_only_conservatively(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Docker"],
        workflow_summary=_PREDICTION_WORKFLOW,
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "docker")
    web = report["website"][0]
    assert web["website_skill_relevance_key"] == "deployment_availability_evidence"
    assert "Docker/Kubernetes/CI-CD internals" in web["limitation"]


def test_genai_chat_ui_stays_product_context_in_report(mem_store: dict, pipeline_db: dict) -> None:
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Generative AI"],
        workflow_summary="The student typed a prompt into the chat box and a generated answer appeared.",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "generative-ai")
    web = report["website"][0]
    assert web["website_purpose_key"] == "chat_prompt_interface"
    assert web["website_skill_relevance_key"] == "genai_product_context"
    assert "LLM/RAG implementation internals" in web["limitation"]


def test_standalone_vault_bucket_never_claims_a_connection_note(
    mem_store: dict, pipeline_db: dict
) -> None:
    """UNATTACHED website + GitHub proofs share no confirmed project, so the
    standalone vault bucket must never claim they corroborate each other."""
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["React"],
        workflow_summary=_PREDICTION_WORKFLOW,
    )
    _seed_github_proof(mem_store)  # unattached Python + React GitHub proof
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "react")
    standalone = next(p for p in report["projects"] if not p["attached"])
    assert standalone["website_evidence"]
    assert standalone["website_connection_note"] is None


def test_missing_website_proof_produces_honest_gap(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(mem_store)  # Python + React, no website proof at all
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    assert not report["website"]
    assert any("No Website Proof maps to this skill" in g for g in report["gaps"])


# ── Public projection safety ──────────────────────────────────────────────────


def _website_report_item(**overrides) -> dict:
    item = {
        "proof_type": "Website Proof",
        "source_id": "wf-session-1",
        "skill_name": "React",
        "title": "https://demo.example.com",
        "safe_summary": "An interactive prediction form flow was recorded.",
        "safe_location": "demo.example.com",
        "public_safe": True,
        "limitation": "Confirms observed behaviour at inspection time.",
        "attached_project_ids": [],
        "public_url": "https://demo.example.com",
        "website_purpose_key": "prediction_result_display",
        "website_skill_relevance_key": "direct_frontend_evidence",
        # Raw-ish hydrated summaries — must NEVER ride into the public artifact.
        "dom_summary": "PRIVATE-DOM-SUMMARY",
        "ocr_summary": "PRIVATE-OCR-SUMMARY",
        "visual_summary": "PRIVATE-VISUAL-SUMMARY",
    }
    item.update(overrides)
    return item


def test_public_view_exposes_only_closed_vocab_website_labels() -> None:
    artifact = normalize_report_item(_website_report_item(), skill_name="React")
    assert artifact is not None
    public = artifact.public_view()
    assert public["website_purpose_key"] == "prediction_result_display"
    assert public["website_purpose_label"] == "Prediction / result display"
    assert public["website_skill_relevance_key"] == "direct_frontend_evidence"
    assert "Direct React evidence" in public["website_skill_relevance_label"]
    # No hydrated/raw field can appear in the public projection.
    flat = str(public)
    for leak in ("PRIVATE-DOM-SUMMARY", "PRIVATE-OCR-SUMMARY", "PRIVATE-VISUAL-SUMMARY"):
        assert leak not in flat
    assert "metadata" not in public and "source_id" not in public


def test_public_view_drops_bogus_website_keys_fail_closed() -> None:
    artifact = normalize_report_item(
        _website_report_item(
            website_purpose_key="raw_dom_dump", website_skill_relevance_key="s3://bucket/secret"
        ),
        skill_name="React",
    )
    assert artifact is not None
    public = artifact.public_view()
    assert public.get("website_purpose_key") is None
    assert public.get("website_purpose_label") is None
    assert public.get("website_skill_relevance_key") is None
    assert public.get("website_skill_relevance_label") is None


def test_public_safe_evidence_artifact_whitelists_website_fields() -> None:
    artifact = normalize_report_item(_website_report_item(), skill_name="React")
    assert artifact is not None
    projected = public_safe_evidence_artifact(artifact.public_view())
    assert projected["website_purpose_key"] == "prediction_result_display"
    assert projected["website_purpose_label"] == "Prediction / result display"
    assert projected["website_skill_relevance_key"] == "direct_frontend_evidence"
    assert projected["website_skill_relevance_label"]
    # A tampered payload with a smuggled key fails closed at the outer whitelist too.
    tampered = dict(artifact.public_view())
    tampered["website_purpose_key"] = "raw_dom_dump"
    tampered["website_skill_relevance_key"] = "not_a_real_key"
    reprojected = public_safe_evidence_artifact(tampered)
    assert reprojected.get("website_purpose_key") is None
    assert reprojected.get("website_purpose_label") is None
    assert reprojected.get("website_skill_relevance_key") is None
    assert reprojected.get("website_skill_relevance_label") is None


# ── Website Evidence Card (recruiter-inspectable, closed vocabularies) ────────


def test_evidence_chips_are_closed_vocabulary_and_purpose_aware() -> None:
    chips = derive_website_evidence_chips(
        "prediction_result_display",
        has_route=True,
        live_reachable=True,
        has_workflow=True,
        has_visual=True,
        has_ocr=True,
        has_dom=True,
    )
    assert set(chips) <= ALLOWED_WEBSITE_EVIDENCE_CHIPS
    assert "Route observed" in chips
    assert "Live check passed" in chips
    assert "Visual frame" in chips
    assert "Workflow navigation" in chips
    assert "Output / result visible" in chips
    # Input-driven purposes surface the input flow chip; dashboards their own.
    assert "User input flow" in derive_website_evidence_chips("interactive_form_flow")
    assert "Dashboard visible" in derive_website_evidence_chips("dashboard_view")
    # No signal at all → no chips (never invented).
    assert derive_website_evidence_chips("landing_overview") == []


def test_card_carries_purpose_relevance_chips_and_limitation() -> None:
    card = build_website_evidence_card(
        purpose_key="prediction_result_display",
        relevance_key="ml_product_context",
        skill="Machine Learning",
        workflow_summary=_PREDICTION_WORKFLOW,
        workflow_steps=["Enter accident details", "View prediction"],
        has_visual_summary=True,
        live_check={"is_reachable": True, "final_url": "https://demo.example.com/dashboard", "page_title": "Risk Dashboard"},
        open_website_url="https://demo.example.com",
        observed_at="2026-06-30T12:34:56Z",
    )
    assert card["route_or_page"] == "demo.example.com/dashboard"
    assert card["page_title"] == "Risk Dashboard"
    assert card["observed_at"] == "2026-06-30"
    assert card["website_purpose_label"] == "Prediction / result display"
    assert "not Machine Learning implementation proof" in card["skill_relevance_label"]
    assert "model training" in card["limitation"]
    assert card["open_website_url"] == "https://demo.example.com"
    assert set(card["evidence_basis_chips"]) <= ALLOWED_WEBSITE_EVIDENCE_CHIPS
    assert "Output / result visible" in card["evidence_basis_chips"]
    assert card["card_key"].startswith("web-")
    # Schema round-trip: the card validates against the strict report model.
    item = SkillReportEvidenceItem(
        proof_type="Website Proof", source_id="s1", website_evidence_card=card
    )
    assert item.website_evidence_card is not None


def test_card_screenshot_is_permission_gated_never_a_url() -> None:
    with_frames = build_website_evidence_card(
        purpose_key="dashboard_view",
        relevance_key="direct_frontend_evidence",
        skill="React",
        has_visual_summary=True,
    )
    assert with_frames["screenshot_available"] is True
    assert with_frames["screenshot_access_label"] == "private_candidate_permission_required"
    assert with_frames["screenshot_preview_url"] is None

    without_frames = build_website_evidence_card(
        purpose_key="dashboard_view",
        relevance_key="direct_frontend_evidence",
        skill="React",
    )
    assert without_frames["screenshot_available"] is False
    assert without_frames["screenshot_access_label"] == "unavailable"
    assert without_frames["screenshot_preview_url"] is None


def test_card_never_leaks_raw_payloads_or_unsafe_urls() -> None:
    # OCR/DOM/visual enter as PRESENCE booleans only — the card can only emit
    # closed-template sentences; a signed/internal URL is dropped fail-closed.
    card = build_website_evidence_card(
        purpose_key="chat_prompt_interface",
        relevance_key="genai_product_context",
        skill="Generative AI",
        has_ocr_summary=True,
        has_dom_summary=True,
        open_website_url="https://storage.internal/bucket/frame.jpg?X-Amz-Signature=SECRET",
        live_check={"is_reachable": True, "final_url": "not-a-url", "page_title": "Chat"},
    )
    assert card["open_website_url"] is None
    flat = str(card)
    for leak in ("SECRET", "X-Amz", "storage.internal"):
        assert leak not in flat
    assert "on-screen text consistent with" in card["ocr_evidence_summary_safe"]
    assert "page structure consistent with" in card["dom_evidence_summary_safe"]
    # Bogus keys fail closed to the needs-review vocabulary.
    bogus = build_website_evidence_card(
        purpose_key="raw_dom_dump", relevance_key="s3://x", skill="React"
    )
    assert bogus["website_purpose_key"] == "unknown_needs_review"
    assert bogus["skill_relevance_key"] == "unknown_needs_review"


def test_skill_report_website_item_carries_evidence_card(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Machine Learning"],
        workflow_summary=_PREDICTION_WORKFLOW,
        visual_reasoning_summary={
            "status": "analyzed",
            "summary": "A results panel displaying a computed crash-risk prediction.",
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    web = report["website"][0]
    card = web["website_evidence_card"]
    assert card, "website report items must carry the evidence card"
    assert card["website_purpose_key"] == "prediction_result_display"
    assert card["skill_relevance_key"] == "ml_product_context"
    assert card["open_website_url"] == "https://demo.example.com"
    assert "Workflow navigation" in card["evidence_basis_chips"]
    assert "Visual frame" in card["evidence_basis_chips"]
    # Frames were analyzed → honestly permission-gated, never a URL.
    assert card["screenshot_available"] is True
    assert card["screenshot_access_label"] == "private_candidate_permission_required"
    assert card["screenshot_preview_url"] is None
    assert card["observed_at"], "the capture date (date-only) rides on the card"
    assert len(str(card["observed_at"])) == 10


def test_public_view_carries_validated_chips_and_coerced_screenshot_status() -> None:
    item = _website_report_item(
        website_evidence_card={
            "evidence_basis_chips": [
                "Route observed",
                "Visual frame",
                "TOTALLY-BOGUS-CHIP",
                "s3://bucket/frame.jpg",
            ],
            "screenshot_available": True,
            # A preview-shaped label must NEVER survive the public projection.
            "screenshot_access_label": "public_safe_preview",
            "screenshot_preview_url": "https://storage.internal/frame.jpg?sig=SECRET",
            "observed_behavior_summary": "PRIVATE-NARRATIVE",
            "page_title": "PRIVATE-TITLE",
        }
    )
    artifact = normalize_report_item(item, skill_name="React")
    assert artifact is not None
    public = artifact.public_view()
    assert public["website_evidence_chips"] == ["Route observed", "Visual frame"]
    assert public["website_screenshot_available"] is True
    assert public["website_screenshot_access_label"] == "private_candidate_permission_required"
    flat = str(public)
    for leak in ("SECRET", "storage.internal", "PRIVATE-NARRATIVE", "PRIVATE-TITLE", "BOGUS"):
        assert leak not in flat

    # The outer public whitelist applies the same validation/coercion.
    projected = public_safe_evidence_artifact(public)
    assert projected["website_evidence_chips"] == ["Route observed", "Visual frame"]
    assert projected["website_screenshot_access_label"] == "private_candidate_permission_required"
    tampered = dict(public)
    tampered["website_evidence_chips"] = ["raw DOM dump", "Route observed"]
    tampered["website_screenshot_access_label"] = "public_safe_preview"
    tampered["website_screenshot_available"] = False
    reprojected = public_safe_evidence_artifact(tampered)
    assert reprojected["website_evidence_chips"] == ["Route observed"]
    assert reprojected["website_screenshot_access_label"] == "unavailable"


def test_public_screenshot_access_label_fails_closed() -> None:
    assert public_screenshot_access_label("public_safe_preview", screenshot_available=True) == (
        "private_candidate_permission_required"
    )
    assert public_screenshot_access_label("unavailable") == "unavailable"
    assert public_screenshot_access_label("s3://bucket/frame.jpg") == "unavailable"
    assert public_screenshot_access_label(None, screenshot_available=True) == (
        "private_candidate_permission_required"
    )


def test_missing_frames_render_unavailable_status_in_report(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["React"],
        workflow_summary=_PREDICTION_WORKFLOW,
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "react")
    card = report["website"][0]["website_evidence_card"]
    assert card["screenshot_available"] is False
    assert card["screenshot_access_label"] == "unavailable"
    assert card["screenshot_preview_url"] is None


# ── Website Live Behavior Evidence Chain (claim-first + cross-proof links) ────


def test_every_purpose_has_a_behavior_claim_and_fails_closed() -> None:
    for key in ALLOWED_WEBSITE_PURPOSE_KEYS:
        claim = website_behavior_claim(key)
        assert claim and claim.endswith(".")
    # Bogus / hostile keys fail closed to the unclassified claim.
    fallback = website_behavior_claim("unknown_needs_review")
    assert website_behavior_claim("raw_dom_dump") == fallback
    assert website_behavior_claim(None) == fallback


def test_card_leads_with_a_behavior_claim_and_defaults_to_standalone() -> None:
    card = build_website_evidence_card(
        purpose_key="prediction_result_display",
        relevance_key="ml_product_context",
        skill="Machine Learning",
    )
    assert card["behavior_claim"] == "User input produces a prediction/result display."
    # Corroboration is OFF by default — only the confirmed project-chain pass
    # may turn it on, so an unattached proof can never claim a connection.
    assert card["corroborates_github"] is False
    assert card["corroborates_defense"] is False
    assert card["corroborates_document"] is False
    assert card["corroboration_note"] is None
    assert card["connected_project_title"] is None
    # Schema round-trip with the new claim/corroboration fields.
    item = SkillReportEvidenceItem(
        proof_type="Website Proof", source_id="s1", website_evidence_card=card
    )
    assert item.website_evidence_card is not None


def test_attach_website_corroboration_sets_flags_note_and_chips() -> None:
    card = build_website_evidence_card(
        purpose_key="dashboard_view",
        relevance_key="direct_frontend_evidence",
        skill="React",
    )
    attach_website_corroboration(
        card,
        project_title="Boston Smart Accident Risk Rerouting",
        has_github=True,
        has_defense=True,
        has_document=False,
    )
    assert card["corroborates_github"] is True
    assert card["corroborates_defense"] is True
    assert card["corroborates_document"] is False
    assert card["connected_project_title"] == "Boston Smart Accident Risk Rerouting"
    assert "GitHub provides implementation evidence" in card["corroboration_note"]
    assert "Project Defense" in card["corroboration_note"]
    assert "document" not in card["corroboration_note"].lower()
    chips = card["evidence_basis_chips"]
    assert set(chips) <= ALLOWED_WEBSITE_EVIDENCE_CHIPS
    assert "Attached project" in chips
    assert "Corroborates GitHub" in chips
    assert "Corroborates Defense" in chips
    assert "Corroborates Document" not in chips
    # Idempotent + OR semantics: a second chain adds Document without
    # duplicating chips, and the first project title wins.
    attach_website_corroboration(card, project_title="Other Project", has_document=True)
    assert card["corroborates_github"] is True
    assert card["corroborates_document"] is True
    assert card["connected_project_title"] == "Boston Smart Accident Risk Rerouting"
    assert card["evidence_basis_chips"].count("Attached project") == 1
    assert card["evidence_basis_chips"].count("Corroborates GitHub") == 1
    assert "Corroborates Document" in card["evidence_basis_chips"]


def test_corroboration_note_is_none_without_companions() -> None:
    assert (
        website_corroboration_note(has_github=False, has_defense=False, has_document=False)
        is None
    )


def test_attached_chain_card_gains_cross_proof_corroboration(
    mem_store: dict, pipeline_db: dict
) -> None:
    sid = _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Machine Learning"],
        workflow_summary=_PREDICTION_WORKFLOW,
    )
    gh_id = _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {"skill": "Machine Learning", "file_path": "train.py", "line_start": 10, "line_end": 20}
            ]
        },
    )
    pid = _seed_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": sid}],
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if p["project_id"] == pid)
    card = chain["website_evidence"][0]["website_evidence_card"]
    assert card["behavior_claim"] == "User input produces a prediction/result display."
    assert card["corroborates_github"] is True
    assert card["corroborates_defense"] is False
    assert "GitHub provides implementation evidence" in card["corroboration_note"]
    assert card["connected_project_title"] == "Boston Smart Accident Risk Rerouting"
    assert "Corroborates GitHub" in card["evidence_basis_chips"]
    assert "Attached project" in card["evidence_basis_chips"]


def test_standalone_card_never_gains_corroboration(mem_store: dict, pipeline_db: dict) -> None:
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["React"],
        workflow_summary=_PREDICTION_WORKFLOW,
    )
    _seed_github_proof(mem_store)  # unattached — shares no confirmed project
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "react")
    standalone = next(p for p in report["projects"] if not p["attached"])
    card = standalone["website_evidence"][0]["website_evidence_card"]
    assert card["corroborates_github"] is False
    assert card["corroboration_note"] is None
    assert card["connected_project_title"] is None
    assert "Corroborates GitHub" not in card["evidence_basis_chips"]
    assert "Attached project" not in card["evidence_basis_chips"]


def test_public_projection_derives_claim_and_rederives_corroboration_note() -> None:
    item = _website_report_item(
        website_evidence_card={
            "evidence_basis_chips": ["Route observed", "Corroborates GitHub"],
            "screenshot_available": False,
            "screenshot_access_label": "unavailable",
            "corroborates_github": True,
            "corroborates_defense": False,
            "corroborates_document": False,
            # Hostile stored note — must be RE-DERIVED, never echoed.
            "corroboration_note": "EVIL-NOTE s3://bucket/secret",
            "connected_project_title": "PRIVATE-TITLE",
        }
    )
    artifact = normalize_report_item(item, skill_name="React")
    assert artifact is not None
    public = artifact.public_view()
    # Claim derived from the validated purpose key's closed vocabulary.
    assert public["website_behavior_claim"] == "User input produces a prediction/result display."
    assert public["website_corroborates_github"] is True
    assert "GitHub provides implementation evidence" in public["website_corroboration_note"]
    flat = str(public)
    assert "EVIL-NOTE" not in flat and "s3://bucket" not in flat

    # The outer public whitelist re-derives both again from validated inputs.
    projected = public_safe_evidence_artifact(public)
    assert projected["website_behavior_claim"] == (
        "User input produces a prediction/result display."
    )
    assert projected["website_corroborates_github"] is True
    assert "GitHub provides implementation evidence" in projected["website_corroboration_note"]
    tampered = dict(public)
    tampered["website_corroboration_note"] = "SMUGGLED tokens sk-ABC"
    reprojected = public_safe_evidence_artifact(tampered)
    assert "SMUGGLED" not in str(reprojected)
