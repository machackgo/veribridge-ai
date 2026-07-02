"""Website semantic proof intelligence — deterministic, recruiter-honest labels.

The GitHub Smart-Evidence layer explains WHAT a code block does
(``code_block_purpose_*``) and HOW it relates to the report's selected skill
(``skill_relevance_*``). This module is the Website Proof counterpart: from the
ALREADY-SAFE Website Proof summaries the pipeline persisted (the sanitized
workflow narrative, demonstrated workflow steps, DOM/OCR/visual summaries and
the live reachability check — see ``website_proof_detail_service``), it derives:

* ``website_purpose_*``   — what the recorded page/app demonstrably showed
  (a chat interface, a prediction/result display, an interactive form flow,
  a dashboard, a landing page, plain deployed availability, …), from a CLOSED
  vocabulary — never stored free text;
* ``website_skill_relevance_*`` — how that observed behaviour relates to the
  report's SELECTED skill (recomputed per report, never trusted from storage):
  direct/supporting Frontend evidence, ML/GenAI *product behaviour context*
  (never implementation proof), API-backed behaviour context, conservative
  deployment availability, …;
* an honest per-relevance ``website_limitation`` (a website UI never proves
  source-code authorship, model training, LLM/RAG internals, or CI/CD
  internals by itself);
* a chain "connection note" explaining how Website Proof corroborates the
  other sources ("the website demonstrates the product behaviour, GitHub code
  shows the implementation, the Project Defense shows personal understanding").

Security / honesty invariants:
  - Pure regex/structural classification over already-sanitized summary text.
    NO LLM calls, NO network calls, NO DB reads, NO render-time crawling.
  - Every emitted label/summary comes from the closed vocabularies below —
    raw DOM/OCR/provider text can never ride out through a purpose label.
  - Website evidence NEVER claims implementation proof for ML / GenAI /
    DevOps-style skills: those families are always labelled *product
    behaviour / availability context* so a demo UI can never overclaim.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from app.services.github_skill_evidence_service import is_ml_skill, skill_profile
from app.services.safe_public_url import is_safe_public_url

__all__ = [
    "ALLOWED_WEBSITE_EVIDENCE_CHIPS",
    "ALLOWED_WEBSITE_PURPOSE_KEYS",
    "ALLOWED_WEBSITE_RELEVANCE_KEYS",
    "SCREENSHOT_ACCESS_PERMISSION_REQUIRED",
    "SCREENSHOT_ACCESS_UNAVAILABLE",
    "attach_website_corroboration",
    "build_website_evidence_card",
    "classify_website_purpose",
    "classify_website_skill_relevance",
    "derive_website_evidence_chips",
    "describe_website_purpose",
    "describe_website_skill_relevance",
    "is_direct_website_relevance",
    "public_screenshot_access_label",
    "website_behavior_claim",
    "website_chain_connection_note",
    "website_corroboration_note",
    "website_limitation_for",
    "website_purpose_summary",
    "website_skill_relevance_summary",
]


# ── Closed website-purpose vocabulary ─────────────────────────────────────────

PURPOSE_CHAT_PROMPT = "chat_prompt_interface"
PURPOSE_GENERATED_RESPONSE = "generated_response_display"
PURPOSE_PREDICTION_RESULT = "prediction_result_display"
PURPOSE_FILE_UPLOAD = "file_upload_flow"
PURPOSE_AUTHENTICATION = "authentication_screen"
PURPOSE_SEARCH_RETRIEVAL = "search_retrieval_interface"
PURPOSE_DATA_VISUALIZATION = "data_visualization"
PURPOSE_DASHBOARD = "dashboard_view"
PURPOSE_DATA_TABLE = "data_table_view"
PURPOSE_API_INTERACTION = "api_backed_interaction"
PURPOSE_INTERACTIVE_FORM = "interactive_form_flow"
PURPOSE_ERROR_LOADING = "error_loading_state"
PURPOSE_DOCUMENTATION = "documentation_static"
PURPOSE_NAVIGATION_LAYOUT = "navigation_layout"
PURPOSE_LANDING_OVERVIEW = "landing_overview"
PURPOSE_DEPLOYED_AVAILABILITY = "deployed_availability"
PURPOSE_UNKNOWN = "unknown_needs_review"

_PURPOSE_LABELS: dict[str, str] = {
    PURPOSE_CHAT_PROMPT: "Chat / prompt interface",
    PURPOSE_GENERATED_RESPONSE: "Generated response display",
    PURPOSE_PREDICTION_RESULT: "Prediction / result display",
    PURPOSE_FILE_UPLOAD: "File upload flow",
    PURPOSE_AUTHENTICATION: "Authentication screen",
    PURPOSE_SEARCH_RETRIEVAL: "Search / retrieval interface",
    PURPOSE_DATA_VISUALIZATION: "Data visualization / chart",
    PURPOSE_DASHBOARD: "Dashboard view",
    PURPOSE_DATA_TABLE: "Data table / list view",
    PURPOSE_API_INTERACTION: "API-backed interaction",
    PURPOSE_INTERACTIVE_FORM: "Interactive form flow",
    PURPOSE_ERROR_LOADING: "Error / loading state",
    PURPOSE_DOCUMENTATION: "Documentation / static page",
    PURPOSE_NAVIGATION_LAYOUT: "Navigation / page layout",
    PURPOSE_LANDING_OVERVIEW: "Landing page / product overview",
    PURPOSE_DEPLOYED_AVAILABILITY: "Deployed application availability",
    PURPOSE_UNKNOWN: "Unknown / needs review",
}

_PURPOSE_SUMMARIES: dict[str, str] = {
    PURPOSE_CHAT_PROMPT: (
        "The recorded session shows a chat/prompt-style interface where a message "
        "was entered and a response was displayed."
    ),
    PURPOSE_GENERATED_RESPONSE: (
        "The recorded session shows the app displaying a generated response/answer "
        "to the user's input."
    ),
    PURPOSE_PREDICTION_RESULT: (
        "The recorded session shows an input → prediction/result flow: values were "
        "entered and a computed result was displayed."
    ),
    PURPOSE_FILE_UPLOAD: (
        "The recorded session shows a file being selected/uploaded and the app "
        "responding to it."
    ),
    PURPOSE_AUTHENTICATION: (
        "The recorded session shows an authentication screen (sign-in / sign-up flow)."
    ),
    PURPOSE_SEARCH_RETRIEVAL: (
        "The recorded session shows a search/retrieval interface returning results "
        "for a query."
    ),
    PURPOSE_DATA_VISUALIZATION: (
        "The recorded session shows charts/plots rendering data visually."
    ),
    PURPOSE_DASHBOARD: (
        "The recorded session shows a dashboard view presenting product data/metrics."
    ),
    PURPOSE_DATA_TABLE: (
        "The recorded session shows structured data rendered as a table/list view."
    ),
    PURPOSE_API_INTERACTION: (
        "The recorded session shows the page exchanging requests/responses with a "
        "backing API and rendering the returned data."
    ),
    PURPOSE_INTERACTIVE_FORM: (
        "The recorded session shows an interactive form flow: inputs were filled and "
        "submitted, and the page responded."
    ),
    PURPOSE_ERROR_LOADING: (
        "The recorded session captured an error/loading state rather than a completed "
        "product flow."
    ),
    PURPOSE_DOCUMENTATION: (
        "The recorded page is documentation/static content rather than an interactive "
        "product flow."
    ),
    PURPOSE_NAVIGATION_LAYOUT: (
        "The recorded session shows the app's page layout and navigation between views."
    ),
    PURPOSE_LANDING_OVERVIEW: (
        "The recorded page is a landing/product-overview page describing the app."
    ),
    PURPOSE_DEPLOYED_AVAILABILITY: (
        "A live deployment was reachable at inspection time; no richer in-app flow "
        "was captured."
    ),
    PURPOSE_UNKNOWN: (
        "The captured website evidence was not specific enough to classify what the "
        "page demonstrated."
    ),
}

ALLOWED_WEBSITE_PURPOSE_KEYS = frozenset(_PURPOSE_LABELS)

# Recruiter-first BEHAVIOR CLAIMS (closed vocabulary, one per purpose). The
# claim is the sentence a recruiter reads FIRST on a Website Behavior Evidence
# card: what live behaviour the recorded session demonstrably showed, phrased
# as a checkable statement — never proof strength, never authorship.
_BEHAVIOR_CLAIMS: dict[str, str] = {
    PURPOSE_CHAT_PROMPT: (
        "A chat/prompt interface accepts a message and displays a response."
    ),
    PURPOSE_GENERATED_RESPONSE: (
        "User input produces a generated response/answer on screen."
    ),
    PURPOSE_PREDICTION_RESULT: "User input produces a prediction/result display.",
    PURPOSE_FILE_UPLOAD: "A file upload flow accepts a file and the app responds to it.",
    PURPOSE_AUTHENTICATION: "An authentication flow (sign-in/sign-up) is demonstrated.",
    PURPOSE_SEARCH_RETRIEVAL: "A search/retrieval interface returns results for a query.",
    PURPOSE_DATA_VISUALIZATION: "Charts/visualizations render product data on screen.",
    PURPOSE_DASHBOARD: "An interactive dashboard displays product data/metrics.",
    PURPOSE_DATA_TABLE: "Structured data is rendered as a table/list view.",
    PURPOSE_API_INTERACTION: (
        "A user action exchanges data with a backing API and the result is rendered."
    ),
    PURPOSE_INTERACTIVE_FORM: "An interactive form accepts input and the page responds.",
    PURPOSE_ERROR_LOADING: (
        "The captured state shows an error/loading screen rather than a completed flow."
    ),
    PURPOSE_DOCUMENTATION: "A documentation/static page describes the project.",
    PURPOSE_NAVIGATION_LAYOUT: "Navigation between the app's pages/views is demonstrated.",
    PURPOSE_LANDING_OVERVIEW: "A landing/product-overview page presents the app.",
    PURPOSE_DEPLOYED_AVAILABILITY: (
        "The deployed application was live and reachable at inspection time."
    ),
    PURPOSE_UNKNOWN: (
        "The captured website behaviour could not be classified into a specific claim."
    ),
}


def website_behavior_claim(key: str | None) -> str:
    """The recruiter-first behaviour claim for a purpose key (fail-closed)."""
    return _BEHAVIOR_CLAIMS.get(str(key or ""), _BEHAVIOR_CLAIMS[PURPOSE_UNKNOWN])


# ── Closed website skill-relevance vocabulary ─────────────────────────────────

RELEVANCE_DIRECT_FRONTEND = "direct_frontend_evidence"
RELEVANCE_SUPPORTING_FRONTEND = "supporting_frontend_evidence"
RELEVANCE_DATA_VISUALIZATION = "data_visualization_evidence"
RELEVANCE_PRODUCT_DEMONSTRATION = "product_demonstration_context"
RELEVANCE_API_BEHAVIOR = "api_behavior_context"
RELEVANCE_ML_PRODUCT = "ml_product_context"
RELEVANCE_GENAI_PRODUCT = "genai_product_context"
RELEVANCE_DEPLOYMENT_AVAILABILITY = "deployment_availability_evidence"
RELEVANCE_DOCUMENTATION = "documentation_context"
RELEVANCE_UNKNOWN = "unknown_needs_review"

ALLOWED_WEBSITE_RELEVANCE_KEYS = frozenset(
    {
        RELEVANCE_DIRECT_FRONTEND,
        RELEVANCE_SUPPORTING_FRONTEND,
        RELEVANCE_DATA_VISUALIZATION,
        RELEVANCE_PRODUCT_DEMONSTRATION,
        RELEVANCE_API_BEHAVIOR,
        RELEVANCE_ML_PRODUCT,
        RELEVANCE_GENAI_PRODUCT,
        RELEVANCE_DEPLOYMENT_AVAILABILITY,
        RELEVANCE_DOCUMENTATION,
        RELEVANCE_UNKNOWN,
    }
)

# Relevance keys that may read as DIRECT evidence of the selected skill. Every
# other key is context/corroboration and must never be presented as direct proof.
_DIRECT_RELEVANCE_KEYS = frozenset({RELEVANCE_DIRECT_FRONTEND, RELEVANCE_DATA_VISUALIZATION})


# ── Purpose classification (ordered, most-specific first) ─────────────────────
#
# Matched against the concatenated ALREADY-SAFE summaries. Order matters: a
# prediction-form demo must land on the prediction/result purpose (not the
# generic form purpose), and an upload-driven prediction demo on upload → the
# earlier, more product-specific patterns win.

_PURPOSE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        PURPOSE_CHAT_PROMPT,
        re.compile(
            r"\bchat\b|chatbot|prompt (?:box|input|interface|field)|conversation(?:al)?\b"
            r"|typed? (?:a |the )?(?:message|prompt|question)|assistant repl",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_GENERATED_RESPONSE,
        re.compile(
            r"generated (?:a |an |the )?(?:response|answer|reply|text|summary|image)"
            r"|ai[- ]generated|llm (?:response|output|answer)|model repl"
            r"|response (?:was |is )?generated|retrieved (?:passage|source|document|citation)"
            r"|citation[s]? (?:shown|displayed|listed)",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_FILE_UPLOAD,
        re.compile(
            r"upload|drag[- ]and[- ]drop|choose file|file (?:was )?(?:chosen|selected|attached|dropped)",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_PREDICTION_RESULT,
        re.compile(
            r"predict|prediction|inference|classif(?:y|ied|ication|ier)|forecast"
            r"|recommend(?:ation|ed|s)\b|model (?:output|result|score)|probability"
            r"|risk score|estimated? (?:price|value|score)|result[s]? (?:panel|page|section|displayed|shown)",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_AUTHENTICATION,
        re.compile(
            r"log[- ]?in|logged in|sign[- ]?in|sign[- ]?up|authenticat|\bpassword\b|register(?:ed|ing)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_SEARCH_RETRIEVAL,
        re.compile(
            r"\bsearch(?:ed|ing)?\b|query (?:was )?(?:entered|typed|submitted)|retriev"
            r"|filter(?:ed)? (?:the )?results|lookup",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_DATA_VISUALIZATION,
        re.compile(
            r"\bchart[s]?\b|\bgraph[s]?\b|\bplot[s]?\b|visuali[sz]ation|heatmap"
            r"|bar chart|line chart|pie chart|scatter",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_DASHBOARD,
        re.compile(
            r"dashboard|analytics (?:view|page|panel)|metrics (?:panel|view|page)|\bkpi[s]?\b",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_DATA_TABLE,
        re.compile(
            r"\btable[s]?\b|data grid|list view|rows of (?:data|records)|record[s]? list(?:ed|ing)?",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_API_INTERACTION,
        re.compile(
            r"api (?:call|request|response|endpoint)|endpoint|request (?:was )?sent"
            r"|fetch(?:ed|es|ing)? (?:data|results|records)|server respon",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_INTERACTIVE_FORM,
        re.compile(
            r"\bform[s]?\b|input field|text (?:box|input|area)|dropdown|select(?:ed)? an option"
            r"|submit(?:ted|ting)?\b|entered (?:a |the )?(?:value|values|text|detail|data|number)"
            r"|fill(?:ed|ing)? (?:in|out)",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_ERROR_LOADING,
        re.compile(
            r"error (?:message|state|page|screen)|failed to load|\b404\b|\b500\b"
            r"|loading (?:state|spinner|screen)",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_DOCUMENTATION,
        re.compile(
            r"documentation|\breadme\b|docs page|static (?:page|content|site)|blog post|article",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_NAVIGATION_LAYOUT,
        re.compile(
            r"navigat|\bmenu\b|sidebar|header|tab(?:s)? (?:were |was )?(?:clicked|switched|opened)"
            r"|page layout|switched (?:between )?(?:pages|views)|routing",
            re.IGNORECASE,
        ),
    ),
    (
        PURPOSE_LANDING_OVERVIEW,
        re.compile(
            r"landing page|home ?page|product overview|hero section|welcome (?:page|screen)"
            r"|marketing page",
            re.IGNORECASE,
        ),
    ),
)


def classify_website_purpose(
    *,
    workflow_summary: str | None = None,
    workflow_steps: list[str] | None = None,
    dom_summary: str | None = None,
    ocr_summary: str | None = None,
    visual_summary: str | None = None,
    live_check: dict[str, Any] | None = None,
    fallback_summary: str | None = None,
) -> str:
    """Classify what the recorded website demonstrably showed (closed vocabulary).

    Inputs are the ALREADY-SAFE Website Proof summaries (never raw DOM/OCR/
    provider payloads). Matching is ordered most-product-specific first, so an
    "entered values and a prediction was shown" narrative lands on the
    prediction/result purpose rather than the generic form purpose. When no
    textual signal exists but the live reachability check confirmed the
    deployment, the honest floor is *deployed application availability*; with
    no signal at all the classification fails closed to *unknown / needs review*.
    """
    haystack = " ".join(
        part
        for part in (
            str(workflow_summary or ""),
            " ".join(str(s) for s in (workflow_steps or [])),
            str(dom_summary or ""),
            str(ocr_summary or ""),
            str(visual_summary or ""),
            str(fallback_summary or ""),
        )
        if part
    ).strip()

    if haystack:
        for key, pattern in _PURPOSE_PATTERNS:
            if pattern.search(haystack):
                return key

    reachable = bool(isinstance(live_check, dict) and live_check.get("is_reachable"))
    if reachable:
        return PURPOSE_DEPLOYED_AVAILABILITY
    if haystack:
        # Some safe narrative exists but matched no product pattern — an observed
        # deployment without a classifiable flow is still availability evidence.
        return PURPOSE_DEPLOYED_AVAILABILITY
    return PURPOSE_UNKNOWN


def describe_website_purpose(key: str | None) -> str:
    """Closed-vocabulary recruiter label for a website purpose key (fail-closed)."""
    return _PURPOSE_LABELS.get(str(key or ""), _PURPOSE_LABELS[PURPOSE_UNKNOWN])


def website_purpose_summary(key: str | None) -> str:
    """One safe helper sentence for a website purpose key (closed vocabulary)."""
    return _PURPOSE_SUMMARIES.get(str(key or ""), _PURPOSE_SUMMARIES[PURPOSE_UNKNOWN])


# ── Skill families (report-selected skill → conservative relevance family) ────
#
# GenAI is checked BEFORE ML because GenAI-style names ("LLM Engineering",
# "NLP with LLMs") also match the broad ML regex; data-visualization before
# frontend because "Data Visualization" would otherwise read as generic UI.

_GENAI_SKILL_RE = re.compile(
    r"gen\s*ai|generative|\bllm[s]?\b|large\s+language|\brag\b|retrieval[- ]augmented"
    r"|prompt\s+engineer|langchain|llama\s*index|chat\s*bot|chat\s*gpt|\bagentic\b|ai\s+agent",
    re.IGNORECASE,
)
_DATAVIZ_SKILL_RE = re.compile(
    r"data\s*visuali[sz]|visuali[sz]ation|\bd3(?:\.js)?\b|chart|plotly|recharts"
    r"|tableau|power\s*bi|\bdashboard",
    re.IGNORECASE,
)
_FRONTEND_SKILL_RE = re.compile(
    r"front[- ]?end|\bui\b|user\s+interface|\bhtml\b|\bcss\b|javascript|typescript"
    r"|next\.?js|\bvue\b|angular|svelte|tailwind|web\s+develop",
    re.IGNORECASE,
)
_BACKEND_SKILL_RE = re.compile(
    r"back[- ]?end|node\.?js|express|django|flask|fastapi|\brest\b|graphql|\bapi\b"
    r"|server[- ]side",
    re.IGNORECASE,
)
_DEVOPS_SKILL_RE = re.compile(
    r"devops|docker|kubernetes|\bk8s\b|ci\s*/?\s*cd|deploy|terraform|cloud\s+engineer"
    r"|\bsre\b|infrastructure",
    re.IGNORECASE,
)

_FAMILY_GENAI = "genai"
_FAMILY_ML = "ml"
_FAMILY_DATAVIZ = "dataviz"
_FAMILY_DEVOPS = "devops"
_FAMILY_FRONTEND = "frontend"
_FAMILY_BACKEND = "backend"
_FAMILY_GENERIC = ""


def _website_skill_family(skill: str | None) -> str:
    """Map the report's selected skill to one conservative website family."""
    s = str(skill or "")
    if not s.strip():
        return _FAMILY_GENERIC
    if _GENAI_SKILL_RE.search(s):
        return _FAMILY_GENAI
    if is_ml_skill(s) or skill_profile(s) in ("ml", "mle"):
        return _FAMILY_ML
    if _DATAVIZ_SKILL_RE.search(s):
        return _FAMILY_DATAVIZ
    if skill_profile(s) == "devops" or _DEVOPS_SKILL_RE.search(s):
        return _FAMILY_DEVOPS
    if skill_profile(s) == "react" or _FRONTEND_SKILL_RE.search(s):
        return _FAMILY_FRONTEND
    if skill_profile(s) == "api" or _BACKEND_SKILL_RE.search(s):
        return _FAMILY_BACKEND
    return _FAMILY_GENERIC


