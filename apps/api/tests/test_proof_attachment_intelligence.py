"""Tests for the centralized Attachment Intelligence helper (Passport 1B Step 4).

``classify_vault_attachments`` must:

* split every vault proof into DISJOINT attached / suggested / unattached
  buckets — suggested evidence never counts as attached or verified;
* deduplicate duplicate rows of the same real-world proof (documents by safe
  title, GitHub by owner/repo, websites by hostname, defense attempts by
  project) without merging distinct proofs;
* emit closed reason codes and relation-strength labels (deterministic /
  likely / weak / none) — never numeric scores;
* expose ONLY safe display fields (no source ids/tables, paths, URLs other
  than owner-only app routes, raw text, or provider payloads).

Pure-function tests — no DB, no network, no LLM.
"""

from __future__ import annotations

from app.services.proof_attachment_intelligence import (
    REASON_LABELS,
    STATE_ATTACHED,
    STATE_SUGGESTED,
    STATE_UNATTACHED,
    STRENGTH_DETERMINISTIC,
    STRENGTH_LIKELY,
    STRENGTH_NONE,
    STRENGTH_WEAK,
    SUGGESTED_STATUS_LABEL,
    classify_vault_attachments,
    suggested_evidence_for_project,
)


def _item(**overrides) -> dict:
    base = {
        "proof_type": "Document Proof",
        "source_id": "src-1",
        "source_table": "optional_evidence_submissions",
        "title": "Untitled",
        "skill_name": None,
        "safe_summary": "",
        "safe_snippet": "",
        "is_attached_to_project": False,
        "attached_project_ids": [],
    }
    base.update(overrides)
    return base


def _project(pid: str = "p1", title: str = "Stroke Prediction App", repo: str = "", skills=None) -> dict:
    return {
        "project_id": pid,
        "project_title": title,
        "repo_full_name": repo,
        "claimed_skills": skills or ["Machine Learning"],
    }


# ── Deduplication ─────────────────────────────────────────────────────────────


def test_duplicate_documents_collapse_by_safe_title() -> None:
    items = [
        _item(source_id="d1", title="Stroke Prediction Report", skill_name="Machine Learning"),
        _item(source_id="d2", title="Stroke Prediction Report", skill_name="Data Analysis"),
    ]
    out = classify_vault_attachments(items, [_project()])
    all_entries = out["attached"] + out["suggested"] + out["unattached"]
    assert len(all_entries) == 1
    entry = all_entries[0]
    assert entry["duplicate_count"] == 2
    # Both rows' skills merge into the single display entry.
    assert set(entry["skill_names"]) == {"Machine Learning", "Data Analysis"}


def test_duplicate_github_rows_collapse_by_owner_repo() -> None:
    items = [
        _item(
            proof_type="GitHub Proof",
            source_id=f"g{i}",
            source_table="github_proofs",
            title="octo/stroke-repo",
            repo_url="https://github.com/octo/stroke-repo",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
            skill_name=skill,
        )
        for i, skill in enumerate(["Python", "FastAPI", "Python"])
    ]
    out = classify_vault_attachments(items, [_project(repo="octo/stroke-repo")])
    assert out["attached_count"] == 1
    assert out["attached"][0]["duplicate_count"] == 3
    assert out["attached"][0]["relation_reason"] == "exact_repo_match"


def test_duplicate_websites_collapse_by_hostname() -> None:
    items = [
        _item(
            proof_type="Website Proof",
            source_id=f"w{i}",
            source_table="workflow_analysis",
            title="https://myapp.example.com",
            public_url="https://myapp.example.com",
        )
        for i in range(2)
    ]
    out = classify_vault_attachments(items, [])
    assert out["unattached_count"] == 1
    assert out["unattached"][0]["duplicate_count"] == 2


def test_same_repo_on_two_different_projects_does_not_merge() -> None:
    items = [
        _item(
            proof_type="GitHub Proof",
            source_id="g1",
            source_table="github_proofs",
            title="octo/shared-repo",
            repo_url="https://github.com/octo/shared-repo",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        ),
        _item(
            proof_type="GitHub Proof",
            source_id="g2",
            source_table="github_proofs",
            title="octo/shared-repo",
            repo_url="https://github.com/octo/shared-repo",
            is_attached_to_project=True,
            attached_project_ids=["p2"],
        ),
    ]
    projects = [_project("p1", "Project One"), _project("p2", "Project Two")]
    out = classify_vault_attachments(items, projects)
    # Same repo, DIFFERENT projects — must stay two attached entries.
    assert out["attached_count"] == 2
    refs = {ref for e in out["attached"] for ref in e["project_refs_safe"]}
    assert refs == {"/student/vbr/projects/p1/report", "/student/vbr/projects/p2/report"}


