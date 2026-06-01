"""Live Proof Feedback Engine.

Pure function — no DB, no Qwen, no external calls.
Takes lightweight live signals from the recording session and returns:
  - evidence checklist
  - live score (0–100)
  - per-skill support status
  - up to 3 actionable suggestions
  - sensitive_warning flag

Skill categories are reusable and project-agnostic — not hardcoded to TensorFlow,
p5.js, or Gapminder. The engine matches on semantic categories (code, data
visualization, ML/model, GitHub/open-source, document, media, etc.).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.schemas.live_feedback import (
    EvidenceChecklist,
    LiveFeedbackState,
    LiveSignalsInput,
    SkillSupport,
    SupportLevel,
)

# ── Skill category patterns ───────────────────────────────────────────────────
# Maps category → regex that matches claimed skill names (case-insensitive).
# Order matters — first match wins per skill.

_SKILL_CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("github_open_source", re.compile(
        r"\b(open[\s_-]?source|github|repository|repo|git)\b", re.IGNORECASE
    )),
    ("data_visualization", re.compile(
        r"\b(data[\s_-]?vis(ualization)?|chart|dashboard|plot(ting)?|graph(ing)?|"
        r"d3|vega|plotly|tableau|observable|matplotlib|seaborn|bokeh|"
        r"bi|business[\s_-]?intelligence|analytics[\s_-]?dashboard)\b", re.IGNORECASE
    )),
    ("ml_ai", re.compile(
        r"\b(machine[\s_-]?learning|ml|deep[\s_-]?learning|ai|"
        r"tensorflow|pytorch|keras|scikit|sklearn|model|neural|nlp|"
        r"computer[\s_-]?vision|object[\s_-]?detection|classification|"
        r"regression|clustering|transformer|llm|generative)\b", re.IGNORECASE
    )),
    ("code_software", re.compile(
        r"\b(javascript|typescript|python|java|c\+\+|c#|go|rust|ruby|php|swift|kotlin|"
        r"coding|programming|software|algorithm|api|backend|frontend|fullstack|"
        r"react|vue|angular|next\.?js|node|django|flask|fastapi|spring|rails|"
        r"html|css|web[\s_-]?dev(elopment)?)\b", re.IGNORECASE
    )),
    ("document_pdf", re.compile(
        r"\b(document|pdf|report|spreadsheet|excel|word|presentation|slide)\b",
        re.IGNORECASE
    )),
    ("video_media", re.compile(
        r"\b(video|audio|media|stream(ing)?|player|recording)\b", re.IGNORECASE
    )),
    ("engineering_design", re.compile(
        r"\b(cad|solidworks|autocad|fusion|design|mechanical|electrical|"
        r"circuit|schematic|simulation|finite[\s_-]?element|ansys|matlab)\b",
        re.IGNORECASE
    )),
    ("business_finance", re.compile(
        r"\b(finance|financial|accounting|trading|portfolio|stock|investment|"
        r"economics|budget|forecast|erp|crm|salesforce)\b", re.IGNORECASE
    )),
]

# ── Text-based evidence patterns ──────────────────────────────────────────────

_RESULT_RE = re.compile(
    r"\b(prediction|result|output|score|confidence|probability|risk|"
    r"detected|label|class|summary|answer|response|route|recommendation|"
    r"generated|analysis|accuracy|precision|recall|f1|loss|error|"
    r"total|count|mean|average|percentage|trend)\b",
    re.IGNORECASE,
)

_CHART_TEXT_RE = re.compile(
    r"\b(chart|graph|plot|axis|legend|tooltip|bar|line|pie|scatter|"
    r"histogram|heatmap|treemap|sunburst|choropleth|dashboard)\b",
    re.IGNORECASE,
)

_CODE_TEXT_RE = re.compile(
    r"\b(def |class |function |import |require|const |let |var |"
    r"return |if\s*\(|for\s*\(|while\s*\(|console\.log|print\(|"
    r"github\.com|commit|branch|pull[\s_-]?request|\.py|\.js|\.ts|\.java)\b",
    re.IGNORECASE,
)

_GITHUB_URL_RE = re.compile(r"github\.com/[\w\-]+/[\w\-]", re.IGNORECASE)


# ── Checklist computation ─────────────────────────────────────────────────────

def _build_checklist(sig: LiveSignalsInput) -> EvidenceChecklist:
    url_lower = sig.current_url.lower()
    all_text = " ".join(sig.dom_text_snippets)

    website_loaded = bool(sig.current_url and not url_lower.startswith("chrome://"))
    dom_text_seen = len(sig.dom_text_snippets) > 0
    interaction_seen = sig.click_count > 0
    form_input_seen = sig.input_count > 0 or sig.form_submit_count > 0
    output_or_result_seen = sig.output_block_count > 0 or bool(_RESULT_RE.search(all_text))
    chart_or_visual_seen = (
        sig.canvas_count > 0
        or sig.svg_count > 0
        or bool(_CHART_TEXT_RE.search(all_text))
    )
    code_or_repo_seen = bool(_CODE_TEXT_RE.search(all_text))
    github_seen = sig.github_url_seen or bool(_GITHUB_URL_RE.search(url_lower))

    return EvidenceChecklist(
        website_loaded=website_loaded,
        dom_text_seen=dom_text_seen,
        interaction_seen=interaction_seen,
        form_input_seen=form_input_seen,
        output_or_result_seen=output_or_result_seen,
        chart_or_visual_seen=chart_or_visual_seen,
        code_or_repo_seen=code_or_repo_seen,
        github_seen=github_seen,
        sensitive_warning=sig.sensitive_warning_seen,
    )


# ── Score computation ─────────────────────────────────────────────────────────

_SCORE_WEIGHTS = {
    "website_loaded":       15,
    "dom_text_seen":        15,
    "interaction_seen":     15,
    "form_input_seen":      10,
    "output_or_result_seen": 15,
    "chart_or_visual_seen": 10,
    "code_or_repo_seen":    10,
    "github_seen":          10,
}


def _compute_score(c: EvidenceChecklist) -> int:
    total = sum(
        weight
        for field, weight in _SCORE_WEIGHTS.items()
        if getattr(c, field, False)
    )
    return min(total, 100)


# ── Skill support computation ─────────────────────────────────────────────────

def _classify_skill(skill: str) -> str:
    for category, pattern in _SKILL_CATEGORIES:
        if pattern.search(skill):
            return category
    return "generic"


def _skill_support(skill: str, c: EvidenceChecklist) -> SkillSupport:
    category = _classify_skill(skill)

    level: SupportLevel
    evidence_source: str
    short_reason: str

    if category == "github_open_source":
        if c.github_seen:
            level, evidence_source = "likely", "github_url"
            short_reason = "GitHub URL visited — repository evidence captured"
        elif c.code_or_repo_seen:
            level, evidence_source = "partial", "code_text"
            short_reason = "Code text seen — visit GitHub for stronger evidence"
        else:
            level, evidence_source = "missing", "none"
            short_reason = "No GitHub URL or code seen yet"

    elif category == "data_visualization":
        if c.chart_or_visual_seen and c.interaction_seen:
            level, evidence_source = "likely", "chart_and_interaction"
            short_reason = "Chart/visual detected and interaction recorded"
        elif c.chart_or_visual_seen:
            level, evidence_source = "partial", "chart_seen"
            short_reason = "Chart/visual detected — interact with a control for stronger evidence"
        elif c.output_or_result_seen:
            level, evidence_source = "partial", "output_text"
            short_reason = "Output text seen — show the chart clearly"
        else:
            level, evidence_source = "missing", "none"
            short_reason = "No chart, canvas, or visualization detected yet"

    elif category == "ml_ai":
        if c.output_or_result_seen and c.interaction_seen:
            level, evidence_source = "likely", "result_and_interaction"
            short_reason = "Result/output detected with user interaction"
        elif c.output_or_result_seen:
            level, evidence_source = "partial", "result_text"
            short_reason = "Result text seen — interact with the model for stronger evidence"
        else:
            level, evidence_source = "missing", "none"
            short_reason = "No model output or prediction result detected yet"

    elif category == "code_software":
        if c.code_or_repo_seen and c.interaction_seen:
            level, evidence_source = "likely", "code_and_interaction"
            short_reason = "Code text seen with user interaction"
        elif c.github_seen:
            level, evidence_source = "likely", "github"
            short_reason = "GitHub repository evidence captured"
        elif c.code_or_repo_seen:
            level, evidence_source = "partial", "code_text"
            short_reason = "Code text seen — show more code or add GitHub URL"
        elif c.interaction_seen and c.output_or_result_seen:
            level, evidence_source = "partial", "app_interaction"
            short_reason = "App interaction and output seen — show code for stronger evidence"
        else:
            level, evidence_source = "missing", "none"
            short_reason = "No code, GitHub, or running app output detected yet"

    else:  # generic, document, media, engineering, business
        if c.interaction_seen and c.output_or_result_seen:
            level, evidence_source = "likely", "interaction_and_output"
            short_reason = "App interaction and output captured"
        elif c.interaction_seen:
            level, evidence_source = "partial", "interaction"
            short_reason = "Interaction seen — show the result/output clearly"
        elif c.dom_text_seen:
            level, evidence_source = "partial", "dom_text"
            short_reason = "Page text captured — interact with the app"
        else:
            level, evidence_source = "missing", "none"
            short_reason = "No app interaction detected yet"

    return SkillSupport(
        skill=skill,
        support_level=level,
        evidence_source=evidence_source,
        short_reason=short_reason,
    )


# ── Suggestion computation ────────────────────────────────────────────────────

def _build_suggestions(
    sig: LiveSignalsInput,
    c: EvidenceChecklist,
    skill_supports: list[SkillSupport],
) -> list[str]:
    suggestions: list[str] = []

    # Privacy is always first and most urgent
    if c.sensitive_warning:
        suggestions.append(
            "Avoid showing API keys, tokens, passwords, SSNs, or payment info."
        )

    if len(suggestions) >= 3:
        return suggestions[:3]

    # Missing output is the most common gap
    if not c.output_or_result_seen and c.interaction_seen:
        suggestions.append("Show the result or output area clearly after running the app.")

    if len(suggestions) >= 3:
        return suggestions[:3]

    # No interaction yet
    if not c.interaction_seen and c.website_loaded:
        suggestions.append("Good start. Now interact with the app — click a control or run a task.")

    if len(suggestions) >= 3:
        return suggestions[:3]

    # Skill-specific gaps (pick the first missing one)
    for support in skill_supports:
        if support.support_level == "missing":
            cat = _classify_skill(support.skill)
            if cat == "github_open_source":
                suggestions.append(
                    f"For '{support.skill}': visit your GitHub repository or provide a repo URL."
                )
            elif cat == "data_visualization":
                suggestions.append(
                    f"For '{support.skill}': show the chart or visualization clearly and interact with one control."
                )
            elif cat == "ml_ai":
                suggestions.append(
                    f"For '{support.skill}': run the model and show the prediction or output clearly."
                )
            elif cat == "code_software":
                suggestions.append(
                    f"For '{support.skill}': show code in the browser or add a GitHub repository URL."
                )
            else:
                suggestions.append(
                    f"For '{support.skill}': interact with the app and show its output."
                )
            if len(suggestions) >= 3:
                break

    if len(suggestions) >= 3:
        return suggestions[:3]

    # Partial skill gaps
    for support in skill_supports:
        if support.support_level == "partial":
            cat = _classify_skill(support.skill)
            if cat == "data_visualization" and not c.github_seen:
                suggestions.append(
                    f"For '{support.skill}': add a GitHub or code repository link for stronger evidence."
                )
            elif cat == "code_software" and not c.github_seen:
                suggestions.append(
                    f"For '{support.skill}': visit GitHub to add repository evidence."
                )
            elif cat == "ml_ai" and not c.interaction_seen:
                suggestions.append(
                    f"For '{support.skill}': interact with the model (upload data, run inference)."
                )
            if len(suggestions) >= 3:
                break

    # Default encouragement if nothing specific
    if not suggestions and c.interaction_seen and c.output_or_result_seen:
        suggestions.append("Good evidence captured! Consider showing more of the app's output.")

    return suggestions[:3]


# ── Main entry point ──────────────────────────────────────────────────────────

def compute_live_feedback(session_id: str, sig: LiveSignalsInput) -> LiveFeedbackState:
    """Compute live proof feedback from lightweight recording signals.

    Pure function — no I/O, no external calls, deterministic.
    """
    checklist = _build_checklist(sig)
    score = _compute_score(checklist)
    skill_supports = [_skill_support(s, checklist) for s in sig.claimed_skills]
    suggestions = _build_suggestions(sig, checklist, skill_supports)

    return LiveFeedbackState(
        session_id=session_id,
        recording_status="recording",
        checklist=checklist,
        live_score=score,
        claimed_skill_support=skill_supports,
        suggestions=suggestions,
        sensitive_warning=checklist.sensitive_warning,
        last_updated_at=datetime.now(timezone.utc),
    )