# Purposes that show a genuinely INTERACTIVE, stateful product UI (direct
# frontend behaviour) vs. lighter structural UI (supporting frontend evidence).
_INTERACTIVE_UI_PURPOSES = frozenset(
    {
        PURPOSE_CHAT_PROMPT,
        PURPOSE_GENERATED_RESPONSE,
        PURPOSE_PREDICTION_RESULT,
        PURPOSE_FILE_UPLOAD,
        PURPOSE_SEARCH_RETRIEVAL,
        PURPOSE_DATA_VISUALIZATION,
        PURPOSE_DASHBOARD,
        PURPOSE_DATA_TABLE,
        PURPOSE_INTERACTIVE_FORM,
        PURPOSE_API_INTERACTION,
    }
)
_STRUCTURAL_UI_PURPOSES = frozenset(
    {
        PURPOSE_AUTHENTICATION,
        PURPOSE_NAVIGATION_LAYOUT,
        PURPOSE_LANDING_OVERVIEW,
        PURPOSE_ERROR_LOADING,
    }
)
# Purposes that specifically evidence model/AI-powered product behaviour.
_MODEL_BEHAVIOUR_PURPOSES = frozenset(
    {
        PURPOSE_CHAT_PROMPT,
        PURPOSE_GENERATED_RESPONSE,
        PURPOSE_PREDICTION_RESULT,
        PURPOSE_DATA_VISUALIZATION,
        PURPOSE_DASHBOARD,
        PURPOSE_SEARCH_RETRIEVAL,
    }
)
# Purposes that plausibly show a request→result exchange with a backing API.
_API_FLOW_PURPOSES = frozenset(
    {
        PURPOSE_API_INTERACTION,
        PURPOSE_PREDICTION_RESULT,
        PURPOSE_SEARCH_RETRIEVAL,
        PURPOSE_INTERACTIVE_FORM,
        PURPOSE_FILE_UPLOAD,
        PURPOSE_CHAT_PROMPT,
        PURPOSE_GENERATED_RESPONSE,
    }
)
_DATAVIZ_PURPOSES = frozenset(
    {PURPOSE_DATA_VISUALIZATION, PURPOSE_DASHBOARD, PURPOSE_DATA_TABLE}
)