def test_defense_attempts_collapse_per_project_without_spamming_counts() -> None:
    # Two sessions × two skill rows each → ONE entry, duplicate_count = sessions.
    items = [
        _item(
            proof_type="Project Defense",
            source_id=session,
            source_table="vbr_verification_sessions",
            title="Project Defense",
            skill_name=skill,
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        )
        for session in ("s1", "s2")
        for skill in ("Python", "React")
    ]
    out = classify_vault_attachments(items, [_project()])
    assert out["attached_count"] == 1
    entry = out["attached"][0]
    assert entry["duplicate_count"] == 2
    assert entry["relation_reason"] == "project_defense_session"
    assert entry["relation_strength"] == STRENGTH_DETERMINISTIC


# ── Attached classification (deterministic only) ─────────────────────────────


def test_user_attached_document_counts_as_attached_deterministic() -> None:
    items = [
        _item(
            source_id="d1",
            title="Design Notes",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        )
    ]
    out = classify_vault_attachments(items, [_project()])
    assert out["attached_count"] == 1
    entry = out["attached"][0]
    assert entry["attachment_state"] == STATE_ATTACHED
    assert entry["relation_strength"] == STRENGTH_DETERMINISTIC
    assert entry["relation_reason"] == "exact_document_attachment"
    assert entry["project_titles"] == ["Stroke Prediction App"]


def test_attached_reason_codes_per_proof_type() -> None:
    items = [
        _item(
            proof_type="Website Proof",
            source_id="w1",
            source_table="workflow_analysis",
            title="https://app.example.com",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        ),
        _item(
            proof_type="Skill Graph",
            source_id="sp1",
            source_table="skill_pipelines",
            title="Skill Graph — Python",
            skill_name="Python",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        ),
        _item(
            proof_type="GitHub Proof",
            source_id="g1",
            source_table="github_proofs",
            title="Some scanner row",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        ),
    ]
    out = classify_vault_attachments(items, [_project()])
    reasons = {e["proof_type"]: e["relation_reason"] for e in out["attached"]}
    assert reasons["Website Proof"] == "exact_website_attachment"
    assert reasons["Skill Graph"] == "exact_project_id_match"
    # GitHub row with no repo identity matching a project repo → user_attached.
    assert reasons["GitHub Proof"] == "user_attached"
    assert all(e["relation_strength"] == STRENGTH_DETERMINISTIC for e in out["attached"])


# ── Suggested classification (never attached) ────────────────────────────────


def test_title_similarity_becomes_suggestion_not_attached() -> None:
    items = [
        _item(
            source_id="d1",
            title="Stroke Prediction Report",
            skill_name="Machine Learning",
            safe_summary="Findings for the Stroke Prediction App",
        )
    ]
    out = classify_vault_attachments(items, [_project()])
    assert out["attached_count"] == 0
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["attachment_state"] == STATE_SUGGESTED
    assert entry["relation_reason"] == "title_similarity_suggestion"
    assert entry["relation_strength"] in (STRENGTH_LIKELY, STRENGTH_WEAK)
    assert entry["status_label"] == SUGGESTED_STATUS_LABEL


def test_repo_identity_suggestion_uses_repo_reason_code() -> None:
    items = [
        _item(
            proof_type="GitHub Proof",
            source_id="g1",
            source_table="github_proofs",
            title="octo/stroke-repo",
            repo_url="https://github.com/octo/stroke-repo",
            skill_name="Python",
        )
    ]
    out = classify_vault_attachments(items, [_project(repo="octo/stroke-repo")])
    assert out["suggested_count"] == 1
    assert out["suggested"][0]["relation_reason"] == "repo_owner_repo_suggestion"
    assert out["suggested"][0]["relation_strength"] == STRENGTH_LIKELY


