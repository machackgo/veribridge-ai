"""Tests for the centralized Public Safety / Recruiter Sharing Layer (Step 7).

Every public/recruiter-facing surface must project internal objects through
``public_report_safety_service`` so a recruiter only ever sees safe, qualitative
proof summaries — never raw transcripts/docs/DOM/OCR/provider JSON, storage
paths, signed URLs, local paths, ``source_id`` values, private ids, emails,
tokens/secrets, raw payloads, internal metadata, or score/ranking/"fully
verified" language.

These tests feed each projection function deliberately HOSTILE data (a token
smuggled into a summary, a ``/Users/…`` path in a location, an email in a
limitation, a score in a synthesis claim, a UUID as a skill name, …) and assert
the projection is fail-closed: unsafe fragments are scrubbed/omitted, private
keys never appear, and the whole-payload gate refuses anything that slips
through. All deterministic — no network, no LLM.
"""

from __future__ import annotations

import json

import pytest

from app.services.public_report_safety_service import (
    _NO_PUBLIC_SYNTHESIS_LIMITATION,
    _NO_PUBLIC_SYNTHESIS_SUMMARY,
    DEFENSE_PRIVACY_HIDDEN_MESSAGE,
    PublicReportUnsafeError,
    contains_unsafe_fields,
    defense_privacy_is_clean,
    enforce_public_safe,
    public_safe_defense_analysis,
    public_safe_evidence_artifact,
    public_safe_linked_chain,
    public_safe_skill_name,
    public_safe_skill_report,
    public_safe_stale_marker,
    public_safe_synthesis_claim,
    public_safe_synthesis_result,
    scrub_public_payload,
    scrub_public_text,
)

# A grab-bag of fragments that must NEVER survive into a public projection.
_SIGNED_URL = "https://proj.supabase.co/storage/v1/object/sign/vbr/sessions/abc.webm?token=ey.secret"
_LOCAL_PATH = "/Users/student/Desktop/secret-demo.mp4"
_FILE_URI = "file:///private/var/folders/tmp/full.webm"
_STORAGE_PATH = "vbr/sessions/9f/raw/frame_001.png"
_EMAIL = "private.student@example.com"
_ACCESS_TOKEN = "access_token=eyJhbGciOiA9.aaa.bbb"
_BEARER = "Bearer sk-live-1234567890abcdef"
_UUID = "550e8400-e29b-41d4-a716-446655440000"
_PRIVATE_ID = "user_1234567890abcdef"

_LEAK_FRAGMENTS = [
    "supabase.co/storage",
    "/storage/v1/object",
    "vbr/sessions/",
    "/users/",
    "file://",
    "example.com",
    "access_token",
    "bearer ",
    "eyjhbgci",
]

_SCORE_FRAGMENTS = ["/100", "%", "score", "trust score", "fully verified", "ranked #", "percentile", "stars"]


def _lower_blob(value: object) -> str:
    return json.dumps(value, default=str).lower()


def _assert_no_leaks(value: object, *, fragments: list[str] = _LEAK_FRAGMENTS) -> None:
    blob = _lower_blob(value)
    for fragment in fragments:
        assert fragment not in blob, f"leaked sensitive fragment {fragment!r} into {blob!r}"


def _assert_no_scores(value: object) -> None:
    blob = _lower_blob(value)
    for fragment in _SCORE_FRAGMENTS:
        assert fragment not in blob, f"leaked score/rank fragment {fragment!r} into {blob!r}"


# ── Text scrub ────────────────────────────────────────────────────────────────


def test_scrub_public_text_strips_paths_tokens_urls_emails() -> None:
    text = f"Built it; demo at {_SIGNED_URL}, local copy {_LOCAL_PATH}, {_FILE_URI}, contact {_EMAIL}, {_BEARER}"
    out = scrub_public_text(text)
    _assert_no_leaks(out)
    assert _EMAIL not in out


def test_scrub_public_text_strips_score_rank_percentile_language() -> None:
    text = "Trust score 92/100, ranked #1, 9.8 out of 10, 4.9 stars, top 1 percentile, fully verified."
    out = scrub_public_text(text)
    _assert_no_scores(out)


def test_scrub_public_text_keeps_qualitative_prose() -> None:
    text = "Implemented a FastAPI risk-scoring endpoint and a React dashboard."
    out = scrub_public_text(text)
    # "scoring" is a substring of a skill phrase; the word "score" must be gone but
    # the legitimate technical prose around it should still be readable.
    assert "fastapi" in out.lower()
    assert "react dashboard" in out.lower()


def test_scrub_public_payload_preserves_safe_deployed_url() -> None:
    payload = {"deployed_url": "https://my-live-app.example.io/app", "summary": "scored 90/100"}
    out = scrub_public_payload(payload)
    # The safe outbound URL survives the recursive whole-payload scrub…
    assert out["deployed_url"] == "https://my-live-app.example.io/app"
    # …while the score fragment is removed.
    assert "/100" not in out["summary"]
    assert "score" not in out["summary"].lower()


# ── Unsafe-field scan (fail-closed) ───────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"source_id": "abc123"},
        {"metadata": {"anything": 1}},
        {"raw_payload": {"x": 1}},
        {"provider_response": {"model": "x"}},
        {"provider_name": "anthropic"},
        {"nested": [{"deep": {"refresh_token": "x"}}]},
        {"summary": _SIGNED_URL},
        {"location": _LOCAL_PATH},
        {"note": f"reach me at {_EMAIL}"},
        {"link": _FILE_URI},
        {"path": _STORAGE_PATH},
        {"auth": _ACCESS_TOKEN},
    ],
)
def test_contains_unsafe_fields_flags_hostile_payloads(payload: dict) -> None:
    assert contains_unsafe_fields(payload) is True


def test_contains_unsafe_fields_allows_safe_payload() -> None:
    safe = {
        "skill": "Python",
        "qualitative_tier": "Strongly corroborated",
        "evidence_id": "ev_github_deadbeefcafe01",
        "public_url": "https://github.com/octocat/Hello-World/blob/main/app.py#L10",
        "limitations": ["Documents corroborate but are never primary proof."],
    }
    assert contains_unsafe_fields(safe) is False


def test_enforce_public_safe_raises_on_unsafe_after_scrub() -> None:
    # A storage path is not removed by the score/rank scrub, so the scan must
    # still catch it and the gate must fail closed.
    with pytest.raises(PublicReportUnsafeError):
        enforce_public_safe({"summary": "all good", "leaked": _STORAGE_PATH})


def test_enforce_public_safe_returns_scrubbed_when_safe() -> None:
    out = enforce_public_safe({"summary": "Scored 95/100 on review.", "tier": "Corroborated"})
    assert out["tier"] == "Corroborated"
    _assert_no_scores(out)


# ── Skill-name scrubbing ──────────────────────────────────────────────────────


@pytest.mark.parametrize("hostile", [_UUID, _PRIVATE_ID, _EMAIL, _STORAGE_PATH, _SIGNED_URL])
def test_public_safe_skill_name_drops_private_id_like_labels(hostile: str) -> None:
    assert public_safe_skill_name(hostile) is None


def test_public_safe_skill_name_keeps_human_label() -> None:
    assert public_safe_skill_name("FastAPI") == "FastAPI"
    assert public_safe_skill_name("Data Visualization") == "Data Visualization"


def test_public_safe_skill_name_strips_id_from_mixed_label() -> None:
    out = public_safe_skill_name(f"Python {_UUID}")
    assert out == "Python"


@pytest.mark.parametrize(
    "hostile",
    [
        "user_1234567890ghijkl",
        "project_ABCXYZ1234567890",
        "student_1234567890ghijkl",
        "artifact_ABCXYZ1234567890",
        "source_ABCXYZ1234567890",
        "provider_1234567890ghijkl",
        "report_ABCXYZ1234567890",
    ],
)
def test_public_safe_skill_name_drops_long_alphanumeric_private_ids(hostile: str) -> None:
    # Long alphanumeric (not just hex) private-prefixed ids are dropped entirely.
    assert public_safe_skill_name(hostile) is None


def test_public_safe_skill_name_strips_alphanumeric_id_from_mixed_label() -> None:
    assert public_safe_skill_name("Python user_1234567890ghijkl") == "Python"


# ── Step 2 — normalized evidence artifact ─────────────────────────────────────


def test_public_safe_evidence_artifact_strips_source_id_metadata_and_scrubs() -> None:
    hostile = {
        "evidence_id": "ev_github_deadbeefcafe01",
        "source_id": "proof-row-uuid-private",  # private — must be dropped
        "source_type": "github",
        "source_label": "GitHub Proof",
        "canonical_skill_name": _UUID,  # private id masquerading as a skill
        "subskill_name": "Routing",
        "project_title": "Risk Platform",
        "exact_location": f"app.py · lines 10-20 {_LOCAL_PATH}",
        "safe_summary": f"Scored 92/100; demo {_SIGNED_URL}; ask {_EMAIL}",
        "proof_strength": "precise_code",
        "public_safe": True,
        "limitations": [f"Token {_ACCESS_TOKEN} only on request"],
        "public_url": _SIGNED_URL,  # signed URL — not publicly linkable
        "metadata": {"raw": {"provider_json": {"x": 1}}},  # must be dropped
        "raw_payload": "do not leak",
    }
    out = public_safe_evidence_artifact(hostile)

    assert "source_id" not in out
    assert "metadata" not in out
    assert "raw_payload" not in out
    assert out["evidence_id"] == "ev_github_deadbeefcafe01"
    assert out["canonical_skill_name"] is None  # UUID skill scrubbed away
    assert out["public_url"] is None  # signed URL refused
    _assert_no_leaks(out)
    _assert_no_scores(out)
    # Whole projection must pass the fail-closed gate.
    assert contains_unsafe_fields(out) is False