def classify_website_skill_relevance(purpose_key: str | None, *, skill: str | None) -> str:
    """How the observed website behaviour relates to the report's SELECTED skill.

    Recomputed per report against the selected skill (never trusted from
    storage). The mapping is conservative by design: implementation-heavy
    families (ML / GenAI / DevOps-style skills) can only ever receive *product
    behaviour / availability context* — a demo UI is honest corroboration of the
    product, never implementation proof. Frontend-family skills are the one
    family where an interactive recorded UI IS the skill's direct subject
    matter, so those may read as direct/supporting Frontend evidence.
    """
    purpose = str(purpose_key or "")
    if purpose not in ALLOWED_WEBSITE_PURPOSE_KEYS or purpose == PURPOSE_UNKNOWN:
        return RELEVANCE_UNKNOWN
    family = _website_skill_family(skill)

    # Family-independent floors: a docs/static page is context for any skill and
    # bare availability is availability for any skill.
    if purpose == PURPOSE_DOCUMENTATION:
        return RELEVANCE_DOCUMENTATION
    if purpose == PURPOSE_DEPLOYED_AVAILABILITY:
        return RELEVANCE_DEPLOYMENT_AVAILABILITY

    if family == _FAMILY_GENAI:
        if purpose in _MODEL_BEHAVIOUR_PURPOSES:
            return RELEVANCE_GENAI_PRODUCT
        return RELEVANCE_PRODUCT_DEMONSTRATION
    if family == _FAMILY_ML:
        if purpose in _MODEL_BEHAVIOUR_PURPOSES:
            return RELEVANCE_ML_PRODUCT
        return RELEVANCE_PRODUCT_DEMONSTRATION
    if family == _FAMILY_DEVOPS:
        # A working URL/flow corroborates that the app is deployed — never
        # Docker/Kubernetes/CI-CD internals.
        return RELEVANCE_DEPLOYMENT_AVAILABILITY
    if family == _FAMILY_DATAVIZ:
        if purpose in _DATAVIZ_PURPOSES:
            return RELEVANCE_DATA_VISUALIZATION
        return RELEVANCE_PRODUCT_DEMONSTRATION
    if family == _FAMILY_FRONTEND:
        if purpose in _INTERACTIVE_UI_PURPOSES:
            return RELEVANCE_DIRECT_FRONTEND
        if purpose in _STRUCTURAL_UI_PURPOSES:
            return RELEVANCE_SUPPORTING_FRONTEND
        return RELEVANCE_PRODUCT_DEMONSTRATION
    if family == _FAMILY_BACKEND:
        if purpose in _API_FLOW_PURPOSES:
            return RELEVANCE_API_BEHAVIOR
        return RELEVANCE_PRODUCT_DEMONSTRATION
    return RELEVANCE_PRODUCT_DEMONSTRATION


