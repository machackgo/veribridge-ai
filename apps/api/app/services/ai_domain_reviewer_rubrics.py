"""Field-specific rubrics for AI Domain Reviewer Agents.

These definitions are project-agnostic. Criteria refer only to generic evidence
signals such as claimed skills, workflow analysis, GitHub analysis, live checks,
defense analysis, privacy scans, readiness reports, missing evidence, and risk
flags.
"""

from __future__ import annotations

from typing import Any


Rubric = dict[str, Any]


COMMON_LIMITATION = (
    "This is an AI Domain Review using available evidence and a field-specific "
    "rubric. It can assess evidence consistency, technical substance, ownership "
    "signals, and missing artifacts. It cannot certify identity, guarantee work "
    "quality, replace faculty/company review, or complete human verification."
)


def _criterion(
    name: str,
    description: str,
    sources: list[str],
    *,
    red_flags: list[str] | None = None,
    human_triggers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "criterion_name": name,
        "max_score": 5,
        "description": description,
        "strong_evidence_signals": [
            "Multiple independent evidence sources support the claim",
            "Artifacts are specific, recent, and tied to the student's claimed skills",
            "Defense or workflow evidence explains decisions, tradeoffs, and ownership",
        ],
        "weak_evidence_signals": [
            "Only one evidence source supports the claim",
            "Evidence is generic, incomplete, inaccessible, or mostly narrative",
            "Claimed skills are present only as keywords without artifact support",
        ],
        "red_flags": red_flags or [
            "Evidence contradicts the student's explanation",
            "Major claimed skills have little or no artifact support",
            "Privacy or integrity risk flags are present",
        ],
        "evidence_sources_to_check": sources,
        "human_review_triggers": human_triggers or [
            "Low confidence after reviewing available evidence",
            "Contradictions across transcript, workflow, repository, or live checks",
            "High-stakes domain claims that affect safety, legal, clinical, or financial outcomes",
        ],
    }