def test_public_safe_website_artifact_marks_verification_mode() -> None:
    # Public website evidence with a safe public URL → directly-verifiable-live,
    # closed recruiter copy, no deployment recommendation. Verification is
    # DERIVED from the revalidated public_url, never echoed from the payload.
    live = public_safe_evidence_artifact(
        {
            "evidence_id": "ev_website_abcdef123456",
            "source_type": "website",
            "source_label": "Website Proof",
            "canonical_skill_name": "React",
            "website_purpose_key": "dashboard_view",
            "website_screenshot_available": True,
            "website_screenshot_access_label": "private_candidate_permission_required",
            "public_safe": True,
            "public_url": "https://my-risk-demo.vercel.app/dash",
            # Hostile echoes must be ignored — recomputed from the safe URL.
            "website_verification_mode": "recorded_replay_only",
            "website_verification_note": "leak me",
        }
    )
    assert live["website_verification_mode"] == "directly_verifiable_live"
    assert live["website_verification_mode_label"] == "Directly verifiable live"
    assert live["website_deployment_recommended"] is False
    assert "leak me" not in str(live)
    _assert_no_leaks(live)
    _assert_no_scores(live)
    assert contains_unsafe_fields(live) is False

    # A localhost/private URL is stripped by _safe_url → recorded replay only.
    local = public_safe_evidence_artifact(
        {
            "evidence_id": "ev_website_abcdef123456",
            "source_type": "website",
            "canonical_skill_name": "React",
            "website_purpose_key": "prediction_result_display",
            "website_screenshot_available": True,
            "public_safe": True,
            "public_url": "http://localhost:3000",
        }
    )
    assert local["public_url"] is None
    assert local["website_verification_mode"] == "recorded_replay_only"
    assert local["website_deployment_recommended"] is True


# ── Step 3 — linked proof chain ───────────────────────────────────────────────


def test_public_safe_linked_chain_drops_project_id_and_private_ids() -> None:
    hostile = {
        "chain_id": "chain_1",
        "project_id": _UUID,  # private — must be dropped
        "project_title": "Checkout Service",
        "canonical_skill_name": "Python",
        "chain_label": f"Checkout · {_STORAGE_PATH}",
        # Mix a safe ev_ id with a raw private id — only the safe one survives.
        "linked_evidence_ids": ["ev_github_deadbeefcafe01", _PRIVATE_ID, _UUID],
        "source_types_present": ["github", "website"],
        "primary_source_type": "github",
        "connection_reasons": [
            f"Same repo; provider payload {{'raw': '{_SIGNED_URL}'}}",
            "Same project title.",
        ],
        "proof_strength_summary": {"precise_code": 1, "runtime": 1, "source_id": "leak"},
        "limitations": [f"Contact {_EMAIL}"],
        "public_safe": True,
        "evidence": [
            {
                "evidence_id": "ev_github_deadbeefcafe01",
                "source_id": "private-row",
                "source_type": "github",
                "safe_summary": f"scored 80/100 {_LOCAL_PATH}",
                "public_safe": True,
            }
        ],
    }
    out = public_safe_linked_chain(hostile)

    assert "project_id" not in out
    assert out["linked_evidence_ids"] == ["ev_github_deadbeefcafe01"]
    assert "source_id" not in out["proof_strength_summary"]
    assert "source_id" not in out["evidence"][0]
    _assert_no_leaks(out)
    _assert_no_scores(out)
    assert contains_unsafe_fields(out) is False


# ── Step 4 — synthesis claim / result ─────────────────────────────────────────


def test_public_safe_synthesis_claim_scrubs_scores_and_keeps_safe_citations() -> None:
    hostile = {
        "claim_id": "c1",
        "claim": "Candidate ranked #1, fully verified, scored 98/100 on this skill.",
        "supporting_evidence_ids": ["ev_website_abcdef123456", "raw-private-id"],
        "why_connected": f"Linked via repo {_SIGNED_URL}",
        "limitations": [f"Email {_EMAIL}"],
        "qualitative_tier": "Strongly corroborated",
        "public_safe": True,
    }
    out = public_safe_synthesis_claim(hostile)
    _assert_no_scores(out)
    _assert_no_leaks(out)
    assert out["supporting_evidence_ids"] == ["ev_website_abcdef123456"]
    assert out["qualitative_tier"] == "Strongly corroborated"


def test_public_safe_synthesis_result_drops_unsafe_claims_and_project_id() -> None:
    hostile = {
        "chain_id": "chain_1",
        "project_id": _UUID,
        "canonical_skill_name": "Python",
        "project_title": "Risk Platform",
        "claims": [
            {"claim_id": "claim_abc123def456", "claim": "Implements risk scoring.",
             "public_safe": True, "supporting_evidence_ids": ["ev_github_deadbeefcafe01"],
             "why_connected": "", "limitations": [], "qualitative_tier": "Corroborated"},
            {"claim_id": "claim_dead00beef11", "claim": "secret", "public_safe": False},  # not public-safe
        ],
        "overall_summary": "Scored 90/100 overall.",
        "limitations": [f"Path {_STORAGE_PATH}"],
        "public_safe": True,
        "source": "deterministic",
    }
    out = public_safe_synthesis_result(hostile)
    assert "project_id" not in out
    assert len(out["claims"]) == 1
    # The surviving claim's opaque claim_id passes validation and is echoed.
    assert out["claims"][0]["claim_id"] == "claim_abc123def456"
    _assert_no_scores(out)
    _assert_no_leaks(out)
    assert contains_unsafe_fields(out) is False


# ── Step 6 — stale / reanalysis marker ────────────────────────────────────────


def test_public_safe_stale_marker_drops_project_id_and_scrubs_skill_name() -> None:
    hostile = {
        "evidence_id": "ev_github_deadbeefcafe01",
        "reason": f"Repo-level only; raw {_SIGNED_URL}",
        "recommended_action": "Add a precise code citation.",
        "source_type": "github",
        "project_id": _UUID,
        "skill_name": _PRIVATE_ID,  # private id as skill name
    }
    out = public_safe_stale_marker(hostile)
    assert "project_id" not in out
    assert out["skill_name"] is None
    _assert_no_leaks(out)
    assert contains_unsafe_fields(out) is False


# ── Work Passport skill-report payload ────────────────────────────────────────


def _hostile_skill_report() -> dict:
    """A skill-report-shaped payload riddled with hostile content."""
    return {
        "skill": "Python",
        "synthesis_summary": "Skill is strongly corroborated; scored 95/100, ranked #1.",
        "source_coverage": {"GitHub": True, "Website": True, "Document": False},
        # Internal, rich proof_chains carry private source_ids — must be dropped.
        "proof_chains": [
            {"project_id": _UUID, "github_evidence": [{"source_id": "private-row"}]}
        ],
        "linked_proof_chains": [
            {
                "chain_id": "chain_1",
                "project_id": _UUID,
                "project_title": "Checkout",
                "canonical_skill_name": "Python",
                "chain_label": "Checkout",
                "linked_evidence_ids": ["ev_github_deadbeefcafe01"],
                "source_types_present": ["github"],
                "primary_source_type": "github",
                "connection_reasons": [f"Same repo {_STORAGE_PATH}"],
                "proof_strength_summary": {"precise_code": 1},
                "limitations": [],
                "public_safe": True,
                "evidence": [],
            }
        ],
        "llm_synthesis": [
            {
                "chain_id": "chain_1",
                "project_id": _UUID,
                "canonical_skill_name": "Python",
                "project_title": "Checkout",
                "claims": [
                    {"claim_id": "c", "claim": "Implements checkout flow.", "public_safe": True,
                     "supporting_evidence_ids": ["ev_github_deadbeefcafe01"], "why_connected": "",
                     "limitations": [], "qualitative_tier": "Corroborated"}
                ],
                "overall_summary": f"Built it; contact {_EMAIL}",
                "limitations": [],
                "public_safe": True,
                "source": "deterministic",
            }
        ],
        "unlinked_supporting_evidence": {
            "items": [
                {
                    "proof_type": "Document Proof",
                    "source_id": "private-doc-row",  # must be dropped
                    "title": "Design Doc",
                    "safe_summary": f"Scored 80/100; {_FILE_URI}",
                    "safe_location": "Page 3",
                    "corroborates": "the implementation",
                    "limitation": f"raw {_BEARER}",
                }
            ],
            "count": 1,
            "more_count": 0,
        },
        "limitations": [f"Reach me at {_EMAIL}"],
    }