_RELEVANCE_LABEL_TEMPLATES: dict[str, str] = {
    RELEVANCE_DIRECT_FRONTEND: "Direct {skill} evidence — interactive product UI demonstrated",
    RELEVANCE_SUPPORTING_FRONTEND: "Supporting {skill} evidence — page structure and navigation demonstrated",
    RELEVANCE_DATA_VISUALIZATION: "Direct data-visualization evidence for {skill}",
    RELEVANCE_PRODUCT_DEMONSTRATION: "Product demonstration context for {skill}",
    RELEVANCE_API_BEHAVIOR: "API-backed product behaviour for {skill} — not server-code proof",
    RELEVANCE_ML_PRODUCT: "{skill} product behaviour context — not {skill} implementation proof",
    RELEVANCE_GENAI_PRODUCT: "{skill} product behaviour context — not {skill} implementation proof",
    RELEVANCE_DEPLOYMENT_AVAILABILITY: "Deployed application availability evidence for {skill}",
    RELEVANCE_DOCUMENTATION: "Documentation / static context for {skill}",
    RELEVANCE_UNKNOWN: "Unclear relevance to {skill} — needs review",
}

_RELEVANCE_SUMMARIES: dict[str, str] = {
    RELEVANCE_DIRECT_FRONTEND: (
        "The recorded interactive UI behaviour is itself the subject of {skill}, so "
        "this is direct evidence of working {skill} product behaviour (authorship is "
        "corroborated by GitHub/Defense evidence, not by the UI alone)."
    ),
    RELEVANCE_SUPPORTING_FRONTEND: (
        "The recorded page structure/navigation supports {skill} but shows less "
        "interactive behaviour than a full product flow."
    ),
    RELEVANCE_DATA_VISUALIZATION: (
        "Charts/dashboards visibly rendering data directly support the {skill} claim."
    ),
    RELEVANCE_PRODUCT_DEMONSTRATION: (
        "The recorded flow demonstrates the working product this {skill} claim belongs "
        "to; it corroborates the claim without directly proving the skill's internals."
    ),
    RELEVANCE_API_BEHAVIOR: (
        "The observed request→result behaviour indicates an API-backed product, which "
        "corroborates {skill}; the server-side implementation itself is proven by code "
        "evidence, not by the UI."
    ),
    RELEVANCE_ML_PRODUCT: (
        "The website shows model-powered product behaviour (input → prediction/output), "
        "which corroborates an {skill} product; it does not, by itself, prove model "
        "training or {skill} implementation — that comes from GitHub code, documents, "
        "or the Project Defense."
    ),
    RELEVANCE_GENAI_PRODUCT: (
        "The website shows a generative-AI product behaviour (prompt → generated "
        "response), which corroborates a {skill} product; a chat UI does not, by "
        "itself, prove LLM/RAG implementation internals — that comes from GitHub "
        "code, documents, or the Project Defense."
    ),
    RELEVANCE_DEPLOYMENT_AVAILABILITY: (
        "A reachable, working deployment conservatively supports {skill} availability; "
        "it does not, by itself, prove Docker/Kubernetes/CI-CD internals."
    ),
    RELEVANCE_DOCUMENTATION: (
        "The captured page is documentation/static content — useful context for "
        "{skill}, not a demonstrated product flow."
    ),
    RELEVANCE_UNKNOWN: (
        "The captured website evidence could not be confidently related to {skill}; "
        "treat it as needing review rather than proof."
    ),
}


