"""Tests for the Evaluation / QA Agent (Step 8).

The evaluator is an internal, deterministic QA layer over the artifacts Steps 2–7
build: it audits internal reports for correctness (unsupported claims, broken
citations, cross-project chains, document/repo overclaims) and audits public
payloads for safety leaks (secrets, signed URLs, paths, emails, raw payloads,
score/ranking language, non-opaque ids, ``public_safe=False`` items).

These tests feed it deliberately HOSTILE fixtures and assert it is fail-closed:
the verdict turns to ``fail`` on a blocker, and — critically — every issue
message describes the *pattern* it found, never the offending secret value. All
deterministic: no network, no LLM.
"""

from __future__ import annotations

import socket

import pytest

from app.services.proof_evaluation_qa_service import (
    EvaluationCategory,
    EvaluationSeverity,
    EvaluationVerdict,
    evaluate_internal_report,
    evaluate_public_output,
    evaluate_report,
)

# Approved opaque ids (the only id shapes a public citation may carry).
_EV_GH = "ev_github_0123456789abcdef"
_EV_DOC = "ev_document_0123456789abcd01"
_EV_DOC2 = "ev_document_0123456789abcd02"
_CHAIN = "chain_0123456789abcdef"
_CLAIM = "claim_0123456789abcdef"

# Hostile fragments that must never survive into / be approved for public output.
_SIGNED_URL = "https://proj.supabase.co/storage/v1/object/sign/vbr/a.webm?token=ey.secret"
_LOCAL_PATH = "/Users/student/Desktop/secret-demo.mp4"
_EMAIL = "private.student@example.com"
_BEARER = "Bearer sk-live-1234567890abcdef"
_APIKEY = "api_key=sk-private-1234567890"
_SECRET_VALUES = (
    "sk-private-1234567890",
    "sk-live-1234567890abcdef",
    "ey.secret",
    "private.student",
)


def _categories(report) -> set[EvaluationCategory]:
    return {issue.category for issue in report.issues}


def _no_secret_echoed(report) -> None:
    """Every issue must be self-safe: no raw secret value in any message."""
    for issue in report.issues:
        assert issue.public_safe is True
        blob = (issue.message + " " + issue.recommended_fix).lower()
        for secret in _SECRET_VALUES:
            assert secret.lower() not in blob, issue.message
        for eid in issue.evidence_ids:
            # Only approved opaque ids may ride along.
            assert eid.startswith("ev_")


# ── 1. PASS on clean input ────────────────────────────────────────────────────


def _clean_artifact(eid=_EV_GH, source="github", strength="precise_code"):
    return {
        "evidence_id": eid,
        "source_type": source,
        "project_id": "proj-1",
        "project_title": "Inventory App",
        "proof_strength": strength,
        "public_safe": True,
        "safe_summary": "Implements the auth guard in middleware.",
    }


def test_pass_on_clean_report():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "project_id": "proj-1",
                "project_title": "Inventory App",
                "linked_evidence_ids": [_EV_GH],
                "proof_strength_summary": {"has_precise_code": True},
                "public_safe": True,
                "evidence": [_clean_artifact()],
            }
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "claim": "Built JWT auth middleware.",
                        "supporting_evidence_ids": [_EV_GH],
                        "qualitative_tier": "Corroborated",
                        "public_safe": True,
                    }
                ],
                "public_safe": True,
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.PASS
    assert result.blocker_count == 0
    assert result.public_safe is True