def test_public_safe_skill_report_is_fail_closed_and_drops_private_chains() -> None:
    out = public_safe_skill_report(_hostile_skill_report())

    # The rich internal proof_chains (with source_ids) are not exposed publicly.
    assert "proof_chains" not in out
    # The unlinked card's private source_id is dropped.
    assert "source_id" not in out["unlinked_supporting_evidence"]["items"][0]
    # The linked chain's project_id is dropped.
    assert "project_id" not in out["linked_proof_chains"][0]
    assert "project_id" not in out["synthesis"][0]
    # No leaks of any kind survive the projection + gate.
    _assert_no_leaks(out)
    _assert_no_scores(out)
    # Qualitative content survives.
    assert out["skill"] == "Python"
    assert out["source_coverage"] == {"GitHub": True, "Website": True, "Document": False}
    assert out["synthesis"][0]["claims"][0]["qualitative_tier"] == "Corroborated"


def test_public_safe_skill_report_handles_old_report_without_step_2_6_fields() -> None:
    """A pre-Step-2..6 report (no linked chains / synthesis / unlinked) still
    projects to a safe, well-formed payload — never raises, never leaks."""
    old = {"skill": "React", "synthesis_summary": "Supporting evidence only.", "limitations": []}
    out = public_safe_skill_report(old)
    assert out["skill"] == "React"
    assert out["linked_proof_chains"] == []
    assert out["synthesis"] == []
    assert out["unlinked_supporting_evidence"]["items"] == []
    assert contains_unsafe_fields(out) is False


def test_public_safe_skill_report_scrubs_rather_than_over_rejecting() -> None:
    """A storage path in a scrubbable free-text position is redacted (not echoed)
    and the projection succeeds — proving the layer scrubs recoverable content
    instead of over-rejecting it, while still leaking nothing."""
    bad = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "linked_proof_chains": [],
        "llm_synthesis": [],
        # An unlinked card whose location is a raw storage path the scrub leaves
        # detectable should be caught by the gate.
        "unlinked_supporting_evidence": {
            "items": [{"proof_type": "Document Proof", "title": "Doc", "safe_summary": "ok",
                       "safe_location": _STORAGE_PATH, "corroborates": "", "limitation": ""}],
            "count": 1,
            "more_count": 0,
        },
        "limitations": [],
    }
    # safe_location is scrubbed by scrub_public_text (storage paths redacted), so
    # this particular payload is *recoverable* and must NOT raise — proving the
    # projection scrubs rather than over-rejects safe-after-scrub content.
    out = public_safe_skill_report(bad)
    _assert_no_leaks(out)


# ── Must-fix 1 — secret/credential-bearing strings ────────────────────────────

# Exact secret VALUES that must never appear anywhere in public output.
_SECRET_VALUES = [
    "sk-test-123",
    "abc123",
    "eyJhbGciOiA9.aaa.bbb",
    "AKIAEXAMPLE",
    "deadsignature99",
]


def _assert_no_secret_values(value: object) -> None:
    blob = _lower_blob(value)
    for secret in _SECRET_VALUES:
        assert secret.lower() not in blob, f"leaked secret value {secret!r} into {blob!r}"


_SECRET_STRINGS = [
    "api_key=sk-test-123",
    "apikey=sk-test-123",
    "token=abc123",
    "access_token=abc123",
    "refresh_token=abc123",
    "client_secret=abc123",
    "secret=abc123",
    "key=abc123",
    "password=abc123",
    "https://example.com/path?token=abc123",
    "https://example.com/path?x=1&api_key=abc123",
    "https://files.example.com/o?X-Amz-Signature=deadsignature99&X-Amz-Credential=AKIAEXAMPLE",
    "https://blob.example.net/x?sig=deadsignature99",
    "Authorization: Bearer abc123",
    "Bearer sk-test-123",
]


@pytest.mark.parametrize("hostile", _SECRET_STRINGS)
def test_scrub_public_text_redacts_secret_bearing_strings(hostile: str) -> None:
    out = scrub_public_text(hostile)
    _assert_no_secret_values(out)
    # bare secret param names + values must not survive scrubbing
    low = out.lower()
    assert "=sk-test-123" not in low
    assert "=abc123" not in low
    assert "bearer abc123" not in low
    assert "bearer sk-test-123" not in low


@pytest.mark.parametrize("hostile", _SECRET_STRINGS)
def test_contains_unsafe_fields_flags_secret_bearing_strings(hostile: str) -> None:
    # The fail-closed gate must reject the raw (un-scrubbed) secret-bearing string.
    assert contains_unsafe_fields({"field": hostile}) is True


def test_scrub_public_payload_strips_secret_query_keeps_safe_base() -> None:
    # The URL-preserving whole-payload scrub keeps a safe deployed URL but drops
    # its credential query string (the must-fix's "strip the query if base safe").
    out = scrub_public_payload({"deployed_url": "https://example.com/app?token=abc123"})
    assert "token=abc123" not in out["deployed_url"]
    assert "abc123" not in out["deployed_url"]
    assert out["deployed_url"] == "https://example.com/app"


def test_scrub_public_text_redacts_full_url_with_secret_query() -> None:
    # A prose field redacts the whole link (it should never carry a raw outbound
    # URL); either way the exact secret never survives.
    out = scrub_public_text("Live demo at https://example.com/app?token=abc123 — try it")
    assert "token=abc123" not in out
    assert "abc123" not in out


def test_enforce_public_safe_redacts_secrets_then_serves() -> None:
    # A secret smuggled into scrubbable free text is redacted and the payload is
    # served (proving the layer scrubs rather than only rejecting).
    out = enforce_public_safe({"summary": "config api_key=sk-test-123 for the demo"})
    _assert_no_secret_values(out)
    assert "api_key=sk-test-123" not in _lower_blob(out)


def test_enforce_public_safe_fails_closed_on_secret_in_unscrubbed_key() -> None:
    # contains_unsafe_fields scans the scrubbed payload; if a secret somehow lands
    # in a position scrubbing cannot rewrite it must still fail closed. A raw
    # access_token key value is caught by the unsafe-field scan.
    with pytest.raises(PublicReportUnsafeError):
        enforce_public_safe({"access_token": "abc123"})


def test_evidence_artifact_scrubs_secret_in_summary_and_limitations() -> None:
    hostile = {
        "evidence_id": "ev_github_deadbeefcafe01",
        "source_type": "github",
        "safe_summary": "Endpoint reads client_secret=abc123 from env; demo at "
        "https://example.com/app?token=abc123",
        "limitations": ["Set api_key=sk-test-123 to run", "Authorization: Bearer abc123"],
        "public_safe": True,
    }
    out = public_safe_evidence_artifact(hostile)
    _assert_no_secret_values(out)
    assert contains_unsafe_fields(out) is False


# ── Must-fix 2 — public_safe=False chains / synthesis / evidence are dropped ───


def _safe_chain(public_safe: bool, *, evidence_safe: bool = True) -> dict:
    return {
        "chain_id": "chain_deadbeefcafe01",
        "project_title": "Checkout",
        "canonical_skill_name": "Python",
        "chain_label": "Checkout",
        "linked_evidence_ids": ["ev_github_deadbeefcafe01"],
        "source_types_present": ["github"],
        "primary_source_type": "github",
        "connection_reasons": ["Same repo."],
        "proof_strength_summary": {"precise_code": 1},
        "limitations": [],
        "public_safe": public_safe,
        "evidence": [
            {"evidence_id": "ev_github_deadbeefcafe01", "source_type": "github",
             "safe_summary": "Implements checkout.", "public_safe": evidence_safe},
        ],
    }


def _safe_synth(public_safe: bool, *, claim_safe: bool = True) -> dict:
    return {
        "chain_id": "chain_deadbeefcafe01",
        "canonical_skill_name": "Python",
        "project_title": "Checkout",
        "claims": [
            {"claim_id": "claim_abc123def456", "claim": "Implements checkout.",
             "public_safe": claim_safe, "supporting_evidence_ids": ["ev_github_deadbeefcafe01"],
             "why_connected": "", "limitations": [], "qualitative_tier": "Corroborated"},
        ],
        "overall_summary": "Built the checkout flow.",
        "limitations": [],
        "public_safe": public_safe,
        "source": "deterministic",
    }


def test_skill_report_drops_unsafe_linked_chain() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "linked_proof_chains": [_safe_chain(True), _safe_chain(False)],
        "llm_synthesis": [],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    # Only the public_safe=True chain survives.
    assert len(out["linked_proof_chains"]) == 1
    assert all(c["public_safe"] for c in out["linked_proof_chains"])


def test_skill_report_drops_unsafe_synthesis_result() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "linked_proof_chains": [],
        "llm_synthesis": [_safe_synth(True), _safe_synth(False)],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    assert len(out["synthesis"]) == 1
    assert all(s["public_safe"] for s in out["synthesis"])


def test_synthesis_result_drops_unsafe_claim() -> None:
    out = public_safe_synthesis_result(_safe_synth(True, claim_safe=False))
    # The single claim is public_safe=False → dropped, leaving a safe empty list.
    assert out["claims"] == []


def test_linked_chain_drops_unsafe_nested_evidence() -> None:
    out = public_safe_linked_chain(_safe_chain(True, evidence_safe=False))
    # The nested evidence artifact is public_safe=False → dropped.
    assert out["evidence"] == []