def _skill_text(skill: str | None) -> str:
    return str(skill or "").strip() or "this skill"


def describe_website_skill_relevance(key: str | None, skill: str | None) -> str:
    """Recruiter label for a website relevance key, formatted with the skill name.

    The template vocabulary is closed; only the (already-safe) skill display name
    is interpolated. Unknown keys fail closed to the needs-review label.
    """
    template = _RELEVANCE_LABEL_TEMPLATES.get(
        str(key or ""), _RELEVANCE_LABEL_TEMPLATES[RELEVANCE_UNKNOWN]
    )
    return template.format(skill=_skill_text(skill))


def website_skill_relevance_summary(key: str | None, skill: str | None) -> str:
    """One safe helper sentence for a website relevance key (closed templates)."""
    template = _RELEVANCE_SUMMARIES.get(str(key or ""), _RELEVANCE_SUMMARIES[RELEVANCE_UNKNOWN])
    return template.format(skill=_skill_text(skill))


def is_direct_website_relevance(key: str | None) -> bool:
    """True only for the relevance keys allowed to read as DIRECT skill evidence."""
    return str(key or "") in _DIRECT_RELEVANCE_KEYS


# ── Honest limitations (per relevance family) ─────────────────────────────────

_BASE_WEBSITE_LIMITATION = (
    "Confirms observed behaviour at inspection time, not source-code authorship or ongoing uptime."
)