def test_pass_on_clean_public_payload():
    payload = {
        "skill": "FastAPI",
        "synthesis_summary": "Demonstrated building authenticated APIs.",
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "linked_evidence_ids": [_EV_GH],
                "public_safe": True,
                "evidence": [
                    {
                        "evidence_id": _EV_GH,
                        "source_type": "github",
                        "safe_summary": "Auth guard middleware.",
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.PASS
    assert result.public_safe is True


# ── 2. Unsupported claim (no citations) ───────────────────────────────────────


def test_fail_claim_without_supporting_evidence_ids():
    report = {
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "claim": "Built a distributed cache.",
                        "supporting_evidence_ids": [],
                        "public_safe": True,
                    }
                ],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNSUPPORTED_CLAIM in _categories(result)


# ── 3. Claim cites a non-existent evidence id ─────────────────────────────────


def test_fail_claim_cites_unknown_evidence_id():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "linked_evidence_ids": [_EV_GH],
                "evidence": [_clean_artifact()],
            }
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "claim": "Built X.",
                        "supporting_evidence_ids": ["ev_github_deadbeefdeadbeef"],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.MISSING_CITATION in _categories(result)
    _no_secret_echoed(result)


# ── 4. Public payload carries secrets ─────────────────────────────────────────


@pytest.mark.parametrize("secret", [_BEARER, _APIKEY, _SIGNED_URL, "client_secret=abc123xyz"])
def test_fail_public_payload_contains_secret(secret):
    payload = {"synthesis_summary": f"Notes: {secret}"}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in _categories(result)
    assert result.public_safe is False
    _no_secret_echoed(result)


# ── 5. Public payload carries paths / email / raw payload keys ────────────────


def test_fail_public_payload_storage_and_local_paths():
    for leak in (_LOCAL_PATH, _EMAIL, "file:///private/var/x.webm"):
        result = evaluate_public_output({"safe_summary": f"see {leak}"})
        assert result.verdict is EvaluationVerdict.FAIL
        assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in _categories(result)
    _no_secret_echoed(result)


def test_fail_public_payload_raw_payload_keys():
    for key in ("source_id", "metadata", "raw_payload", "provider_response"):
        result = evaluate_public_output({"evidence": [{key: "anything"}]})
        assert result.verdict is EvaluationVerdict.FAIL
        assert EvaluationCategory.RAW_PAYLOAD_LEAK in _categories(result)


# ── 6. Score / ranking / numeric-confidence language ──────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Trust score: 92/100",
        "Ranked #1 of all candidates",
        "98% match",
        "Fully verified developer",
        "Confidence: 0.95",
    ],
)
def test_fail_public_payload_score_or_ranking_language(text):
    result = evaluate_public_output({"synthesis_summary": text})
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.SCORE_OR_RANKING_LANGUAGE in _categories(result)


# ── 7. Invalid public ids ─────────────────────────────────────────────────────


def test_fail_public_payload_invalid_ids():
    payload = {
        "evidence": [{"evidence_id": "550e8400-e29b-41d4-a716-446655440000"}],
        "chain_id": "chain-not-opaque!",
        "claims": [{"claim_id": "user_123", "supporting_evidence_ids": ["raw-source-id"]}],
    }
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    _no_secret_echoed(result)


# ── 8. public_safe=False item in public output ────────────────────────────────


def test_fail_public_safe_false_item_in_public_output():
    payload = {"evidence": [{"evidence_id": _EV_GH, "public_safe": False}]}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.PUBLIC_SAFE_FALSE_LEAK in _categories(result)


def test_fail_stale_marker_not_public_safe_in_public_output():
    payload = {
        "stale_markers": [
            {"evidence_id": _EV_GH, "recommended_action": "re-run", "public_safe": False}
        ]
    }
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.STALE_MARKER_LEAK in _categories(result)


# ── 9. Document-only evidence classified as implementation proof ──────────────


def test_fail_document_evidence_with_implementation_strength():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "evidence": [
                    _clean_artifact(eid=_EV_DOC, source="document", strength="precise_code")
                ],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.DOCUMENT_OVERCLAIM in _categories(result)


def test_fail_strong_claim_from_document_only_evidence():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "evidence": [
                    _clean_artifact(eid=_EV_DOC, source="document", strength="corroboration"),
                    _clean_artifact(eid=_EV_DOC2, source="document", strength="corroboration"),
                ],
            }
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "claim": "Strong proof of building the system.",
                        "supporting_evidence_ids": [_EV_DOC, _EV_DOC2],
                        "qualitative_tier": "Strongly corroborated",
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.DOCUMENT_OVERCLAIM in _categories(result)