def test_skill_report_renders_with_safe_items_after_dropping_unsafe() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "linked_proof_chains": [_safe_chain(False), _safe_chain(True)],
        "llm_synthesis": [_safe_synth(False), _safe_synth(True)],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    assert out["skill"] == "Python"
    assert len(out["linked_proof_chains"]) == 1
    assert len(out["synthesis"]) == 1


def test_skill_report_safe_empty_sections_when_all_unsafe() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "linked_proof_chains": [_safe_chain(False), _safe_chain(False)],
        "llm_synthesis": [_safe_synth(False)],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    # Fail closed: all-unsafe sections collapse to safe empty lists, never leak.
    assert out["linked_proof_chains"] == []
    assert out["synthesis"] == []
    assert contains_unsafe_fields(out) is False


# ── Must-fix 3 — public id validation (approved opaque formats only) ───────────

_HOSTILE_IDS = [
    _UUID,                                   # raw UUID
    "private.student@example.com",           # email-shaped
    "/Users/student/proofs/row.json",        # path-like
    "proof-row-uuid-private",                # source_id-style
    "student_1234567890",                    # student id
    "project_9f8e7d6c5b4a",                  # project id
    "ev_github_NOTHEX!",                      # ev_ prefix but invalid body
    "chain_not_hex",                          # chain_ prefix but invalid body
    "claim_xyz",                              # claim_ prefix but invalid body
    "",                                       # empty
]


@pytest.mark.parametrize("bad_id", _HOSTILE_IDS)
def test_evidence_artifact_omits_invalid_evidence_id(bad_id: str) -> None:
    out = public_safe_evidence_artifact(
        {"evidence_id": bad_id, "source_type": "github", "public_safe": True}
    )
    assert out["evidence_id"] is None


@pytest.mark.parametrize("bad_id", _HOSTILE_IDS)
def test_linked_chain_omits_invalid_chain_id(bad_id: str) -> None:
    out = public_safe_linked_chain({"chain_id": bad_id, "public_safe": True})
    assert out["chain_id"] is None


@pytest.mark.parametrize("bad_id", _HOSTILE_IDS)
def test_synthesis_claim_omits_invalid_claim_id(bad_id: str) -> None:
    out = public_safe_synthesis_claim({"claim_id": bad_id, "claim": "x", "public_safe": True})
    assert out["claim_id"] is None


def test_valid_opaque_ids_survive() -> None:
    ev = public_safe_evidence_artifact(
        {"evidence_id": "ev_github_deadbeefcafe01", "source_type": "github", "public_safe": True}
    )
    chain = public_safe_linked_chain({"chain_id": "chain_deadbeefcafe01", "public_safe": True})
    claim = public_safe_synthesis_claim(
        {"claim_id": "claim_abc123def456", "claim": "x", "public_safe": True}
    )
    stale = public_safe_stale_marker({"evidence_id": "ev_website_abcdef123456"})
    assert ev["evidence_id"] == "ev_github_deadbeefcafe01"
    assert chain["chain_id"] == "chain_deadbeefcafe01"
    assert claim["claim_id"] == "claim_abc123def456"
    assert stale["evidence_id"] == "ev_website_abcdef123456"


def test_stale_marker_omits_invalid_evidence_id() -> None:
    out = public_safe_stale_marker({"evidence_id": _UUID, "reason": "stale"})
    assert out["evidence_id"] is None


def test_citation_lists_drop_invalid_evidence_ids() -> None:
    # supporting_evidence_ids / linked_evidence_ids keep only approved ev_ ids;
    # private/invalid citation chips are omitted.
    claim = public_safe_synthesis_claim(
        {
            "claim_id": "claim_abc123def456",
            "claim": "x",
            "public_safe": True,
            "supporting_evidence_ids": [
                "ev_github_deadbeefcafe01", _UUID, "source-row-private", "student_123",
            ],
        }
    )
    chain = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "linked_evidence_ids": ["ev_website_abcdef123456", _UUID, "/Users/x/y"],
        }
    )
    assert claim["supporting_evidence_ids"] == ["ev_github_deadbeefcafe01"]
    assert chain["linked_evidence_ids"] == ["ev_website_abcdef123456"]


# ── Codex must-fix 1 — proof_strength_summary is a STRICT allowlist ────────────


def test_strength_summary_drops_unknown_key_carrying_uuid() -> None:
    # A UUID smuggled under an innocent-looking key ("owner") must NOT survive the
    # proof-strength-summary projection — only documented fields are allowed.
    out = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "proof_strength_summary": {
                "owner": _UUID,  # unknown key carrying a private UUID — must be dropped
                "label": "Implementation proven by precise code",
                "has_precise_code": True,
            },
        }
    )
    summary = out["proof_strength_summary"]
    assert "owner" not in summary
    assert _UUID not in _lower_blob(summary)
    assert _UUID.lower() not in _lower_blob(out)
    # The documented fields that were present still survive.
    assert summary["label"] == "Implementation proven by precise code"
    assert summary["has_precise_code"] is True


def test_strength_summary_keeps_documented_fields_and_scrubs_values() -> None:
    out = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "proof_strength_summary": {
                "label": "Runtime behaviour demonstrated",
                "strengths_present": ["precise_code", "runtime_behavior", _UUID, "leak"],
                "has_precise_code": True,
                "has_runtime_behavior": True,
                "has_self_explanation": False,
                "has_supporting_moment": False,
                "repo_level_only": False,
                "corroborating_document_count": 2,
                # hostile extras
                "project_id": _UUID,
                "raw_payload": {"x": 1},
                "corroborating_document_count_evil": -5,
            },
        }
    )
    summary = out["proof_strength_summary"]
    # Documented fields survive with correct types.
    assert summary["label"] == "Runtime behaviour demonstrated"
    assert summary["has_precise_code"] is True
    assert summary["has_self_explanation"] is False
    assert summary["corroborating_document_count"] == 2
    # strengths_present keeps only known labels; the UUID / "leak" are dropped.
    assert summary["strengths_present"] == ["precise_code", "runtime_behavior"]
    # Unknown keys are gone entirely.
    assert "project_id" not in summary
    assert "raw_payload" not in summary
    assert "corroborating_document_count_evil" not in summary
    assert contains_unsafe_fields(out) is False


def test_strength_summary_count_coerced_to_non_negative_int() -> None:
    out = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "proof_strength_summary": {"corroborating_document_count": -3},
        }
    )
    assert out["proof_strength_summary"]["corroborating_document_count"] == 0


# ── Codex must-fix 2 — source_coverage keys are whitelisted ───────────────────


def test_source_coverage_drops_email_key_keeps_known_source() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "source_coverage": {"student@example.com": True, "github": True},
        "linked_proof_chains": [],
        "llm_synthesis": [],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    coverage = out["source_coverage"]
    assert coverage == {"github": True}
    assert "student@example.com" not in coverage
    _assert_no_leaks(out)


def test_source_coverage_drops_uuid_and_private_id_keys() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "source_coverage": {
            _UUID: True,
            _PRIVATE_ID: True,
            "GitHub": True,  # producer's capitalised key still passes
            "Website": False,
            "owner_secret": True,  # unknown private-looking key — dropped
        },
        "linked_proof_chains": [],
        "llm_synthesis": [],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    coverage = out["source_coverage"]
    assert coverage == {"GitHub": True, "Website": False}
    assert _UUID not in coverage
    assert _PRIVATE_ID not in coverage
    assert "owner_secret" not in coverage
    assert contains_unsafe_fields(out) is False


def test_source_coverage_values_coerced_to_bool() -> None:
    # A non-boolean value under a known key must not ride out as a raw string/dict.
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "source_coverage": {"github": {"raw": "leak"}, "website": "yes"},
        "linked_proof_chains": [],
        "llm_synthesis": [],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    assert out["source_coverage"] == {"github": True, "website": True}
    assert all(isinstance(v, bool) for v in out["source_coverage"].values())


# ── Codex must-fix 3 — unsupported synthesis claims are dropped ───────────────


def test_synthesis_result_drops_claim_with_only_private_citations() -> None:
    # A public_safe claim whose every citation id is a raw UUID / private id is an
    # UNSUPPORTED public claim and must be dropped (no traceable citation).
    result = {
        "chain_id": "chain_deadbeefcafe01",
        "canonical_skill_name": "Python",
        "project_title": "Checkout",
        "claims": [
            {
                "claim_id": "claim_abc123def456",
                "claim": "Implements the checkout flow end to end.",
                "public_safe": True,
                "supporting_evidence_ids": [_UUID, "source-row-private", "student_123"],
                "why_connected": "",
                "limitations": [],
                "qualitative_tier": "Corroborated",
            }
        ],
        "overall_summary": "Built it.",
        "limitations": [],
        "public_safe": True,
        "source": "deterministic",
    }
    out = public_safe_synthesis_result(result)
    assert out["claims"] == []
    assert contains_unsafe_fields(out) is False