_RELEVANCE_LIMITATIONS: dict[str, str] = {
    RELEVANCE_ML_PRODUCT: (
        "Website prediction/output demonstrates product behaviour at inspection time; it does "
        "not, by itself, prove model training or ML implementation."
    ),
    RELEVANCE_GENAI_PRODUCT: (
        "A chat/generated-response UI demonstrates GenAI product behaviour at inspection time; "
        "it does not, by itself, prove LLM/RAG implementation internals."
    ),
    RELEVANCE_DEPLOYMENT_AVAILABILITY: (
        "A reachable deployment shows the app was live at inspection time; it does not, by "
        "itself, prove Docker/Kubernetes/CI-CD internals or ongoing uptime."
    ),
    RELEVANCE_API_BEHAVIOR: (
        "Observed request/result behaviour suggests an API-backed product at inspection time; "
        "it does not expose or prove the server-side implementation."
    ),
    RELEVANCE_DOCUMENTATION: (
        "A documentation/static page provides context only; it demonstrates no interactive "
        "product behaviour."
    ),
    RELEVANCE_UNKNOWN: (
        "The captured website evidence needs review before it can support this skill."
    ),
}


def website_limitation_for(relevance_key: str | None, skill: str | None = None) -> str:
    """The honest limitation sentence for one website evidence row.

    Implementation-heavy relevances get their explicit "UI alone does not prove
    internals" limitation; UI-native relevances keep the base behaviour-not-
    authorship caveat. Always non-empty.
    """
    del skill  # reserved for future per-skill phrasing; limitations are family-level
    return _RELEVANCE_LIMITATIONS.get(str(relevance_key or ""), _BASE_WEBSITE_LIMITATION)


# ── Connected proof chain explanation ─────────────────────────────────────────


def website_chain_connection_note(
    *, has_github: bool, has_defense: bool, has_document: bool
) -> str | None:
    """One safe sentence explaining how Website Proof corroborates a chain.

    Returned only when the chain actually holds Website Proof PLUS at least one
    other source to connect to (the caller checks the website side); with no
    companion source there is nothing to connect, so ``None`` keeps the chain
    free of a redundant note.
    """
    parts = ["The website demonstrates the working product behaviour"]
    if has_github:
        parts.append("GitHub code shows the implementation")
    if has_defense:
        parts.append("the Project Defense shows the candidate's own understanding")
    if has_document:
        parts.append("documents corroborate the claim")
    if len(parts) == 1:
        return None
    return "; ".join(parts) + "."


def website_corroboration_note(
    *, has_github: bool, has_defense: bool, has_document: bool
) -> str | None:
    """One safe per-card sentence naming the companion proofs that corroborate
    this website behaviour (closed fragments — nothing user-controlled is
    interpolated). ``None`` when no companion source exists."""
    fragments: list[str] = []
    if has_github:
        fragments.append("GitHub provides implementation evidence for the same project")
    if has_defense:
        fragments.append("the candidate explained this behaviour in the Project Defense")
    if has_document:
        fragments.append("a document corroborates the project's stated objective")
    if not fragments:
        return None
    note = "; ".join(fragments)
    return note[0].upper() + note[1:] + "."


def attach_website_corroboration(
    card: dict[str, Any],
    *,
    project_title: str | None = None,
    has_github: bool = False,
    has_defense: bool = False,
    has_document: bool = False,
) -> dict[str, Any]:
    """Wire ONE Website Evidence Card into its confirmed VBR project chain.

    Called only for website proofs ATTACHED to a real project chain (the
    standalone vault bucket never gets corroboration — unattached proofs share
    no confirmed project). Sets the corroboration booleans/note, the
    already-safe connected project title, and appends the closed-vocabulary
    corroboration chips. Booleans OR with any existing value (a proof attached
    to several chains keeps every true connection); the first project title
    wins. Idempotent: chips are appended at most once.
    """
    if not isinstance(card, dict):
        return card
    card["corroborates_github"] = bool(card.get("corroborates_github")) or bool(has_github)
    card["corroborates_defense"] = bool(card.get("corroborates_defense")) or bool(has_defense)
    card["corroborates_document"] = bool(card.get("corroborates_document")) or bool(has_document)
    title = str(project_title or "").strip()[:160]
    if title and not card.get("connected_project_title"):
        card["connected_project_title"] = title
    card["corroboration_note"] = website_corroboration_note(
        has_github=bool(card["corroborates_github"]),
        has_defense=bool(card["corroborates_defense"]),
        has_document=bool(card["corroborates_document"]),
    )
    chips = [str(c) for c in (card.get("evidence_basis_chips") or [])]
    for flag, chip in (
        (True, CHIP_ATTACHED_PROJECT),
        (card["corroborates_github"], CHIP_CORROBORATES_GITHUB),
        (card["corroborates_defense"], CHIP_CORROBORATES_DEFENSE),
        (card["corroborates_document"], CHIP_CORROBORATES_DOCUMENT),
    ):
        if flag and chip not in chips:
            chips.append(chip)
    card["evidence_basis_chips"] = chips
    return card