# ── 10. Repo-level fallback without precise code ──────────────────────────────


def test_warning_repo_fallback_without_precise_code():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "proof_strength_summary": {"repo_level_only": True, "has_precise_code": False},
                "evidence": [
                    _clean_artifact(eid=_EV_GH, source="github", strength="repo_level")
                ],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.PASS_WITH_WARNINGS
    assert result.warning_count >= 1
    assert EvaluationCategory.REPO_FALLBACK_OVERCLAIM in _categories(result)


# ── 11. Chain combines unrelated projects / repos ─────────────────────────────


def test_fail_chain_combines_conflicting_project_ids():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "evidence": [
                    {**_clean_artifact(eid=_EV_GH), "project_id": "proj-1", "project_title": "App A"},
                    {**_clean_artifact(eid=_EV_DOC), "project_id": "proj-2", "project_title": "App B"},
                ],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNRELATED_CHAIN_LINK in _categories(result)


def test_fail_chain_combines_conflicting_repositories():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "evidence": [
                    {**_clean_artifact(eid=_EV_GH), "metadata": {"repo_url": "https://github.com/a/x"}},
                    {**_clean_artifact(eid=_EV_DOC), "metadata": {"repo_url": "https://github.com/b/y"}},
                ],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNRELATED_CHAIN_LINK in _categories(result)


# ── 12. Old / partial report missing Step 2–7 fields ──────────────────────────


def test_old_report_missing_new_fields_does_not_crash():
    for legacy in ({}, {"proof_chains": []}, {"skill": "Python"}, {"llm_synthesis": []}):
        result = evaluate_internal_report(legacy)
        assert result.verdict in (
            EvaluationVerdict.PASS,
            EvaluationVerdict.PASS_WITH_WARNINGS,
        )


def test_evaluate_report_combined_internal_and_public():
    internal = {
        "linked_proof_chains": [
            {"chain_id": _CHAIN, "linked_evidence_ids": [_EV_GH], "evidence": [_clean_artifact()]}
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {"claim_id": _CLAIM, "supporting_evidence_ids": [], "public_safe": True}
                ],
            }
        ],
    }
    public = {"synthesis_summary": _BEARER}
    result = evaluate_report(internal, public_payload=public)
    assert result.verdict is EvaluationVerdict.FAIL
    cats = _categories(result)
    assert EvaluationCategory.UNSUPPORTED_CLAIM in cats
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in cats


# ── 13. No network / LLM ──────────────────────────────────────────────────────


def test_no_network_calls(monkeypatch):
    def _boom(*_a, **_k):  # pragma: no cover - must never be hit
        raise AssertionError("network access attempted by deterministic evaluator")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)

    report = {
        "linked_proof_chains": [
            {"chain_id": _CHAIN, "linked_evidence_ids": [_EV_GH], "evidence": [_clean_artifact()]}
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {"claim_id": _CLAIM, "supporting_evidence_ids": [_EV_GH], "public_safe": True}
                ],
            }
        ],
    }
    assert evaluate_internal_report(report).verdict is EvaluationVerdict.PASS
    assert evaluate_public_output({"synthesis_summary": _BEARER}).verdict is EvaluationVerdict.FAIL


# ── 14. Issue messages never echo raw secret values ───────────────────────────


def test_issue_messages_do_not_echo_secrets():
    payload = {
        "a": _BEARER,
        "b": _APIKEY,
        "c": _SIGNED_URL,
        "d": _EMAIL,
        "e": "client_secret=topsecretvalue",
    }
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    _no_secret_echoed(result)
    assert "topsecretvalue" not in str(result.to_dict())


# ── 15. Transcript recorder files untouched ───────────────────────────────────


# ── 16. Must-fix 1: chain-local citation validation ───────────────────────────