def test_skill_overlap_only_is_weak_suggestion() -> None:
    items = [_item(source_id="d1", title="Generic Notes", skill_name="Machine Learning")]
    out = classify_vault_attachments(items, [_project(title="Totally Different Name")])
    assert out["attached_count"] == 0
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["relation_reason"] == "skill_overlap_suggestion"
    assert entry["relation_strength"] == STRENGTH_WEAK


def test_skill_tie_across_projects_never_guesses_a_project() -> None:
    items = [_item(source_id="d1", title="Generic Notes", skill_name="Machine Learning")]
    projects = [
        _project("p1", "Alpha Project"),
        _project("p2", "Beta Project"),
    ]
    out = classify_vault_attachments(items, projects)
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["project_titles"] == []
    assert entry["project_refs_safe"] == []


def test_suggestions_never_inflate_attached_counts() -> None:
    items = [
        _item(
            source_id="d1",
            title="Attached Doc",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        ),
        _item(source_id="d2", title="Stroke Prediction Notes", skill_name="Machine Learning"),
    ]
    out = classify_vault_attachments(items, [_project()])
    assert out["attached_count"] == 1
    assert out["suggested_count"] == 1
    # Buckets are disjoint: a suggested proof appears nowhere in attached.
    attached_ids = {e["entry_id_safe"] for e in out["attached"]}
    suggested_ids = {e["entry_id_safe"] for e in out["suggested"]}
    assert attached_ids.isdisjoint(suggested_ids)


# ── Unattached ────────────────────────────────────────────────────────────────


def test_unattached_count_excludes_attached_and_deduped_rows() -> None:
    items = [
        # Two duplicate rows of one attached doc.
        _item(source_id="d1", title="Attached Doc", is_attached_to_project=True, attached_project_ids=["p1"]),
        _item(source_id="d2", title="Attached Doc", is_attached_to_project=True, attached_project_ids=["p1"]),
        # Two duplicate rows of one unattached, unmatched website.
        _item(proof_type="Website Proof", source_id="w1", source_table="wf", title="https://elsewhere.example.org", public_url="https://elsewhere.example.org"),
        _item(proof_type="Website Proof", source_id="w2", source_table="wf", title="https://elsewhere.example.org", public_url="https://elsewhere.example.org"),
    ]
    out = classify_vault_attachments(items, [_project()])
    assert out["attached_count"] == 1
    assert out["unattached_count"] == 1
    entry = out["unattached"][0]
    assert entry["attachment_state"] == STATE_UNATTACHED
    assert entry["relation_reason"] == "no_match"
    assert entry["relation_strength"] == STRENGTH_NONE


# ── Safety: whitelisted display fields only ──────────────────────────────────

_ALLOWED_ENTRY_KEYS = {
    "entry_id_safe",
    "proof_type",
    "display_title",
    "source_label",
    "attachment_state",
    "relation_reason",
    "relation_strength",
    "reason_label",
    "status_label",
    "project_titles",
    "project_refs_safe",
    "skill_names",
    "duplicate_count",
}


def test_entries_carry_only_safe_whitelisted_fields() -> None:
    items = [
        _item(
            proof_type="GitHub Proof",
            source_id="g1",
            source_table="github_proofs",
            title="octo/repo",
            repo_url="https://github.com/octo/repo",
            file_path="/Users/someone/private/path.py",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        ),
        _item(source_id="d1", title="Some Doc", skill_name="Python"),
    ]
    out = classify_vault_attachments(items, [_project(skills=["Python"])])
    for entry in out["attached"] + out["suggested"] + out["unattached"]:
        assert set(entry.keys()) == _ALLOWED_ENTRY_KEYS
        # No numeric confidence anywhere — strength is a closed label.
        assert entry["relation_strength"] in ("deterministic", "likely", "weak", "none")
        # Entry ids are one-way digests, never raw source ids.
        assert entry["entry_id_safe"].startswith("att-")
        assert "g1" not in entry["entry_id_safe"] and "d1" not in entry["entry_id_safe"]
        blob = str(entry)
        assert "source_id" not in blob
        assert "/Users/" not in blob
        assert "github_proofs" not in blob


def test_reason_labels_cover_every_reason_code() -> None:
    for code, label in REASON_LABELS.items():
        assert label, f"reason {code} must carry a display label"


# ── Safety: display VALUES are sanitized, not only field names ───────────────
# A document "title" can literally be a local file_path (the vault falls back
# to it), a project title or skill label can carry a pasted secret/private id,
# and a website title can be a signed storage URL. None of these may ever be
# echoed on a display field — they fail closed to a neutral label instead.


