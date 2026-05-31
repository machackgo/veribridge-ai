"""Extension Proof Workflow Analysis Service.

Performs deep timeline-based analysis of a recorded browser workflow to
produce recruiter-readable evidence about what the student demonstrated,
which claimed skills are supported, and what is still missing.

Current analysis_type: 'timeline_only'
  — uses workflow events, URLs, page titles, and recording metadata.
  — does NOT perform video frame extraction or screenshot analysis (yet).
  — the output schema is designed so video/multimodal analysis can be
    dropped in later without changing the API surface.

Target-site filtering (v2):
  — only events on the proof target domain are analysed for skill evidence.
  — VeriBridge internal dashboard pages, Supabase, and unrelated browser
    tabs are classified as "noise" and excluded from recruiter-facing output.
  — GitHub pages are classified as "supporting evidence" and noted separately.
  — raw noise counts are stored internally for debugging; never surfaced to
    recruiters.

Precise Visual Workflow Evidence (v3):
  — builds an observed_demonstration schema with input→action→output steps.
  — detects app type: ml_app, chatbot, route_map, dashboard, document,
    portfolio, generic.
  — extracts IAO patterns from event sequence (upload → predict → result).
  — visual_analysis_status = "not_configured" when no visual provider is set;
    becomes "analyzed" when local OCR / local vision / OpenAI Vision runs.
  — does NOT fake confidence scores or prediction labels from OCR;
    detected_result_values is empty when visual analysis is not configured.
  — Visual frame analysis plugged in via WorkflowVisualAnalysisService (v5).

DOM Visible Evidence Integration (v4):
  — when workflow_visible_evidence_events exist for the session, the
    analysis is enriched with DOM-extracted observations.
  — detected_result_values is populated from sanitized DOM text when
    result values were captured (e.g. "dog: 0.89").
  — visible_evidence_status is set to "partial" or "available" when
    visible evidence was captured; "not_captured" for old recordings.
  — Each DemonstrationStep shows evidence_source: "dom_snapshot" /
    "event_metadata" / "inferred_from_click".
  — Old recordings without visible evidence continue to work unchanged.

Guardrails:
  — never claims skills are "verified" or "guaranteed"
  — uses "evidence supports", "AI Reviewed", "workflow analysis"
  — human_review_needed is set conservatively
  — exact output values only reported when captured in visible evidence
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)

_TABLE = "workflow_analysis_results"
_SESSION_TABLE = "extension_proof_sessions"

ANALYZER_VERSION = "workflow-analysis-v4"

# Status values from which workflow analysis is allowed.
_VALID_ANALYZE_FROM = frozenset({"uploaded_pending_analysis", "analyzing"})


# ── Tech detection maps ───────────────────────────────────────────────────────

_DOMAIN_TECH: dict[str, list[str]] = {
    "vercel.app":        ["Next.js", "React", "Vercel"],
    "netlify.app":       ["React", "Netlify"],
    "railway.app":       ["Railway"],
    "render.com":        ["Render"],
    "fly.dev":           ["Fly.io"],
    "herokuapp.com":     ["Heroku"],
    "streamlit.app":     ["Streamlit", "Python"],
    "huggingface.co":    ["HuggingFace", "Machine Learning", "Python"],
    "github.com":        ["GitHub", "Git"],
    "github.io":         ["GitHub Pages"],
    "supabase.io":       ["Supabase", "PostgreSQL"],
    "supabase.co":       ["Supabase", "PostgreSQL"],
    "firebase.google.com": ["Firebase"],
    "replit.com":        ["Replit"],
}

_PORT_TECH: dict[str, list[str]] = {
    "3000": ["React", "Node.js", "Next.js"],
    "3001": ["React", "Node.js"],
    "4000": ["Node.js", "Express"],
    "4200": ["Angular"],
    "5000": ["Flask", "Python"],
    "5001": ["Flask", "Python"],
    "5173": ["Vite", "React"],
    "8000": ["FastAPI", "Django", "Python"],
    "8001": ["FastAPI", "Django", "Python"],
    "8080": ["Spring Boot", "Java", "Go"],
    "8501": ["Streamlit", "Python"],
    "8888": ["Jupyter Notebook", "Python"],
    "9000": ["Node.js"],
}

_TITLE_TECH: dict[str, str] = {
    "fastapi":       "FastAPI",
    "swagger":       "FastAPI",
    "openapi":       "API",
    "django":        "Django",
    "flask":         "Flask",
    "react":         "React",
    "next.js":       "Next.js",
    "angular":       "Angular",
    "vue":           "Vue",
    "streamlit":     "Streamlit",
    "jupyter":       "Jupyter Notebook",
    "grafana":       "Grafana",
    "postgres":      "PostgreSQL",
    "pgadmin":       "PostgreSQL",
    "mongodb":       "MongoDB",
    "redis":         "Redis",
    "graphql":       "GraphQL",
    "storybook":     "Storybook",
    "prisma":        "Prisma",
    "supabase":      "Supabase",
}

_SKILL_ALIASES: dict[str, str] = {
    "react.js": "React",
    "reactjs": "React",
    "react js": "React",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "fastapi": "FastAPI",
    "fast api": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "angular": "Angular",
    "vue.js": "Vue",
    "vuejs": "Vue",
    "streamlit": "Streamlit",
    "jupyter": "Jupyter Notebook",
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "github": "GitHub",
    "git": "Git",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "graphql": "GraphQL",
    "supabase": "Supabase",
    "firebase": "Firebase",
    "redis": "Redis",
    "celery": "Celery",
    "langchain": "LangChain",
    "huggingface": "HuggingFace",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "sqlalchemy": "SQLAlchemy",
    "mlops": "MLOps",
    "google cloud": "Google Cloud",
    "cloud run": "Google Cloud",
    "gcp": "Google Cloud",
    "aws": "AWS",
    "azure": "Azure",
    "google maps": "Google Maps API",
    # AI/ML aliases to preserve capitalisation through title()
    "tensorflow.js": "TensorFlow.js",
    "tfjs": "TensorFlow.js",
    "browser-based ai": "Browser-Based AI",
    "browser based ai": "Browser-Based AI",
    "image classification": "Image Classification",
    "model testing": "Model Testing",
    "computer vision": "Computer Vision",
    "object detection": "Object Detection",
    "natural language processing": "Natural Language Processing",
    "deep learning": "Deep Learning",
    "reinforcement learning": "Reinforcement Learning",
}

# ── App-type detection patterns ───────────────────────────────────────────────
# Used to classify the target application so IAO extraction can be more precise.

_ML_APP_SIGNALS: tuple[str, ...] = (
    "predict", "detection", "detect", "classify", "classification",
    "inference", "model", "recognition", "object", "image", "vision",
    "nlp", "sentiment", "score", "probability", "confidence",
    "tensorflow", "pytorch", "sklearn", "streamlit", "huggingface",
    "gradio", "yolo", "coco", "ssd",
)

_CHATBOT_SIGNALS: tuple[str, ...] = (
    "chat", "chatbot", "assistant", "bot", "conversation", "message",
    "prompt", "response", "gpt", "llm", "ask", "ai assistant",
)

_ROUTE_MAP_SIGNALS: tuple[str, ...] = (
    "route", "map", "navigation", "directions", "location", "geo",
    "traffic", "risk", "flood", "reroute", "incident", "waypoint",
    "latitude", "longitude", "address",
)

_DASHBOARD_SIGNALS: tuple[str, ...] = (
    "dashboard", "analytics", "chart", "graph", "metric", "kpi",
    "report", "filter", "visuali", "trend", "insight", "stats",
    "tableau", "grafana", "kibana", "powerbi",
)

_DOCUMENT_SIGNALS: tuple[str, ...] = (
    "document", "pdf", "upload", "extract", "parse", "ocr", "scan",
    "invoice", "receipt", "form", "text extraction", "summarize",
    "entity", "nlp",
)

# Action triggers: clicking these strongly implies a "predict/run" step
_ACTION_TRIGGER_TEXTS: tuple[str, ...] = (
    "predict", "analyze", "analyse", "detect", "run", "classify",
    "submit", "search", "generate", "compute", "calculate", "process",
    "check", "scan", "start", "execute", "infer", "translate",
    "summarize", "evaluate", "test",
)

# Upload triggers: clicking/interacting with these implies a file/image was provided
_UPLOAD_TRIGGER_TEXTS: tuple[str, ...] = (
    "upload", "choose file", "browse", "select file", "open file",
    "drag", "drop", "import",
)

# Output signals: page titles or URLs containing these imply results are shown
_OUTPUT_PAGE_SIGNALS: tuple[str, ...] = (
    "result", "output", "prediction", "detection", "classification",
    "response", "answer", "report", "analysis", "evaluation",
    "score", "summary", "insights",
)

_REQUIRES_CODE_EVIDENCE: frozenset[str] = frozenset({
    "fastapi", "django", "flask", "starlette", "aiohttp", "tornado",
    "sqlalchemy", "alembic", "prisma", "drizzle",
    "docker", "docker compose", "kubernetes",
    "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn",
    "xgboost", "lightgbm", "machine learning", "ml", "deep learning", "mlops",
    "celery", "redis", "mongodb", "postgresql", "postgres",
    "langchain", "llamaindex", "huggingface", "openai", "anthropic",
    "google cloud", "cloud run", "gcp", "aws", "azure",
    "python",
    "sqlalchemy", "alembic",
    "fastai", "ray", "dask", "airflow", "prefect",
    "github actions", "ci/cd",
})


# ── OCR frame evidence: page-context detection ────────────────────────────────
# These keyword sets are used to classify what type of content is shown in
# video keyframe OCR text (homepage vs training UI vs prediction output).

# Words strongly associated with homepage / marketing content (no interactive UI)
_OCR_HOMEPAGE_SIGNALS: frozenset[str] = frozenset({
    "get started", "no expertise", "no coding required", "quick, practical",
    "used by", "watch video", "see examples", "how it works", "sign in",
    "sign up", "log in", "create account", "accessibility", "faq",
    "free to use", "download", "documentation", "learn more",
    "a fast, easy way", "no expertise or coding", "sites, apps",
})

# Words strongly associated with training / data collection UI
_OCR_TRAINING_UI_SIGNALS: frozenset[str] = frozenset({
    "add image samples", "image samples", "add samples", "webcam",
    "upload images", "train model", "training", "class 1", "class 2",
    "add a class", "samples added", "epochs", "model trained",
    "you can now", "add class", "sample", "hold to record",
    "flip camera", "upload from file",
})

# Words strongly associated with prediction / testing output being shown
_OCR_PREDICTION_OUTPUT_SIGNALS: frozenset[str] = frozenset({
    "confidence", "prediction", "predicted class", "accuracy",
    "output", "result", "score", "probability", "class label",
    "test your model", "your model is ready", "no input",
})

# OCR snippets that are likely UI noise from other tabs / chrome UI / navigation
_OCR_NOISE_SNIPPETS: frozenset[str] = frozenset({
    "table of contents", "copyright", "all rights reserved", "privacy policy",
    "terms of service", "cookie policy", "subscribe", "newsletter",
    "click here", "read more",
})

# ── OCR → skill keyword maps ───────────────────────────────────────────────────
# Conservative mapping: claim → list of OCR terms that would *partially* support it.
# Ordered by specificity — more specific terms → higher weight.
_SKILL_OCR_KEYWORDS: dict[str, list[str]] = {
    # ── Machine Learning ──────────────────────────────────────────────────────
    "machine learning": [
        "teachable machine", "machine learning", "neural network",
        "train a computer", "train your model", "training",
        "deep learning", "model", "tensorflow", "keras",
        "sklearn", "scikit", "hugging face", "pytorch",
    ],
    # ── Image Classification ──────────────────────────────────────────────────
    "image classification": [
        "add image samples", "image samples", "classify", "classification",
        "class 1", "class 2", "class label", "add a class",
        "predicted class", "recognized", "detected class",
        "confidence", "prediction",
    ],
    # ── TensorFlow / TensorFlow.js ────────────────────────────────────────────
    "tensorflow": [
        "tensorflow", "tfjs", "tensorflow.js", "teachable machine",
        "keras", "tensor", "saved model",
    ],
    "tensorflow.js": [
        "tensorflow.js", "tfjs", "teachable machine",
        "javascript ml", "browser ml", "client-side ml",
    ],
    # ── Browser-Based AI ──────────────────────────────────────────────────────
    "browser-based ai": [
        "teachable machine", "tensorflow.js", "tfjs", "browser",
        "in-browser", "client-side", "webcam", "ml5", "ml in the browser",
        "machine learning", "train a computer",
    ],
    # ── Model Testing ─────────────────────────────────────────────────────────
    "model testing": [
        "confidence", "prediction", "predicted", "accuracy",
        "test your model", "output", "result", "score",
        "probability", "your model is ready",
    ],
    # ── Deep Learning ────────────────────────────────────────────────────────
    "deep learning": [
        "neural network", "deep learning", "convolutional", "layers",
        "epochs", "training", "tensorflow", "keras", "pytorch",
    ],
    # ── Computer Vision ──────────────────────────────────────────────────────
    "computer vision": [
        "image", "detect", "detection", "vision", "object", "classify",
        "bounding box", "segmentation", "yolo", "recognition",
    ],
    # ── NLP ──────────────────────────────────────────────────────────────────
    "natural language processing": [
        "nlp", "text", "sentiment", "language model", "bert", "gpt",
        "tokenize", "entity", "summarize", "translate",
    ],
    # ── React / JS frameworks ────────────────────────────────────────────────
    "react": ["react", "component", "jsx", "hooks", "usestate"],
    "next.js": ["next.js", "nextjs", "getstaticprops", "getserversideprops"],
    # ── Generic ML/AI ────────────────────────────────────────────────────────
    "ai": [
        "artificial intelligence", "ai", "machine learning",
        "neural network", "model", "prediction",
    ],
}


# ── OCR page-context classifier ────────────────────────────────────────────────

def _detect_ocr_page_context(ocr_text: str) -> str:
    """Classify OCR text into a page-context category.

    Returns one of:
        "training_ui"         — training data collection / model training UI
        "prediction_output"   — prediction/inference result output shown
        "homepage_marketing"  — platform homepage or marketing page only
        "demo_content"        — demo or tutorial content
        "unknown"             — cannot classify confidently

    Conservative: only returns a specific category when strong signals are present.
    """
    if not ocr_text or not ocr_text.strip():
        return "unknown"

    lower = ocr_text.lower()

    prediction_matches = sum(1 for s in _OCR_PREDICTION_OUTPUT_SIGNALS if s in lower)
    training_matches   = sum(1 for s in _OCR_TRAINING_UI_SIGNALS if s in lower)
    homepage_matches   = sum(1 for s in _OCR_HOMEPAGE_SIGNALS if s in lower)
    has_numeric        = bool(re.search(r"\b\d+(?:\.\d+)?%?\b", ocr_text))

    # Prediction output — check FIRST: confidence/result with numeric values is
    # unambiguous proof of inference being shown, even if "class N" labels appear.
    if prediction_matches >= 2 and has_numeric:
        return "prediction_output"
    if prediction_matches >= 3:
        return "prediction_output"

    # Training UI — explicit training/data-collection actions
    if training_matches >= 2:
        return "training_ui"

    # Homepage/marketing — explicit marketing phrases
    if homepage_matches >= 2:
        return "homepage_marketing"

    # Fallback: single unambiguous match
    if training_matches >= 1:
        return "training_ui"
    if prediction_matches >= 1:
        return "prediction_output"

    return "unknown"


# ── OCR → claimed-skill signal mapper ─────────────────────────────────────────

def _ocr_skill_signals(
    claimed_skills: list[str],
    ocr_text: str,
    page_context: str,
) -> list[dict[str, Any]]:
    """Map claimed skills to OCR-based support signals.

    Returns a list of dicts:
        {
            "skill":          str   — canonical skill name
            "ocr_support":    str   — "partial" | "insufficient"
            "reasoning":      str   — plain-English explanation
            "ocr_terms_found": list[str]  — OCR terms that matched
        }

    Rules:
    • Only "partial" at most — OCR text alone is never "strong" evidence;
      it shows the platform/context was visible, not that the skill was fully exercised.
    • Homepage-only context: skill-agnostic ML terms (e.g. Machine Learning,
      Browser-Based AI) → partial; specific workflow skills (Image Classification,
      Model Testing) → insufficient (homepage mentions concept ≠ using the feature).
    • Training UI context: classification-related skills → partial.
    • Prediction output context: testing/classification/ML skills → partial.
    """
    if not ocr_text.strip():
        return []

    ocr_lower = ocr_text.lower()
    signals: list[dict[str, Any]] = []

    for raw_skill in claimed_skills:
        canonical = _normalize_skill(raw_skill)
        c_lower = canonical.lower()

        # Build keyword list for this skill
        kw_list = _SKILL_OCR_KEYWORDS.get(c_lower, [])
        if not kw_list:
            # Fallback: use words from the skill name
            kw_list = [w for w in c_lower.split() if len(w) > 3]

        terms_found = [kw for kw in kw_list if kw in ocr_lower]

        if not terms_found:
            signals.append({
                "skill": canonical,
                "ocr_support": "insufficient",
                "reasoning": (
                    f"No OCR text relevant to '{canonical}' was detected in the keyframes. "
                    "The recording frames may not show this skill being used."
                ),
                "ocr_terms_found": [],
            })
            continue

        # Determine support level based on context
        ocr_terms_str = "', '".join(terms_found[:3])

        # Skills that require specific interactive UI evidence (not just platform text)
        _requires_ui_evidence = frozenset({
            "image classification", "model testing", "object detection",
            "computer vision", "natural language processing",
        })

        if page_context == "homepage_marketing":
            if c_lower in _requires_ui_evidence:
                # Homepage mentions the concept but doesn't show it being done
                signals.append({
                    "skill": canonical,
                    "ocr_support": "insufficient",
                    "reasoning": (
                        f"OCR found '{ocr_terms_str}' but this appears in homepage/marketing text. "
                        f"'{canonical}' requires observing the actual feature "
                        "(training classes, prediction output, or classification result) — "
                        "which was not detected in the keyframes."
                    ),
                    "ocr_terms_found": terms_found[:5],
                })
            else:
                # Platform-level skills (Machine Learning, Browser-Based AI) are
                # partially supported even from homepage — the platform itself is relevant
                signals.append({
                    "skill": canonical,
                    "ocr_support": "partial",
                    "reasoning": (
                        f"OCR detected '{ocr_terms_str}' in keyframes. "
                        "Content appears to be homepage/platform description — "
                        "the recording shows the platform context for this skill, "
                        "but an interactive demonstration was not observed."
                    ),
                    "ocr_terms_found": terms_found[:5],
                })

        elif page_context == "training_ui":
            signals.append({
                "skill": canonical,
                "ocr_support": "partial",
                "reasoning": (
                    f"OCR detected '{ocr_terms_str}' and training UI was visible in keyframes. "
                    f"The recording shows training-related activity relevant to '{canonical}'."
                ),
                "ocr_terms_found": terms_found[:5],
            })

        elif page_context == "prediction_output":
            signals.append({
                "skill": canonical,
                "ocr_support": "partial",
                "reasoning": (
                    f"OCR detected '{ocr_terms_str}' and prediction/output content was visible. "
                    f"Evidence supports '{canonical}' being exercised."
                ),
                "ocr_terms_found": terms_found[:5],
            })

        else:
            # Unknown context — conservative partial if terms found
            signals.append({
                "skill": canonical,
                "ocr_support": "partial",
                "reasoning": (
                    f"OCR detected '{ocr_terms_str}' in keyframes. "
                    f"Partial contextual evidence supports '{canonical}'."
                ),
                "ocr_terms_found": terms_found[:5],
            })

    return signals


# ── Frame OCR evidence summary builder ────────────────────────────────────────

def _build_frame_ocr_evidence_summary(
    visual_frame_observations: dict[str, Any] | None,
    claimed_skills: list[str],
) -> dict[str, Any]:
    """Build a structured frame/OCR evidence summary for display.

    Returned dict:
        has_ocr_evidence      bool
        ocr_provider          str
        frames_analyzed       int
        top_ocr_snippets      list[str]   — top N cleaned, deduped text snippets
        detected_page_context str         — homepage_marketing | training_ui | prediction_output | unknown
        observed_summary      str         — what was visually/textually observed
        what_was_not_observed list[str]   — specific things not observed
        skill_signals         list[dict]  — per-skill OCR support signals
    """
    if not visual_frame_observations:
        return {
            "has_ocr_evidence": False,
            "ocr_provider": "none",
            "frames_analyzed": 0,
            "top_ocr_snippets": [],
            "detected_page_context": "unknown",
            "observed_summary": "No keyframe OCR evidence was available.",
            "what_was_not_observed": [],
            "skill_signals": [],
        }

    vf_status = visual_frame_observations.get("visual_frame_analysis_status", "not_configured")
    if vf_status not in ("analyzed",):
        return {
            "has_ocr_evidence": False,
            "ocr_provider": visual_frame_observations.get("provider_used", "none"),
            "frames_analyzed": visual_frame_observations.get("visual_frame_count", 0),
            "top_ocr_snippets": [],
            "detected_page_context": "unknown",
            "observed_summary": (
                "Keyframes were extracted but OCR/visual analysis was not configured. "
                "Set VISUAL_ANALYSIS_PROVIDER=local_ocr to enable frame text analysis."
                if vf_status == "not_configured" else
                "Frame OCR analysis was not completed for this recording."
            ),
            "what_was_not_observed": [],
            "skill_signals": [],
        }

    visual_summary = visual_frame_observations.get("visual_summary", "") or ""
    frames_analyzed = visual_frame_observations.get("visual_frame_count", 0)
    provider = visual_frame_observations.get("provider_used", "local_ocr")

    # Extract and clean top OCR snippets
    raw_snippets = [s.strip() for s in visual_summary.split("|") if s.strip()]
    # Filter out known noisy snippets
    clean_snippets: list[str] = []
    for s in raw_snippets:
        lower_s = s.lower()
        if any(noise in lower_s for noise in _OCR_NOISE_SNIPPETS):
            continue
        if len(s) < 3:
            continue
        clean_snippets.append(s[:120])   # cap snippet length

    top_snippets = clean_snippets[:8]

    # Detect page context from the combined OCR text
    page_context = _detect_ocr_page_context(visual_summary)

    # What was and wasn't observed based on context
    what_was_not_observed: list[str] = []

    if page_context == "homepage_marketing":
        observed_summary = (
            f"OCR text from {frames_analyzed} keyframe(s) shows homepage or platform "
            "description content. The recording appears to capture the platform landing page "
            "rather than interactive features. No training UI, classification classes, "
            "or prediction output was detected in the keyframes."
        )
        what_was_not_observed = [
            "training UI (e.g. 'Add Image Samples', class labels, training progress)",
            "classification output or prediction results",
            "confidence scores or model output values",
        ]

    elif page_context == "training_ui":
        observed_summary = (
            f"OCR text from {frames_analyzed} keyframe(s) shows training-related content. "
            "The recording appears to capture training data collection or model training activity."
        )
        what_was_not_observed = [
            "prediction output or test results (test your model phase)",
        ]

    elif page_context == "prediction_output":
        observed_summary = (
            f"OCR text from {frames_analyzed} keyframe(s) shows prediction or output content. "
            "The recording appears to capture model inference/testing results."
        )
        what_was_not_observed = []

    else:
        observed_summary = (
            f"OCR text from {frames_analyzed} keyframe(s) was analyzed. "
            "The page context could not be clearly classified as training UI or prediction output."
        )
        if not top_snippets:
            observed_summary = (
                f"OCR analysis ran on {frames_analyzed} keyframe(s) but extracted minimal text. "
                "The recording frames may show graphical content (charts, canvas) or low-contrast text."
            )
            what_was_not_observed = ["readable text in keyframes"]

    # Skill signals
    skill_signals = _ocr_skill_signals(claimed_skills, visual_summary, page_context)

    return {
        "has_ocr_evidence": True,
        "ocr_provider": provider,
        "frames_analyzed": frames_analyzed,
        "top_ocr_snippets": top_snippets,
        "detected_page_context": page_context,
        "observed_summary": observed_summary,
        "what_was_not_observed": what_was_not_observed,
        "skill_signals": skill_signals,
    }


# ── URL filtering: noise patterns ─────────────────────────────────────────────

# Exact netlocs that are always noise (no matter what path)
_NOISE_NETLOCS: frozenset[str] = frozenset({
    "app.supabase.io",
    "studio.supabase.com",
    "supabase.com",
    "api.supabase.io",
})

# Netloc suffixes → always noise
_NOISE_NETLOC_SUFFIXES: tuple[str, ...] = (
    ".supabase.io",
    ".supabase.co",
)

# Netloc + path prefix combos that are VeriBridge internal routes
# (VeriBridge app runs on localhost:3000 in development)
_VERIBRIDGE_LOCALHOST_NETLOCS: frozenset[str] = frozenset({
    "localhost:3000",
    "127.0.0.1:3000",
})

# Path prefixes that mark a URL as a VeriBridge internal dashboard page
_VERIBRIDGE_INTERNAL_PATH_PREFIXES: tuple[str, ...] = (
    "/dashboard/",
    "/dashboard",
)


def _safe_netloc(url: str) -> str:
    """Extract netloc (host:port) from a URL, lowercased. Returns '' on failure."""
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_veribridge_internal(url: str) -> bool:
    """Return True if this URL is a VeriBridge internal dashboard page."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()
        if netloc in _VERIBRIDGE_LOCALHOST_NETLOCS:
            for prefix in _VERIBRIDGE_INTERNAL_PATH_PREFIXES:
                if path.startswith(prefix) or path == prefix.rstrip("/"):
                    return True
    except Exception:
        pass
    return False