RUBRICS: dict[str, Rubric] = {
    "cs_ai": {
        "reviewer_name": "Astra",
        "reviewer_role": "CS / AI / Data Science AI Reviewer",
        "domain": "cs_ai",
        "criteria": [
            _criterion(
                "Implementation and Code Evidence",
                "Assesses whether code, repository analysis, and workflow evidence demonstrate the claimed CS, AI, or data skills.",
                ["github_analysis", "workflow_analysis", "claimed_skills"],
            ),
            _criterion(
                "Technical Ownership and Project Understanding",
                "Assesses whether the student can explain architecture, models, data flow, tradeoffs, debugging, and limitations.",
                ["project_defense_analysis", "workflow_analysis"],
            ),
            _criterion(
                "Cross-Evidence Skill Support",
                "Assesses whether claimed skills are supported across repository, workflow, live check, defense, and readiness evidence.",
                ["readiness_report", "github_analysis", "workflow_analysis", "live_website_check", "project_defense_analysis"],
            ),
            _criterion(
                "Functionality and Runtime Evidence",
                "Assesses whether the project runs, is reachable when applicable, and has evidence of real user-facing or data-processing behavior.",
                ["live_website_check", "workflow_analysis", "github_analysis"],
            ),
            _criterion(
                "Privacy, Integrity, and Risk Controls",
                "Assesses privacy scan results, suspicious evidence gaps, and risk flags.",
                ["privacy_scan", "readiness_report", "project_defense_analysis"],
                human_triggers=["Privacy flagged", "Transcript contradicts repository/workflow evidence", "AI/health/legal/safety-critical claims"],
            ),
        ],
    },
    "civil_mech_eng": {
        "reviewer_name": "Atlas",
        "reviewer_role": "Civil / Mechanical Engineering AI Reviewer",
        "domain": "civil_mech_eng",
        "criteria": [
            _criterion(
                "Engineering Design Evidence",
                "Assesses design rationale, constraints, calculations, CAD/simulation artifacts, materials, or mechanical/civil documentation.",
                ["claimed_skills", "workflow_analysis", "github_analysis", "uploaded_files", "project_defense_analysis"],
                human_triggers=["Structural, load-bearing, safety, or compliance claims require human expert review"],
            ),
            _criterion(
                "Analysis, Calculations, and Validation",
                "Assesses whether analysis methods, units, assumptions, tests, or simulation validation are visible and consistent.",
                ["workflow_analysis", "project_defense_analysis", "readiness_report"],
                red_flags=["Missing calculations for structural/safety claims", "Unexplained assumptions", "Contradictory validation evidence"],
                human_triggers=["Civil/mechanical safety calculations are material to the claim"],
            ),
            _criterion(
                "Process and Iteration Evidence",
                "Assesses whether the student shows a real engineering process: requirements, alternatives, tradeoffs, iteration, and testing.",
                ["workflow_analysis", "project_defense_analysis"],
            ),
            _criterion(
                "Cross-Evidence Consistency",
                "Assesses whether claimed engineering skills align across workflow, repository/files, readiness, and defense evidence.",
                ["readiness_report", "workflow_analysis", "github_analysis", "project_defense_analysis"],
            ),
            _criterion(
                "Safety, Ethics, and Privacy Controls",
                "Assesses high-stakes safety implications, privacy scan status, and need for faculty/company/domain expert review.",
                ["privacy_scan", "readiness_report", "project_defense_analysis"],
                human_triggers=["Safety-critical, structural, clinical, legal, or regulated engineering claims"],
            ),
        ],
    },
    "business_finance": {
        "reviewer_name": "Nova",
        "reviewer_role": "Business / Finance / Analytics AI Reviewer",
        "domain": "business_finance",
        "criteria": [
            _criterion(
                "Business Problem Framing",
                "Assesses whether the evidence defines a business question, decision context, stakeholder, or measurable outcome.",
                ["claimed_skills", "workflow_analysis", "project_defense_analysis"],
            ),
            _criterion(
                "Data and Analytical Method Evidence",
                "Assesses whether data handling, assumptions, metrics, models, dashboards, or finance/analytics methods are supported.",
                ["github_analysis", "workflow_analysis", "project_defense_analysis"],
            ),
            _criterion(
                "Insight Quality and Decision Support",
                "Assesses whether outputs are interpreted into defensible business recommendations or analytical conclusions.",
                ["live_website_check", "workflow_analysis", "project_defense_analysis", "readiness_report"],
            ),
            _criterion(
                "Cross-Evidence Skill Support",
                "Assesses consistency of claimed business, finance, analytics, spreadsheet, BI, SQL, or modeling skills across evidence.",
                ["readiness_report", "github_analysis", "workflow_analysis", "project_defense_analysis"],
            ),
            _criterion(
                "Risk, Compliance, and Privacy Controls",
                "Assesses privacy, sensitive business data, financial advice risk, and claims that should be human reviewed.",
                ["privacy_scan", "readiness_report", "project_defense_analysis"],
                human_triggers=["Financial advice, investment recommendation, legal/compliance, or sensitive business data claims"],
            ),
        ],
    },
    "research": {
        "reviewer_name": "Sage",
        "reviewer_role": "Research / Academic AI Reviewer",
        "domain": "research",
        "criteria": [
            _criterion(
                "Research Question and Method Fit",
                "Assesses whether the question, hypothesis, methodology, and scope are visible and appropriate for the claimed discipline.",
                ["claimed_skills", "workflow_analysis", "project_defense_analysis", "uploaded_files"],
            ),
            _criterion(
                "Evidence, Citations, and Reproducibility",
                "Assesses whether sources, data, code, analysis steps, or reproducibility artifacts support the research claim.",
                ["github_analysis", "workflow_analysis", "project_defense_analysis"],
            ),
            _criterion(
                "Analysis and Interpretation Quality",
                "Assesses whether findings are interpreted with limitations, uncertainty, and appropriate conclusions.",
                ["project_defense_analysis", "readiness_report"],
            ),
            _criterion(
                "Academic Integrity and Ownership",
                "Assesses ownership signals, originality indicators, and consistency across submitted evidence.",
                ["workflow_analysis", "project_defense_analysis", "readiness_report"],
            ),
            _criterion(
                "Ethics, Privacy, and Human Review Needs",
                "Assesses sensitive data, human-subjects, clinical, legal, or high-stakes research concerns.",
                ["privacy_scan", "readiness_report", "project_defense_analysis"],
                human_triggers=["Human subjects, clinical, legal, safety-critical, or publishable academic claims"],
            ),
        ],
    },
    "general": {
        "reviewer_name": "General",
        "reviewer_role": "General AI Domain Reviewer",
        "domain": "general",
        "criteria": [
            _criterion(
                "Claimed Skill Evidence",
                "Assesses whether claimed skills are supported by available artifacts.",
                ["claimed_skills", "readiness_report", "workflow_analysis", "github_analysis"],
            ),
            _criterion(
                "Ownership and Explanation",
                "Assesses whether the student can explain what they built, how it works, and what decisions they made.",
                ["project_defense_analysis", "workflow_analysis"],
            ),
            _criterion(
                "Artifact Functionality",
                "Assesses whether the project or work product is visible, functional, reachable when applicable, or otherwise inspectable.",
                ["live_website_check", "workflow_analysis", "github_analysis", "uploaded_files"],
            ),
            _criterion(
                "Cross-Evidence Consistency",
                "Assesses agreement across all available evidence sources.",
                ["readiness_report", "workflow_analysis", "github_analysis", "live_website_check", "project_defense_analysis"],
            ),
            _criterion(
                "Privacy and Escalation Risk",
                "Assesses privacy flags, high-stakes claims, and whether human review is recommended.",
                ["privacy_scan", "readiness_report", "project_defense_analysis"],
            ),
        ],
    },
}


def get_rubric(domain: str | None) -> Rubric:
    return RUBRICS.get(domain or "", RUBRICS["general"])