_EV_A = "ev_github_aaaaaaaaaaaa"
_EV_B = "ev_github_bbbbbbbbbbbb"
_CHAIN_A = "chain_aaaaaaaaaaaa"
_CHAIN_B = "chain_bbbbbbbbbbbb"


def test_fail_claim_cites_other_chains_evidence():
    """A claim in chain A may NOT cite evidence that belongs only to chain B,
    even though that id exists report-wide."""
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN_A,
                "linked_evidence_ids": [_EV_A],
                "evidence": [_clean_artifact(eid=_EV_A)],
            },
            {
                "chain_id": _CHAIN_B,
                "linked_evidence_ids": [_EV_B],
                "evidence": [_clean_artifact(eid=_EV_B)],
            },
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN_A,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "claim": "Built X in project A.",
                        # cites chain B's evidence — out of scope for chain A.
                        "supporting_evidence_ids": [_EV_B],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.MISSING_CITATION in _categories(result)
    _no_secret_echoed(result)


def test_chain_local_citation_passes_when_in_scope():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN_A,
                "linked_evidence_ids": [_EV_A],
                "evidence": [_clean_artifact(eid=_EV_A)],
            },
            {
                "chain_id": _CHAIN_B,
                "linked_evidence_ids": [_EV_B],
                "evidence": [_clean_artifact(eid=_EV_B)],
            },
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN_A,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "supporting_evidence_ids": [_EV_A],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.PASS