def _classify_url(
    url: str,
    target_netloc: str,
    github_netloc: str | None,
) -> str:
    """Classify a URL into 'target', 'supporting', or 'noise'.

    target:     URL is on the same domain/netloc as the proof target site.
    supporting: URL is on GitHub and a github_url was provided.
    noise:      Everything else — VeriBridge internal, Supabase, unrelated tabs.
    """
    if not url:
        return "noise"
    if _is_chrome_internal(url):
        return "noise"

    # VeriBridge internal dashboard routes → always noise
    if _is_veribridge_internal(url):
        return "noise"

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        # Known noise netlocs
        if netloc in _NOISE_NETLOCS:
            return "noise"
        for suffix in _NOISE_NETLOC_SUFFIXES:
            if netloc.endswith(suffix):
                return "noise"

        # Target site match (exact netloc)
        if target_netloc and netloc == target_netloc:
            return "target"

        # GitHub supporting evidence (only when github_url is configured)
        if github_netloc:
            if netloc in ("github.com", "raw.githubusercontent.com", "gist.github.com"):
                return "supporting"
            if netloc == github_netloc:
                return "supporting"

        # Everything else: unrelated tab → noise
        return "noise"

    except Exception:
        return "noise"


class ExtensionProofWorkflowAnalysisService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def run_analysis(
        self,
        user_id: str,
        session_id: str,
        claimed_skills: list[str],
        proof_objective: str,
        original_url: str,
        url_type: str,
        github_url: str | None,
    ) -> dict[str, Any]:
        """Run workflow analysis and persist the result.

        Computes the analysis in-memory first, then persists best-effort.
        Always returns a result dict — never raises due to DB failures.
        A '_db_saved' key indicates whether the result was persisted.
        """
        logger.info("WORKFLOW_ANALYSIS_START session=%s user=%s", session_id, user_id)

        session = self._get_session(user_id, session_id)
        current_status = session.get("status", "")

        if current_status not in _VALID_ANALYZE_FROM:
            raise InvalidAnalysisStateError(
                f"Cannot analyze a session with status '{current_status}'. "
                f"Allowed from: {sorted(_VALID_ANALYZE_FROM)}."
            )

        if current_status == "uploaded_pending_analysis":
            try:
                self._update_session_status(user_id, session_id, "analyzing")
            except Exception:
                logger.warning(
                    "WORKFLOW_ANALYSIS_STATUS_ANALYZING_FAILED session=%s",
                    session_id, exc_info=True,
                )

        logger.info("WORKFLOW_ANALYSIS_LOADING_METADATA session=%s", session_id)
        proof_data: dict[str, Any] = session.get("proof_data") or {}

        event_count = len(proof_data.get("workflow_events") or [])
        logger.info(
            "WORKFLOW_ANALYSIS_READING_TIMELINE session=%s events=%d",
            session_id, event_count,
        )
        logger.info(
            "WORKFLOW_ANALYSIS_MATCHING_OBJECTIVE session=%s objective=%r",
            session_id, (proof_objective or "")[:80],
        )
        logger.info(
            "WORKFLOW_ANALYSIS_MATCHING_SKILLS session=%s skills=%s",
            session_id, claimed_skills,
        )
        logger.info("WORKFLOW_ANALYSIS_GENERATING_SUMMARY session=%s", session_id)

        # ── Load visible evidence observations (v4) ────────────────────────
        visible_observations = None
        try:
            from app.services.workflow_visible_evidence_service import (
                WorkflowVisibleEvidenceService,
            )
            ve_svc = WorkflowVisibleEvidenceService(self._client)
            obs = ve_svc.get_extracted_observations(user_id, session_id)
            if obs.visible_evidence_status != "not_captured":
                visible_observations = obs
                logger.info(
                    "WORKFLOW_ANALYSIS_VISIBLE_EVIDENCE_LOADED session=%s status=%s events=%d",
                    session_id, obs.visible_evidence_status, obs.event_count,
                )
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_VISIBLE_EVIDENCE_LOAD_FAILED session=%s — continuing without",
                session_id, exc_info=True,
            )

        # ── Load visual frame evidence (v5) ────────────────────────────────
        # Provider-agnostic visual analysis (local OCR / local vision / OpenAI / future).
        # If no provider is configured, visual_frame_observations is None — safe fallback.
        visual_frame_observations: dict | None = None
        try:
            from app.services.workflow_visual_analysis_service import (
                WorkflowVisualAnalysisService,
            )
            va_svc = WorkflowVisualAnalysisService(self._client)
            vf_obs = va_svc.get_visual_observations(user_id, session_id)
            # Only use if frames were actually captured and analyzed
            if vf_obs.get("visual_frame_analysis_status") not in ("not_captured", "not_configured"):
                visual_frame_observations = vf_obs
                logger.info(
                    "WORKFLOW_ANALYSIS_VISUAL_FRAMES_LOADED session=%s status=%s frames=%d",
                    session_id,
                    vf_obs.get("visual_frame_analysis_status"),
                    vf_obs.get("visual_frame_count", 0),
                )
            else:
                # Capture the status even when no frames available (for status fields)
                visual_frame_observations = vf_obs
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_VISUAL_FRAMES_LOAD_FAILED session=%s — continuing without",
                session_id, exc_info=True,
            )

        # ── Load stored video keyframe timestamps for sequence analysis ──────────
        # These come from the workflow/video upload endpoint (VideoKeyframeExtractorService).
        # Used to provide temporal anchoring to the sequence analysis even when
        # _analyze_workflow is a pure function with no DB access.
        stored_keyframe_timestamps: list[int] = []
        try:
            _kf_ts_resp = (
                self._client.table("workflow_visual_frame_evidence")
                .select("timestamp_ms")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .eq("frame_type", "video_keyframe")
                .order("timestamp_ms", desc=False)
                .execute()
            )
            stored_keyframe_timestamps = sorted([
                int(r["timestamp_ms"])
                for r in (_kf_ts_resp.data or [])
                if r.get("timestamp_ms") is not None
            ])
            if stored_keyframe_timestamps:
                logger.info(
                    "WORKFLOW_ANALYSIS_KF_TIMESTAMPS_LOADED session=%s count=%d",
                    session_id, len(stored_keyframe_timestamps),
                )
        except Exception:
            logger.debug(
                "WORKFLOW_ANALYSIS_KF_TIMESTAMPS_LOAD_FAILED session=%s — continuing without",
                session_id, exc_info=True,
            )

        result = _analyze_workflow(
            proof_data=proof_data,
            claimed_skills=claimed_skills,
            proof_objective=proof_objective,
            original_url=original_url,
            url_type=url_type,
            github_url=github_url,
            visible_observations=visible_observations,
            visual_frame_observations=visual_frame_observations,
            stored_keyframe_timestamps=stored_keyframe_timestamps,
        )

        logger.info("WORKFLOW_ANALYSIS_DB_INSERT_START session=%s", session_id)
        db_saved = False
        row: dict[str, Any]
        try:
            row = self._upsert_result(user_id, session_id, result)
            db_saved = True
            logger.info("WORKFLOW_ANALYSIS_DB_INSERT_SUCCESS session=%s", session_id)
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_DB_INSERT_FAILED session=%s — degrading to in-memory result",
                session_id, exc_info=True,
            )
            now = _now()
            row = {
                "id": f"mem-{session_id[:8]}",
                "user_id": user_id,
                "proof_session_id": session_id,
                "analyzer_version": ANALYZER_VERSION,
                "created_at": now,
                "updated_at": now,
                **result,
            }

        try:
            self._update_session_status(user_id, session_id, "completed")
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_STATUS_COMPLETED_FAILED session=%s",
                session_id, exc_info=True,
            )

        row["_db_saved"] = db_saved
        logger.info(
            "WORKFLOW_ANALYSIS_COMPLETE session=%s score=%d confidence=%s db_saved=%s",
            session_id,
            result.get("evidence_strength_score", 0),
            result.get("workflow_confidence", ""),
            db_saved,
        )
        return row

    def get_latest(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            store = self._client.get(_TABLE, {})
            for row in store.values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None

        try:
            result = (
                self._client.table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            return rows[0] if rows else None
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_GET_LATEST_FAILED session=%s — table may not exist yet",
                session_id, exc_info=True,
            )
            return None

    def _get_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.get(_SESSION_TABLE, {}).get(session_id)
            if not row or str(row.get("user_id")) != user_id:
                raise SessionNotFoundError(session_id)
            return row

        result = (
            self._client.table(_SESSION_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if result is None or result.data is None:
            raise SessionNotFoundError(session_id)
        return result.data

    def _update_session_status(
        self, user_id: str, session_id: str, new_status: str
    ) -> None:
        if isinstance(self._client, dict):
            store = self._client.setdefault(_SESSION_TABLE, {})
            if session_id in store:
                store[session_id]["status"] = new_status
            return

        self._client.table(_SESSION_TABLE).update(
            {"status": new_status, "updated_at": _now()}
        ).eq("user_id", user_id).eq("id", session_id).execute()

    def _upsert_result(
        self,
        user_id: str,
        session_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        data: dict[str, Any] = {
            "user_id": user_id,
            "proof_session_id": session_id,
            "analyzer_version": ANALYZER_VERSION,
            "updated_at": now,
            **result,
        }

        if isinstance(self._client, dict):
            store = self._client.setdefault(_TABLE, {})
            existing = next(
                (r for r in store.values() if str(r.get("proof_session_id")) == session_id),
                None,
            )
            if existing:
                updated = {**existing, **data}
                store[existing["id"]] = updated
                return updated
            row = {"id": str(uuid4()), "created_at": now, **data}
            store[row["id"]] = row
            return row

        existing = self.get_latest(user_id, session_id)
        if existing:
            res = (
                self._client.table(_TABLE)
                .update(data)
                .eq("proof_session_id", session_id)
                .eq("user_id", user_id)
                .execute()
            )
            rows = getattr(res, "data", []) or []
            return rows[0] if rows else {**existing, **data}

        insert_data = {"created_at": now, **data}
        res = self._client.table(_TABLE).insert(insert_data).execute()
        rows = getattr(res, "data", []) or []
        if rows:
            return rows[0]
        return insert_data


# ── Stage helpers ─────────────────────────────────────────────────────────────

def _build_completed_stages(
    db_saved: bool = True,
    visible_evidence_status: str = "not_captured",
) -> list[dict[str, Any]]:
    """Return analysis stages with final status after a completed analysis run.

    Stage list matches the 10-stage visible evidence system (v4).
    video_frame_analysis is 'coming_soon' until frame extraction is implemented.

    Stage 5 (capturing_visible_evidence) reflects DOM/text capture status:
      - complete:  visible evidence was available and used
      - complete (with warning label) if status is "partial"
      - complete (with not_captured label) if old recording
    """
    # Determine stage 5 label and warning
    if visible_evidence_status == "available":
        ve_label = "Capturing visible page evidence"
        ve_status = "complete"
    elif visible_evidence_status == "partial":
        ve_label = "Capturing visible page evidence (partial)"
        ve_status = "complete"
    else:
        ve_label = "Capturing visible page evidence (not captured for this recording)"
        ve_status = "complete"

    return [
        {"key": "preparing_recording",       "label": "Preparing recording",                    "status": "complete"},
        {"key": "filtering_tabs",            "label": "Filtering background tabs",               "status": "complete"},
        {"key": "identifying_target",        "label": "Identifying target website",              "status": "complete"},
        {"key": "extracting_events",         "label": "Extracting relevant workflow events",     "status": "complete"},
        {"key": "capturing_visible_evidence","label": ve_label,                                  "status": ve_status,
         "note": None if visible_evidence_status == "available" else
                 "Use a new recording after this update to capture visible evidence." if visible_evidence_status == "not_captured" else None},
        {"key": "detecting_iao_flow",        "label": "Detecting input → action → output flow", "status": "complete"},
        {"key": "extracting_result_values",  "label": "Extracting result values from visible text", "status": "complete"},
        {"key": "mapping_skills",            "label": "Mapping demonstration to skills",         "status": "complete"},
        {"key": "generating_summary",        "label": "Generating recruiter-safe summary",       "status": "complete"},
        {"key": "finalizing",                "label": "Finalizing Work Passport evidence",        "status": "complete" if db_saved else "failed"},
        # ── Video recording + visual frame evidence stages ─────────────────────
        # Phase 0 (unified recorder): MediaRecorder WebM video uploaded, keyframes extracted.
        {"key": "video_recording",           "label": "Screen recording + keyframe extraction",   "status": "complete"},
        # Screenshot evidence (captureVisibleTab helper — supplementary DOM evidence).
        {"key": "visual_frame_capture",      "label": "Visual frame capture (DOM screenshot evidence)", "status": "complete"},
    ]


# ── Exceptions ────────────────────────────────────────────────────────────────

class SessionNotFoundError(LookupError):
    pass


class InvalidAnalysisStateError(ValueError):
    pass


# ── App-type detection ────────────────────────────────────────────────────────

def _detect_app_type(
    original_url: str,
    target_visited_titles: list[str],
    target_events: list[dict[str, Any]],
    proof_objective: str,
) -> str:
    """Classify the target app into a broad category for IAO interpretation.

    Returns one of: "ml_app", "chatbot", "route_map", "dashboard",
                    "document", "portfolio", "generic"
    """
    text = " ".join([
        original_url.lower(),
        " ".join(t.lower() for t in target_visited_titles),
        proof_objective.lower(),
        " ".join(
            (e.get("element_text") or "").lower() +
            (e.get("page_title") or "").lower()
            for e in target_events
        ),
    ])

    def _match(signals: tuple[str, ...]) -> bool:
        return any(s in text for s in signals)

    if _match(_ML_APP_SIGNALS):
        return "ml_app"
    if _match(_CHATBOT_SIGNALS):
        return "chatbot"
    if _match(_ROUTE_MAP_SIGNALS):
        return "route_map"
    if _match(_DASHBOARD_SIGNALS):
        return "dashboard"
    if _match(_DOCUMENT_SIGNALS):
        return "document"

    # Portfolio: static site on github.io or simple personal page
    try:
        from urllib.parse import urlparse
        netloc = urlparse(original_url).netloc.lower()
        if netloc.endswith("github.io"):
            return "portfolio"
    except Exception:
        pass

    return "generic"


# ── IAO pattern extraction ────────────────────────────────────────────────────

def _extract_iao_patterns(
    target_events: list[dict[str, Any]],
    app_type: str,
) -> list[dict[str, Any]]:
    """Identify input → action → output patterns from the event timeline.

    Returns a list of IAO pattern dicts:
        {
            "input_event":   dict | None,
            "action_event":  dict | None,
            "output_event":  dict | None,
            "pattern_type":  str,
        }

    NOTE: since frame/OCR is not available, actual output VALUES (e.g. "dog 0.89")
    cannot be extracted. We detect the PATTERN of what happened, not the exact values.
    """
    patterns: list[dict[str, Any]] = []

    upload_events: list[dict[str, Any]] = []
    action_events: list[dict[str, Any]] = []
    output_page_events: list[dict[str, Any]] = []
    input_text_events: list[dict[str, Any]] = []

    for event in target_events:
        etype = event.get("type", "")
        etext = (event.get("element_text") or "").lower()
        eid   = (event.get("element_id") or "").lower()
        title = (event.get("page_title") or "").lower()
        url   = (event.get("page_url") or "").lower()

        # Detect file/image upload interactions
        if etype in ("click", "input_change"):
            if any(s in etext or s in eid for s in _UPLOAD_TRIGGER_TEXTS):
                upload_events.append(event)
            elif etype == "input_change" and any(
                s in eid for s in ("file", "image", "photo", "upload", "img", "pic")
            ):
                upload_events.append(event)

        # Detect text/query input
        if etype == "input_change" and any(
            s in eid for s in ("text", "query", "search", "input", "message", "prompt", "q", "keyword")
        ):
            input_text_events.append(event)

        # Detect action triggers (predict, run, submit, etc.)
        if etype == "click" and any(s in etext for s in _ACTION_TRIGGER_TEXTS):
            action_events.append(event)

        # Detect result/output page visits.
        # Require a path segment like /result, /output, /prediction, etc. OR that
        # the matching signal word appears in the PAGE TITLE only (not the app name).
        # This avoids misclassifying "Object Detection Demo" landing page as output.
        if etype in ("page_visit", "navigation"):
            parsed_path = ""
            try:
                from urllib.parse import urlparse as _up
                parsed_path = _up(url).path.lower()
            except Exception:
                pass
            path_match = any(
                s in parsed_path for s in ("result", "output", "prediction", "report", "summary")
            )
            # Only treat as output if path match OR title has dedicated result words
            # (excluding broad ml-domain words like "detection" to avoid false positives)
            _result_only_signals = ("result", "output", "prediction", "report", "summary", "response", "answer", "evaluation", "score", "insights")
            title_result_match = any(s in title for s in _result_only_signals)
            if path_match or title_result_match:
                output_page_events.append(event)

    # ── Assemble patterns ─────────────────────────────────────────────────────

    if app_type == "ml_app":
        if upload_events or action_events:
            patterns.append({
                "input_event":   (upload_events or [None])[0],
                "action_event":  (action_events or [None])[0],
                "output_event":  (output_page_events or [None])[0],
                "pattern_type":  "image_to_prediction",
            })
    elif app_type == "chatbot":
        if input_text_events or action_events:
            patterns.append({
                "input_event":  (input_text_events or [None])[0],
                "action_event": (action_events or [None])[0],
                "output_event": (output_page_events or [None])[0],
                "pattern_type": "prompt_to_response",
            })
    elif app_type == "route_map":
        if input_text_events or action_events:
            patterns.append({
                "input_event":  (input_text_events or [None])[0],
                "action_event": (action_events or [None])[0],
                "output_event": (output_page_events or [None])[0],
                "pattern_type": "location_to_route_or_risk",
            })
    elif app_type == "dashboard":
        if action_events or target_events:
            patterns.append({
                "input_event":  (action_events or [None])[0],
                "action_event": (action_events or [None])[0],
                "output_event": (output_page_events or [None])[0],
                "pattern_type": "filter_to_visualization",
            })
    elif app_type == "document":
        if upload_events or action_events:
            patterns.append({
                "input_event":   (upload_events or [None])[0],
                "action_event":  (action_events or [None])[0],
                "output_event":  (output_page_events or [None])[0],
                "pattern_type":  "document_to_extraction",
            })
    else:
        # Generic: just report what happened
        if action_events:
            patterns.append({
                "input_event":   (upload_events or input_text_events or [None])[0],
                "action_event":  action_events[0],
                "output_event":  (output_page_events or [None])[0],
                "pattern_type":  "generic_interaction",
            })

    return patterns


# ── Demonstration steps builder ───────────────────────────────────────────────

_APP_TYPE_FEATURE_LABELS: dict[str, str] = {
    "ml_app":       "Machine learning inference (input → prediction)",
    "chatbot":      "Conversational AI (prompt → response)",
    "route_map":    "Route/risk analysis (location input → map or risk output)",
    "dashboard":    "Data visualization (filter → chart/metric output)",
    "document":     "Document processing (file → extracted content)",
    "portfolio":    "Portfolio presentation",
    "generic":      "Web application interaction",
}

_PATTERN_SKILL_MAP: dict[str, list[tuple[str, str, str]]] = {
    # pattern_type → list of (skill, support_level, reasoning)
    "image_to_prediction": [
        ("Object Detection",      "strong",  "Image-input to prediction-output workflow observed"),
        ("Computer Vision",       "strong",  "Visual input was processed by the application"),
        ("ML Inference",          "partial", "Prediction output was displayed; model type requires code evidence"),
        ("TensorFlow.js",         "partial", "Client-side ML inferred; requires GitHub/code confirmation"),
    ],
    "prompt_to_response": [
        ("Chatbot Development",   "strong",  "Prompt-response conversational flow observed"),
        ("LLM Integration",       "partial", "LLM-backed response observed; requires code to confirm model"),
        ("Natural Language Processing", "partial", "Text processing evidenced by response output"),
    ],
    "location_to_route_or_risk": [
        ("Geospatial Analysis",   "strong",  "Location input to route/risk output observed"),
        ("Mapping/GIS",           "partial", "Map or routing visualization shown"),
        ("Risk Assessment",       "partial", "Risk or risk-score output observed; requires code to confirm ML model"),
    ],
    "filter_to_visualization": [
        ("Data Visualization",    "strong",  "Dashboard/chart update from filter interaction observed"),
        ("Data Analytics",        "partial", "Metrics or chart output shown; requires code to confirm data source"),
    ],
    "document_to_extraction": [
        ("Document Processing",   "strong",  "Document upload to extraction/summary output observed"),
        ("Information Extraction","partial", "Extracted content shown; requires code to confirm NLP pipeline"),
    ],
    "generic_interaction": [
        ("Web Development",       "partial", "User interaction with a web application observed"),
    ],
}


def _build_demonstration_steps(
    target_events: list[dict[str, Any]],
    iao_patterns: list[dict[str, Any]],
    app_type: str,
    target_app: str,
    visible_observations: "Any | None" = None,
) -> list[dict[str, Any]]:
    """Build structured DemonstrationStep-like dicts from the event timeline.

    When visible_observations is provided (DOM snapshots captured by extension),
    detected_result_values and visible_text_evidence are enriched from that data.
    evidence_source shows "dom_snapshot" vs "event_metadata" vs "inferred_from_click".

    Without visible_observations (old recordings), detected_result_values is empty.
    """
    steps: list[dict[str, Any]] = []
    step_num = 1

    # Resolve visible observations helpers
    _vis_inputs: list[str] = []
    _vis_actions: list[str] = []
    _vis_outputs: list[str] = []
    _vis_result_values: list[dict[str, Any]] = []
    _vis_features: list[str] = []
    _has_visible_evidence = False

    if visible_observations is not None:
        _vis_inputs  = list(getattr(visible_observations, "observed_inputs",  []) or [])
        _vis_actions = list(getattr(visible_observations, "observed_actions", []) or [])
        _vis_outputs = list(getattr(visible_observations, "observed_outputs", []) or [])
        _vis_features = list(getattr(visible_observations, "demonstrated_features", []) or [])
        raw_rv = getattr(visible_observations, "detected_result_values", []) or []
        # Convert ExtractedResultValue objects to dicts for the step schema
        for rv in raw_rv:
            _vis_result_values.append({
                "label": getattr(rv, "label", ""),
                "value": getattr(rv, "value", ""),
                "confidence": None,
                "source": getattr(rv, "source", "dom"),
            })
        _has_visible_evidence = bool(_vis_inputs or _vis_actions or _vis_outputs or _vis_result_values)

    # Step 1: App opened
    first_page = next(
        (e for e in target_events if e.get("type") == "page_visit"), None
    )
    title_hint = (first_page.get("page_title") or "") if first_page else ""
    visible_features = _vis_features[:2] if _vis_features else ([title_hint] if title_hint else [])

    steps.append({
        "step_number": step_num,
        "timestamp_ms": None,
        "user_action": f"Opened target application: {target_app or 'target app'}",
        "observed_input": None,
        "observed_output": None,
        "visible_text_evidence": visible_features,
        "detected_result_values": [],
        "demonstrated_feature": "Application launch",
        "skill_evidence": [],
        "confidence": "high",
        "needs_review": False,
        "evidence_source": "event_metadata",
    })
    step_num += 1

    # Steps from IAO patterns
    pattern_skill_map = _PATTERN_SKILL_MAP.get(
        (iao_patterns[0]["pattern_type"] if iao_patterns else "generic_interaction"),
        _PATTERN_SKILL_MAP["generic_interaction"],
    )

    for pattern in iao_patterns:
        ptype = pattern["pattern_type"]
        input_ev  = pattern.get("input_event")
        action_ev = pattern.get("action_event")
        output_ev = pattern.get("output_event")

        # Step: input provided
        if input_ev:
            input_text = input_ev.get("element_text") or ""
            eid = input_ev.get("element_id") or ""
            etype = input_ev.get("type", "")

            if ptype == "image_to_prediction":
                action_desc = "Uploaded or selected an image/file as input"
                observed_in = f"Image/file selected via {eid or input_text or 'upload control'}"
            elif ptype == "document_to_extraction":
                action_desc = "Uploaded a document for processing"
                observed_in = f"Document uploaded via {eid or input_text or 'upload control'}"
            elif ptype == "prompt_to_response":
                action_desc = "Entered a text prompt or message"
                observed_in = f"Text entered in {eid or 'input field'}"
            elif ptype == "location_to_route_or_risk":
                action_desc = "Entered a location, address, or route"
                observed_in = f"Location data entered in {eid or 'input field'}"
            else:
                action_desc = f"Provided input via {eid or input_text or 'form field'}"
                observed_in = eid or input_text or "form input"

            # Enrich with visible input observations
            vis_input_text: list[str] = []
            if _vis_inputs:
                vis_input_text = _vis_inputs[:3]
                observed_in = _vis_inputs[0] if _vis_inputs else observed_in
            elif input_text:
                vis_input_text = [input_text]

            input_confidence = "high" if _has_visible_evidence else "medium"
            input_source = "dom_snapshot" if _vis_inputs else "event_metadata"

            steps.append({
                "step_number": step_num,
                "timestamp_ms": None,
                "user_action": action_desc,
                "observed_input": observed_in,
                "observed_output": None,
                "visible_text_evidence": vis_input_text,
                "detected_result_values": [],
                "demonstrated_feature": _APP_TYPE_FEATURE_LABELS.get(app_type, "Web interaction"),
                "skill_evidence": [],
                "confidence": input_confidence,
                "needs_review": not _has_visible_evidence,
                "evidence_source": input_source,
            })
            step_num += 1

        # Step: action triggered
        if action_ev:
            action_text = action_ev.get("element_text") or "button"
            vis_action_text: list[str] = [action_text]
            if _vis_actions:
                vis_action_text = _vis_actions[:3]

            action_source = "dom_snapshot" if _vis_actions else "event_metadata"

            steps.append({
                "step_number": step_num,
                "timestamp_ms": None,
                "user_action": f'Triggered action: clicked "{action_text}"',
                "observed_input": None,
                "observed_output": None,
                "visible_text_evidence": vis_action_text,
                "detected_result_values": [],
                "demonstrated_feature": _APP_TYPE_FEATURE_LABELS.get(app_type, "Web interaction"),
                "skill_evidence": [
                    {
                        "skill": skill,
                        "support_level": level,
                        "reasoning": reasoning,
                    }
                    for skill, level, reasoning in pattern_skill_map[:2]
                ],
                "confidence": "high",
                "needs_review": False,
                "evidence_source": action_source,
            })
            step_num += 1

        # Step: output observed
        if output_ev or _vis_outputs or _vis_result_values:
            out_title = (output_ev.get("page_title") or "") if output_ev else ""
            out_url = (output_ev.get("page_url") or "") if output_ev else ""

            if ptype == "image_to_prediction":
                output_desc = "Prediction or detection results were displayed"
                if _vis_result_values:
                    val_preview = ", ".join(
                        f"{rv['label']}: {rv['value']}"
                        for rv in _vis_result_values[:3]
                    )
                    observed_out = f"Output values captured: {val_preview}"
                elif _vis_outputs:
                    observed_out = _vis_outputs[0]
                elif out_title:
                    observed_out = f"Results page: {out_title}"
                else:
                    observed_out = "Prediction output displayed (exact labels/scores not readable from timeline)"
            elif ptype == "prompt_to_response":
                output_desc = "AI response or answer was displayed"
                observed_out = _vis_outputs[0] if _vis_outputs else f"Response shown on: {out_title or out_url}"
            elif ptype == "location_to_route_or_risk":
                output_desc = "Route, map, or risk output was displayed"
                if _vis_result_values:
                    val_preview = ", ".join(
                        f"{rv['label']}: {rv['value']}"
                        for rv in _vis_result_values[:3]
                    )
                    observed_out = f"Risk/route values captured: {val_preview}"
                else:
                    observed_out = _vis_outputs[0] if _vis_outputs else f"Output page: {out_title or out_url}"
            elif ptype == "document_to_extraction":
                output_desc = "Extracted content, summary, or entities displayed"
                observed_out = _vis_outputs[0] if _vis_outputs else f"Extraction output page: {out_title or out_url}"
            elif ptype == "filter_to_visualization":
                output_desc = "Dashboard or visualization updated"
                observed_out = _vis_outputs[0] if _vis_outputs else f"Dashboard page: {out_title or out_url}"
            else:
                output_desc = "Output or result page observed"
                observed_out = _vis_outputs[0] if _vis_outputs else f"{out_title or out_url}"

            output_evidence_text: list[str] = []
            if _vis_outputs:
                output_evidence_text = _vis_outputs[:3]
            elif out_title:
                output_evidence_text = [out_title]

            # High confidence if we have real result values from DOM
            output_confidence = "high" if _vis_result_values else ("medium" if _vis_outputs else "medium")
            output_source = (
                "dom_snapshot" if _vis_result_values else
                "dom_snapshot" if _vis_outputs else
                "event_metadata"
            )
            output_needs_review = not bool(_vis_result_values or _vis_outputs)

            steps.append({
                "step_number": step_num,
                "timestamp_ms": None,
                "user_action": output_desc,
                "observed_input": None,
                "observed_output": observed_out,
                "visible_text_evidence": output_evidence_text,
                # Populated with real DOM-extracted values if visible evidence captured
                "detected_result_values": _vis_result_values,
                "demonstrated_feature": _APP_TYPE_FEATURE_LABELS.get(app_type, "Web interaction"),
                "skill_evidence": [
                    {
                        "skill": skill,
                        "support_level": level,
                        "reasoning": reasoning,
                    }
                    for skill, level, reasoning in pattern_skill_map
                ],
                "confidence": output_confidence,
                "needs_review": output_needs_review,
                "evidence_source": output_source,
            })
            step_num += 1

    return steps


def _build_observed_demonstration(
    target_events: list[dict[str, Any]],
    app_type: str,
    target_app: str,
    iao_patterns: list[dict[str, Any]],
    visible_observations: "Any | None" = None,
    visual_frame_observations: "dict | None" = None,
) -> dict[str, Any]:
    """Build the observed_demonstration structure.

    visual_analysis_status: dynamically derived from visual_frame_observations.
      Values: not_configured | pending | analyzed | failed | skipped
      "not_configured" when visual_frame_observations is None or provider not set.
      "analyzed" when a local OCR/vision provider ran successfully.
    dom_evidence_status reflects DOM text capture from the browser extension — this IS
    available and should be shown positively when the extension captured page text.

    When visible_observations is provided:
    - detected_result_values may be populated with exact output values
    - visible_text_evidence is enriched with DOM-captured text
    - evidence_source per step is "dom_snapshot" or "event_metadata"

    When visual_frame_observations is provided:
    - visual_analysis_status and ocr_status are derived from actual analysis results
    - The "not configured" limitation is only added when provider truly not configured

    Limitations are surfaced honestly, distinguishing DOM capture from OCR analysis.
    """
    steps = _build_demonstration_steps(
        target_events, iao_patterns, app_type, target_app,
        visible_observations=visible_observations,
    )

    _vis_ev_status = "not_captured"
    _dom_ev_status = "not_captured"
    _has_graphical = False
    _graphical_note: str | None = None
    _top_snippets: list[str] = []
    _page_context: str | None = None

    if visible_observations is not None:
        _vis_ev_status  = getattr(visible_observations, "visible_evidence_status", "not_captured")
        _dom_ev_status  = getattr(visible_observations, "dom_evidence_status", _vis_ev_status)
        _has_graphical  = getattr(visible_observations, "has_graphical_rendering", False)
        _graphical_note = getattr(visible_observations, "graphical_rendering_note", None)
        _top_snippets   = list(getattr(visible_observations, "top_result_snippets", []) or [])
        _page_context   = getattr(visible_observations, "page_context_summary", None)

    # ── Visual frame analysis status — derived, never hardcoded ──────────────────
    # "not_configured" only when the provider genuinely was not set up or no
    # visual_frame_observations dict was passed (e.g. old recording, new session
    # that never submitted frames).
    _vf_status = "not_configured"
    _ocr_status = "not_configured"

    if visual_frame_observations is not None:
        raw_vf = visual_frame_observations.get(
            "visual_frame_analysis_status", "not_configured"
        )
        # "not_captured" means no frames were ever submitted — display as not_configured
        _vf_status = raw_vf if raw_vf != "not_captured" else "not_configured"
        prov = (visual_frame_observations.get("provider_used") or "none").lower()
        if _vf_status == "analyzed" and "ocr" in prov:
            _ocr_status = "analyzed"
        elif _vf_status == "analyzed":
            # Vision model was used (not an OCR pipeline)
            _ocr_status = "not_configured"
        elif _vf_status in ("failed", "pending", "skipped"):
            _ocr_status = _vf_status
        # else: not_configured — ocr_status stays "not_configured"

    # Get result values to decide summary tone
    _has_result_values = any(s.get("detected_result_values") for s in steps)
    _has_dom_evidence  = _dom_ev_status in ("available", "partial")

    # Build honest summary
    ptype = iao_patterns[0]["pattern_type"] if iao_patterns else None

    def _output_note() -> str:
        if _has_result_values:
            return "Exact output values were extracted from the visible page content."
        elif _has_dom_evidence and _has_graphical:
            return (
                "Visible page text was captured. This page uses graphical elements "
                "(charts, canvas, or SVG) — exact visual output values were not readable "
                "from DOM text alone; OCR/frame analysis would be needed for precise values."
            )
        elif _has_dom_evidence:
            return (
                "Visible page text was captured but exact output values were not clearly "
                "identified as numeric labels in the DOM snapshots."
            )
        else:
            return (
                "Exact output values were not readable — visible DOM evidence was not "
                "captured for this recording. Use a new recording to enable DOM capture."
            )

    if ptype == "image_to_prediction":
        summary = (
            "The recording shows an image or file input workflow leading to a prediction "
            "or detection result. The app received an input, ran inference, and displayed "
            f"output. {_output_note()}"
        )
    elif ptype == "prompt_to_response":
        summary = (
            "The recording shows a conversational prompt-response workflow. A text input "
            "was provided and an AI or search response was returned. "
            f"{_output_note()}"
        )
    elif ptype == "location_to_route_or_risk":
        summary = (
            "The recording shows a location input to route or risk output workflow. "
            "A location, address, or route was entered and a result (map, route, or risk "
            f"score) was displayed. {_output_note()}"
        )
    elif ptype == "filter_to_visualization":
        summary = (
            "The recording shows a dashboard or data visualization workflow. Filters or "
            "parameters were adjusted and charts, tables, or metrics were updated. "
            f"{_output_note()}"
        )
    elif ptype == "document_to_extraction":
        summary = (
            "The recording shows a document upload to extraction workflow. A file was "
            "uploaded and the app extracted or summarized content from it. "
            f"{_output_note()}"
        )
    else:
        click_count = sum(1 for e in target_events if e.get("type") == "click")
        input_count = sum(1 for e in target_events if e.get("type") == "input_change")
        if _has_dom_evidence and _page_context:
            summary = (
                f"The recording captures navigation and interaction with {target_app or 'the target application'}. "
                f"{_page_context} "
                f"{_output_note()}"
            )
        else:
            summary = (
                f"The recording shows {click_count} click interaction(s) and "
                f"{input_count} input interaction(s) with {target_app or 'the target application'}. "
                f"{_output_note()}"
            )

    limitations: list[str] = []

    # DOM evidence limitations
    if not _has_dom_evidence:
        limitations.append(
            "Visible DOM evidence was not captured for this recording. "
            "Use a new recording after this update to enable visible evidence capture."
        )
    elif not _has_result_values:
        if _has_graphical:
            # Don't add a duplicate — graphical note handles this
            pass
        else:
            limitations.append(
                "Visible page text was captured but result values (labels, scores, numbers) "
                "were not clearly identified in the captured DOM snapshots."
            )

    # Graphical rendering limitation — most important when outputs are charts/canvas
    if _has_graphical and _graphical_note:
        limitations.append(_graphical_note)

    # Visual frame / OCR limitation — only added when genuinely not configured or failed.
    # "analyzed" / "pending" / "skipped" → provider ran; no limitation needed here.
    if _vf_status == "not_configured":
        limitations.append(
            "Visual frame analysis is not configured.  "
            "Set VISUAL_ANALYSIS_PROVIDER=local_ocr or local_vision to enable "
            "screenshot analysis (DOM evidence is always active regardless)."
        )
    elif _vf_status == "failed":
        limitations.append(
            "Visual frame analysis encountered an error; screenshots may not have been analyzed.  "
            "DOM evidence continues to be used for workflow analysis."
        )
    # "analyzed" | "pending" | "skipped" → no visual-frame limitation needed

    if not iao_patterns:
        limitations.append(
            "No clear input → action → output flow was detected from the event timeline; "
            "the recording may show browsing or navigation without a clear interactive demonstration."
        )

    return {
        "target_app": target_app,
        # Visual analysis status — dynamically derived from visual_frame_observations
        "visual_analysis_status": _vf_status,
        # DOM text capture status — always meaningful regardless of visual provider
        "visible_evidence_status": _vis_ev_status,
        "dom_evidence_status": _dom_ev_status,
        "ocr_status": _ocr_status,
        # Graphical rendering info
        "has_graphical_rendering": _has_graphical,
        # Result snippets for UI surface
        "top_result_snippets": _top_snippets,
        "steps": steps,
        "summary": summary,
        "limitations": limitations,
    }


# ── IAO-aware recruiter summary ────────────────────────────────────────────────

_PTYPE_RECRUITER_INTRO: dict[str, str] = {
    "image_to_prediction": (
        "The student demonstrated an image-input to prediction-output workflow. "
        "An image or file was provided as input, the application ran inference, "
        "and prediction results were displayed."
    ),
    "prompt_to_response": (
        "The student demonstrated a conversational AI workflow. "
        "A text prompt or message was entered and an AI-generated response was returned."
    ),
    "location_to_route_or_risk": (
        "The student demonstrated a geospatial or risk-analysis workflow. "
        "A location or route was entered and a map, route, or risk result was displayed."
    ),
    "filter_to_visualization": (
        "The student demonstrated a data analytics or dashboard workflow. "
        "Filters or parameters were applied and charts or metrics were updated."
    ),
    "document_to_extraction": (
        "The student demonstrated a document processing workflow. "
        "A file was uploaded and the application extracted, summarized, or analysed its content."
    ),
    "generic_interaction": (
        "The student interacted with the target web application, "
        "triggering actions and navigating through the application features."
    ),
}


# ── Core analysis algorithm ───────────────────────────────────────────────────

def _analyze_workflow(
    proof_data: dict[str, Any],
    claimed_skills: list[str],
    proof_objective: str,
    original_url: str,
    url_type: str,
    github_url: str | None,
    visible_observations: "Any | None" = None,
    visual_frame_observations: "dict | None" = None,
    stored_keyframe_timestamps: "list[int] | None" = None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = proof_data.get("workflow_events") or []
    started_at_str: str | None = proof_data.get("started_at")
    stopped_at_str: str | None = proof_data.get("stopped_at")

    # Normalise: split any comma-separated skill strings
    normalized_skills: list[str] = []
    for s in (claimed_skills or []):
        normalized_skills.extend(part.strip() for part in s.split(",") if part.strip())
    claimed_skills = normalized_skills

    # ── URL classification: separate target / supporting / noise ──────────────
    target_netloc = _safe_netloc(original_url)
    github_netloc = _safe_netloc(github_url) if github_url else None

    target_events: list[dict[str, Any]] = []
    supporting_events: list[dict[str, Any]] = []
    noise_events: list[dict[str, Any]] = []

    for event in events:
        url = event.get("page_url") or event.get("url") or ""
        category = _classify_url(url, target_netloc, github_netloc)
        if category == "target":
            target_events.append(event)
        elif category == "supporting":
            supporting_events.append(event)
        else:
            noise_events.append(event)

    # ── Categorize target-site events by type ─────────────────────────────────
    target_page_visits = [e for e in target_events if e.get("type") == "page_visit"]
    target_clicks      = [e for e in target_events if e.get("type") == "click"]
    target_inputs      = [e for e in target_events if e.get("type") == "input_change"]
    target_tab_opens   = [e for e in target_events if e.get("type") == "tab_opened"]
    target_navigations = [e for e in target_events if e.get("type") == "navigation"]

    # All-event counts (for activity / duration signal)
    all_tab_opens = [e for e in events if e.get("type") == "tab_opened"]

    # ── Unique target-site pages and titles ───────────────────────────────────
    target_visited_urls: list[str] = list(dict.fromkeys(
        e.get("page_url", "")
        for e in (target_page_visits + target_navigations)
        if e.get("page_url") and not _is_chrome_internal(e.get("page_url", ""))
    ))
    target_visited_titles: list[str] = list(dict.fromkeys(
        t for e in (target_page_visits + target_navigations)
        if (t := (e.get("page_title") or "").strip())
    ))

    # ── Unique supporting evidence (GitHub) pages ─────────────────────────────
    supporting_visited_urls: list[str] = list(dict.fromkeys(
        e.get("page_url", "")
        for e in supporting_events
        if e.get("page_url") and not _is_chrome_internal(e.get("page_url", ""))
    ))

    # ── Noise URLs (internal/debug only — never surfaced to recruiter) ────────
    noise_urls: list[str] = list(dict.fromkeys(
        e.get("page_url", "")
        for e in noise_events
        if e.get("page_url") and not _is_chrome_internal(e.get("page_url", ""))
    ))

    # ── Recording duration ────────────────────────────────────────────────────
    duration_secs = _compute_duration(started_at_str, stopped_at_str)

    # ── Infer tech stack from TARGET + SUPPORTING URLs only ───────────────────
    inferred_tech = _infer_tech_stack(
        target_visited_urls + supporting_visited_urls,
        target_visited_titles,
        original_url,
    )

    # ── Skill matching ────────────────────────────────────────────────────────
    supported, weakly, unsupported, skill_obs = _match_skills(
        claimed_skills, inferred_tech, proof_objective, original_url, url_type
    )

    # ── Evidence strength score (uses TARGET site counts, not noise) ──────────
    score = _compute_score(
        total_events=len(events),               # all events — activity signal
        page_count=len(target_visited_urls),    # TARGET pages only
        click_count=len(target_clicks),         # TARGET clicks only
        input_count=len(target_inputs),         # TARGET inputs only
        tab_opens=len(all_tab_opens),
        duration_secs=duration_secs,
        url_type=url_type,
        supported_count=len(supported),
        claimed_count=max(1, len(claimed_skills)),
    )

    # ── Confidence ────────────────────────────────────────────────────────────
    confidence = _determine_confidence(score, url_type, len(events), duration_secs)

    # ── App type + IAO pattern detection (v3/v4) ─────────────────────────────
    app_type = _detect_app_type(
        original_url, target_visited_titles, target_events, proof_objective
    )
    iao_patterns = _extract_iao_patterns(target_events, app_type)

    # ── Visible evidence observations (v4) ───────────────────────────────────
    # When the browser extension sent DOM snapshots, integrate them here.
    # For old recordings, visible_observations is None → status stays "not_captured".
    visible_evidence_status: str = "not_captured"
    dom_evidence_status: str = "not_captured"
    has_graphical_rendering: bool = False
    graphical_rendering_note: str | None = None
    top_result_snippets: list[str] = []
    page_context_summary: str | None = None

    if visible_observations is not None:
        visible_evidence_status = getattr(visible_observations, "visible_evidence_status", "not_captured")
        dom_evidence_status     = getattr(visible_observations, "dom_evidence_status", visible_evidence_status)
        has_graphical_rendering = getattr(visible_observations, "has_graphical_rendering", False)
        graphical_rendering_note = getattr(visible_observations, "graphical_rendering_note", None)
        top_result_snippets     = list(getattr(visible_observations, "top_result_snippets", []) or [])
        page_context_summary    = getattr(visible_observations, "page_context_summary", None)

    # ── Visual frame evidence (v5) ────────────────────────────────────────────
    # Evidence priority: DOM values > OCR values > vision summaries > events
    _vf_status: str = "not_configured"
    _ocr_status: str = "not_configured"
    _visual_frame_count: int = 0
    _visual_frames_stored: int = 0    # total frames in DB (inc. not_configured)
    _visual_provider: str = "none"
    _visual_result_values: list[dict] = []
    _visual_summary: str = ""

    if visual_frame_observations is not None:
        raw_vf = visual_frame_observations.get("visual_frame_analysis_status", "not_configured")
        # "not_captured" means no frames were submitted — treat same as not_configured
        _vf_status = raw_vf if raw_vf != "not_captured" else "not_configured"
        _visual_provider = visual_frame_observations.get("provider_used", "none")
        _visual_frame_count = visual_frame_observations.get("visual_frame_count", 0)
        _visual_frames_stored = visual_frame_observations.get("visual_frames_stored", 0)
        _visual_result_values = visual_frame_observations.get("extracted_result_values", [])
        _visual_summary  = visual_frame_observations.get("visual_summary", "")

        # Derive OCR status from provider name
        prov = _visual_provider.lower()
        if _vf_status == "analyzed" and "ocr" in prov:
            _ocr_status = "analyzed"
        elif _vf_status == "analyzed":
            _ocr_status = "not_configured"   # vision model used, not OCR
        else:
            _ocr_status = _vf_status   # propagate not_configured / failed

    # ── Observed demonstration (v3/v4/v5) ─────────────────────────────────────
    target_app_label = target_netloc or _extract_domain(original_url)
    observed_demonstration = _build_observed_demonstration(
        target_events, app_type, target_app_label, iao_patterns,
        visible_observations=visible_observations,
        visual_frame_observations=visual_frame_observations,
    )

    # ── Demonstrated actions (TARGET site events only) ────────────────────────
    demonstrated_actions = _extract_demonstrated_actions(
        target_page_visits, target_clicks, target_inputs,
        target_tab_opens, target_navigations, target_visited_titles,
        supporting_visited_urls=supporting_visited_urls,
        noise_count=len(noise_urls),
    )

    # ── Frame OCR evidence summary (v6) ──────────────────────────────────────
    # Summarises what OCR/visual analysis found in keyframes, per claimed skill.
    # Conservative: OCR alone never moves a skill to "supported" — only partial.
    frame_ocr_evidence_summary = _build_frame_ocr_evidence_summary(
        visual_frame_observations, claimed_skills
    )

    # Promote OCR-supported skills from "unsupported" to "weakly" when OCR
    # evidence provides partial backing.  Never moves to "supported" — requires
    # DOM or code evidence for that.
    if frame_ocr_evidence_summary.get("has_ocr_evidence"):
        _ocr_sig_map = {
            s["skill"]: s["ocr_support"]
            for s in frame_ocr_evidence_summary.get("skill_signals", [])
        }
        _newly_weakly: list[str] = []
        _remaining_unsupported: list[str] = []
        for us in unsupported:
            if _ocr_sig_map.get(us) == "partial":
                _newly_weakly.append(us)
                skill_obs[us] = "from_ocr_evidence"
            else:
                _remaining_unsupported.append(us)
        if _newly_weakly:
            weakly = weakly + _newly_weakly
            unsupported = _remaining_unsupported
            logger.info(
                "WORKFLOW_ANALYSIS_OCR_SKILL_PROMOTION skills=%s session=promoted",
                _newly_weakly,
            )

    # ── Missing evidence ──────────────────────────────────────────────────────
    missing_evidence = _determine_missing_evidence(
        claimed_skills, supported, weakly, url_type, github_url,
        target_visited_urls, skill_obs,
        supporting_visited_urls=supporting_visited_urls,
        frame_ocr_evidence_summary=frame_ocr_evidence_summary,
    )

    # ── Risk flags (uses TARGET site data) ───────────────────────────────────
    risk_flags = _determine_risk_flags(
        duration_secs, len(events), url_type,
        target_visited_urls,
        len(target_clicks), len(target_inputs),
    )

    # ── Narrative text ────────────────────────────────────────────────────────
    workflow_summary = _build_workflow_summary(
        target_visited_urls, target_visited_titles, duration_secs, len(events),
        len(all_tab_opens), url_type, proof_objective,
        target_website=target_netloc,
        noise_count=len(noise_urls),
    )
    recruiter_summary = _build_recruiter_summary(
        proof_objective, target_visited_urls, supported, weakly, unsupported,
        url_type, duration_secs, score, confidence, github_url, skill_obs,
        target_visited_titles=target_visited_titles,
        supporting_visited_urls=supporting_visited_urls,
        original_url=original_url,
        iao_patterns=iao_patterns,
        frame_ocr_evidence_summary=frame_ocr_evidence_summary,
    )
    suggestions = _build_suggestions(
        url_type, duration_secs, len(events),
        len(target_clicks), len(target_inputs),
        supported, weakly, unsupported, github_url, skill_obs,
    )

    human_review_needed = confidence in ("low", "insufficient") or score < 35

    # ── Sequence analysis (v6 — Week 3) ──────────────────────────────────────
    # Analyses extracted keyframes + DOM events + visible evidence as a temporal
    # sequence to produce a structured before/after / IAO chain proof.
    sequence_analysis: dict[str, Any] = {}
    try:
        from app.services.workflow_sequence_analysis_service import (
            WorkflowSequenceAnalysisService,
        )
        from app.services.video_keyframe_extractor_service import (
            VideoKeyframeResult,
            VIDEO_STATUS_ANALYZED,
        )
        _seq_svc = WorkflowSequenceAnalysisService()

        # Build a minimal VideoKeyframeResult from stored timestamps (loaded by run_analysis).
        # This replaces the broken _get_keyframe_result_for_session method lookup.
        _kf_result = None
        _kf_ts = stored_keyframe_timestamps or []
        if _kf_ts:
            _kf_result = VideoKeyframeResult(
                video_analysis_status=VIDEO_STATUS_ANALYZED,
                keyframe_count=len(_kf_ts),
                selected_frame_timestamps_ms=_kf_ts,
                extraction_method="db_stored",
                duration_ms=_kf_ts[-1] if _kf_ts else None,
                frame_width=None,
                frame_height=None,
                limitations=[],
            )

        _seq_result = _seq_svc.analyze(
            keyframe_result=_kf_result,
            dom_events=events,
            visible_observations=visible_observations,
            visual_frame_obs=visual_frame_observations,
        )
        sequence_analysis = _seq_result.to_public_dict()
        logger.info(
            "WORKFLOW_SEQUENCE_ANALYSIS status=%s frames=%d confidence=%d",
            sequence_analysis.get("sequence_analysis_status"),
            sequence_analysis.get("analyzed_frame_count", 0),
            sequence_analysis.get("confidence_score", 0),
        )
    except Exception:
        logger.warning(
            "WORKFLOW_SEQUENCE_ANALYSIS_FAILED — continuing without",
            exc_info=True,
        )

    return {
        "analysis_type":              "timeline_only",
        "workflow_summary":           workflow_summary,
        "demonstrated_actions":       demonstrated_actions,
        "supported_skills":           supported,
        "weakly_supported_skills":    weakly,
        "unsupported_skills":         unsupported,
        "evidence_strength_score":    score,
        "workflow_confidence":        confidence,
        "missing_evidence":           missing_evidence,
        "risk_flags":                 risk_flags,
        "recruiter_summary":          recruiter_summary,
        "student_improvement_suggestions": suggestions,
        "human_review_needed":        human_review_needed,
        # ── Internal / debug fields (not surfaced in recruiter summary) ────────
        "target_website":             target_netloc or _extract_domain(original_url),
        "target_site_pages_count":    len(target_visited_urls),
        "supporting_evidence_count":  len(supporting_visited_urls),
        "noise_filtered_count":       len(noise_urls),
        # ── Precise visual workflow evidence (v3/v4/v5) ───────────────────────
        "observed_demonstration":     observed_demonstration,
        # Visual frame analysis (v5): provider-agnostic, local-first
        # Status values: not_configured | pending | analyzed | skipped | failed
        "visual_analysis_status":     _vf_status,
        "visual_analysis_provider":   _visual_provider,
        "visual_frame_count":         _visual_frame_count,  # analyzed frames
        "visual_frames_stored":       _visual_frames_stored, # total stored (inc. not_configured)
        "visual_result_values":       _visual_result_values,
        "visual_summary":             _visual_summary,
        # OCR status (sub-component of visual analysis when local_ocr provider used)
        "ocr_status":                 _ocr_status,
        # dom_evidence_status / visible_evidence_status: DOM text capture from extension
        "dom_evidence_status":        dom_evidence_status,
        "visible_evidence_status":    visible_evidence_status,
        # Graphical rendering (canvas/SVG detected)
        "has_graphical_rendering":    has_graphical_rendering,
        "graphical_rendering_note":   graphical_rendering_note,
        "top_result_snippets":        top_result_snippets,
        "page_context_summary":       page_context_summary,
        # ── Sequence analysis (v6 — Week 3) ──────────────────────────────────
        # Multi-frame temporal analysis: keyframes + DOM + visible evidence.
        # to_public_dict() used — no raw paths or private metadata.
        "sequence_analysis":          sequence_analysis,
        # ── Frame OCR evidence summary (v6) ──────────────────────────────────
        # Structured summary of OCR evidence from video keyframes.
        # Shows page context, OCR snippets, and per-skill OCR support signals.
        "frame_ocr_evidence_summary": frame_ocr_evidence_summary,
    }


# ── Tech stack inference ──────────────────────────────────────────────────────

def _infer_tech_stack(
    relevant_urls: list[str],
    relevant_titles: list[str],
    original_url: str,
) -> set[str]:
    """Infer tech signals from target-site + supporting URLs only."""
    tech: set[str] = set()

    for url in ([original_url] + relevant_urls):
        if not url:
            continue
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            port = parsed.port

            for domain_suffix, skills in _DOMAIN_TECH.items():
                if netloc.endswith(domain_suffix):
                    tech.update(skills)

            if port and netloc in ("localhost", "127.0.0.1"):
                port_skills = _PORT_TECH.get(str(port), [])
                tech.update(port_skills)

            path = parsed.path.lower()
            if "/docs" in path or "/redoc" in path or "/openapi" in path:
                tech.add("FastAPI")
            if "/admin" in path:
                tech.add("Django")
            if "/api/" in path or "/api" == path:
                tech.add("API")
            if "jupyter" in path or "lab" in path:
                tech.add("Jupyter Notebook")
        except Exception:
            pass

    titles_lower = " ".join(relevant_titles).lower()
    for keyword, canonical in _TITLE_TECH.items():
        if keyword in titles_lower:
            tech.add(canonical)

    return tech


# ── Skill observability helpers ───────────────────────────────────────────────

def _is_code_evidence_skill(canonical: str) -> bool:
    return canonical.lower() in _REQUIRES_CODE_EVIDENCE


def _normalize_skill(skill: str) -> str:
    lower = skill.strip().lower()
    canonical = _SKILL_ALIASES.get(lower)
    if canonical:
        return canonical
    for alias, canon in _SKILL_ALIASES.items():
        if alias in lower or lower in alias:
            return canon
    return skill.strip().title()


def _match_skills(
    claimed_skills: list[str],
    inferred_tech: set[str],
    proof_objective: str,
    original_url: str,
    url_type: str,
) -> tuple[list[str], list[str], list[str], dict[str, str]]:
    supported: list[str] = []
    weakly: list[str] = []
    unsupported: list[str] = []
    observability: dict[str, str] = {}

    objective_lower = proof_objective.lower()
    inferred_lower = {t.lower() for t in inferred_tech}

    is_local = url_type in ("localhost_url", "local_network_url")

    for raw in claimed_skills:
        if not raw.strip():
            continue
        canonical = _normalize_skill(raw)
        canonical_lower = canonical.lower()

        direct_match = (
            canonical_lower in inferred_lower
            or any(canonical_lower in t or t in canonical_lower for t in inferred_lower)
        )
        objective_mentions = (
            canonical_lower in objective_lower
            or raw.lower() in objective_lower
        )
        is_code_skill = _is_code_evidence_skill(canonical)

        if direct_match:
            if is_local:
                weakly.append(canonical)
                observability[canonical] = "from_objective" if objective_mentions else "requires_code_evidence"
            else:
                supported.append(canonical)
                observability[canonical] = "supported"
        elif is_code_skill:
            weakly.append(canonical)
            observability[canonical] = "requires_code_evidence"
        elif objective_mentions:
            weakly.append(canonical)
            observability[canonical] = "from_objective"
        else:
            unsupported.append(canonical)
            observability[canonical] = "unsupported"

    def _dedup(lst: list[str]) -> list[str]:
        seen: set[str] = set()
        return [x for x in lst if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]

    return _dedup(supported), _dedup(weakly), _dedup(unsupported), observability


# ── Evidence strength scoring ─────────────────────────────────────────────────

def _compute_score(
    total_events: int,
    page_count: int,
    click_count: int,
    input_count: int,
    tab_opens: int,
    duration_secs: float,
    url_type: str,
    supported_count: int,
    claimed_count: int,
) -> int:
    score = 0

    # Recording activity (max 20 pts) — uses all events as activity signal
    if total_events >= 30:
        score += 20
    elif total_events >= 20:
        score += 16
    elif total_events >= 10:
        score += 11
    elif total_events >= 5:
        score += 6
    elif total_events > 0:
        score += 3

    # Target-site page diversity (max 15 pts)
    if page_count >= 5:
        score += 15
    elif page_count >= 3:
        score += 10
    elif page_count >= 2:
        score += 7
    elif page_count >= 1:
        score += 4

    # Recording duration (max 20 pts)
    if duration_secs >= 300:
        score += 20
    elif duration_secs >= 180:
        score += 16
    elif duration_secs >= 90:
        score += 11
    elif duration_secs >= 45:
        score += 7
    elif duration_secs >= 15:
        score += 4

    # Target-site user interaction depth (max 20 pts)
    interactions = click_count + input_count
    if interactions >= 20:
        score += 20
    elif interactions >= 10:
        score += 15
    elif interactions >= 5:
        score += 10
    elif interactions >= 2:
        score += 6
    elif interactions >= 1:
        score += 3

    # Multi-tab depth bonus (max 5 pts)
    score += min(5, tab_opens * 2)

    # URL type (max 15 pts for live, less for local)
    if url_type == "live_deployed_url":
        score += 15
    elif url_type in ("localhost_url", "local_network_url"):
        score += 5

    # Skill coverage ratio (max 5 pts)
    ratio = supported_count / claimed_count if claimed_count > 0 else 0
    score += int(ratio * 5)

    return min(80, max(0, score))


# ── Confidence determination ──────────────────────────────────────────────────

def _determine_confidence(
    score: int,
    url_type: str,
    total_events: int,
    duration_secs: float,
) -> str:
    if total_events < 3 or duration_secs < 10:
        return "insufficient"
    if score < 20:
        return "insufficient"
    if score < 35:
        return "low"
    if url_type == "live_deployed_url" and score >= 55 and duration_secs >= 120:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


# ── Demonstrated actions ──────────────────────────────────────────────────────

def _extract_demonstrated_actions(
    target_page_visits: list[dict],
    target_clicks: list[dict],
    target_inputs: list[dict],
    target_tab_opens: list[dict],
    target_navigations: list[dict],
    target_visited_titles: list[str],
    *,
    supporting_visited_urls: list[str] | None = None,
    noise_count: int = 0,
) -> list[str]:
    """Build human-readable action bullets — TARGET site events only.

    Noise events are excluded entirely.
    Supporting GitHub evidence is noted separately.
    """
    actions: list[str] = []
    supporting_visited_urls = supporting_visited_urls or []

    # Target site page visits
    target_urls = list(dict.fromkeys(
        e.get("page_url", "") for e in target_page_visits if e.get("page_url")
    ))

    if not target_urls and not target_navigations:
        actions.append(
            "No interactions with the target application were observed in the recording."
        )
    else:
        if target_urls:
            first_url = target_urls[0]
            actions.append(f"Target application loaded: {_format_url(first_url)}")
            if len(target_urls) > 1:
                actions.append(
                    f"{len(target_urls)} pages navigated within the target application"
                )
                for url in target_urls[1:4]:
                    actions.append(f"  • {_format_url(url)}")
                if len(target_urls) > 4:
                    actions.append(f"  • … and {len(target_urls) - 4} more")

    # Meaningful page titles (context, not noise)
    meaningful_titles = [
        t for t in target_visited_titles if len(t) > 5 and "://" not in t
    ]
    if meaningful_titles:
        actions.append(f"Page context: {'; '.join(meaningful_titles[:3])}")

    # Interactions on target site
    click_count = len(target_clicks)
    input_count = len(target_inputs)
    if click_count > 0 or input_count > 0:
        interaction_parts: list[str] = []
        if click_count:
            significant = [
                c for c in target_clicks if c.get("element_text") or c.get("element_id")
            ]
            if significant:
                sample = significant[:3]
                label = ", ".join(
                    f'"{(c.get("element_text") or c.get("element_id") or "")[:40]}"'
                    for c in sample
                )
                interaction_parts.append(f"{click_count} click(s) including {label}")
            else:
                interaction_parts.append(f"{click_count} click(s)")
        if input_count:
            interaction_parts.append(f"{input_count} form/input interaction(s)")
        actions.append(f"User interactions: {', '.join(interaction_parts)}")
    elif target_urls:
        actions.append(
            "No click or input interactions were recorded on the target application — "
            "page load only was observed."
        )

    # Supporting GitHub evidence
    if supporting_visited_urls:
        actions.append(
            f"Supporting evidence: {len(supporting_visited_urls)} GitHub page(s) also visited "
            "during the session"
        )

    # Navigations within target
    if target_navigations:
        actions.append(
            f"Navigated through {len(target_navigations)} page(s) within the target application"
        )

    return actions if actions else ["No workflow events were captured"]


# ── Missing evidence ──────────────────────────────────────────────────────────

def _determine_missing_evidence(
    claimed_skills: list[str],
    supported: list[str],
    weakly: list[str],
    url_type: str,
    github_url: str | None,
    target_visited_urls: list[str],
    skill_obs: dict[str, str] | None = None,
    *,
    supporting_visited_urls: list[str] | None = None,
    frame_ocr_evidence_summary: dict[str, Any] | None = None,
) -> list[str]:
    missing: list[str] = []
    skill_obs = skill_obs or {}
    supporting_visited_urls = supporting_visited_urls or []
    frame_ocr_evidence_summary = frame_ocr_evidence_summary or {}

    is_local = url_type in ("localhost_url", "local_network_url")

    if is_local:
        missing.append(
            "Live deployed URL — recruiters cannot access the app independently from a localhost recording"
        )
    if not github_url:
        missing.append("GitHub repository URL for source code evidence")
    elif not supporting_visited_urls:
        missing.append(
            "GitHub repository was not visited during the recording session"
        )

    code_evidence_skills = [
        s for s in weakly if skill_obs.get(s) == "requires_code_evidence"
    ]
    if code_evidence_skills:
        skills_str = ", ".join(code_evidence_skills[:3])
        missing.append(
            f"GitHub repository analysis to verify back-end/code skill(s): {skills_str} "
            "(these skills are implemented in code, not directly visible in a browser recording)"
        )

    truly_unsupported = [
        s for s in claimed_skills if s not in supported and s not in weakly
    ]

    # Build skill-specific missing evidence messages
    # When OCR evidence is available, give specific feedback per unsupported skill
    ocr_skill_signals_map: dict[str, dict] = {}
    if frame_ocr_evidence_summary.get("has_ocr_evidence"):
        for sig in frame_ocr_evidence_summary.get("skill_signals", []):
            ocr_skill_signals_map[sig["skill"]] = sig

    page_context = frame_ocr_evidence_summary.get("detected_page_context", "unknown")
    what_not_observed = frame_ocr_evidence_summary.get("what_was_not_observed", [])

    for skill in truly_unsupported[:4]:
        ocr_sig = ocr_skill_signals_map.get(skill)
        if ocr_sig and ocr_sig.get("ocr_support") == "insufficient":
            # Give specific OCR-backed missing evidence message
            _ocr_reasoning = ocr_sig.get("reasoning", "")
            if _ocr_reasoning:
                missing.append(
                    f"Observable evidence for '{skill}': {_ocr_reasoning}"
                )
            else:
                missing.append(f"Observable evidence for claimed skill: {skill}")
        elif page_context == "homepage_marketing" and what_not_observed:
            # Mention what specific UI elements would demonstrate the skill
            missing.append(
                f"Observable evidence for '{skill}': "
                f"Keyframes show homepage content only. "
                f"To demonstrate this skill, record the interactive UI — "
                f"{what_not_observed[0]}."
            )
        else:
            missing.append(f"Observable evidence for claimed skill: {skill}")

    if not target_visited_urls:
        missing.append(
            "Any recorded interactions with the target application — "
            "no target site pages were captured in the workflow"
        )

    return missing


# ── Risk flags ────────────────────────────────────────────────────────────────

def _determine_risk_flags(
    duration_secs: float,
    total_events: int,
    url_type: str,
    target_visited_urls: list[str],
    target_click_count: int,
    target_input_count: int,
) -> list[str]:
    """Generate risk flags based on TARGET site evidence only."""
    flags: list[str] = []

    if total_events == 0:
        flags.append("No workflow events captured — recording may not have started correctly")
    elif total_events < 5:
        flags.append(f"Very few events captured ({total_events}) — recording may be incomplete")

    if duration_secs < 20 and total_events > 0:
        flags.append(f"Very short recording ({int(duration_secs)}s) — limited workflow demonstrated")
    elif duration_secs < 60 and total_events > 0:
        flags.append(f"Short recording ({int(duration_secs)}s) — consider a more complete walkthrough")

    if url_type in ("localhost_url", "local_network_url"):
        flags.append(
            "Localhost/local URL — app runs only on the student's machine; "
            "recruiters cannot independently open or verify the deployed application"
        )

    if not target_visited_urls and total_events > 0:
        flags.append(
            "No interactions with the target application were recorded — "
            "the recording appears to show only unrelated browser tabs or development tools"
        )
    elif target_visited_urls and target_click_count == 0 and target_input_count == 0:
        flags.append(
            "Target application page loaded but no user interactions (clicks, form inputs) "
            "were recorded — workflow shows page load only; deeper app functionality "
            "was not demonstrated"
        )

    return flags


# ── Narrative builders ────────────────────────────────────────────────────────

def _build_workflow_summary(
    target_visited_urls: list[str],
    target_visited_titles: list[str],
    duration_secs: float,
    total_events: int,
    tab_opens_total: int,
    url_type: str,
    proof_objective: str,
    *,
    target_website: str = "",
    noise_count: int = 0,
) -> str:
    """Target-site-focused workflow summary.

    Only describes what was demonstrated on the proof target website.
    Noise events (unrelated tabs, Supabase, VeriBridge dashboard) are not mentioned.
    """
    duration_label = _fmt_duration(duration_secs)
    page_count = len(target_visited_urls)
    url_label = (
        "a locally-running application"
        if url_type in ("localhost_url", "local_network_url")
        else "a live web application"
    )

    if total_events == 0:
        return "No workflow events were recorded. The recording may not have captured any activity."

    if not target_visited_urls:
        base = f"The student recorded a {duration_label} workflow session."
        if noise_count > 0:
            base += (
                f" {noise_count} event(s) from unrelated browser tabs or development tools "
                "were captured but are excluded from this analysis as they fall outside "
                "the target proof application."
            )
        return base

    site_label = f"'{target_website}'" if target_website else url_label
    parts: list[str] = [
        f"The student recorded a {duration_label} workflow session "
        f"demonstrating {site_label}."
    ]

    if page_count == 1:
        parts.append("1 page within the target application was visited.")
    elif page_count > 1:
        parts.append(f"{page_count} pages within the target application were visited.")

    meaningful_titles = [t for t in target_visited_titles if len(t) > 5 and "://" not in t]
    if meaningful_titles:
        parts.append(f"Application context: {'; '.join(meaningful_titles[:3])}.")

    if proof_objective:
        parts.append(f"The stated proof objective was: \"{proof_objective.strip()[:200]}\".")

    if url_type in ("localhost_url", "local_network_url"):
        parts.append(
            "Because this is a local recording, the application is not publicly accessible — "
            "this demonstrates the project running on the student's development machine."
        )

    if noise_count > 0:
        parts.append(
            f"Note: {noise_count} background event(s) from unrelated browser tabs "
            "were filtered out and are not included in this evidence analysis."
        )

    return " ".join(parts)


def _build_recruiter_summary(
    proof_objective: str,
    target_visited_urls: list[str],
    supported: list[str],
    weakly: list[str],
    unsupported: list[str],
    url_type: str,
    duration_secs: float,
    score: int,
    confidence: str,
    github_url: str | None,
    skill_obs: dict[str, str] | None = None,
    *,
    target_visited_titles: list[str] | None = None,
    supporting_visited_urls: list[str] | None = None,
    original_url: str = "",
    iao_patterns: list[dict[str, Any]] | None = None,
    frame_ocr_evidence_summary: dict[str, Any] | None = None,
) -> str:
    """Recruiter-facing summary focused on the proof target website.

    Never mentions unrelated browser tabs, Supabase, VeriBridge dashboard,
    or any noise URLs. Only describes what was observed on the target app
    and any supporting GitHub evidence.

    When IAO patterns are detected, opens with a precise description of the
    input→action→output flow rather than just "user clicked upload".
    """
    is_local = url_type in ("localhost_url", "local_network_url")
    duration_label = _fmt_duration(duration_secs)
    skill_obs = skill_obs or {}
    target_visited_titles = target_visited_titles or []
    supporting_visited_urls = supporting_visited_urls or []
    iao_patterns = iao_patterns or []

    target_domain = _extract_domain(original_url) or ""
    app_label = f"'{target_domain}'" if target_domain else "the target application"
    app_type_label = (
        "locally-running application" if is_local else "live web application"
    )

    lines: list[str] = []

    # ── Opening: what was demonstrated ───────────────────────────────────────
    if not target_visited_urls:
        lines.append(
            f"The {duration_label} recording was captured, but no interactions with "
            f"{app_label} were observed in the workflow. The recording may show navigation "
            f"to unrelated browser tabs; the target application workflow was not captured."
        )
    else:
        page_count = len(target_visited_urls)
        meaningful_titles = [t for t in target_visited_titles if len(t) > 5]

        title_context = ""
        if meaningful_titles:
            title_context = f" ({'; '.join(meaningful_titles[:2])})"

        # Use IAO-pattern-aware opening when a pattern was detected
        if iao_patterns:
            ptype = iao_patterns[0].get("pattern_type", "generic_interaction")
            iao_intro = _PTYPE_RECRUITER_INTRO.get(ptype, _PTYPE_RECRUITER_INTRO["generic_interaction"])
            lines.append(
                f"The recording shows the student using {app_label}{title_context}, "
                f"a {app_type_label}. {iao_intro}"
            )
        else:
            lines.append(
                f"The recording shows the student demonstrating {app_label}{title_context}, "
                f"a {app_type_label}."
            )

        if page_count > 1:
            lines.append(
                f"{page_count} pages within the target application were observed in the session."
            )

        # Honest note about output visibility
        if iao_patterns:
            ptype = iao_patterns[0].get("pattern_type", "")
            has_output = iao_patterns[0].get("output_event") is not None
            if ptype == "image_to_prediction":
                if has_output:
                    lines.append(
                        "The recording shows that prediction or detection output was displayed. "
                        "The exact output labels and confidence scores were not readable from "
                        "the browser event timeline — video frame analysis would be required "
                        "to extract precise values."
                    )
                else:
                    lines.append(
                        "The recording shows an image upload and detection workflow, but a clear "
                        "result or output page was not observed in the event timeline."
                    )

    # ── Proof objective ───────────────────────────────────────────────────────
    if proof_objective:
        lines.append(
            f"The student intended to demonstrate: \"{proof_objective.strip()[:200]}\"."
        )

    # ── Skills directly supported by target-site workflow ────────────────────
    if supported:
        lines.append(
            f"The observed workflow supports evidence for: {', '.join(supported)}."
        )

    # ── Skills weakly supported: split code vs. objective-mentioned ───────────
    if weakly:
        code_evidence_skills = [
            s for s in weakly if skill_obs.get(s) == "requires_code_evidence"
        ]
        indirect_skills = [
            s for s in weakly if skill_obs.get(s) not in ("requires_code_evidence",)
        ]

        if code_evidence_skills:
            skill_word = "skill" if len(code_evidence_skills) == 1 else "skills"
            it_them = "it" if len(code_evidence_skills) == 1 else "them"
            is_are = "is" if len(code_evidence_skills) == 1 else "are"
            lines.append(
                f"{', '.join(code_evidence_skills)} {is_are} back-end or code-level "
                f"{skill_word} not directly observable in a browser recording. "
                f"GitHub repository analysis is recommended to verify {it_them}."
            )
        if indirect_skills:
            lines.append(
                f"Partial evidence is available for: {', '.join(indirect_skills)}. "
                "These skills are consistent with the observed workflow but require "
                "additional evidence for full confirmation."
            )

    # ── No observable evidence ────────────────────────────────────────────────
    if unsupported:
        lines.append(
            f"No observable evidence was found for: {', '.join(unsupported)}. "
            "Consider a more focused demonstration or add GitHub and live deployment evidence."
        )

    # ── Supporting GitHub evidence ────────────────────────────────────────────
    if supporting_visited_urls and github_url:
        lines.append(
            "GitHub repository evidence was also visited during the recording, "
            "providing additional context for code-level skills."
        )

    # ── Localhost caveat ──────────────────────────────────────────────────────
    if is_local:
        lines.append(
            "This is a local (localhost) recording — the application is not publicly accessible. "
            "A live deployment URL would significantly strengthen this proof."
        )

    # ── Frame OCR evidence note ───────────────────────────────────────────────
    # When OCR was analyzed, append a concise summary of what frames showed.
    if frame_ocr_evidence_summary and frame_ocr_evidence_summary.get("has_ocr_evidence"):
        _ctx = frame_ocr_evidence_summary.get("detected_page_context", "unknown")
        _fcount = frame_ocr_evidence_summary.get("frames_analyzed", 0)
        _observed_summary = frame_ocr_evidence_summary.get("observed_summary", "")
        if _observed_summary and _fcount > 0:
            lines.append(
                f"Keyframe OCR analysis ({_fcount} frame(s)): {_observed_summary}"
            )

    # ── Score / confidence footer ─────────────────────────────────────────────
    confidence_label = {
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "insufficient": "Insufficient",
    }.get(confidence, confidence.capitalize())
    ocr_note = (
        " OCR keyframe analysis included."
        if frame_ocr_evidence_summary and frame_ocr_evidence_summary.get("has_ocr_evidence")
        else " visual video evidence not yet available"
    )
    lines.append(
        f"Evidence strength: {score}/100 · Confidence: {confidence_label} "
        f"(Workflow Timeline Analysis —{ocr_note})."
    )

    return " ".join(lines)


def _build_suggestions(
    url_type: str,
    duration_secs: float,
    total_events: int,
    click_count: int,
    input_count: int,
    supported: list[str],
    weakly: list[str],
    unsupported: list[str],
    github_url: str | None,
    skill_obs: dict[str, str] | None = None,
) -> list[str]:
    suggestions: list[str] = []
    skill_obs = skill_obs or {}

    if url_type in ("localhost_url", "local_network_url"):
        suggestions.append(
            "Deploy the application to a live URL (e.g., Vercel, Railway, Render) so recruiters "
            "can independently access and verify it"
        )

    code_evidence_skills = [s for s in weakly if skill_obs.get(s) == "requires_code_evidence"]
    if code_evidence_skills and not github_url:
        skills_str = ", ".join(code_evidence_skills[:3])
        suggestions.append(
            f"Add a public GitHub repository URL — back-end/code skill(s) {skills_str} cannot "
            "be verified from the browser recording alone and require repository analysis"
        )
    elif not github_url:
        suggestions.append(
            "Add a GitHub repository URL to allow code-level verification of your implementation"
        )

    if duration_secs < 90:
        suggestions.append(
            "Record a longer, more comprehensive walkthrough (at least 2–3 minutes) "
            "showing the core features end-to-end"
        )

    if click_count + input_count < 5:
        suggestions.append(
            "Interact more with the application — submit forms, trigger API calls, "
            "and show real results to demonstrate the app working"
        )

    if unsupported:
        skills_str = ", ".join(unsupported[:3])
        suggestions.append(
            f"Demonstrate evidence for unsupported claimed skill(s): {skills_str} — "
            "navigate to the relevant part of your app during the recording"
        )

    indirect_weakly = [s for s in weakly if skill_obs.get(s) == "from_objective"]
    if indirect_weakly and not unsupported:
        suggestions.append(
            "Consider showing specific features that directly demonstrate your claimed skills "
            "(e.g., triggering an API call, running a model inference, submitting a database query)"
        )

    if github_url:
        suggestions.append(
            "Run GitHub Evidence Analysis to verify back-end and code skills from your repository"
        )
    else:
        suggestions.append(
            "Once GitHub evidence is added, run GitHub analysis to strengthen the overall verification score"
        )

    return suggestions


# ── Utility helpers ───────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return url


def _is_chrome_internal(url: str) -> bool:
    return url.startswith(("chrome://", "chrome-extension://", "about:", "data:"))


def _compute_duration(started_at: str | None, stopped_at: str | None) -> float:
    if not started_at:
        return 0.0
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = (
            datetime.fromisoformat(stopped_at.replace("Z", "+00:00"))
            if stopped_at
            else datetime.now(timezone.utc)
        )
        delta = (end - start).total_seconds()
        return max(0.0, delta)
    except Exception:
        return 0.0


def _fmt_duration(secs: float) -> str:
    if secs < 5:
        return "brief"
    if secs < 60:
        return f"{int(secs)}-second"
    minutes = int(secs // 60)
    return f"{minutes}-minute"


def _format_url(url: str) -> str:
    try:
        p = urlparse(url)
        if p.netloc:
            path = p.path.rstrip("/") or "/"
            return f"{p.netloc}{path[:60]}"
    except Exception:
        pass
    return url[:80]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