def test_synthesis_result_keeps_claim_with_valid_citation() -> None:
    result = {
        "chain_id": "chain_deadbeefcafe01",
        "canonical_skill_name": "Python",
        "project_title": "Checkout",
        "claims": [
            {
                "claim_id": "claim_abc123def456",
                "claim": "Implements the checkout flow.",
                "public_safe": True,
                # one valid public citation among the private ones
                "supporting_evidence_ids": ["ev_github_deadbeefcafe01", _UUID],
                "why_connected": "",
                "limitations": [],
                "qualitative_tier": "Corroborated",
            }
        ],
        "overall_summary": "Built it.",
        "limitations": [],
        "public_safe": True,
        "source": "deterministic",
    }
    out = public_safe_synthesis_result(result)
    assert len(out["claims"]) == 1
    assert out["claims"][0]["supporting_evidence_ids"] == ["ev_github_deadbeefcafe01"]


def test_skill_report_drops_unsupported_synthesis_claims() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "linked_proof_chains": [],
        "llm_synthesis": [
            {
                "chain_id": "chain_deadbeefcafe01",
                "canonical_skill_name": "Python",
                "project_title": "Checkout",
                "claims": [
                    {
                        "claim_id": "claim_abc123def456",
                        "claim": "Skill present.",
                        "public_safe": True,
                        "supporting_evidence_ids": [_UUID],  # no valid citation
                        "why_connected": "",
                        "limitations": [],
                        "qualitative_tier": "Corroborated",
                    }
                ],
                "overall_summary": "Built it.",
                "limitations": [],
                "public_safe": True,
                "source": "deterministic",
            }
        ],
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    assert out["synthesis"][0]["claims"] == []


# ── Codex must-fix 4 — public_safe=False stale markers are dropped ────────────


def test_stale_marker_dropped_when_not_public_safe() -> None:
    marker = {
        "evidence_id": "ev_github_deadbeefcafe01",
        "reason": "Repo-level only.",
        "recommended_action": "Add a precise code citation.",
        "source_type": "github",
        "skill_name": "Python",
        "public_safe": False,  # explicitly not for public surfaces
    }
    assert public_safe_stale_marker(marker) is None


def test_stale_marker_public_safe_true_is_projected() -> None:
    marker = {
        "evidence_id": "ev_github_deadbeefcafe01",
        "reason": f"Repo-level only; raw {_SIGNED_URL}",
        "recommended_action": "Add a precise code citation.",
        "source_type": "github",
        "skill_name": _PRIVATE_ID,  # private id as skill name — scrubbed away
        "public_safe": True,
    }
    out = public_safe_stale_marker(marker)
    assert out is not None
    assert out["evidence_id"] == "ev_github_deadbeefcafe01"
    assert out["skill_name"] is None
    _assert_no_leaks(out)
    assert contains_unsafe_fields(out) is False


def test_stale_marker_without_public_safe_field_is_projected() -> None:
    # Backward compatible: a marker that simply omits public_safe is still
    # projected (only an explicit False omits it).
    out = public_safe_stale_marker(
        {"evidence_id": "ev_website_abcdef123456", "reason": "stale"}
    )
    assert out is not None
    assert out["evidence_id"] == "ev_website_abcdef123456"


# ── Codex must-fix 5 — overall_summary cannot ride out when every claim drops ──

# An assertion that, if surfaced without a single traceable public citation,
# overstates the candidate's contribution. It lives in overall_summary AND in the
# only claim, whose citations are all private/invalid (so the claim is dropped).
_UNSUPPORTED_ASSERTION = "Architected the entire payment platform single-handedly."


def test_synthesis_result_does_not_expose_summary_when_all_claims_dropped() -> None:
    # Hostile: the unsupported assertion is parked in overall_summary while every
    # claim carries only private/invalid citations and is dropped. The original
    # summary must NOT survive into the public projection — otherwise the same
    # uncited assertion rides out via the summary field instead of a claim.
    result = {
        "chain_id": "chain_deadbeefcafe01",
        "canonical_skill_name": "Python",
        "project_title": "Checkout",
        "claims": [
            {
                "claim_id": "claim_abc123def456",
                "claim": _UNSUPPORTED_ASSERTION,
                "public_safe": True,
                # every citation is a raw UUID / private id → claim dropped
                "supporting_evidence_ids": [_UUID, "source-row-private", _PRIVATE_ID],
                "why_connected": "",
                "limitations": [],
                "qualitative_tier": "Corroborated",
            }
        ],
        "overall_summary": _UNSUPPORTED_ASSERTION,
        "limitations": [],
        "public_safe": True,
        "source": "deterministic",
    }
    out = public_safe_synthesis_result(result)

    # No claim survived.
    assert out["claims"] == []
    # The original unsupported assertion is gone from every field.
    assert _UNSUPPORTED_ASSERTION not in json.dumps(out)
    # Summary is replaced with neutral language, not the original prose.
    assert out["overall_summary"] == _NO_PUBLIC_SYNTHESIS_SUMMARY
    # A limitation explains why no summary is shown.
    assert _NO_PUBLIC_SYNTHESIS_LIMITATION in out["limitations"]
    assert contains_unsafe_fields(out) is False


def test_synthesis_result_retains_safe_summary_when_a_cited_claim_survives() -> None:
    # Positive control: at least one claim keeps a valid public citation, so the
    # (scrubbed) overall_summary is allowed to remain.
    result = {
        "chain_id": "chain_deadbeefcafe01",
        "canonical_skill_name": "Python",
        "project_title": "Checkout",
        "claims": [
            {
                "claim_id": "claim_abc123def456",
                "claim": "Implements the checkout flow.",
                "public_safe": True,
                "supporting_evidence_ids": ["ev_github_deadbeefcafe01", _UUID],
                "why_connected": "",
                "limitations": [],
                "qualitative_tier": "Corroborated",
            }
        ],
        "overall_summary": "Built the checkout flow end to end.",
        "limitations": [],
        "public_safe": True,
        "source": "deterministic",
    }
    out = public_safe_synthesis_result(result)
    assert len(out["claims"]) == 1
    assert out["overall_summary"] == "Built the checkout flow end to end."
    assert _NO_PUBLIC_SYNTHESIS_LIMITATION not in out["limitations"]
    assert contains_unsafe_fields(out) is False


# ── Codex must-fix 6 — enum-like fields are held to a STRICT allowlist ─────────
#
# source / source_type / proof_strength / qualitative_tier / proof_type /
# source_types_present / primary_source_type are *assumed* to be short, known
# enum labels by recruiter surfaces. A hostile/internal producer could instead
# put ``api_key=sk-private`` / ``token=private`` / ``client_secret=private`` (or a
# signed URL, an email, a raw UUID) where a label belongs. These must never ride
# out raw: an unknown value is replaced with a neutral fallback (or dropped).

# The literal secret bodies that must never survive in any enum field.
_ENUM_SECRET_BODIES = ["sk-private", "private", "client_secret", "api_key", "token="]


def _assert_no_enum_secrets(value: object) -> None:
    blob = _lower_blob(value)
    for fragment in ["sk-private", "api_key=", "token=", "client_secret="]:
        assert fragment not in blob, f"leaked enum secret {fragment!r} into {blob!r}"


def test_evidence_artifact_source_type_secret_falls_back_to_other() -> None:
    out = public_safe_evidence_artifact(
        {"evidence_id": "ev_github_deadbeefcafe01", "source_type": "api_key=sk-private",
         "public_safe": True}
    )
    # The unknown/hostile source_type is replaced with the neutral "other" label,
    # never echoed raw — the secret cannot ride out.
    assert out["source_type"] == "other"
    _assert_no_enum_secrets(out)
    assert contains_unsafe_fields(out) is False


def test_evidence_artifact_proof_strength_secret_falls_back_to_unknown() -> None:
    out = public_safe_evidence_artifact(
        {"evidence_id": "ev_github_deadbeefcafe01", "source_type": "github",
         "proof_strength": "token=private", "public_safe": True}
    )
    assert out["proof_strength"] == "unknown"
    _assert_no_enum_secrets(out)
    assert contains_unsafe_fields(out) is False


def test_synthesis_claim_qualitative_tier_secret_falls_back_to_needs_review() -> None:
    out = public_safe_synthesis_claim(
        {"claim_id": "claim_abc123def456", "claim": "x", "public_safe": True,
         "supporting_evidence_ids": ["ev_github_deadbeefcafe01"],
         "qualitative_tier": "client_secret=private"}
    )
    # An unknown tier never inflates the candidate and never carries the secret —
    # it collapses to the neutral "Needs review".
    assert out["qualitative_tier"] == "Needs review"
    _assert_no_enum_secrets(out)
    assert contains_unsafe_fields(out) is False


def test_synthesis_result_source_secret_falls_back_to_deterministic() -> None:
    out = public_safe_synthesis_result(
        {
            "chain_id": "chain_deadbeefcafe01",
            "canonical_skill_name": "Python",
            "project_title": "Checkout",
            "claims": [
                {"claim_id": "claim_abc123def456", "claim": "Implements checkout.",
                 "public_safe": True, "supporting_evidence_ids": ["ev_github_deadbeefcafe01"],
                 "why_connected": "", "limitations": [], "qualitative_tier": "Corroborated"}
            ],
            "overall_summary": "Built it.",
            "limitations": [],
            "public_safe": True,
            "source": "api_key=sk-private",  # hostile provenance label
        }
    )
    assert out["source"] == "deterministic"
    _assert_no_enum_secrets(out)
    assert contains_unsafe_fields(out) is False


