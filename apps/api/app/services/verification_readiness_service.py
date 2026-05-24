"""
Verification Readiness Report — computes a 0–100 readiness score and
actionable report from existing proof evidence.

This is a pure computation with no new database table.  The report is
derived entirely from evidence data already stored: workflow analysis,
live website check, GitHub analysis, and privacy scan.

Project-agnostic: no hardcoded project names, URLs, frameworks, or
disciplines.  Works for frontend apps, full-stack projects, ML models,
dashboards, local-only apps, portfolios, and future non-CS fields.

IMPORTANT: Final Verification is NEVER marked "complete" by this
service.  The only statuses emitted are "pending" and "ready_for_review".
Final Verification completion is a separate human/VeriBridge reviewer step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ReadinessLevel = Literal["strong", "moderate", "weak", "insufficient"]
FinalVerificationStatus = Literal["pending", "ready_for_review"]
# "complete" is intentionally absent.


# ── URL classification (mirrors frontend classifyUrl) ─────────────────────────

def _classify_url(url: str) -> str:
    """Return one of: localhost_url | local_network_url | live_deployed_url | invalid_url."""
    import re
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "invalid_url"
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        if hostname in ("localhost", "127.0.0.1"):
            return "localhost_url"
        if re.match(r"^10\.", hostname):
            return "local_network_url"
        if re.match(r"^192\.168\.", hostname):
            return "local_network_url"
        if re.match(r"^172\.(1[6-9]|2\d|3[01])\.", hostname):
            return "local_network_url"
        return "live_deployed_url"
    except Exception:
        return "invalid_url"


# ── Skill improvement tips ─────────────────────────────────────────────────────

#: Pattern-matched skill tips.  Each entry matches one or more substrings
#: in a skill name (case-insensitive) and provides two tip variants:
#:   tip_missing  — for skills with NO evidence at all
#:   tip_partial  — for skills with PARTIAL/WEAK evidence, or when the
#:                  student already has a GitHub repo linked
_SKILL_TIPS: list[dict[str, Any]] = [
    {
        "category": "backend_framework",
        "patterns": [
            "fastapi", "flask", "django", "express", "node.js", "nodejs",
            "spring", "rails", "laravel", "gin", "actix",
        ],
        "tip_missing": (
            "Backend frameworks aren't visible in the browser. "
            "Add a public GitHub repo with route/controller files or API documentation."
        ),
        "tip_partial": (
            "Strengthen backend evidence by adding API route files, controller code, "
            "or Swagger/OpenAPI docs to your GitHub repo."
        ),
    },
    {
        "category": "ml_framework",
        "patterns": [
            "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn",
            "xgboost", "lightgbm", "hugging face", "huggingface",
        ],
        "tip_missing": (
            "Add model metrics, a Jupyter notebook, training script, "
            "or an inference demo to make ML skills verifiable."
        ),
        "tip_partial": (
            "Strengthen ML evidence by adding model evaluation metrics, "
            "a training script, or a notebook with results."
        ),
    },
    {
        "category": "llm_agent",
        "patterns": [
            "langchain", "openai", "rag", "llm", "gpt", "llama",
            "autogen", "crewai",
        ],
        "tip_missing": (
            "Show a prompt→response flow. "
            "Add agent or RAG pipeline code to your GitHub repository."
        ),
        "tip_partial": (
            "Add the agent/RAG code, chain definition, or sample prompt-response "
            "pairs to your GitHub repository."
        ),
    },
    {
        "category": "frontend_framework",
        "patterns": [
            "react", "vue", "angular", "next.js", "nextjs",
            "svelte", "nuxt", "remix",
        ],
        "tip_missing": (
            "Show multi-view navigation in your recording. "
            "Add package.json and component files to your GitHub repository."
        ),
        "tip_partial": (
            "Add component source files and package.json to your GitHub repository "
            "to confirm the frontend framework used."
        ),
    },
    {
        "category": "ts_js",
        "patterns": ["typescript", "javascript"],
        "tip_missing": "Add source files to a public GitHub repository.",
        "tip_partial": "Add TypeScript/JavaScript source files to GitHub to confirm usage.",
    },
    {
        "category": "containers",
        "patterns": ["docker", "kubernetes", "k8s", "helm", "container"],
        "tip_missing": (
            "Add a Dockerfile, docker-compose.yml, or Kubernetes manifests "
            "to your GitHub repository."
        ),
        "tip_partial": (
            "Add container configuration files (Dockerfile, compose, or K8s manifests) "
            "to GitHub."
        ),
    },
    {
        "category": "cicd",
        "patterns": [
            "github actions", "circleci", "gitlab ci", "jenkins",
            "travis", "ci/cd", "pipeline",
        ],
        "tip_missing": (
            "Add CI/CD workflow configuration files to your GitHub repository "
            "(e.g., .github/workflows/)."
        ),
        "tip_partial": "Add or expand your CI/CD workflow configuration files in GitHub.",
    },
    {
        "category": "deployment_paas",
        "patterns": ["vercel", "heroku", "netlify", "render", "railway", "fly.io"],
        "tip_missing": (
            "A live URL helps confirm deployment. "
            "Add a deployment README section or config file to GitHub."
        ),
        "tip_partial": (
            "Add a deployment README section or deployment config file "
            "to strengthen evidence."
        ),
    },
    {
        "category": "cloud_platform",
        "patterns": ["aws", "gcp", "azure", "google cloud", "amazon web services"],
        "tip_missing": (
            "Add IaC files, deployment scripts, or cloud architecture documentation "
            "to your GitHub repository."
        ),
        "tip_partial": (
            "Add cloud config files (Terraform, CloudFormation, or deployment docs) "
            "to GitHub."
        ),
    },
    {
        "category": "api_design",
        "patterns": ["rest", "graphql", "swagger", "openapi"],
        "tip_missing": (
            "Show a Swagger/OpenAPI UI in your recording or add API route definitions "
            "to your GitHub repository."
        ),
        "tip_partial": (
            "Add API schema files (OpenAPI spec, route definitions) "
            "to your GitHub repository."
        ),
    },
    {
        "category": "maps_geo",
        "patterns": [
            "google maps", "mapbox", "leaflet", "geo", "geospatial", "mapping",
        ],
        "tip_missing": (
            "Show map interactions in your recording and add the map API integration "
            "source code to GitHub."
        ),
        "tip_partial": (
            "Add the map integration source code showing API usage "
            "to your GitHub repository."
        ),
    },
    {
        "category": "database",
        "patterns": [
            "postgresql", "postgres", "mysql", "mongodb", "redis", "sqlite",
            "prisma", "sqlalchemy", "typeorm", "orm",
        ],
        "tip_missing": (
            "Databases aren't visible in the browser. "
            "Add schema files, migrations, or ORM model definitions "
            "to your GitHub repository."
        ),
        "tip_partial": (
            "Add database schema, migration files, or ORM models to GitHub "
            "to confirm database usage."
        ),
    },
    {
        "category": "data_science",
        "patterns": [
            "pandas", "numpy", "matplotlib", "seaborn", "jupyter",
            "data analysis", "scipy",
        ],
        "tip_missing": (
            "Show data analysis results in your recording and add a notebook "
            "or data pipeline script to GitHub."
        ),
        "tip_partial": (
            "Add a Jupyter notebook or data pipeline script with analysis results "
            "to your GitHub repository."
        ),
    },
    {
        "category": "programming_language",
        "patterns": [
            "python", "java", "golang", "rust", "c++", "c#", "kotlin",
            "swift", "ruby", "php",
        ],
        "tip_missing": (
            "Add a public GitHub repository with source code to confirm this language is used."
        ),
        "tip_partial": "Add more source files in this language to your GitHub repository.",
    },
]


def _detect_skill_tip(
    skill: str,
    status: Literal["partial", "missing"],
    *,
    has_github: bool,
) -> dict[str, Any]:
    """
    Return a skill-improvement tip dict for the given skill and status.

    Parameters
    ----------
    skill      : claimed skill name (original case)
    status     : "partial" | "missing"
    has_github : True if the student already has a GitHub repo linked
                 (even if the analysis failed).  Softens the
                 "add to GitHub" language.
    """
    lc = skill.lower()
    for entry in _SKILL_TIPS:
        if any(p in lc for p in entry["patterns"]):
            if status == "partial":
                tip = entry["tip_partial"]
            elif has_github:
                # Student already has GitHub — use the gentler partial tip
                tip = entry["tip_partial"]
            else:
                tip = entry["tip_missing"]
            return {
                "skill": skill,
                "status": status,
                "category": entry["category"],
                "tip": tip,
            }
    # Generic fallback for unrecognised skills
    return {
        "skill": skill,
        "status": status,
        "category": "general",
        "tip": (
            "Show this skill explicitly in your recording and add supporting "
            "code to a public GitHub repository."
        ),
    }


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class VerificationReadinessResult:
    proof_session_id: str
    readiness_score: int
    readiness_level: ReadinessLevel
    final_verification_status: FinalVerificationStatus
    strongly_supported_skills: list[str] = field(default_factory=list)
    partially_supported_skills: list[str] = field(default_factory=list)
    needs_more_evidence: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    recommended_next_actions: list[str] = field(default_factory=list)
    recruiter_summary: str = ""
    is_local_only: bool = False
    has_github_evidence: bool = False
    computed_at: str = ""
    # ── Personalized recommendations ──────────────────────────────────────
    score_contributors: list[dict[str, Any]] = field(default_factory=list)
    #: Each contributor: {"label": str, "points": int, "type": "positive"|"negative"|"info"}
    #: positive → earned points, negative → deductions, info → potential (not yet earned)
    score_explanation: list[str] = field(default_factory=list)
    #: Human-readable sentences explaining why the score is what it is.
    skill_improvement_tips: list[dict[str, Any]] = field(default_factory=list)
    #: Each tip: {"skill": str, "status": "partial"|"missing", "category": str, "tip": str}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _level(score: int) -> ReadinessLevel:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "moderate"
    if score >= 40:
        return "weak"
    return "insufficient"


def _deduplicate(lst: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ── Core computation (pure — no DB dependency) ────────────────────────────────

def compute_readiness_report(
    *,
    proof_session_id: str,
    session_status: str,
    url_type: str | None = None,
    website_url: str = "",
    claimed_skills: list[str] | None = None,
    workflow_analysis: dict[str, Any] | None = None,
    live_check: dict[str, Any] | None = None,
    github_analysis: dict[str, Any] | None = None,
    privacy_scan: dict[str, Any] | None = None,
) -> VerificationReadinessResult:
    """
    Compute a readiness score (0–100) and full report from all available evidence.

    Parameters
    ----------
    url_type:
        Pre-classified URL type; derived from website_url if not supplied.
    claimed_skills:
        Skills the student claims — extracted from the session row.
    workflow_analysis, live_check, github_analysis, privacy_scan:
        Stored evidence rows (plain dicts).  Pass None for any not yet run.
    """
    if url_type is None:
        url_type = _classify_url(website_url)
    if claimed_skills is None:
        claimed_skills = []

    is_local = url_type in ("localhost_url", "local_network_url")
    session_uploaded = session_status in (
        "uploaded_pending_analysis", "analyzing", "completed"
    )

    score = 0
    risk_flags: list[str] = []
    needs_more_evidence: list[str] = []
    next_actions: list[str] = []
    contributors: list[dict[str, Any]] = []
    explanation: list[str] = []

    # ── Positive contributions ─────────────────────────────────────────────

    # +15  workflow evidence uploaded
    if session_uploaded:
        score += 15
        contributors.append({"label": "Workflow recording uploaded", "points": 15, "type": "positive"})
        explanation.append("Workflow evidence was uploaded.")
    else:
        contributors.append({"label": "Workflow recording not yet uploaded", "points": 15, "type": "info"})

    # +15  workflow analysis complete
    has_wf = workflow_analysis is not None
    if has_wf:
        score += 15
        contributors.append({"label": "Workflow evidence AI-reviewed", "points": 15, "type": "positive"})
        explanation.append("Workflow analysis is complete.")
    elif session_uploaded:
        contributors.append({"label": "Workflow evidence not yet AI-reviewed", "points": 15, "type": "info"})

    # +15  GitHub evidence AI reviewed (only if a URL was provided)
    github_provided = github_analysis is not None
    github_ok = github_provided and github_analysis.get("status") == "success"  # type: ignore[union-attr]

    if github_ok:
        score += 15
        contributors.append({"label": "GitHub evidence AI-reviewed", "points": 15, "type": "positive"})
        explanation.append("GitHub repository was analysed successfully.")
    elif github_provided and not github_ok:
        risk_flags.append("GitHub repository could not be accessed or is private")
        explanation.append("GitHub repository could not be accessed.")
    elif session_uploaded:
        contributors.append({"label": "No GitHub repository linked", "points": 15, "type": "info"})

    # +15  live website check complete and reachable (deployed URLs only)
    live_ok = (
        not is_local
        and live_check is not None
        and live_check.get("is_reachable") is True
    )
    if live_ok:
        score += 15
        contributors.append({"label": "Deployed website is publicly reachable", "points": 15, "type": "positive"})
        explanation.append("Deployed website is publicly accessible.")
    elif is_local:
        contributors.append({"label": "Live check not applicable (local-only project)", "points": 0, "type": "info"})
    elif not is_local and live_check is not None and not live_check.get("is_reachable"):
        risk_flags.append("Deployed website is not publicly accessible")
        explanation.append("Deployed website could not be confirmed as publicly accessible.")
    elif not is_local and live_check is None and session_uploaded:
        contributors.append({"label": "Live website check not yet run", "points": 15, "type": "info"})

    # +10  privacy scan clean or redacted (not flagged)
    privacy_status: str | None = (privacy_scan or {}).get("status")
    if privacy_status in ("clean", "redacted"):
        score += 10
        label = "Privacy scan passed with redactions applied" if privacy_status == "redacted" else "Privacy scan is clean"
        contributors.append({"label": label, "points": 10, "type": "positive"})
        explanation.append(f"{label}.")
    elif privacy_status == "flagged":
        risk_flags.append("Privacy scan flagged — potential sensitive data in recording")
        explanation.append("Privacy scan flagged sensitive data — score will be capped at Weak.")
    elif session_uploaded:
        contributors.append({"label": "Privacy scan not yet run", "points": 10, "type": "info"})

    # ── Skill support analysis ─────────────────────────────────────────────

    wf_supported: list[str] = (workflow_analysis or {}).get("supported_skills", [])
    wf_weakly:    list[str] = (workflow_analysis or {}).get("weakly_supported_skills", [])
    gh_matched:   list[str] = (github_analysis or {}).get("matched_claimed_skills", []) if github_ok else []
    gh_weakly:    list[str] = (github_analysis or {}).get("weakly_matched_claimed_skills", []) if github_ok else []

    wf_supported_lc = {s.lower() for s in wf_supported}
    wf_weakly_lc    = {s.lower() for s in wf_weakly}
    gh_matched_lc   = {s.lower() for s in gh_matched}
    gh_weakly_lc    = {s.lower() for s in gh_weakly}

    strongly: list[str] = []
    partially: list[str] = []

    for skill in claimed_skills:
        lc = skill.lower()
        if lc in wf_supported_lc or lc in gh_matched_lc:
            strongly.append(skill)
        elif lc in wf_weakly_lc or lc in gh_weakly_lc:
            partially.append(skill)
        else:
            needs_more_evidence.append(f"{skill} — no strong evidence detected")

    # +15  at least one skill strongly supported
    if strongly:
        score += 15
        contributors.append({
            "label": f"Strong skill support ({len(strongly)} skill(s) confirmed)",
            "points": 15,
            "type": "positive",
        })
        skill_names = ", ".join(strongly[:3]) + (" …" if len(strongly) > 3 else "")
        explanation.append(
            f"{len(strongly)} claimed skill(s) strongly supported by evidence: {skill_names}."
        )
    else:
        score = max(0, score - 10)  # -10  no strong skill support
        contributors.append({"label": "No claimed skills with strong support", "points": -10, "type": "negative"})
        explanation.append("No claimed skills have strong evidence support.")

    if partially:
        explanation.append(
            f"{len(partially)} claimed skill(s) have partial evidence support."
        )

    unsupported_skills: list[str] = [
        s for s in claimed_skills
        if s not in strongly and s not in partially
    ]
    if unsupported_skills:
        explanation.append(
            f"{len(unsupported_skills)} claimed skill(s) have no supporting evidence yet."
        )

    # +10  multiple evidence sources confirm the same skill (cross-evidence)
    cross_confirmed = {
        s.lower() for s in strongly
        if s.lower() in wf_supported_lc and s.lower() in gh_matched_lc
    }
    if cross_confirmed:
        score += 10
        contributors.append({
            "label": f"Cross-evidence confirmation ({len(cross_confirmed)} skill(s) in workflow + GitHub)",
            "points": 10,
            "type": "positive",
        })
        explanation.append(
            f"{len(cross_confirmed)} skill(s) confirmed in both workflow and GitHub evidence."
        )

    # +5   a meaningful recruiter summary exists (from any analysis)
    recruiter_text = (
        (workflow_analysis or {}).get("recruiter_summary", "")
        or (github_analysis or {}).get("recruiter_summary", "")
    )
    if recruiter_text and len(recruiter_text.strip()) > 30:
        score += 5
        contributors.append({"label": "Meaningful recruiter summary present", "points": 5, "type": "positive"})

    # ── Deductions ─────────────────────────────────────────────────────────

    # -10  short / brief recording
    wf_risk_flags: list[str] = (workflow_analysis or {}).get("risk_flags", [])
    short_recording = any(
        any(kw in f.lower() for kw in ("short", "brief", "too short"))
        for f in wf_risk_flags
    )
    if short_recording:
        score = max(0, score - 10)
        contributors.append({"label": "Recording is brief", "points": -10, "type": "negative"})
        risk_flags.append("Recording is brief — a longer walkthrough would strengthen evidence")
        explanation.append("Recording was brief, which lowered confidence.")

    # -15  privacy flagged
    if privacy_status == "flagged":
        score = max(0, score - 15)
        contributors.append({"label": "Privacy scan flagged sensitive data", "points": -15, "type": "negative"})

    # -5 per missing evidence item (capped at -15)
    wf_missing: list[str] = (workflow_analysis or {}).get("missing_evidence", [])
    if wf_missing:
        missing_penalty = min(len(wf_missing) * 5, 15)
        score = max(0, score - missing_penalty)
        contributors.append({
            "label": f"Missing evidence items ({len(wf_missing)} item(s) flagged)",
            "points": -missing_penalty,
            "type": "negative",
        })
        explanation.append(
            f"{len(wf_missing)} evidence item(s) flagged as missing from the workflow analysis."
        )
    for item in wf_missing:
        needs_more_evidence.append(item)

    # -10  broken live site (deployed URLs only)
    if not is_local and live_check is not None and not live_check.get("is_reachable"):
        score = max(0, score - 10)
        contributors.append({"label": "Deployed website not publicly accessible", "points": -10, "type": "negative"})

    # -10  GitHub provided but inaccessible
    if github_provided and not github_ok:
        score = max(0, score - 10)
        contributors.append({"label": "GitHub repository inaccessible", "points": -10, "type": "negative"})

    # ── Privacy-flagged cap: cannot exceed Weak (max 59) ──────────────────
    if privacy_status == "flagged":
        score = min(score, 59)

    score = max(0, min(100, score))

    # ── Level + Final Verification status ─────────────────────────────────
    level = _level(score)

    # INVARIANT: "complete" is NEVER returned from this function.
    fv_status: FinalVerificationStatus = (
        "ready_for_review"
        if score >= 80 and privacy_status != "flagged"
        else "pending"
    )

    # ── Skill improvement tips ─────────────────────────────────────────────
    skill_improvement_tips: list[dict[str, Any]] = []
    for skill in partially:
        skill_improvement_tips.append(
            _detect_skill_tip(skill, "partial", has_github=bool(github_provided))
        )
    for skill in unsupported_skills:
        skill_improvement_tips.append(
            _detect_skill_tip(skill, "missing", has_github=bool(github_provided))
        )

    # ── Recommended next actions ───────────────────────────────────────────

    if not session_uploaded:
        next_actions.append("Upload your workflow recording to begin evidence analysis.")

    if session_uploaded and not has_wf:
        next_actions.append(
            "Run Workflow Evidence Analysis to get an AI review of your recording."
        )

    if privacy_status == "flagged":
        next_actions.append(
            "Re-record the workflow using demo accounts and sample data. "
            "Avoid passwords, API keys, tokens, and personal information."
        )

    if short_recording:
        next_actions.append(
            "Record a longer 2–3 minute walkthrough showing the main feature "
            "from input to output end-to-end."
        )

    if not is_local and live_check is None and session_uploaded:
        next_actions.append(
            "Run the Live Website Check to confirm your deployed site is publicly accessible."
        )

    if not is_local and live_check is not None and not live_check.get("is_reachable"):
        next_actions.append(
            "Confirm the deployed app is running and publicly reachable, "
            "then re-run the Live Website Check."
        )

    if not github_provided and session_uploaded:
        next_actions.append(
            "Add a public GitHub repository URL and run GitHub Evidence Analysis "
            "to provide code-level proof of your work."
        )

    if github_provided and not github_ok:
        next_actions.append(
            "Make the GitHub repository public or verify the repository URL, "
            "then re-run GitHub Evidence Analysis."
        )

    if github_ok:
        detected_features: list[str] = github_analysis.get("detected_features", [])  # type: ignore[union-attr]
        if "readme" not in detected_features:
            next_actions.append(
                "Add a README with a project overview, setup instructions, "
                "and usage examples."
            )
        if "deployment" not in detected_features and not is_local:
            next_actions.append(
                "Add deployment configuration or documentation to your repository."
            )

    # Skill-specific next actions from improvement tips
    for tip_entry in skill_improvement_tips:
        next_actions.append(f"{tip_entry['skill']}: {tip_entry['tip']}")

    if has_wf and (workflow_analysis or {}).get("human_review_needed"):
        next_actions.append(
            "Request a faculty or human review — AI confidence is low for this recording."
        )

    # ── Overall recruiter summary ──────────────────────────────────────────

    sources: list[str] = []
    if session_uploaded:
        sources.append("workflow recording")
    if live_ok:
        sources.append("live website confirmation")
    if github_ok:
        sources.append("GitHub repository analysis")

    def _join(lst: list[str]) -> str:
        if len(lst) == 0:
            return ""
        if len(lst) == 1:
            return lst[0]
        if len(lst) == 2:
            return f"{lst[0]} and {lst[1]}"
        return ", ".join(lst[:-1]) + f", and {lst[-1]}"

    if not sources or not has_wf:
        summary = (
            "Insufficient evidence has been submitted for recruiter review. "
            "Complete the workflow analysis and available evidence steps."
        )
    elif level == "strong":
        summary = (
            f"This evidence package is strongly ready for recruiter review. "
            f"The {_join(sources)} support the claimed skills with high confidence."
        )
    elif level == "moderate":
        skill_note = (
            f" {len(strongly)} skill(s) have strong support"
            + (f" and {len(partially)} have partial evidence" if partially else "")
            + "."
        ) if strongly else ""
        summary = (
            f"This evidence package is moderately ready for recruiter review. "
            f"The {_join(sources)} support several claimed skills, "
            f"but some still need clearer evidence.{skill_note}"
        )
    elif level == "weak":
        summary = (
            "This evidence package is partially assembled. "
            "Some evidence steps are incomplete. "
            "Follow the recommended next actions to improve readiness."
        )
    else:
        summary = (
            "Insufficient evidence to support recruiter review. "
            "Upload a recording, run the available analyses, and confirm "
            "site accessibility."
        )

    return VerificationReadinessResult(
        proof_session_id=proof_session_id,
        readiness_score=score,
        readiness_level=level,
        final_verification_status=fv_status,
        strongly_supported_skills=strongly,
        partially_supported_skills=partially,
        needs_more_evidence=_deduplicate(needs_more_evidence),
        risk_flags=_deduplicate(risk_flags),
        recommended_next_actions=_deduplicate(next_actions),
        recruiter_summary=summary,
        is_local_only=is_local,
        has_github_evidence=bool(github_ok),
        computed_at=datetime.now(UTC).isoformat(),
        score_contributors=contributors,
        score_explanation=explanation,
        skill_improvement_tips=skill_improvement_tips,
    )
