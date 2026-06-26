"""Tests for the canonical GitHub skill-evidence extractor.

This is the single, shared filter the VBR Project Report and the Work Passport
Skill Report both use to turn stored ``analysis_snapshot.skill_code_evidence``
into safe, strength-ranked evidence. The contract:

* strong code (functions / classes / endpoints / model code) keeps its exact
  file/line/function/snippet and a safe ``…#L`` link;
* weak code (imports, sys.path/setup, package/README/metadata, notebook
  markdown/prose) is downgraded and never surfaced as primary line proof;
* GitHub line URLs prefer the pinned commit SHA, and a ``#L`` anchor is only ever
  built for a valid line range — line numbers are never fabricated.
"""

from __future__ import annotations

from app.services.github_skill_evidence_service import extract_github_skill_evidence


def _gh_row(evidence: list[dict], **overrides) -> dict:
    row = {
        "id": "gh-1",
        "repo_owner": "octocat",
        "repo_name": "Hello-World",
        "repo_url": "https://github.com/octocat/Hello-World",
        "default_branch": "main",
        "visibility": "public",
        "detected_skills": [],
        "public_safe_summary": "Repository analyzed.",
        "analysis_snapshot": {"raw_dump": "should-never-leak", "skill_code_evidence": evidence},
    }
    row.update(overrides)
    return row


# ── Strong evidence is preserved with exact locators + link ──────────────────


def test_strong_function_evidence_keeps_file_line_function_snippet_link() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "src/model/train.py",
                    "line_start": 10,
                    "line_end": 24,
                    "function_name": "train_model",
                    "code_snippet": "def train_model(df):\n    return clf.fit(df)",
                    "commit_sha": "abc1234def5678",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.evidence_strength == "strong"
    assert ev.file_path == "src/model/train.py"
    assert ev.line_start == 10 and ev.line_end == 24
    assert ev.function_name == "train_model"
    assert ev.evidence_kind == "function"
    assert ev.code_snippet and "train_model" in ev.code_snippet


def test_builds_github_line_url_preferring_commit_sha() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "code_snippet": '@app.post("/predict")\ndef predict(req):\n    return model.predict(req)',
                    "commit_sha": "deadbeef1234",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.github_url == "https://github.com/octocat/Hello-World/blob/deadbeef1234/api.py#L252-L255"
    assert ev.endpoint_path == "/predict"
    assert ev.evidence_kind == "endpoint"


def test_falls_back_to_branch_when_no_commit_sha() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 5,
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.github_url == "https://github.com/octocat/Hello-World/blob/main/api.py#L5"


# ── Weak evidence is downgraded ──────────────────────────────────────────────


def test_import_only_snippet_classified_weak() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "api.py",
                    "line_start": 6,
                    "line_end": 9,
                    "code_snippet": "import sys\nimport io\nimport time",
                }
            ]
        )
    )
    assert result.best_strong_for_skill("Python") is None
    assert "Python" in result.weak_only_skill_names
    weak = result.weak_items[0]
    assert weak.evidence_strength == "weak"
    # Weak snippets are never carried as displayable code.
    assert weak.code_snippet is None


def test_sys_path_setup_snippet_classified_weak() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Google Cloud",
                    "file_path": "src/predict/predictor.py",
                    "line_start": 1,
                    "line_end": 3,
                    "code_snippet": (
                        "# Ensure repo root is on sys.path so src.predict.predictor is importable\n"
                        "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))"
                    ),
                }
            ]
        )
    )
    assert result.best_strong_for_skill("Google Cloud") is None
    assert "Google Cloud" in result.weak_only_skill_names


def test_package_metadata_and_notebook_markdown_classified_weak() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "requirements.txt",
                    "line_start": 1,
                    "code_snippet": "flask==2.0.1\nnumpy==1.26.0",
                },
                {
                    "skill": "API Development",
                    "file_path": "notebooks/overview.ipynb",
                    "line_start": 1,
                    "code_snippet": "## Project Overview\n- This notebook describes the API design\nhttps://example.com",
                },
            ]
        )
    )
    assert result.strong_items == []
    assert "Python" in result.weak_only_skill_names
    assert "API Development" in result.weak_only_skill_names


# ── Never fabricate line URLs / handle missing lines ─────────────────────────


def test_no_line_url_for_weak_evidence() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "api.py",
                    "line_start": 6,
                    "code_snippet": "import sys",
                }
            ]
        )
    )
    assert all(i.github_url is None for i in result.items)


def test_strong_evidence_without_lines_has_no_line_anchor() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.line_start is None
    assert ev.github_url and "#L" not in ev.github_url


# ── Strong ranked above weak for the same skill ──────────────────────────────