def test_linked_chain_source_types_present_keeps_known_drops_secret() -> None:
    out = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "source_types_present": ["github", "token=private", _UUID, "website"],
        }
    )
    # Known labels survive (order preserved); the hostile entries are dropped.
    assert out["source_types_present"] == ["github", "website"]
    _assert_no_enum_secrets(out)
    assert contains_unsafe_fields(out) is False


def test_linked_chain_source_types_present_dedupes() -> None:
    out = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "source_types_present": ["github", "github", "website"],
        }
    )
    assert out["source_types_present"] == ["github", "website"]


def test_linked_chain_primary_source_type_secret_falls_back_to_none() -> None:
    out = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "primary_source_type": "api_key=sk-private",
        }
    )
    # A nullable enum collapses an unknown/hostile value to None, never raw.
    assert out["primary_source_type"] is None
    _assert_no_enum_secrets(out)
    assert contains_unsafe_fields(out) is False


def test_stale_marker_source_type_secret_falls_back_to_other() -> None:
    out = public_safe_stale_marker(
        {"evidence_id": "ev_github_deadbeefcafe01", "reason": "stale",
         "source_type": "client_secret=private"}
    )
    assert out is not None
    assert out["source_type"] == "other"
    _assert_no_enum_secrets(out)
    assert contains_unsafe_fields(out) is False


def test_unlinked_card_proof_type_secret_falls_back_to_other() -> None:
    report = {
        "skill": "Python",
        "synthesis_summary": "ok",
        "linked_proof_chains": [],
        "llm_synthesis": [],
        "unlinked_supporting_evidence": {
            "items": [
                {"proof_type": "api_key=sk-private", "title": "Doc", "safe_summary": "ok",
                 "safe_location": None, "corroborates": "", "limitation": ""}
            ],
            "count": 1,
            "more_count": 0,
        },
        "limitations": [],
    }
    out = public_safe_skill_report(report)
    card = out["unlinked_supporting_evidence"]["items"][0]
    assert card["proof_type"] == "Other"
    _assert_no_enum_secrets(out)


@pytest.mark.parametrize(
    "source_type", ["github", "website", "document", "defense", "video", "skill_graph"]
)
def test_known_source_types_survive(source_type: str) -> None:
    out = public_safe_evidence_artifact(
        {"evidence_id": "ev_github_deadbeefcafe01", "source_type": source_type,
         "public_safe": True}
    )
    assert out["source_type"] == source_type


@pytest.mark.parametrize(
    "proof_strength",
    ["precise_code", "runtime_behavior", "self_explanation", "supporting_moment",
     "repo_level", "aggregated", "corroboration"],
)
def test_known_proof_strengths_survive(proof_strength: str) -> None:
    out = public_safe_evidence_artifact(
        {"evidence_id": "ev_github_deadbeefcafe01", "source_type": "github",
         "proof_strength": proof_strength, "public_safe": True}
    )
    assert out["proof_strength"] == proof_strength


@pytest.mark.parametrize(
    "tier",
    ["Strongly corroborated", "Corroborated", "Supporting evidence", "Needs review",
     "Insufficient evidence"],
)
def test_known_qualitative_tiers_survive(tier: str) -> None:
    out = public_safe_synthesis_claim(
        {"claim_id": "claim_abc123def456", "claim": "x", "public_safe": True,
         "supporting_evidence_ids": ["ev_github_deadbeefcafe01"], "qualitative_tier": tier}
    )
    assert out["qualitative_tier"] == tier


def test_known_enum_values_survive_in_linked_chain() -> None:
    out = public_safe_linked_chain(
        {
            "chain_id": "chain_deadbeefcafe01",
            "public_safe": True,
            "source_types_present": ["github", "website", "document"],
            "primary_source_type": "github",
        }
    )
    assert out["source_types_present"] == ["github", "website", "document"]
    assert out["primary_source_type"] == "github"


# ── Smart GitHub Evidence integration — public safety of grade-aware synthesis ──


def test_public_skill_report_drops_internal_github_assessment_fields() -> None:
    """The rich, internal proof_chains (with the new Smart-Evidence assessment and
    private source ids) are never exposed publicly — only the citation-safe linked
    chains / synthesis survive."""
    from app.services.proof_synthesis_agent_service import synthesize_skill_report

    internal = synthesize_skill_report(
        {
            "skill": "Machine Learning",
            "source_counts": {"GitHub Proof": 1},
            "projects": [
                {
                    "attached": True,
                    "project_id": "p-secret-uuid",
                    "project_title": "Boston Model Trainer",
                    "github_evidence": [
                        {
                            "proof_type": "GitHub Proof",
                            "source_id": "gh-secret-uuid",
                            "skill_name": "Machine Learning",
                            "display_mode": "code_line",
                            "has_precise_line_evidence": True,
                            "file_path": "train.py",
                            "line_start": 94,
                            "line_end": 135,
                            "evidence_quality_grade": "implementation_body",
                            "selection_reason": "model training/evaluation",
                            "safe_summary": "model training/evaluation",
                            "safe_snippet": "clf = LGBMClassifier()\nclf.fit(X_train, y_train)",
                            "public_safe": True,
                        }
                    ],
                }
            ],
        }
    )
    # Sanity: the internal chain carries the new assessment fields.
    assert internal["proof_chains"][0]["github_evidence_assessment"]["strength"] == "implementation"

    public = public_safe_skill_report(internal)
    # The rich proof_chains (and their internal fields / private ids) are dropped.
    assert "proof_chains" not in public
    assert "github_evidence_assessment" not in json.dumps(public)
    assert "gh-secret-uuid" not in json.dumps(public)
    assert "p-secret-uuid" not in json.dumps(public)


def test_public_linked_chain_does_not_claim_precise_code_for_weak_grade() -> None:
    """A weak-graded precise line must not surface has_precise_code=True publicly."""
    from app.services.proof_synthesis_agent_service import synthesize_skill_report

    internal = synthesize_skill_report(
        {
            "skill": "Machine Learning",
            "source_counts": {"GitHub Proof": 1},
            "projects": [
                {
                    "attached": True,
                    "project_id": "p1",
                    "project_title": "Boston Model Trainer",
                    "github_evidence": [
                        {
                            "proof_type": "GitHub Proof",
                            "source_id": "gh-weak",
                            "skill_name": "Machine Learning",
                            "display_mode": "code_line",
                            "has_precise_line_evidence": True,
                            "file_path": "api.py",
                            "line_start": 19,
                            "line_end": 23,
                            "evidence_quality_grade": "route_decorator_only",
                            "selection_reason": "API endpoint decorator",
                            "safe_summary": "API endpoint decorator",
                            "public_safe": True,
                        }
                    ],
                }
            ],
        }
    )
    public = public_safe_skill_report(internal)
    for chain in public["linked_proof_chains"]:
        summary = chain.get("proof_strength_summary") or {}
        assert summary.get("has_precise_code") is not True, (
            "a weak-graded precise line must never read as precise implementation code"
        )


def test_public_skill_report_code_role_fields_never_leak_private_data() -> None:
    """Code-role fields ride on internal GitHub evidence rows; the public projection
    must stay whitelist-only — role fields never smuggle a raw snippet, a stale
    overclaiming reason, or a private source id onto the recruiter surface."""
    from app.services.proof_synthesis_agent_service import synthesize_skill_report

    internal = synthesize_skill_report(
        {
            "skill": "Machine Learning",
            "source_counts": {"GitHub Proof": 1},
            "projects": [
                {
                    "attached": True,
                    "project_id": "p-secret-uuid",
                    "project_title": "Boston Model Trainer",
                    "github_evidence": [
                        {
                            "proof_type": "GitHub Proof",
                            "source_id": "gh-secret-uuid",
                            "skill_name": "Machine Learning",
                            "display_mode": "code_line",
                            "has_precise_line_evidence": True,
                            "file_path": "scripts/pipeline_retrain.py",
                            "line_start": 29,
                            "line_end": 47,
                            "evidence_quality_grade": "import_only",
                            # Descriptive role fields (weak row → imports role).
                            "code_role_key": "imports_setup",
                            "code_role_label": "Imports / setup context",
                            # Stale overclaiming reason + raw snippet that must
                            # never surface publicly.
                            "selection_reason": "ML training call SECRET_REASON_MARKER",
                            "safe_summary": "imports",
                            "safe_snippet": "import lightgbm  # SECRET_SNIPPET_MARKER",
                            "public_safe": True,
                        }
                    ],
                }
            ],
        }
    )

    public = public_safe_skill_report(internal)
    payload = json.dumps(public)
    # No private ids, raw snippet, or stale reason text on the public surface.
    assert "gh-secret-uuid" not in payload
    assert "p-secret-uuid" not in payload
    assert "SECRET_SNIPPET_MARKER" not in payload
    assert "SECRET_REASON_MARKER" not in payload
    # Role keys are internal enums; the public whitelist does not echo them today —
    # if that ever changes, only the two safe fields may appear (never raw fields).
    for key in ("code_role_key", "code_role_label"):
        if key in payload:
            assert '"code_role_key": "imports_setup"' in payload or (
                '"code_role_label": "Imports / setup context"' in payload
            )