# ── Website Evidence Card (recruiter-inspectable, closed vocabularies) ────────
#
# The card is the Website counterpart of GitHub's "View code lines" row: one
# structured, recruiter-verifiable unit answering "what page was observed, what
# behaviour was visible, what evidence backs it, what it supports and what it
# does NOT prove". Every field is either (a) a closed-vocabulary label derived
# here, (b) an already-safe summary the detail service sanitized, or (c) a URL
# revalidated through ``is_safe_public_url``. The card NEVER carries raw
# DOM/OCR/frame/provider payloads, storage paths, signed URLs, or private IDs —
# OCR/DOM/visual evidence surfaces only as derived closed-template sentences.

# Evidence basis chips (closed vocabulary — public projection filters to these).
CHIP_VISUAL_FRAME = "Visual frame"
CHIP_OCR_SUMMARY = "Safe OCR summary"
CHIP_DOM_SUMMARY = "Safe DOM summary"
CHIP_ROUTE_OBSERVED = "Route observed"
CHIP_LIVE_CHECK = "Live check passed"
CHIP_WORKFLOW_NAVIGATION = "Workflow navigation"
CHIP_USER_INPUT_FLOW = "User input flow"
CHIP_OUTPUT_VISIBLE = "Output / result visible"
CHIP_DASHBOARD_VISIBLE = "Dashboard visible"
# Cross-proof corroboration chips — appended by ``attach_website_corroboration``
# ONLY when the website proof sits inside a confirmed VBR project chain that
# actually holds the companion source (never guessed from titles alone).
CHIP_ATTACHED_PROJECT = "Attached project"
CHIP_CORROBORATES_GITHUB = "Corroborates GitHub"
CHIP_CORROBORATES_DEFENSE = "Corroborates Defense"
CHIP_CORROBORATES_DOCUMENT = "Corroborates Document"

ALLOWED_WEBSITE_EVIDENCE_CHIPS = frozenset(
    {
        CHIP_VISUAL_FRAME,
        CHIP_OCR_SUMMARY,
        CHIP_DOM_SUMMARY,
        CHIP_ROUTE_OBSERVED,
        CHIP_LIVE_CHECK,
        CHIP_WORKFLOW_NAVIGATION,
        CHIP_USER_INPUT_FLOW,
        CHIP_OUTPUT_VISIBLE,
        CHIP_DASHBOARD_VISIBLE,
        CHIP_ATTACHED_PROJECT,
        CHIP_CORROBORATES_GITHUB,
        CHIP_CORROBORATES_DEFENSE,
        CHIP_CORROBORATES_DOCUMENT,
    }
)

# Screenshot / keyframe access (closed enum). Keyframes live in PRIVATE storage
# behind the visibility-gated thumbnail proxy (``keyframe_storage_service``), so
# the MVP card never carries a preview URL — only an honest access status. The
# public projection additionally coerces anything preview-shaped down to the
# permission-gated status (``public_screenshot_access_label``).
SCREENSHOT_ACCESS_PERMISSION_REQUIRED = "private_candidate_permission_required"
SCREENSHOT_ACCESS_UNAVAILABLE = "unavailable"
_ALLOWED_SCREENSHOT_ACCESS_LABELS = frozenset(
    {SCREENSHOT_ACCESS_PERMISSION_REQUIRED, SCREENSHOT_ACCESS_UNAVAILABLE}
)

# Purposes where the user demonstrably DROVE the page (input flow) vs. where a
# computed output/result was demonstrably visible.
_INPUT_FLOW_PURPOSES = frozenset(
    {
        PURPOSE_CHAT_PROMPT,
        PURPOSE_FILE_UPLOAD,
        PURPOSE_SEARCH_RETRIEVAL,
        PURPOSE_INTERACTIVE_FORM,
        PURPOSE_AUTHENTICATION,
    }
)
_OUTPUT_VISIBLE_PURPOSES = frozenset(
    {
        PURPOSE_GENERATED_RESPONSE,
        PURPOSE_PREDICTION_RESULT,
        PURPOSE_DATA_VISUALIZATION,
        PURPOSE_DASHBOARD,
        PURPOSE_DATA_TABLE,
        PURPOSE_API_INTERACTION,
    }
)

# Derived evidence sentences (closed templates — only the closed purpose LABEL
# is interpolated, never OCR/DOM/provider text).
_VISUAL_EVIDENCE_TEMPLATE = (
    "Visual frame analysis of the recorded session is consistent with: {label}."
)
_OCR_EVIDENCE_TEMPLATE = "Safe OCR summary indicates on-screen text consistent with: {label}."
_DOM_EVIDENCE_TEMPLATE = "Safe DOM summary indicates page structure consistent with: {label}."


def derive_website_evidence_chips(
    purpose_key: str | None,
    *,
    has_route: bool = False,
    live_reachable: bool = False,
    has_workflow: bool = False,
    has_visual: bool = False,
    has_ocr: bool = False,
    has_dom: bool = False,
) -> list[str]:
    """The closed-vocabulary basis chips for one website evidence card.

    Order is deterministic (observation → analysis → behaviour) so the same
    evidence always renders the same chip row. Every chip states what evidence
    EXISTS — never how strong it is.
    """
    purpose = str(purpose_key or "")
    chips: list[str] = []
    if has_route:
        chips.append(CHIP_ROUTE_OBSERVED)
    if live_reachable:
        chips.append(CHIP_LIVE_CHECK)
    if has_visual:
        chips.append(CHIP_VISUAL_FRAME)
    if has_ocr:
        chips.append(CHIP_OCR_SUMMARY)
    if has_dom:
        chips.append(CHIP_DOM_SUMMARY)
    if has_workflow:
        chips.append(CHIP_WORKFLOW_NAVIGATION)
    if purpose in _INPUT_FLOW_PURPOSES:
        chips.append(CHIP_USER_INPUT_FLOW)
    if purpose in _OUTPUT_VISIBLE_PURPOSES:
        chips.append(CHIP_OUTPUT_VISIBLE)
    if purpose == PURPOSE_DASHBOARD:
        chips.append(CHIP_DASHBOARD_VISIBLE)
    return chips


