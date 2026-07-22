"""Honest wording + metric normalization for Website Proof analysis (§8/§9).

Locks in the recruiter-summary framing so regressions can't reintroduce
dismissive or contradictory language:

  * implementation frameworks are described as "not directly observable from
    browser workflow evidence", never asserted unsupported — and no vendor name
    (React / Next.js / Supabase / FastAPI) leaks into the recruiter summary
  * localhost is honest but not dismissive: it separates deployment
    accessibility from the workflow that was demonstrated
  * the evidence-ladder vocabulary is used (Demonstrated / Partially
    demonstrated / Not assessed)

No network / LLM calls.
"""

from __future__ import annotations

from app.services.extension_proof_workflow_analysis_service import _build_recruiter_summary


def _summary(**overrides) -> str:
    kwargs = dict(
        proof_objective="Show the dashboard working",
        target_visited_urls=["https://app.example.com/", "https://app.example.com/reports"],
        supported=["Data Visualization"],
        weakly=[],
        unsupported=["Machine Learning"],
        url_type="deployed_url",
        duration_secs=90.0,
        score=68,
        confidence="medium",
        github_url=None,
        original_url="https://app.example.com/",
    )
    kwargs.update(overrides)
    return _build_recruiter_summary(**kwargs)


def test_framework_caveat_present_without_vendor_names():
    s = _summary()
    assert "cannot be directly verified from browser-visible workflow evidence alone" in s
    # No specific framework/vendor name leaks into the recruiter summary.
    for vendor in ("React", "Next.js", "Supabase", "FastAPI"):
        assert vendor not in s


def test_unsupported_phrased_as_not_assessed_not_absent():
    s = _summary(unsupported=["Machine Learning"])
    assert "Not assessed from this workflow" in s
    # Never claims the technology is absent — only that it wasn't demonstrated here.
    assert "not evidence they are absent" in s


def test_evidence_ladder_demonstrated_and_partially_demonstrated():
    s = _summary(
        supported=["Data Visualization"],
        weakly=["API Integration"],
        skill_obs={"API Integration": "indirect"},
        unsupported=[],
    )
    assert "Demonstrated in the recorded workflow: Data Visualization" in s
    assert "Partially demonstrated: API Integration" in s


def test_localhost_is_honest_not_dismissive():
    s = _summary(url_type="localhost_url", original_url="http://localhost:3000/")
    assert "local development environment" in s
    # Separates deployment accessibility from the demonstrated workflow.
    assert "cannot independently open" in s
    assert "not the workflow demonstrated" in s