def test_public_skill_report_purpose_fields_never_leak_private_data() -> None:
    """Block-purpose fields ride on internal GitHub evidence rows exactly like the
    role fields; the public projection stays whitelist-only — a purpose surface can
    never smuggle a raw snippet, a stale overclaiming reason, or a private id."""
    from app.services.proof_synthesis_agent_service import synthesize_skill_report

    internal = synthesize_skill_report(
        {
            "skill": "Machine Learning",
            "source_counts": {"GitHub Proof": 1},
            "projects": [
                {
                    "attached": True,
                    "project_id": "p-secret-uuid",
                    "project_title": "Boston Model Trainer",
                    "github_evidence": [
                        {
                            "proof_type": "GitHub Proof",
                            "source_id": "gh-secret-uuid",
                            "skill_name": "Machine Learning",
                            "display_mode": "code_line",
                            "has_precise_line_evidence": True,
                            "file_path": "scripts/pipeline_retrain.py",
                            "line_start": 2,
                            "line_end": 20,
                            "evidence_quality_grade": "comment_or_docstring",
                            # Closed-vocabulary purpose fields (weak docstring row).
                            "code_block_purpose_key": "retraining_documentation",
                            "code_block_purpose_label": (
                                "Documentation describing retraining pipeline"
                            ),
                            "code_block_purpose_summary": (
                                "This header describes the planned retraining workflow "
                                "and artifacts, but it is not executable training code."
                            ),
                            # Stale overclaiming reason + raw snippet that must
                            # never surface publicly.
                            "selection_reason": "ML training call SECRET_REASON_MARKER",
                            "safe_summary": "module docstring",
                            "safe_snippet": '"""retrain SECRET_SNIPPET_MARKER"""',
                            "public_safe": True,
                        }
                    ],
                }
            ],
        }
    )

    public = public_safe_skill_report(internal)
    payload = json.dumps(public)
    assert "gh-secret-uuid" not in payload
    assert "p-secret-uuid" not in payload
    assert "SECRET_SNIPPET_MARKER" not in payload
    assert "SECRET_REASON_MARKER" not in payload
    # Purpose fields are internal closed enums; the public whitelist does not echo
    # them today — if that ever changes, only the safe static strings may appear.
    for key in ("code_block_purpose_key", "code_block_purpose_label", "code_block_purpose_summary"):
        if key in payload:
            assert '"code_block_purpose_key": "retraining_documentation"' in payload or (
                "Documentation describing retraining pipeline" in payload
            )


def test_public_skill_report_skill_relevance_fields_never_leak_private_data() -> None:
    """Skill-relevance fields ride on internal GitHub evidence rows exactly like the
    purpose fields; the public projection stays whitelist-only — a relevance surface
    can never smuggle a raw snippet, a stale overclaiming reason, or a private id."""
    from app.services.proof_synthesis_agent_service import synthesize_skill_report

    internal = synthesize_skill_report(
        {
            "skill": "Machine Learning",
            "source_counts": {"GitHub Proof": 1},
            "projects": [
                {
                    "attached": True,
                    "project_id": "p-secret-uuid",
                    "project_title": "Boston Model Trainer",
                    "github_evidence": [
                        {
                            "proof_type": "GitHub Proof",
                            "source_id": "gh-secret-uuid",
                            "skill_name": "Machine Learning",
                            "display_mode": "code_line",
                            "has_precise_line_evidence": True,
                            "file_path": "scripts/pipeline_retrain.py",
                            "line_start": 2,
                            "line_end": 20,
                            "evidence_quality_grade": "comment_or_docstring",
                            "code_block_purpose_key": "retraining_documentation",
                            # Closed-template relevance fields (weak docstring row).
                            "skill_relevance_key": "documentation_context",
                            "skill_relevance_label": (
                                "Documentation context, not executable Machine Learning proof"
                            ),
                            "skill_relevance_summary": (
                                "This is documentation prose — context for Machine "
                                "Learning, never executable proof."
                            ),
                            # Stale overclaiming reason + raw snippet that must
                            # never surface publicly.
                            "selection_reason": "ML training call SECRET_REASON_MARKER",
                            "safe_summary": "module docstring",
                            "safe_snippet": '"""retrain SECRET_SNIPPET_MARKER"""',
                            "public_safe": True,
                        }
                    ],
                }
            ],
        }
    )

    public = public_safe_skill_report(internal)
    payload = json.dumps(public)
    assert "gh-secret-uuid" not in payload
    assert "p-secret-uuid" not in payload
    assert "SECRET_SNIPPET_MARKER" not in payload
    assert "SECRET_REASON_MARKER" not in payload
    # Relevance fields are internal closed templates; the public whitelist does not
    # echo them today — if that ever changes, only the safe rendered strings may
    # appear (never braces/markup/stored prose).
    for key in ("skill_relevance_key", "skill_relevance_label", "skill_relevance_summary"):
        if key in payload:
            assert '"skill_relevance_key": "documentation_context"' in payload or (
                "Documentation context, not executable Machine Learning proof" in payload
            )


# ── Project Defense privacy fail-closed ───────────────────────────────────────

# A synthetic, SSN-shaped value the scrubbers do NOT recognise (not a token,
# path, URL, email, or score) — it survives generic scrubbing, so the ONLY thing
# that keeps it out of a public report is the privacy fail-closed projection.
_SSN_MARKER = "123-45-6789"


def _flagged_defense_analysis(status: str = "flagged") -> dict:
    """A Project Defense analysis whose transcript failed privacy review."""
    return {
        "transcript_summary": f"Transcript (11 words): my social security number is {_SSN_MARKER} and I built it.",
        "skills_mentioned": ["Python"],
        "skills_explained_well": ["Python"],
        "skills_missing_from_explanation": [],
        "overall_assessment": "Partially demonstrated",
        "explanation_clarity": "Demonstrated",
        "ownership_signal": "Partially demonstrated",
        "technical_depth": "Supporting evidence",
        "consistency_with_evidence": "Needs review",
        "risk_flags": ["Transcript contains potential sensitive data."],
        "recruiter_summary": "Project defense transcript analyzed. NOTE: hidden from recruiter view.",
        "recommended_improvements": [],
        "privacy_scan_status": status,
    }


def _clean_defense_analysis() -> dict:
    analysis = _flagged_defense_analysis(status="clean")
    analysis["transcript_summary"] = "Transcript (11 words): I built a task manager with FastAPI and React."
    analysis["risk_flags"] = []
    analysis["recruiter_summary"] = "Project defense transcript analyzed. Clear technical explanation."
    return analysis


def test_defense_privacy_is_clean_true_only_for_clean_status() -> None:
    assert defense_privacy_is_clean(_clean_defense_analysis()) is True
    # An explicit clean status (case/whitespace tolerant) still passes.
    assert defense_privacy_is_clean({"privacy_scan_status": " Clean "}) is True


def test_defense_privacy_is_clean_fails_closed_on_none_and_non_dict() -> None:
    # A missing (``None``) or non-dict analysis carries NO explicit clean status,
    # so it must fail CLOSED — any orphaned transcript-derived artifacts that exist
    # without a clean analysis object are withheld by the caller.
    assert defense_privacy_is_clean(None) is False
    assert defense_privacy_is_clean("not a dict") is False
    assert defense_privacy_is_clean([]) is False
    assert defense_privacy_is_clean(123) is False


@pytest.mark.parametrize(
    "analysis",
    [
        {"privacy_scan_status": "flagged"},
        {"privacy_scan_status": "sensitive"},
        {"privacy_scan_status": "review_required"},
        {"privacy_scan_status": "redacted"},
        {"privacy_scan_status": "clean", "contains_sensitive_data": True},
        {"privacy_scan_status": "clean", "hidden": True},
        {"privacy_scan_status": "clean", "privacy_flagged": True},
    ],
)
def test_defense_privacy_is_clean_false_on_any_unsafe_signal(analysis: dict) -> None:
    assert defense_privacy_is_clean(analysis) is False


# ── P0 #1 — missing / None / unknown privacy status fails CLOSED ───────────────


@pytest.mark.parametrize(
    "analysis",
    [
        {"transcript_summary": "hi"},                       # status key entirely missing
        {"privacy_scan_status": None},                       # explicit None
        {"privacy_scan_status": ""},                         # empty string
        {"privacy_scan_status": "   "},                      # whitespace only
        {"privacy_scan_status": "unknown_status_value"},     # unrecognized string
        {"privacy_scan_status": 123},                        # non-string junk
    ],
)
def test_defense_privacy_is_clean_fails_closed_on_missing_none_unknown(analysis: dict) -> None:
    # Fail-closed: only an allowlisted clean status is shareable; anything else —
    # missing / None / empty / unrecognized — is NOT clean.
    assert defense_privacy_is_clean(analysis) is False


@pytest.mark.parametrize(
    "status_kwargs",
    [
        {},                                          # missing privacy_scan_status
        {"privacy_scan_status": None},               # None privacy_scan_status
        {"privacy_scan_status": "unknown_value"},    # unrecognized privacy_scan_status
    ],
)
def test_missing_or_unknown_status_withholds_ssn_summary(status_kwargs: dict) -> None:
    # An SSN-shaped transcript summary with no allowlisted-clean status must be
    # withheld publicly — the legacy/malformed fail-open leak is closed.
    analysis = _flagged_defense_analysis()
    analysis.pop("privacy_scan_status", None)
    analysis.update(status_kwargs)
    projected = public_safe_defense_analysis(analysis)
    assert projected is not None
    assert _SSN_MARKER not in json.dumps(projected)
    assert projected["transcript_summary"] == DEFENSE_PRIVACY_HIDDEN_MESSAGE
    assert projected["skills_mentioned"] == []