def test_attached_document_title_from_local_file_path_never_leaks() -> None:
    items = [
        _item(
            source_id="d1",
            title="/Users/alice/private/report.pdf",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        )
    ]
    out = classify_vault_attachments(items, [_project()])
    assert out["attached_count"] == 1
    entry = out["attached"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(out)
    assert "/Users/" not in blob
    assert "report.pdf" not in blob


def test_suggested_entry_title_from_local_file_path_never_leaks() -> None:
    items = [
        _item(
            source_id="d1",
            title="/Users/alice/private/report.pdf",
            skill_name="Machine Learning",
        )
    ]
    out = classify_vault_attachments(items, [_project()])
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(suggested_evidence_for_project(out, "p1")) + str(out)
    assert "/Users/" not in blob
    assert "report.pdf" not in blob


def test_windows_path_title_never_leaks() -> None:
    items = [
        _item(
            source_id="d1",
            title="C:\\Users\\Alice\\secret.docx",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        )
    ]
    out = classify_vault_attachments(items, [_project()])
    entry = out["attached"][0]
    assert entry["display_title"] == "Document Proof"
    assert "C:\\" not in str(out)
    assert "secret.docx" not in str(out)


def test_project_title_that_is_a_path_becomes_neutral_project_label() -> None:
    items = [
        _item(
            source_id="d1",
            title="Design Notes",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        )
    ]
    out = classify_vault_attachments(items, [_project(title="/Users/alice/private/project.md")])
    entry = out["attached"][0]
    assert entry["project_titles"] == ["Project"]
    blob = str(out)
    assert "/Users/" not in blob
    assert "project.md" not in blob


def test_secret_and_private_id_skill_names_are_dropped() -> None:
    items = [
        _item(source_id="d1", title="Notes", skill_name="api_key=sk-private"),
        _item(source_id="d2", title="Notes", skill_name="source_id=user_123"),
        _item(source_id="d3", title="Notes", skill_name="Python"),
    ]
    out = classify_vault_attachments(items, [])
    all_entries = out["attached"] + out["suggested"] + out["unattached"]
    assert all_entries, "expected the merged document entry"
    skills = {s for e in all_entries for s in e["skill_names"]}
    assert skills == {"Python"}
    blob = str(out)
    assert "sk-private" not in blob
    assert "api_key" not in blob
    assert "user_123" not in blob
    assert "source_id" not in blob


def test_signed_storage_url_title_shows_hostname_or_neutral_label_only() -> None:
    signed = "https://example.supabase.co/storage/v1/object/sign/private/report.pdf?token=abc"
    items = [
        _item(
            proof_type="Website Proof",
            source_id="w1",
            source_table="workflow_analysis",
            title=signed,
            public_url=signed,
        )
    ]
    out = classify_vault_attachments(items, [])
    all_entries = out["attached"] + out["suggested"] + out["unattached"]
    assert len(all_entries) == 1
    entry = all_entries[0]
    assert entry["display_title"] in ("example.supabase.co", "Website Proof")
    blob = str(out)
    assert "token=abc" not in blob
    assert "/storage/v1/object" not in blob
    assert "report.pdf" not in blob


# ── Hostile display values: relative paths / provider JSON / raw evidence ────
# Every value below survived the earlier sanitizer (Codex read-only repro) and
# must now fail closed to a neutral proof-type label through BOTH the attached
# view (``attachment_overview``) and the per-project suggested view.


def _attached_doc(title: str) -> dict:
    """One document proof attached to project ``p1`` with a hostile title."""
    return classify_vault_attachments(
        [
            _item(
                source_id="d1",
                title=title,
                is_attached_to_project=True,
                attached_project_ids=["p1"],
            )
        ],
        [_project()],
    )


def _suggested_doc(title: str) -> dict:
    """One unattached document proof that becomes a skill-overlap suggestion."""
    return classify_vault_attachments(
        [_item(source_id="d1", title=title, skill_name="Machine Learning")],
        [_project()],
    )


def test_relative_storage_path_never_leaks_in_attachment_overview() -> None:
    out = _attached_doc("private-bucket/users/alice/report.pdf")
    entry = out["attached"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(out)
    assert "private-bucket" not in blob
    assert "report.pdf" not in blob
    assert "alice" not in blob


def test_relative_storage_path_never_leaks_in_suggested_evidence() -> None:
    out = _suggested_doc("private-bucket/users/alice/report.pdf")
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(suggested_evidence_for_project(out, "p1")) + str(out)
    assert "private-bucket" not in blob
    assert "report.pdf" not in blob
    assert "alice" not in blob


def test_uploads_path_never_leaks_in_attachment_overview() -> None:
    out = _attached_doc("uploads/user-123/report.pdf")
    entry = out["attached"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(out)
    assert "uploads/" not in blob
    assert "user-123" not in blob
    assert "report.pdf" not in blob


def test_uploads_path_never_leaks_in_suggested_evidence() -> None:
    out = _suggested_doc("uploads/user-123/report.pdf")
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(suggested_evidence_for_project(out, "p1")) + str(out)
    assert "uploads/" not in blob
    assert "user-123" not in blob
    assert "report.pdf" not in blob


def test_provider_json_payload_never_leaks_in_attachment_overview() -> None:
    out = _attached_doc('{"provider":"openai","model":"gpt-4"}')
    entry = out["attached"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(out)
    assert '{"provider"' not in blob
    assert "openai" not in blob
    assert "gpt-4" not in blob
    assert "provider" not in blob


def test_provider_json_payload_never_leaks_in_suggested_evidence() -> None:
    out = _suggested_doc('{"provider":"openai","model":"gpt-4"}')
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(suggested_evidence_for_project(out, "p1")) + str(out)
    assert '{"provider"' not in blob
    assert "openai" not in blob
    assert "gpt-4" not in blob


def test_raw_transcript_text_never_leaks_in_attachment_overview() -> None:
    out = _attached_doc("Raw transcript: my internal deployment uses a private endpoint.")
    entry = out["attached"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(out)
    assert "Raw transcript" not in blob
    assert "internal deployment" not in blob
    assert "private endpoint" not in blob


def test_raw_transcript_text_never_leaks_in_suggested_evidence() -> None:
    out = _suggested_doc("Raw transcript: my internal deployment uses a private endpoint.")
    assert out["suggested_count"] == 1
    entry = out["suggested"][0]
    assert entry["display_title"] == "Document Proof"
    blob = str(suggested_evidence_for_project(out, "p1")) + str(out)
    assert "Raw transcript" not in blob
    assert "internal deployment" not in blob
    assert "private endpoint" not in blob


def test_normal_safe_display_values_are_preserved() -> None:
    items = [
        _item(
            proof_type="GitHub Proof",
            source_id="g1",
            source_table="github_proofs",
            title="machackgo/boston-smart-accident-risk-rerouting-google-cloud",
            repo_url="https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
            skill_name="Python",
            is_attached_to_project=True,
            attached_project_ids=["p1"],
        ),
        _item(source_id="d1", title="Model Evaluation Notes", skill_name="Machine Learning"),
    ]
    projects = [
        _project(
            "p1",
            "Boston Smart Accident Risk Rerouting",
            repo="machackgo/boston-smart-accident-risk-rerouting-google-cloud",
            skills=["Python", "Machine Learning"],
        )
    ]
    out = classify_vault_attachments(items, projects)
    attached = out["attached"][0]
    assert attached["display_title"] == "machackgo/boston-smart-accident-risk-rerouting-google-cloud"
    assert attached["project_titles"] == ["Boston Smart Accident Risk Rerouting"]
    assert attached["skill_names"] == ["Python"]
    all_entries = out["attached"] + out["suggested"] + out["unattached"]
    doc = next(e for e in all_entries if e["proof_type"] == "Document Proof")
    assert doc["display_title"] == "Model Evaluation Notes"
    assert doc["skill_names"] == ["Machine Learning"]


# ── Per-project suggested evidence (report preview) ──────────────────────────


def test_suggested_evidence_for_project_filters_by_project() -> None:
    items = [
        _item(source_id="d1", title="Stroke Prediction Notes", skill_name="Machine Learning"),
    ]
    out = classify_vault_attachments(items, [_project("p1"), _project("p2", "Other Project", skills=["Go"])])
    assert suggested_evidence_for_project(out, "p1"), "expected a suggestion for p1"
    assert suggested_evidence_for_project(out, "p2") == []