def test_fail_synthesis_scope_undetermined_with_multiple_chains():
    """A synthesis result with no chain_id can't be scoped when many chains exist
    → citations fail closed rather than fall back to a report-wide set."""
    report = {
        "linked_proof_chains": [
            {"chain_id": _CHAIN_A, "evidence": [_clean_artifact(eid=_EV_A)]},
            {"chain_id": _CHAIN_B, "evidence": [_clean_artifact(eid=_EV_B)]},
        ],
        "llm_synthesis": [
            {
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "supporting_evidence_ids": [_EV_A],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.MISSING_CITATION in _categories(result)


# ── 17. Must-fix 2: invalid ids rejected even when consistently present ────────


def test_fail_uuid_evidence_id_even_when_cited_consistently():
    """A UUID used as evidence_id and cited by the same UUID must FAIL — existence
    in the report does not make an invalid-format id valid."""
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "linked_evidence_ids": [uuid],
                "evidence": [_clean_artifact(eid=uuid)],
            }
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "supporting_evidence_ids": [uuid],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    # The raw UUID must not be echoed in any issue message.
    assert uuid not in str(result.to_dict())


def test_fail_private_like_chain_id():
    report = {
        "linked_proof_chains": [
            {"chain_id": "proj-1/student-42", "evidence": [_clean_artifact()]}
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    assert "proj-1/student-42" not in str(result.to_dict())


def test_fail_email_or_path_claim_id():
    for bad_claim_id in ("student@example.com", "/Users/private/claim.txt"):
        report = {
            "linked_proof_chains": [
                {"chain_id": _CHAIN, "evidence": [_clean_artifact()]}
            ],
            "llm_synthesis": [
                {
                    "chain_id": _CHAIN,
                    "claims": [
                        {
                            "claim_id": bad_claim_id,
                            "supporting_evidence_ids": [_EV_GH],
                            "public_safe": True,
                        }
                    ],
                }
            ],
        }
        result = evaluate_internal_report(report)
        assert result.verdict is EvaluationVerdict.FAIL
        assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
        assert bad_claim_id not in str(result.to_dict())


def test_valid_opaque_ids_survive():
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "linked_evidence_ids": [_EV_GH],
                "evidence": [_clean_artifact()],
            }
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "supporting_evidence_ids": [_EV_GH],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.PASS
    assert EvaluationCategory.INVALID_PUBLIC_ID not in _categories(result)


# ── 18. Must-fix 3: unsafe dictionary keys scanned (not just values) ───────────


@pytest.mark.parametrize(
    "payload",
    [
        {"student@example.com": "safe"},
        {"api_key=sk-private": "safe"},
        {"/Users/private/file.txt": "safe"},
        {"token=private": {"nested": "safe"}},
    ],
)
def test_fail_unsafe_dictionary_key(payload):
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in _categories(result)
    # The offending key text must never be echoed back.
    blob = str(result.to_dict())
    for forbidden in (
        "student@example.com",
        "sk-private",
        "/Users/private/file.txt",
        "token=private",
    ):
        assert forbidden not in blob


# ── 19. Must-fix A: unsafe dictionary keys never echoed in issue LOCATIONS ─────


def _blob(report) -> str:
    """Every field of every issue, concatenated — the full public surface."""
    return str(report.to_dict())


def test_nested_unsafe_key_not_echoed_in_location():
    """A leak nested UNDER an unsafe key must fail closed, and neither the key nor
    the secret may appear in any issue field (location included)."""
    payload = {"safe": {"api_key=sk-supersecret": {"nested": "value"}}}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    blob = _blob(result)
    assert "sk-supersecret" not in blob
    assert "api_key=sk-supersecret" not in blob
    _no_secret_echoed(result)


def test_descendant_leak_location_uses_placeholder_not_raw_key():
    """When a deeper leak produces its own issue, the parent unsafe key in that
    issue's location is a placeholder — never the raw email/path/secret."""
    payload = {
        "outer": {
            _EMAIL: {"deep": _BEARER},
            _LOCAL_PATH: {"deeper": _APIKEY},
        }
    }
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    blob = _blob(result)
    for forbidden in (_EMAIL, _LOCAL_PATH, "sk-live-1234567890abcdef", "sk-private-1234567890"):
        assert forbidden not in blob, forbidden
    assert "<email_key>" in blob
    assert "<path_key>" in blob
    _no_secret_echoed(result)


def test_private_key_message_does_not_echo_raw_key():
    """The RAW_PAYLOAD private-key message uses a placeholder, not the raw key."""
    result = evaluate_public_output({"raw_payload": "anything"})
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.RAW_PAYLOAD_LEAK in _categories(result)
    assert "<private_key>" in _blob(result)


# ── 20. Must-fix B: legacy/internal proof_chains are evaluated too ─────────────


def test_fail_legacy_proof_chains_invalid_evidence_id():
    """An invalid (UUID) evidence_id inside a legacy ``proof_chains`` block must
    FAIL — it previously produced PASS because only linked_proof_chains was audited."""
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    report = {
        "proof_chains": [
            {
                "chain_id": _CHAIN,
                "linked_evidence_ids": [uuid],
                "evidence": [_clean_artifact(eid=uuid)],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    assert uuid not in _blob(result)


def test_fail_legacy_proof_chains_invalid_inline_claim_citation():
    """A legacy ``proof_chains`` chain that embeds claims with a bad claim_id /
    citation must FAIL with INVALID_PUBLIC_ID."""
    report = {
        "proof_chains": [
            {
                "chain_id": _CHAIN,
                "evidence": [_clean_artifact()],
                "claims": [
                    {
                        "claim_id": "student@example.com",
                        "supporting_evidence_ids": ["550e8400-e29b-41d4-a716-446655440000"],
                    }
                ],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    assert "student@example.com" not in _blob(result)
    assert "550e8400-e29b-41d4-a716-446655440000" not in _blob(result)


def test_legacy_proof_chains_valid_ids_pass():
    """A legacy ``proof_chains`` block with valid ev_/chain_/claim_ ids passes ID
    validation (no INVALID_PUBLIC_ID)."""
    report = {
        "proof_chains": [
            {
                "chain_id": _CHAIN,
                "linked_evidence_ids": [_EV_GH],
                "evidence": [_clean_artifact()],
                "claims": [
                    {"claim_id": _CLAIM, "supporting_evidence_ids": [_EV_GH]}
                ],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert EvaluationCategory.INVALID_PUBLIC_ID not in _categories(result)
    assert result.verdict in (
        EvaluationVerdict.PASS,
        EvaluationVerdict.PASS_WITH_WARNINGS,
    )


# ── 21. Must-fix C: non-string citation ids produce INVALID_PUBLIC_ID ──────────


@pytest.mark.parametrize("bad", [123, None, {"id": "ev_github_hiddenvalue1234"}])
def test_fail_supporting_evidence_ids_non_string(bad):
    report = {
        "linked_proof_chains": [
            {"chain_id": _CHAIN, "linked_evidence_ids": [_EV_GH], "evidence": [_clean_artifact()]}
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "supporting_evidence_ids": [_EV_GH, bad],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    # The raw object contents must never be dumped into an issue.
    assert "hiddenvalue1234" not in _blob(result)


def test_fail_supporting_evidence_ids_mixed_hostile_values():
    """The exact hostile example from the must-fix: [123, null, {dict}]."""
    report = {
        "linked_proof_chains": [
            {"chain_id": _CHAIN, "linked_evidence_ids": [_EV_GH], "evidence": [_clean_artifact()]}
        ],
        "llm_synthesis": [
            {
                "chain_id": _CHAIN,
                "claims": [
                    {
                        "claim_id": _CLAIM,
                        "supporting_evidence_ids": [123, None, {"id": "ev_github_hiddenvalue1234"}],
                        "public_safe": True,
                    }
                ],
            }
        ],
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    assert "hiddenvalue1234" not in _blob(result)


@pytest.mark.parametrize("bad", [False, ["ev_github_hiddenvalue1234"], 0, {"id": "x"}])
def test_fail_linked_evidence_ids_non_string(bad):
    report = {
        "linked_proof_chains": [
            {
                "chain_id": _CHAIN,
                "linked_evidence_ids": [_EV_GH, bad],
                "evidence": [_clean_artifact()],
            }
        ]
    }
    result = evaluate_internal_report(report)
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.INVALID_PUBLIC_ID in _categories(result)
    assert "hiddenvalue1234" not in _blob(result)


# ── 22. Must-fix D: UUID / private-ID-shaped dictionary keys are unsafe ────────


def test_fail_top_level_uuid_dictionary_key():
    """A bare UUID used as a top-level dictionary key must FAIL — a UUID-shaped key
    leaks an internal record id even though it carries no secret/email/path token."""
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    result = evaluate_public_output({uuid: "safe"})
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in _categories(result)
    assert uuid not in _blob(result)
    _no_secret_echoed(result)


def test_fail_top_level_private_prefix_dictionary_key():
    """A ``prefix_<long-hex>`` private id used as a top-level key must FAIL."""
    key = "user_1234567890abcdef"
    result = evaluate_public_output({key: "safe"})
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in _categories(result)
    assert key not in _blob(result)
    _no_secret_echoed(result)


@pytest.mark.parametrize(
    "key",
    [
        "550e8400-e29b-41d4-a716-446655440000",  # UUID
        "550e8400e29b41d4a716446655440000",  # bare long hex blob
        "user_1234567890abcdef",
        "project_1234567890abcdef",
        "artifact_1234567890abcdef",
        "student_1234567890abcdef",
        "source_1234567890abcdef",
        "provider_1234567890abcdef",
        "report_1234567890abcdef",
    ],
)
def test_fail_private_identifier_dictionary_keys(key):
    """Every UUID / hex-blob / ``prefix_<hex>`` shaped key must FAIL closed and is
    never echoed into any issue field."""
    result = evaluate_public_output({key: "safe"})
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in _categories(result)
    assert key not in _blob(result)
    _no_secret_echoed(result)


def test_nested_private_prefix_key_with_deeper_leak_not_echoed():
    """A leak nested UNDER a private-id key must fail closed, and neither the
    private-id key nor the deeper secret may appear in any issue field."""
    payload = {"safe": {"user_1234567890abcdef": {"nested": "api_key=sk-supersecret"}}}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    blob = _blob(result)
    for forbidden in ("user_1234567890abcdef", "sk-supersecret", "api_key=sk-supersecret"):
        assert forbidden not in blob, forbidden
    assert "<private_id_key>" in blob
    _no_secret_echoed(result)


def test_nested_uuid_key_with_deeper_issue_uses_placeholder_location():
    """A deeper issue under a UUID key must carry a placeholder in its location —
    the raw UUID must never reach location/message/recommended_fix/evidence_ids."""
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    payload = {"safe": {uuid: {"raw_payload": "provider_response"}}}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    blob = _blob(result)
    assert uuid not in blob
    assert "<private_id_key>" in blob
    for issue in result.issues:
        assert uuid not in issue.location
        assert uuid not in issue.message
        assert uuid not in issue.recommended_fix
        for eid in issue.evidence_ids:
            assert uuid not in eid
    _no_secret_echoed(result)


def test_safe_ordinary_dictionary_keys_not_flagged_as_private_ids():
    """Ordinary structural keys must NOT be flagged merely for their names."""
    payload = {"linked_proof_chains": [], "claims": [], "evidence": []}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.PASS
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK not in _categories(result)
    assert result.public_safe is True


# ── 23. Step-8-only: long *alphanumeric* (non-hex) private-ID keys are unsafe ──
#
# Step 7's prefix detector only catches a *hex* suffix, so a long alphanumeric
# private id such as ``user_1234567890ghijkl`` or ``project_ABCXYZ1234567890``
# previously slipped through and produced PASS. The Step-8-only key detector must
# fail these closed without echoing the raw key and without changing Step 7.


@pytest.mark.parametrize(
    "key",
    [
        "user_1234567890ghijkl",
        "project_ABCXYZ1234567890",
        "artifact_ABCXYZ1234567890",
        "student_1234567890ghijkl",
        "source_ABCXYZ1234567890",
        "provider_1234567890ghijkl",
        "report_ABCXYZ1234567890",
    ],
)
def test_fail_long_alphanumeric_private_identifier_keys(key):
    """A private prefix followed by a long alphanumeric (non-hex) suffix used as a
    dictionary key must FAIL closed and is never echoed into any issue field."""
    result = evaluate_public_output({key: "safe"})
    assert result.verdict is EvaluationVerdict.FAIL
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK in _categories(result)
    assert key not in _blob(result)
    assert "<private_id_key>" in _blob(result) or "private-identifier-shaped" in _blob(result)
    _no_secret_echoed(result)


def test_nested_alphanumeric_private_prefix_key_with_deeper_leak_not_echoed():
    """A leak nested UNDER a long-alphanumeric private-id key must fail closed, and
    neither the private-id key nor the deeper secret may appear in any issue field."""
    payload = {"safe": {"project_ABCXYZ1234567890": {"nested": "api_key=sk-supersecret"}}}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.FAIL
    blob = _blob(result)
    for forbidden in ("project_ABCXYZ1234567890", "sk-supersecret", "api_key=sk-supersecret"):
        assert forbidden not in blob, forbidden
    assert "<private_id_key>" in blob
    _no_secret_echoed(result)


def test_safe_source_prefixed_structural_keys_not_flagged():
    """``source_coverage`` / ``source_types_present`` share the ``source_`` prefix
    but are ordinary structural keys (short / underscored suffix) and must NOT be
    flagged by the long-alphanumeric private-id key detector."""
    payload = {"source_coverage": {"github": True}, "source_types_present": ["github"]}
    result = evaluate_public_output(payload)
    assert result.verdict is EvaluationVerdict.PASS
    assert EvaluationCategory.UNSAFE_PUBLIC_LEAK not in _categories(result)
    assert result.public_safe is True


def test_evaluator_does_not_reference_transcript_recorder():
    import app.services.proof_evaluation_qa_service as svc

    with open(svc.__file__, "r", encoding="utf-8") as handle:
        source = handle.read()
    for forbidden in ("VBRSessionRecorder", "vbr-session-recorder", "project-defense-record"):
        assert forbidden not in source