def test_explicit_clean_status_renders_safe_content() -> None:
    # Positive control: an explicit clean status with safe content still renders.
    clean = _clean_defense_analysis()
    assert defense_privacy_is_clean(clean) is True
    projected = public_safe_defense_analysis(clean)
    assert projected == clean
    assert "fastapi" in projected["transcript_summary"].lower()


def test_public_safe_defense_analysis_hides_flagged_transcript() -> None:
    """Fail-closed: a flagged analysis has its transcript-derived text replaced
    with the safe placeholder (the SSN-shaped value never survives)."""
    projected = public_safe_defense_analysis(_flagged_defense_analysis())
    assert projected is not None
    # P0 #2: the public status is the fixed neutral value, never the raw status.
    assert projected["privacy_scan_status"] == "withheld"
    # transcript_summary / recruiter_summary become the safe placeholder wording.
    assert projected["transcript_summary"] == DEFENSE_PRIVACY_HIDDEN_MESSAGE
    assert projected["recruiter_summary"] == DEFENSE_PRIVACY_HIDDEN_MESSAGE

    payload = json.dumps(projected)
    assert _SSN_MARKER not in payload
    # Every derived list/label field is emptied or neutralized — no flagged content.
    assert projected["skills_mentioned"] == []
    assert projected["skills_explained_well"] == []
    assert projected["risk_flags"] == []
    assert projected["recommended_improvements"] == []
    assert projected["overall_assessment"] == "Not assessed"


# ── P0 #2 — raw / internal status text is never echoed publicly ────────────────

_HOSTILE_STATUS = "flagged<script>alert(1)</script> INTERNAL_LEAK_MARKER token=sk-secret"


def test_public_safe_defense_analysis_never_echoes_raw_status_text() -> None:
    # A hostile / internal privacy_scan_status must NOT appear in the public output;
    # the withheld projection reports only the fixed allowlisted "withheld".
    analysis = _flagged_defense_analysis(status=_HOSTILE_STATUS)
    projected = public_safe_defense_analysis(analysis)
    assert projected is not None
    payload = json.dumps(projected)
    assert "INTERNAL_LEAK_MARKER" not in payload
    assert "<script>" not in payload
    assert "sk-secret" not in payload
    assert projected["privacy_scan_status"] == "withheld"


def test_public_safe_defense_uses_fixed_withheld_value() -> None:
    # Whatever the raw status, the withheld public projection collapses it to the
    # single allowlisted neutral value.
    for status in ("flagged", "redacted", "sensitive", "needs_review", "surprise"):
        projected = public_safe_defense_analysis(_flagged_defense_analysis(status=status))
        assert projected is not None
        assert projected["privacy_scan_status"] == "withheld"


def test_public_safe_defense_analysis_passes_clean_through() -> None:
    """A clean analysis is returned unchanged for the caller's normal scrub/gate."""
    clean = _clean_defense_analysis()
    assert public_safe_defense_analysis(clean) == clean


def test_public_safe_defense_analysis_none_for_no_defense() -> None:
    assert public_safe_defense_analysis(None) is None
    assert public_safe_defense_analysis("not a dict") is None


def test_public_safe_defense_analysis_is_enforce_public_safe_clean() -> None:
    """The fail-closed placeholder itself passes the whole-payload unsafe scan."""
    projected = public_safe_defense_analysis(_flagged_defense_analysis())
    # enforce_public_safe would raise if the placeholder still smelled unsafe.
    assert enforce_public_safe(projected) == projected
    assert contains_unsafe_fields(projected) is False


# ── Project Defense inspection cards — fail-closed public projection ──────────


def _owner_inspection_card(**overrides) -> dict:
    """One owner Project Defense inspection card (public-safe by default)."""
    base = {
        "evidence_id_safe": "defense-inspection-1",
        "question_text": "How does your model make predictions?",
        "question_kind": "skill_explanation",
        "project_title": "Boston Housing",
        "mapped_skill": "Machine Learning",
        "claim_type": "skill_understanding",
        "answer_purpose": "skill_explanation",
        "evidence_role": "candidate_explanation",
        "qualitative_status": "Explained with evidence",
        "safe_answer_summary": "I trained a regression model and use it for inference on features.",
        "evidence_basis_chips": ["Targeted question", "Candidate answer", "Privacy-safe summary"],
        "timestamp_label": "Video 03:12",
        "clip_start_seconds": 192.0,
        "clip_end_seconds": 205.0,
        "clip_available": True,
        "corroborates_github": True,
        "corroborates_website": False,
        "corroborates_document": False,
        "corroboration_summary": "Corroborating defense evidence: GitHub Proof (implementation) for the same project.",
        "what_this_demonstrates": "The student explained this Machine Learning claim in their own words.",
        "limitation": "Project Defense is explanation evidence.",
        "public_safe": True,
        "withheld_reason": None,
    }
    base.update(overrides)
    return base


def test_public_inspection_clean_card_derives_summary_and_keeps_locator() -> None:
    """A clean, public-safe card keeps its safe question, a DERIVED summary (never
    the raw answer text), the clip locator, and the corroboration flags."""
    from app.services.public_report_safety_service import (
        public_safe_project_defense_inspection,
    )

    cards = public_safe_project_defense_inspection(
        [_owner_inspection_card()], {"privacy_scan_status": "clean"}
    )
    assert len(cards) == 1
    card = cards[0]
    assert card["public_safe"] is True
    assert card["question_text"]
    # The candidate's raw answer text is NEVER echoed — summary is derived wording.
    assert "regression model" not in card["safe_answer_summary"]
    assert card["safe_answer_summary"]
    # The clip locator survives as a label + seconds only.
    assert card["clip_available"] is True
    assert card["timestamp_label"] == "Video 03:12"
    assert card["corroborates_github"] is True
    # No internal id / raw status leaks.
    assert "question_id" not in card


def test_public_inspection_unsafe_status_withholds_answer_and_clip() -> None:
    """When the session privacy review did not pass, every card is a withheld
    placeholder: no answer text, no question text, no clip, a withheld reason."""
    from app.services.public_report_safety_service import (
        DEFENSE_INSPECTION_WITHHELD_MESSAGE,
        public_safe_project_defense_inspection,
    )

    cards = public_safe_project_defense_inspection(
        [_owner_inspection_card()], {"privacy_scan_status": "flagged"}
    )
    assert len(cards) == 1
    card = cards[0]
    assert card["public_safe"] is False
    assert card["withheld_reason"] == DEFENSE_INSPECTION_WITHHELD_MESSAGE
    assert card["safe_answer_summary"] == DEFENSE_INSPECTION_WITHHELD_MESSAGE
    assert card["question_text"] is None
    assert card["clip_available"] is False
    assert card["timestamp_label"] is None
    # No answer-derived content, corroboration, or internal id survives.
    assert "regression model" not in json.dumps(card)
    assert card["corroborates_github"] is False
    assert "question_id" not in card


def test_public_inspection_per_card_not_public_safe_is_withheld() -> None:
    """Even on a clean session, a card marked ``public_safe: False`` (e.g. a
    contradicted answer) fails closed to a withheld placeholder."""
    from app.services.public_report_safety_service import (
        public_safe_project_defense_inspection,
    )

    cards = public_safe_project_defense_inspection(
        [_owner_inspection_card(public_safe=False)], {"privacy_scan_status": "clean"}
    )
    assert cards[0]["public_safe"] is False
    assert cards[0]["question_text"] is None
    assert "regression model" not in json.dumps(cards[0])


def test_public_inspection_preserves_limitation_and_corroboration_labels() -> None:
    """A clean card keeps the honest limitation framing and corroboration labels."""
    from app.services.public_report_safety_service import (
        public_safe_project_defense_inspection,
    )

    cards = public_safe_project_defense_inspection(
        [_owner_inspection_card(corroborates_website=True)],
        {"privacy_scan_status": "clean"},
    )
    card = cards[0]
    assert card["limitation"]
    assert card["corroboration_summary"]
    assert card["corroborates_website"] is True


def test_public_inspection_strips_unsafe_free_text_and_ids() -> None:
    """Defense in depth: storage paths / signed URLs / SSNs in owner free text are
    scrubbed, and no internal id survives, on the public card."""
    from app.services.public_report_safety_service import (
        public_safe_project_defense_inspection,
    )

    dirty = _owner_inspection_card(
        corroboration_summary="See storage_path=vbr/sessions/abc and https://x/y?token=abc",
        what_this_demonstrates="my SSN is 123-45-6789",
        question_id="internal-qid-123",  # extra key must never survive
    )
    cards = public_safe_project_defense_inspection([dirty], {"privacy_scan_status": "clean"})
    blob = json.dumps(cards[0])
    for unsafe in ("vbr/sessions", "token=abc", "123-45-6789", "internal-qid-123", "question_id"):
        assert unsafe not in blob