def test_prefers_strong_function_over_weak_import_for_same_skill() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "api.py",
                    "line_start": 6,
                    "line_end": 9,
                    "code_snippet": "import sys\nimport io",
                },
                {
                    "skill": "Python",
                    "file_path": "src/train.py",
                    "line_start": 40,
                    "line_end": 44,
                    "function_name": "train_model",
                    "code_snippet": "def train_model(df):\n    return clf.fit(df)",
                },
            ]
        )
    )
    ev = result.best_strong_for_skill("Python")
    assert ev is not None
    assert ev.function_name == "train_model"
    assert ev.evidence_strength == "strong"
    # Python now has strong evidence, so it is NOT weak-only.
    assert "Python" not in result.weak_only_skill_names


# ── Private repos never expose a public link or snippet ──────────────────────


def test_private_repo_hides_link_and_snippet() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 1,
                    "function_name": "predict",
                    "code_snippet": "def predict(req): ...",
                }
            ],
            visibility="private",
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.public_safe is False
    assert ev.github_url is None
    assert ev.code_snippet is None
    # The locator path/line is still known (just not publicly linkable).
    assert ev.file_path == "api.py"


def test_raw_snapshot_never_echoed() -> None:
    result = extract_github_skill_evidence(
        _gh_row([{"skill": "Python", "file_path": "api.py", "line_start": 1, "code_snippet": "import sys"}])
    )
    assert "should-never-leak" not in str([i.to_dict() for i in result.items])


# ── Canonical skill_evidence adapter (old Profile & Proof engine rows) ─────────

from app.services.github_canonical_skill_evidence_adapter import (  # noqa: E402
    collect_canonical_github_skill_evidence,
    repo_identity,
)

_USER = "00000000-0000-0000-0000-000000000042"


def _seed_skill_evidence_row(store: dict, **overrides) -> str:
    eid = overrides.pop("id", "se-1")
    row = {
        "id": eid,
        "user_id": _USER,
        "skill_name": "API Development",
        "evidence_type": "github repository",
        "repository_url": "https://github.com/octocat/Hello-World",
        "file_path": "app/api/routes.py",
        "line_start": 10,
        "line_end": 20,
        "evidence_description": "API route handler.",
        "proof_visibility": "public",
        "metadata": {
            "github_highlight_url": "https://github.com/octocat/Hello-World/blob/main/app/api/routes.py#L10-L20",
            "selection_reason": "API endpoint decorator",
            "evidence_title": "Boston Rerouting",
            "secret_token": "should-never-leak",
        },
    }
    row.update(overrides)
    store.setdefault("skill_evidence", {})[eid] = row
    return eid


def test_repo_identity_normalizes_urls_and_full_names() -> None:
    assert repo_identity("https://github.com/Octocat/Hello-World") == "octocat/hello-world"
    assert repo_identity("git@github.com:octocat/Hello-World.git") == "octocat/hello-world"
    assert repo_identity("octocat/Hello-World") == "octocat/hello-world"
    assert repo_identity("") == ""
    assert repo_identity("not a repo") == ""


def test_adapter_reads_precise_canonical_github_evidence() -> None:
    store: dict = {}
    _seed_skill_evidence_row(store)
    items = collect_canonical_github_skill_evidence(store, _USER)
    assert len(items) == 1
    ev = items[0]
    assert ev.source == "skill_evidence"
    assert ev.display_mode == "code_line"
    assert ev.has_precise_line_evidence is True
    assert ev.file_path == "app/api/routes.py"
    assert ev.line_start == 10 and ev.line_end == 20
    assert ev.selection_reason == "API endpoint decorator"
    assert ev.github_line_url and "#L10-L20" in ev.github_line_url
    assert ev.repo_id == "octocat/hello-world"
    assert "should-never-leak" not in str(ev.to_dict())


def test_adapter_filters_by_skill_and_skips_non_github_rows() -> None:
    store: dict = {}
    _seed_skill_evidence_row(store, id="se-gh", skill_name="API Development")
    # An extension-proof row (no github, no file_path) must be ignored.
    _seed_skill_evidence_row(
        store,
        id="se-ext",
        skill_name="React",
        evidence_type="private website (extension proof)",
        repository_url=None,
        file_path=None,
    )
    assert [e.skill_name for e in collect_canonical_github_skill_evidence(store, _USER)] == [
        "API Development"
    ]
    assert collect_canonical_github_skill_evidence(store, _USER, "react") == []


def test_adapter_hides_link_for_private_proof() -> None:
    store: dict = {}
    _seed_skill_evidence_row(store, proof_visibility="private")
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.public_safe is False
    assert ev.github_line_url is None
    # The locator path/line is still known (just not publicly linkable).
    assert ev.file_path == "app/api/routes.py"
    assert ev.to_dict()["repo_url"] is None