def public_screenshot_access_label(value: Any, *, screenshot_available: Any = None) -> str:
    """Coerce a screenshot access label for the PUBLIC projection (fail-closed).

    The public surface never grants preview access: any preview-shaped or
    unrecognised label collapses to the permission-gated status when evidence
    frames exist, otherwise to ``unavailable``.
    """
    label = str(value or "")
    if label == SCREENSHOT_ACCESS_UNAVAILABLE:
        return SCREENSHOT_ACCESS_UNAVAILABLE
    if label == SCREENSHOT_ACCESS_PERMISSION_REQUIRED or bool(screenshot_available):
        return SCREENSHOT_ACCESS_PERMISSION_REQUIRED
    return SCREENSHOT_ACCESS_UNAVAILABLE


def _safe_route_or_page(open_url: str | None, live_final_url: str | None, safe_location: str | None) -> str:
    """A short recruiter-facing route/page locator derived ONLY from safe URLs.

    Prefers the live check's post-redirect URL path (the page that was actually
    observed), then the attach-time public URL path, then the already-safe
    domain label. Never a storage path, never a private ID.
    """
    for candidate in (live_final_url, open_url):
        url = str(candidate or "").strip()
        if not url or not is_safe_public_url(url):
            continue
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        path = (parts.path or "/").rstrip("/") or "/"
        host = parts.hostname or ""
        return f"{host}{path}" if path != "/" else (host or path)
    location = str(safe_location or "").strip()
    return location or "Recorded session"


def build_website_evidence_card(
    *,
    purpose_key: str | None,
    relevance_key: str | None,
    skill: str | None,
    workflow_summary: str | None = None,
    workflow_steps: list[str] | None = None,
    has_dom_summary: bool = False,
    has_ocr_summary: bool = False,
    has_visual_summary: bool = False,
    live_check: dict[str, Any] | None = None,
    open_website_url: str | None = None,
    safe_location: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Build ONE recruiter-inspectable Website Evidence Card (all fields safe).

    Inputs are the closed-vocabulary keys the read-time classifier produced plus
    PRESENCE booleans for the sanitized DOM/OCR/visual summaries — the raw-ish
    texts themselves never enter the card; they surface only as derived
    closed-template sentences. ``open_website_url`` survives only when it passes
    ``is_safe_public_url``. Screenshot/keyframe evidence is represented as an
    availability flag plus a closed access status; ``screenshot_preview_url`` is
    ALWAYS ``None`` in this MVP because keyframes live in private storage behind
    the candidate-permission thumbnail proxy.
    """
    purpose = str(purpose_key or "")
    if purpose not in ALLOWED_WEBSITE_PURPOSE_KEYS:
        purpose = PURPOSE_UNKNOWN
    relevance = str(relevance_key or "")
    if relevance not in ALLOWED_WEBSITE_RELEVANCE_KEYS:
        relevance = RELEVANCE_UNKNOWN

    live = live_check if isinstance(live_check, dict) else {}
    live_final_url = str(live.get("final_url") or "") or None
    page_title = str(live.get("page_title") or "").strip()[:160] or None

    open_url = str(open_website_url or "").strip()
    if not (open_url and is_safe_public_url(open_url)):
        open_url = None

    route_or_page = _safe_route_or_page(open_url, live_final_url, safe_location)
    purpose_label = describe_website_purpose(purpose)

    steps = [str(s) for s in (workflow_steps or []) if str(s).strip()]
    chips = derive_website_evidence_chips(
        purpose,
        has_route=bool(live_final_url or open_url or page_title),
        live_reachable=bool(live.get("is_reachable")),
        has_workflow=bool(steps or workflow_summary),
        has_visual=has_visual_summary,
        has_ocr=has_ocr_summary,
        has_dom=has_dom_summary,
    )

    # Frames were captured and analyzed exactly when a sanitized visual/OCR
    # summary exists; the frames themselves stay in private storage, so access
    # is honestly "with candidate permission" — never a raw/preview URL here.
    screenshot_available = bool(has_visual_summary or has_ocr_summary)
    screenshot_access = (
        SCREENSHOT_ACCESS_PERMISSION_REQUIRED
        if screenshot_available
        else SCREENSHOT_ACCESS_UNAVAILABLE
    )

    # Stable key over safe display fields only (no session/source/private IDs).
    card_key = "web-" + hashlib.sha1(
        f"{purpose}|{relevance}|{route_or_page}".encode()
    ).hexdigest()[:12]

    observed = str(observed_at or "").strip()
    # Date precision only — a full timestamp is provenance metadata the card
    # does not need.
    observed = observed[:10] if len(observed) >= 10 else (observed or None)

    return {
        "card_key": card_key,
        "route_or_page": route_or_page,
        "page_title": page_title,
        "observed_at": observed,
        # Recruiter-first behaviour claim (closed vocabulary keyed by purpose) —
        # the first line the card renders.
        "behavior_claim": website_behavior_claim(purpose),
        "website_purpose_key": purpose,
        "website_purpose_label": purpose_label,
        "website_purpose_summary": website_purpose_summary(purpose),
        "skill_relevance_key": relevance,
        "skill_relevance_label": describe_website_skill_relevance(relevance, skill),
        "skill_relevance_summary": website_skill_relevance_summary(relevance, skill),
        "observed_behavior_summary": (str(workflow_summary or "").strip()[:320] or None),
        "visual_evidence_summary": (
            _VISUAL_EVIDENCE_TEMPLATE.format(label=purpose_label) if has_visual_summary else None
        ),
        "ocr_evidence_summary_safe": (
            _OCR_EVIDENCE_TEMPLATE.format(label=purpose_label) if has_ocr_summary else None
        ),
        "dom_evidence_summary_safe": (
            _DOM_EVIDENCE_TEMPLATE.format(label=purpose_label) if has_dom_summary else None
        ),
        "evidence_basis_chips": chips,
        "limitation": website_limitation_for(relevance, skill),
        "open_website_url": open_url,
        "screenshot_available": screenshot_available,
        "screenshot_access_label": screenshot_access,
        "screenshot_preview_url": None,
        # Cross-proof corroboration — OFF by default; only the vault service's
        # confirmed project-chain pass (``attach_website_corroboration``) may
        # turn these on, so an unattached proof can never claim a connection.
        "corroborates_github": False,
        "corroborates_defense": False,
        "corroborates_document": False,
        "corroboration_note": None,
        "connected_project_title": None,
    }
