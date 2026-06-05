"""Final Evidence Evaluator — combines all available proof sources.

Produces a final_score (0–100), confidence, evidence source breakdown, and
a source-aware next_best_actions list.  Only runs scoring on sources that
have actually been run; missing sources are listed but not penalised if the
proof type does not require them.

Next Best Action Engine
-----------------------
If final_score >= 80: show optional improvements only.
If final_score < 80: recommend the single most impactful action for the weakest
evidence gap, prioritised by source type and skill evidence gaps.

Action types (recording-based or not):
  run_github_analysis      — non-recording, high priority when repo exists
  add_github_url           — non-recording, when code/OSS claimed but no URL
  run_live_website_check   — non-recording
  upload_document          — non-recording
  record_followup_proof    — recording
  add_linkedin_proof       — non-recording (future)
  record_camera_proof      — recording (future)
  record_cad_proof         — recording (future)
  record_presentation      — recording (future)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote, urlparse

from app.services.url_classification_service import (
    classify_website_url,
    local_private_live_check_note,
)

logger = logging.getLogger(__name__)


def _build_github_blob_url(
    repo_url: str,
    file_path: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str | None:
    """Build a GitHub blob URL for a specific file with optional line-range anchor.

    Returns None if repo_url cannot be parsed as a GitHub URL.
    Never invents line numbers — only appends #L fragment when explicitly provided.
    """
    from app.services.github_evidence_service import parse_github_repo_url
    ref = parse_github_repo_url(repo_url)
    if ref is None:
        return None
    owner = str(ref.owner or "").strip()
    repo = str(ref.repo or "").strip()
    if not owner or not repo:
        return None
    branch = str(ref.branch or "main").strip() or "main"
    norm_path = file_path.lstrip("/")
    encoded_path = "/".join(quote(part, safe="") for part in norm_path.split("/"))
    url = f"https://github.com/{owner}/{repo}/blob/{branch}/{encoded_path}"
    if line_start is not None:
        url += f"#L{line_start}"
        if line_end is not None and line_end != line_start:
            url += f"-L{line_end}"
    return url


def _github_repo_name(repo_url: str) -> str | None:
    if not repo_url:
        return None
    try:
        from app.services.github_evidence_service import parse_github_repo_url
        ref = parse_github_repo_url(repo_url)
        if ref is None:
            return None
        owner = str(ref.owner or "").strip()
        repo = str(ref.repo or "").strip()
        if owner and repo:
            return f"{owner}/{repo}"
        return repo or None
    except Exception:
        return None


# ── Tables ────────────────────────────────────────────────────────────────────

_WF_TABLE     = "workflow_analysis_results"
_GH_TABLE     = "extension_proof_github_analysis"
_LW_TABLE     = "live_website_check_results"
_PD_TABLE     = "project_defense_analysis_results"
_VF_TABLE     = "workflow_visual_frame_evidence"
_OPT_TABLE    = "optional_evidence_submissions"

# Generic metadata files that should never be shown as deep code evidence.
# README.md/package.json mentions of skill terms are not line-level proof.
_GENERIC_META_PATHS = frozenset({
    "README.md", "readme.md", "README.rst",
    "package.json", "package-lock.json",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "Makefile", "Dockerfile", ".env.example",
})

_SKILL_ALIAS_TOKENS: dict[str, set[str]] = {
    "frontend development": {"javascript", "typescript", "react", "vue", "angular", "html", "css", "frontend", "web"},
    "web development": {"javascript", "typescript", "html", "css", "frontend", "web"},
    "three.js": {"three", "threejs", "webgl", "renderer", "scene", "camera", "mesh", "material"},
    "threejs": {"three", "threejs", "webgl", "renderer", "scene", "camera", "mesh", "material"},
    "webgl": {"webgl", "glsl", "shader", "renderer", "three", "threejs"},
    "interactive 3d graphics": {"three", "threejs", "webgl", "3d", "renderer", "scene", "camera", "mesh", "animation"},
    "computer graphics": {"three", "threejs", "webgl", "graphics", "renderer", "scene", "camera", "mesh", "shader", "texture"},
    "video texture rendering": {"video", "texture", "videotexture", "webgl", "three", "threejs", "material"},
    "javascript": {"javascript", "js", "jsx", "export", "function", "class", "const", "let"},
    "typescript": {"typescript", "ts", "tsx", "interface", "type"},
}

# Skills that primarily manifest as rendered visual/GPU output.
# OCR cannot read the skill name from canvas/WebGL-rendered content.
# Qwen visual analysis and GitHub code evidence are the appropriate evidence
# sources for these skills; OCR absence must not mark them as missing.
_VISUAL_GRAPHICS_SKILL_PATTERNS: tuple[str, ...] = (
    "three.js", "threejs", "webgl", "webgpu", "interactive 3d graphics",
    "computer graphics", "video texture rendering", "data visualization",
    "canvas", "svg", "shader", "glsl", "opengl", "3d graphics", "3d rendering",
    "visual demo", "particle system", "d3.js", "d3js",
)

# Qwen observation keywords that indicate visual/graphics rendering was seen
_QWEN_VISUAL_RENDER_INDICATORS: tuple[str, ...] = (
    "webgl", "three.js", "threejs", "3d", "canvas", "render", "rendering",
    "animated", "animation", "rotating", "graphics", "geometric", "interactive",
    "colorful", "video texture", "mesh", "scene", "shader", "blocky", "objects",
    "visual", "demo", "texture",
)


def _skill_match_tokens(skill: str) -> set[str]:
    import re as _re

    raw = skill.lower().replace(".js", "js")
    tokens = {t for t in _re.split(r"[^a-z0-9]+", raw) if len(t) >= 2}
    tokens.update(_SKILL_ALIAS_TOKENS.get(skill.lower(), set()))
    return tokens


def _github_code_evidence_matches_skill(ev: dict[str, Any], skill: str) -> bool:
    """Return True when one GitHub code evidence item supports one skill."""
    ev_skill = str(ev.get("skill") or "").strip().lower()
    skill_lower = skill.strip().lower()
    if ev_skill == skill_lower:
        return True

    ev_text = " ".join(
        str(ev.get(k) or "")
        for k in ("skill", "file_path", "reason", "code_snippet", "github_url")
    ).lower()
    tokens = _skill_match_tokens(skill)
    if not tokens:
        return False

    hits = {tok for tok in tokens if tok in ev_text}
    if skill_lower in _SKILL_ALIAS_TOKENS:
        return len(hits) >= 1
    return len(hits) >= 2


def _github_code_evidence_sort_key(ev: dict[str, Any], skill: str) -> tuple[int, int]:
    ev_skill = str(ev.get("skill") or "").strip().lower()
    exact = 0 if ev_skill == skill.strip().lower() else 1
    has_lines = 0 if ev.get("line_start") is not None and ev.get("line_end") is not None else 1
    return (exact, has_lines)


def _is_visual_graphics_skill(skill: str) -> bool:
    """Return True for skills that primarily manifest as rendered visual/GPU output.

    OCR cannot read skill names from canvas/WebGL renderers.  For these skills
    Qwen visual analysis and GitHub code evidence carry more weight than OCR.
    """
    lower = skill.lower()
    return any(pat in lower for pat in _VISUAL_GRAPHICS_SKILL_PATTERNS)


# ── Types ─────────────────────────────────────────────────────────────────────

EvidenceSourceKey = Literal[
    "website_workflow",
    "dom_visible_evidence",
    "video_keyframes",
    "ocr",
    "qwen_visual_reasoning",
    "github",
    "live_website_check",
    "project_defense",
    "uploaded_documents",
    "linkedin_profile",
    "certificate",
    # Future — wired as enum only
    "transcript_nlp",
    "pdf_report",
    "resume",
    "camera_physical_proof",
    "cad_simulation_proof",
    "presentation_voice_proof",
]

# ── Detected Skill Profile types ──────────────────────────────────────────────

_SKILL_CATEGORY_MAP: list[tuple[list[str], str]] = [
    (["data visualization", "chart analysis", "chart", "plot", "d3", "observable",
      "vega", "plotly", "matplotlib", "seaborn", "visualization", "highcharts",
      "bokeh", "altair", "dashboard"], "DATA"),
    (["javascript", "typescript", "frontend", "react", "vue", "angular", "html",
      "css", "web development", "interactive documentation", "interactive",
      "web app", "ui ", "ux "], "FRONTEND"),
    (["machine learning", "deep learning", "neural network", "tensorflow", "pytorch",
      "scikit-learn", "sklearn", "nlp", "computer vision", "ai model", "llm",
      "transformers", "inference", "model evaluation", "mlops"], "AI/ML"),
    (["technical documentation", "documentation", "technical writing", "docs",
      "readme", "tutorial", "getting started"], "DOCUMENTATION"),
    (["open source", "github", "version control", "git", "repository", "open-source"], "OPEN_SOURCE"),
    (["python", "backend", "fastapi", "django", "flask", "api ", "rest api",
      "database", "sql", "node", "express"], "BACKEND"),
    (["devops", "deployment", "docker", "kubernetes", "ci/cd", "cloud", "aws",
      "gcp", "azure", "hosting"], "DEVOPS"),
    (["product demo", "workflow demonstration", "demo", "project presentation",
      "product walkthrough"], "PRODUCT"),
    (["data analysis", "statistics", "pandas", "numpy", "jupyter", "r programming",
      "eda", "statistical analysis", "data science"], "DATA"),
]

_SOURCE_LABEL_MAP: dict[str, str] = {
    "workflow":        "Recording",
    "OCR":             "OCR",
    "Qwen":            "Qwen",
    "GitHub":          "GitHub",
    "dom":             "DOM",
    "live_check":      "Live Website",
    "project_defense": "Project Defense",
    "transcript":      "Transcript",
    "document":        "Documents",
    "linkedin_profile": "LinkedIn/Profile",
    "certificate_transcript": "Certificates/Transcript",
}


def _skill_category(skill_name: str) -> str:
    lower = skill_name.lower()
    for keywords, cat in _SKILL_CATEGORY_MAP:
        if any(kw in lower for kw in keywords):
            return cat
    return "OTHER"


def _fmt_ts(seconds: float) -> str:
    """Format seconds as MM:SS string."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def _find_transcript_quotes(
    skill: str,
    transcript_text: str,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find transcript quotes relevant to a skill.

    Returns up to 2 dicts with keys: text, start_time, end_time, has_timestamp.
    Searches timed segments first; falls back to sentence splitting.
    Never fabricates content — only returns text already in the transcript.
    """
    import re as _re

    skill_words = [w for w in _re.split(r"[\s/._\-]+", skill) if len(w) >= 3]
    if not skill_words:
        return []
    pattern = _re.compile("|".join(_re.escape(w) for w in skill_words), _re.IGNORECASE)

    results: list[dict[str, Any]] = []

    if segments:
        for seg in segments:
            text = str(seg.get("text") or "").strip()
            if text and pattern.search(text):
                results.append({
                    "text": text[:200],
                    "start_time": float(seg.get("start_time") or 0.0),
                    "end_time": float(seg.get("end_time") or 0.0),
                    "has_timestamp": True,
                })
            if len(results) >= 2:
                break
    else:
        for sentence in _re.split(r"[.!?]", transcript_text or ""):
            s = sentence.strip()
            if s and pattern.search(s):
                results.append({
                    "text": s[:200],
                    "start_time": 0.0,
                    "end_time": 0.0,
                    "has_timestamp": False,
                })
            if len(results) >= 2:
                break

    return results


def _sources_to_labels(sources: list[str]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for src in sources:
        label = _SOURCE_LABEL_MAP.get(src)
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


@dataclass
class EvidenceObject:
    evidence_type: str   # recording_keyframe | ocr_text | dom_text | qwen_visual | github_file | live_check | transcript | document
    source_name: str
    confidence: Literal["high", "medium", "low"]
    short_summary: str
    timestamp_seconds: float | None = None
    keyframe_url: str | None = None
    text_snippet: str | None = None
    file_path: str | None = None
    repo_name: str | None = None
    source_type: str | None = None
    page_number: int | None = None
    profile_url: str | None = None
    section_label: str | None = None
    issuer: str | None = None
    title: str | None = None
    date: str | None = None
    line_range: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    github_url: str | None = None
    code_snippet: str | None = None
    matched_keywords: list[str] = field(default_factory=list)
    provenance: str = ""                 # Human-readable source label
    # evidence_kind: direct_workflow | contextual_page | embedded_video | unrelated | deployment_only
    evidence_kind: str = ""
    # skill_support_level: strong | partial | weak | none
    skill_support_level: str = ""
    # trace_action: open_github | view_keyframe | view_ocr | view_qwen | view_workflow_event | view_live_check | view_document | view_transcript
    trace_action: str = ""
    action_available: bool = True
    route_url: str | None = None
    source_url: str | None = None
    source_host: str | None = None
    target_match: bool = True
    exclusion_reason: str | None = None
    evidence_source_type: str = "target_website"
    recruiter_safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        source_url = self.source_url or self.route_url or self.github_url
        source_host = self.source_host
        if not source_host and source_url:
            try:
                from urllib.parse import urlparse as _urlparse
                source_host = _urlparse(source_url).netloc or None
            except Exception:
                source_host = None
        evidence_source_type = self.evidence_source_type
        if self.evidence_type == "github_file":
            evidence_source_type = "github_repo"
        elif self.evidence_type in ("document", "document_snippet", "profile_snippet", "certificate_or_transcript_snippet"):
            evidence_source_type = "document"
        elif self.evidence_type in ("transcript", "transcript_quote"):
            evidence_source_type = "transcript"
        return {
            "evidence_type":      self.evidence_type,
            "source_name":        self.source_name,
            "confidence":         self.confidence,
            "short_summary":      self.short_summary,
            "timestamp_seconds":  self.timestamp_seconds,
            "keyframe_url":       self.keyframe_url,
            "text_snippet":       self.text_snippet,
            "file_path":          self.file_path,
            "repo_name":          self.repo_name,
            "source_type":        self.source_type,
            "page_number":        self.page_number,
            "profile_url":        self.profile_url,
            "section_label":      self.section_label,
            "issuer":             self.issuer,
            "title":              self.title,
            "date":               self.date,
            "line_range":         self.line_range,
            "line_start":         self.line_start,
            "line_end":           self.line_end,
            "github_url":         self.github_url,
            "code_snippet":       self.code_snippet,
            "matched_keywords":   self.matched_keywords,
            "provenance":         self.provenance,
            "evidence_kind":      self.evidence_kind,
            "skill_support_level": self.skill_support_level,
            "trace_action":       self.trace_action,
            "action_available":   self.action_available,
            "route_url":          self.route_url,
            "source_url":         source_url,
            "source_host":        source_host,
            "target_match":       self.target_match,
            "exclusion_reason":   self.exclusion_reason,
            "evidence_source_type": evidence_source_type,
            "recruiter_safe":     self.recruiter_safe,
        }


@dataclass
class DetectedSkillEntry:
    skill: str
    confidence: Literal["high", "medium", "low"]
    evidence_support: str
    sources: list[str]
    is_inferred: bool = False  # True when not in the student's claimed_skills
    status_label: str = ""     # e.g. "claimed — strongly supported" / "inferred from evidence"
    keyframe_evidence: list[str] = field(default_factory=list)
    github_evidence: list[str] = field(default_factory=list)
    category: str = "OTHER"
    source_labels: list[str] = field(default_factory=list)
    evidence_objects: list[EvidenceObject] = field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        return len(self.evidence_objects)

    @property
    def sources_count(self) -> int:
        return len(self.source_labels)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "confidence": self.confidence,
            "evidence_support": self.evidence_support,
            "sources": self.sources,
            "is_inferred": self.is_inferred,
            "status_label": self.status_label,
            "keyframe_evidence": self.keyframe_evidence,
            "github_evidence": self.github_evidence,
            "category": self.category,
            "source_labels": self.source_labels,
            "evidence_count": self.evidence_count,
            "sources_count": self.sources_count,
            "evidence_objects": [e.to_dict() for e in self.evidence_objects],
        }


@dataclass
class DetectedCapability:
    role_title: str
    confidence: Literal["high", "medium", "low"]
    why_detected: list[str]
    supporting_skills: list[DetectedSkillEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_title": self.role_title,
            "confidence": self.confidence,
            "why_detected": self.why_detected,
            "supporting_skills": [s.to_dict() for s in self.supporting_skills],
        }


# Role profiles for mapping skill clusters → high-level role titles
# Each entry: (role_title, primary_keywords, secondary_keywords, inferred_extra_skills)
_ROLE_PROFILES: list[tuple[str, list[str], list[str], list[str]]] = [
    (
        "AI / Data Visualization Engineer",
        ["visualization", "data viz", "chart", "plot", "d3", "observable", "vega",
         "plotly", "matplotlib", "seaborn", "chart analysis"],
        ["javascript", "typescript", "open source", "data analysis", "interactive",
         "dashboard", "technical documentation"],
        ["JavaScript", "Technical Documentation", "Open Source Project Understanding",
         "Data Analysis", "Frontend Development"],
    ),
    (
        "ML / AI Engineer",
        ["machine learning", "deep learning", "neural network", "ai model", "tensorflow",
         "pytorch", "transformers", "llm", "nlp", "computer vision"],
        ["python", "data science", "mlops", "api integration", "model evaluation",
         "inference"],
        ["Python", "Model Evaluation", "API Integration", "Data Engineering", "MLOps"],
    ),
    (
        "Data Scientist",
        ["data science", "statistics", "pandas", "numpy", "jupyter", "r programming",
         "statistical analysis", "eda"],
        ["python", "visualization", "machine learning", "sql", "hypothesis testing",
         "feature engineering"],
        ["Python", "Statistical Analysis", "Data Visualization", "SQL"],
    ),
    (
        "Frontend / Web Engineer",
        ["frontend", "react", "vue", "angular", "html", "css", "ui", "ux",
         "web development"],
        ["javascript", "typescript", "responsive design", "accessibility", "web app"],
        ["JavaScript", "TypeScript", "API Integration", "Responsive Design"],
    ),
    (
        "Full Stack Engineer",
        ["full stack", "fullstack", "backend", "django", "fastapi", "flask", "node",
         "express", "rest api"],
        ["javascript", "python", "database", "deployment", "devops", "docker"],
        ["API Design", "Database", "Deployment", "JavaScript"],
    ),
    (
        "Software Engineer",
        ["software", "programming", "algorithm", "open source", "code", "github",
         "version control", "software development"],
        ["javascript", "python", "typescript", "java", "testing", "documentation",
         "clean code"],
        ["Software Design", "Testing", "Documentation", "Version Control"],
    ),
]

ActionType = Literal[
    "run_github_analysis",
    "add_github_url",
    "run_live_website_check",
    "upload_document",
    "record_followup_proof",
    "add_linkedin_proof",
    "record_camera_proof",
    "record_cad_proof",
    "record_presentation",
]


@dataclass
class NextBestAction:
    action_type: ActionType
    target_skill: str
    reason: str
    objective: str
    button_label: str
    priority: Literal["high", "medium", "low"]
    is_recording: bool
    recommended_duration: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target_skill": self.target_skill,
            "reason": self.reason,
            "objective": self.objective,
            "button_label": self.button_label,
            "priority": self.priority,
            "is_recording": self.is_recording,
            "recommended_duration": self.recommended_duration,
        }


@dataclass
class RecommendationAction:
    title: str
    reason: str
    action: str
    skill_learned: str
    evidence_to_record: str
    difficulty: Literal["beginner", "intermediate", "advanced"]
    estimated_time: Literal["30 min", "1–2 hr", "1 day", "1 week"]
    priority: Literal["high", "medium", "low"]
    source_reason: str
    action_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "reason": self.reason,
            "action": self.action,
            "skill_learned": self.skill_learned,
            "evidence_to_record": self.evidence_to_record,
            "difficulty": self.difficulty,
            "estimated_time": self.estimated_time,
            "priority": self.priority,
            "source_reason": self.source_reason,
            "action_type": self.action_type,
        }


@dataclass
class FinalRecommendations:
    mode: Literal["proof_repair", "project_growth"]
    proof_actions: list[RecommendationAction]
    learning_actions: list[RecommendationAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "proof_actions": [a.to_dict() for a in self.proof_actions],
            "learning_actions": [a.to_dict() for a in self.learning_actions],
        }


@dataclass
class EvidenceSourceResult:
    key: EvidenceSourceKey
    status: Literal["pass", "partial", "missing", "not_run", "not_available", "not_applicable"]
    score: int | None  # 0–100 contribution; None when a source is not applicable
    weight: float
    notes: str = ""


@dataclass
class ProjectContext:
    project_type: str
    project_types: set[str] = field(default_factory=set)
    target_keywords: set[str] = field(default_factory=set)
    claimed_skill_keywords: set[str] = field(default_factory=set)
    allowed_domains: set[str] = field(default_factory=set)
    negative_mismatch_keywords: set[str] = field(default_factory=set)
    context_summary: str = ""


@dataclass
class EvidenceRelevanceResult:
    relevance_score: int
    is_relevant: bool
    mismatch_detected: bool
    matched_project_terms: list[str] = field(default_factory=list)
    conflicting_project_terms: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass
class GroupedSkillEvidence:
    """One category group of skills for the grouped skill evidence UI."""
    group_name: str
    category: str
    confidence: Literal["high", "medium", "low"]
    evidence_count: int
    sources_count: int
    source_labels: list[str]
    skills: list[DetectedSkillEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_name":    self.group_name,
            "category":      self.category,
            "confidence":    self.confidence,
            "evidence_count": self.evidence_count,
            "sources_count": self.sources_count,
            "source_labels": self.source_labels,
            "skills":        [s.to_dict() for s in self.skills],
        }


@dataclass
class FinalEvaluationResult:
    proof_session_id: str
    final_score: int
    confidence: Literal["high", "medium", "low"]
    evidence_sources_used: list[EvidenceSourceKey]
    evidence_sources_missing: list[EvidenceSourceKey]
    per_skill_scores: dict[str, int]
    evidence_source_breakdown: list[dict[str, Any]]
    final_recruiter_summary: str
    final_student_summary: str
    next_best_actions: list[dict[str, Any]]
    recommendations: FinalRecommendations
    strong_proof: bool  # True when final_score >= 80
    detected_capability: DetectedCapability | None = None
    detected_additional_skills: list[DetectedSkillEntry] = field(default_factory=list)
    grouped_skill_evidence: list[GroupedSkillEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proof_session_id": self.proof_session_id,
            "final_score": self.final_score,
            "confidence": self.confidence,
            "evidence_sources_used": list(self.evidence_sources_used),
            "evidence_sources_missing": list(self.evidence_sources_missing),
            "per_skill_scores": self.per_skill_scores,
            "evidence_source_breakdown": self.evidence_source_breakdown,
            "final_recruiter_summary": self.final_recruiter_summary,
            "final_student_summary": self.final_student_summary,
            "next_best_actions": self.next_best_actions,
            "recommendations": self.recommendations.to_dict(),
            "strong_proof": self.strong_proof,
            "detected_capability": self.detected_capability.to_dict() if self.detected_capability else None,
            "detected_additional_skills": [s.to_dict() for s in self.detected_additional_skills],
            "grouped_skill_evidence": [g.to_dict() for g in self.grouped_skill_evidence],
        }


# ── Scoring weights ───────────────────────────────────────────────────────────

_SOURCE_WEIGHTS: dict[EvidenceSourceKey, float] = {
    "website_workflow":       0.25,
    "dom_visible_evidence":   0.15,
    "video_keyframes":        0.10,
    "ocr":                    0.10,
    "qwen_visual_reasoning":  0.10,
    "github":                 0.15,
    "live_website_check":     0.05,
    "project_defense":        0.10,
    # Optional boosters are neutral when absent and low-weight when present.
    "uploaded_documents":     0.04,
    "linkedin_profile":       0.03,
    "certificate":            0.03,
}

_OPTIONAL_BOOSTER_KEYS: set[EvidenceSourceKey] = {
    "uploaded_documents",
    "linkedin_profile",
    "certificate",
}


def _clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, v))


_PROJECT_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "chatbot_nlp": (
        "huggingchat", "chatbot", "chat ui", "chat interface", "prompt",
        "assistant", "llm", "large language", "nlp", "conversation", "message",
        "model response", "generated response", "chatgpt",
    ),
    "webgl_3d": (
        "three.js", "threejs", "webgl", "3d", "mesh", "geometry", "renderer",
        "scene", "camera", "texture", "shader", "simplification",
    ),
    "geospatial_map": (
        "leaflet", "map", "maps", "marker", "popup", "tile", "zoom", "pan",
        "openstreetmap", "geospatial", "gis", "coordinates", "web mapping",
        "interactive maps",
    ),
    "data_visualization": (
        "d3", "chart", "graph", "axis", "dataset", "visualization", "tooltip",
        "plot", "dashboard",
    ),
    "ml_demo": (
        "prediction", "inference", "training", "classes", "confidence",
        "tensorflow", "pytorch", "classifier", "model evaluation",
    ),
    "backend_api": (
        "api", "endpoint", "request", "response", "fastapi", "express",
        "backend", "server", "database", "auth", "rest", "graphql",
    ),
    "frontend_web": (
        "react", "typescript", "javascript", "frontend", "ui", "component",
        "browser", "css", "html",
    ),
}


def _project_terms_in_text(text: str, project_type: str) -> set[str]:
    lower = (text or "").lower()
    return {term for term in _PROJECT_TYPE_TERMS.get(project_type, ()) if _contains_project_term(lower, term)}


def _contains_project_term(lower_text: str, term: str) -> bool:
    if " " in term or "." in term:
        return term in lower_text
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lower_text) is not None


def _project_types_from_text(text: str) -> set[str]:
    return {
        project_type
        for project_type in _PROJECT_TYPE_TERMS
        if _project_terms_in_text(text, project_type)
    }


def _keywords_from_text(text: str) -> set[str]:
    lower = (text or "").lower()
    words = {
        token.strip(".,;:()[]{}'\"")
        for token in lower.replace("/", " ").replace("_", " ").replace("-", " ").split()
    }
    project_terms = {term for terms in _PROJECT_TYPE_TERMS.values() for term in terms if _contains_project_term(lower, term)}
    return {w for w in words if len(w) >= 3} | project_terms


def _host_from_url(value: str) -> str:
    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        return (parsed.netloc or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _proof_context_text(
    claimed_skills: list[str],
    wf: dict[str, Any] | None,
    gh: dict[str, Any] | None,
) -> str:
    parts: list[str] = list(claimed_skills or [])
    if wf:
        parts.extend(str(x) for x in wf.get("supported_skills") or [])
        parts.extend(str(x) for x in wf.get("weakly_supported_skills") or [])
        parts.append(str(wf.get("target_website") or ""))
        parts.append(str(wf.get("workflow_summary") or ""))
        parts.append(str(wf.get("recruiter_summary") or ""))
        parts.append(str(wf.get("page_context_summary") or ""))
        parts.append(str(wf.get("visual_summary") or ""))
        parts.append(str(wf.get("frame_ocr_evidence_summary") or ""))
        parts.append(str(wf.get("visual_reasoning_summary") or ""))
    if gh:
        parts.append(str(gh.get("repo_name") or ""))
        parts.append(str(gh.get("github_url") or gh.get("repo_url") or ""))
        parts.extend(str(x) for x in gh.get("detected_stack") or [])
        parts.extend(str(x) for x in gh.get("matched_claimed_skills") or [])
    return " ".join(parts)


def extract_project_context(
    claimed_skills: list[str],
    wf: dict[str, Any] | None,
    gh: dict[str, Any] | None,
) -> ProjectContext:
    text = _proof_context_text(claimed_skills, wf, gh)
    project_types = _project_types_from_text(text)
    # Generic frontend should not dominate a specific project family.
    specific_types = {t for t in project_types if t != "frontend_web"}
    primary = sorted(specific_types or project_types or {"unknown"})[0]
    claimed_text = " ".join(claimed_skills or [])
    domains = {
        h for h in [
            _host_from_url(str(wf.get("target_website") or "")) if wf else "",
            _host_from_url(str(gh.get("github_url") or gh.get("repo_url") or "")) if gh else "",
        ] if h
    }
    target_terms: set[str] = set()
    for project_type in project_types:
        target_terms |= _project_terms_in_text(text, project_type)
    if wf:
        target_terms |= _keywords_from_text(str(wf.get("target_website") or ""))
    return ProjectContext(
        project_type=primary,
        project_types=project_types,
        target_keywords=target_terms,
        claimed_skill_keywords=_keywords_from_text(claimed_text),
        allowed_domains=domains,
        negative_mismatch_keywords={
            term
            for project_type, terms in _PROJECT_TYPE_TERMS.items()
            if project_type not in project_types
            for term in terms
        },
        context_summary=text[:500],
    )


def _evidence_text_from_mapping(data: dict[str, Any] | None, fields: tuple[str, ...]) -> str:
    if not data:
        return ""
    values: list[str] = []
    for field in fields:
        value = data.get(field)
        if value is None:
            continue
        values.append(str(value))
    return " ".join(values)


def _workflow_source_text(wf: dict[str, Any] | None) -> str:
    return _evidence_text_from_mapping(wf, (
        "target_website", "workflow_summary", "recruiter_summary",
        "page_context_summary", "visual_summary", "observed_demonstration",
        "demonstrated_actions", "top_result_snippets", "frame_ocr_evidence_summary",
        "visual_reasoning_summary", "supported_skills", "weakly_supported_skills",
    ))


def _project_defense_text(pd: dict[str, Any] | None) -> str:
    return _evidence_text_from_mapping(pd, (
        "transcript_text", "refined_transcript", "raw_transcript",
        "transcript_summary", "recruiter_summary", "skills_mentioned",
        "skills_explained_well", "recommended_improvements",
    ))


def validate_evidence_relevance(
    context: ProjectContext,
    evidence_source_type: str,
    evidence_text: str,
) -> EvidenceRelevanceResult:
    text = evidence_text or ""
    if len(text.strip()) < 20:
        return EvidenceRelevanceResult(
            0, False, False, explanation=f"{evidence_source_type} has insufficient text for relevance validation",
        )

    evidence_types = _project_types_from_text(text)
    evidence_terms = _keywords_from_text(text)
    specific_context_types = {t for t in context.project_types if t != "frontend_web"}
    specific_evidence_types = {t for t in evidence_types if t != "frontend_web"}
    matched_terms = sorted((context.target_keywords | context.claimed_skill_keywords) & evidence_terms)
    conflicting_types = sorted(specific_evidence_types - specific_context_types)
    conflicting_terms = sorted({
        term
        for project_type in conflicting_types
        for term in _project_terms_in_text(text, project_type)
    })

    mismatch = bool(specific_context_types and specific_evidence_types and specific_context_types.isdisjoint(specific_evidence_types))
    if mismatch:
        return EvidenceRelevanceResult(
            15,
            False,
            True,
            matched_project_terms=matched_terms,
            conflicting_project_terms=conflicting_terms,
            explanation=(
                f"{evidence_source_type} appears unrelated to submitted proof "
                f"(proof={','.join(sorted(specific_context_types))}; "
                f"evidence={','.join(sorted(specific_evidence_types))})"
            ),
        )

    if evidence_types & context.project_types:
        score = 80 if matched_terms else 65
    elif matched_terms:
        score = 60
    elif not context.project_types or context.project_type == "unknown":
        score = 50
    else:
        score = 25
    return EvidenceRelevanceResult(
        score,
        score >= 45,
        False,
        matched_project_terms=matched_terms,
        conflicting_project_terms=conflicting_terms,
        explanation=f"{evidence_source_type} relevance score={score}",
    )


def _is_relevant_to_proof(
    evidence_text: str,
    claimed_skills: list[str],
    wf: dict[str, Any] | None,
    gh: dict[str, Any] | None,
) -> tuple[bool, str]:
    result = validate_evidence_relevance(
        extract_project_context(claimed_skills, wf, gh),
        "evidence",
        evidence_text,
    )
    return result.is_relevant, result.explanation


# ── Service ───────────────────────────────────────────────────────────────────

class FinalEvidenceEvaluatorService:
    """Combines all available evidence sources and produces a final score.

    Usage (sync — follows existing pattern in this repo):
        svc = FinalEvidenceEvaluatorService(db)
        result = svc.evaluate(user_id=..., session_id=..., claimed_skills=..., github_url=...)
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Data loaders ──────────────────────────────────────────────────────────

    def _load_workflow_analysis(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        # In-memory dict store (dev/test env override): iterate values directly.
        if isinstance(self._db, dict):
            store = self._db.get(_WF_TABLE, {})
            for row in store.values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None
        try:
            resp = (
                self._db.table(_WF_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("FinalEvaluator: workflow analysis load failed", exc_info=True)
            return None

    def _load_github_analysis(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        # In-memory dict store: GitHub analysis service keys rows by proof_session_id.
        if isinstance(self._db, dict):
            return self._db.get(_GH_TABLE, {}).get(session_id)
        try:
            resp = (
                self._db.table(_GH_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("FinalEvaluator: GitHub analysis load failed", exc_info=True)
            return None

    def _load_live_website_check(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        # In-memory dict store: live-check service keys rows by row id; filter by session+user.
        if isinstance(self._db, dict):
            for row in self._db.get(_LW_TABLE, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None
        try:
            resp = (
                self._db.table(_LW_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("checked_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("FinalEvaluator: live website check load failed", exc_info=True)
            return None

    def _load_project_defense(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        # In-memory dict store: project defense service uses proof_session_id as key.
        if isinstance(self._db, dict):
            direct = self._db.get(_PD_TABLE, {}).get(session_id)
            if direct:
                return direct
            for row in self._db.get(_PD_TABLE, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None
        try:
            resp = (
                self._db.table(_PD_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("FinalEvaluator: project defense load failed", exc_info=True)
            return None

    def _load_optional_evidence(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        # In-memory dict store: collect all submissions for this session+user.
        if isinstance(self._db, dict):
            return [
                row for row in self._db.get(_OPT_TABLE, {}).values()
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                )
            ]
        try:
            resp = (
                self._db.table(_OPT_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.warning("FinalEvaluator: optional evidence load failed", exc_info=True)
            return []

    def _load_frame_text_summary_from_frames(self, user_id: str, session_id: str) -> str:
        """Collect public OCR/frame text from keyframe rows for final scoring only."""
        rows: list[dict[str, Any]] = []
        try:
            if isinstance(self._db, dict):
                rows = [
                    row for row in self._db.get(_VF_TABLE, {}).values()
                    if (
                        str(row.get("proof_session_id")) == session_id
                        and str(row.get("user_id")) == user_id
                        and row.get("frame_type") == "video_keyframe"
                    )
                ]
            else:
                resp = (
                    self._db.table(_VF_TABLE)
                    .select("ocr_text, visual_summary")
                    .eq("user_id", user_id)
                    .eq("proof_session_id", session_id)
                    .eq("frame_type", "video_keyframe")
                    .limit(20)
                    .execute()
                )
                rows = resp.data or []
        except Exception:
            return ""

        snippets: list[str] = []
        for row in rows:
            raw_ocr = row.get("ocr_text")
            if isinstance(raw_ocr, list):
                for item in raw_ocr:
                    if isinstance(item, dict) and item.get("text"):
                        snippets.append(str(item["text"]))
                    elif isinstance(item, str):
                        snippets.append(item)
            elif isinstance(raw_ocr, str):
                snippets.append(raw_ocr)
            if row.get("visual_summary"):
                snippets.append(str(row["visual_summary"]))
        return " | ".join(s.strip() for s in snippets if s and s.strip())[:1200]

    def _enrich_workflow_for_final(
        self,
        wf: dict[str, Any] | None,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Mirror the workflow endpoint's live enrichment before final scoring."""
        if wf is None:
            return None
        enriched = dict(wf)

        frame_text = self._load_frame_text_summary_from_frames(user_id, session_id)
        if frame_text and not enriched.get("visual_summary"):
            enriched["visual_summary"] = frame_text
        if frame_text and not int(enriched.get("visual_frame_count") or 0):
            enriched["visual_frame_count"] = max(1, self._count_video_keyframes(user_id, session_id))
        if frame_text and enriched.get("visual_analysis_status") in (None, "", "not_configured", "not_available"):
            enriched["visual_analysis_status"] = "analyzed"

        ocr_summary = enriched.get("frame_ocr_evidence_summary")
        if not (isinstance(ocr_summary, dict) and ocr_summary):
            try:
                from app.services.extension_proof_workflow_analysis_service import _build_frame_ocr_evidence_summary
                claimed = (
                    list(enriched.get("supported_skills") or [])
                    + list(enriched.get("weakly_supported_skills") or [])
                    + list(enriched.get("unsupported_skills") or [])
                )
                enriched["frame_ocr_evidence_summary"] = _build_frame_ocr_evidence_summary({
                    "visual_frame_analysis_status": enriched.get("visual_analysis_status", "not_configured"),
                    "provider_used": enriched.get("visual_analysis_provider", "frame_text"),
                    "visual_frame_count": int(enriched.get("visual_frame_count") or 0),
                    "visual_summary": enriched.get("visual_summary", "") or frame_text,
                }, claimed)
            except Exception:
                if frame_text:
                    enriched["frame_ocr_evidence_summary"] = {
                        "has_ocr_evidence": True,
                        "top_ocr_snippets": [frame_text[:300]],
                        "detected_page_context": "unknown",
                        "skill_signals": [],
                    }

        if not enriched.get("visual_reasoning_summary"):
            per_frame = self._load_visual_reasoning_from_frames(user_id, session_id)
            if per_frame:
                enriched["visual_reasoning_summary"] = per_frame

        return enriched

    def _count_video_keyframes(self, user_id: str, session_id: str) -> int:
        # In-memory dict store: count video_keyframe rows for this session+user.
        if isinstance(self._db, dict):
            return sum(
                1 for row in self._db.get(_VF_TABLE, {}).values()
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                    and row.get("frame_type") == "video_keyframe"
                )
            )
        try:
            resp = (
                self._db.table(_VF_TABLE)
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .eq("frame_type", "video_keyframe")
                .execute()
            )
            if hasattr(resp, "count") and resp.count is not None:
                return int(resp.count)
            return len(resp.data or [])
        except Exception:
            return 0

    # ── Score individual sources ──────────────────────────────────────────────

    def _score_workflow(
        self,
        wf: dict[str, Any] | None,
        context: ProjectContext | None = None,
    ) -> EvidenceSourceResult:
        if wf is None:
            return EvidenceSourceResult("website_workflow", "not_run", 0, _SOURCE_WEIGHTS["website_workflow"])
        if context:
            rel = validate_evidence_relevance(context, "website workflow", _workflow_source_text(wf))
            if rel.mismatch_detected:
                return EvidenceSourceResult(
                    "website_workflow", "missing", 15, _SOURCE_WEIGHTS["website_workflow"],
                    notes=rel.explanation,
                )
        raw_score = wf.get("evidence_strength_score") or 0
        score = _clamp(int(raw_score))
        conf = wf.get("workflow_confidence", "insufficient")
        if score >= 60:
            status = "pass"
        elif score >= 30:
            status = "partial"
        else:
            status = "missing"
        return EvidenceSourceResult(
            "website_workflow", status, score, _SOURCE_WEIGHTS["website_workflow"],
            notes=f"workflow confidence={conf}",
        )

    def _score_dom(
        self,
        wf: dict[str, Any] | None,
        context: ProjectContext | None = None,
    ) -> EvidenceSourceResult:
        if wf is None:
            return EvidenceSourceResult("dom_visible_evidence", "not_run", 0, _SOURCE_WEIGHTS["dom_visible_evidence"])
        vis = wf.get("dom_evidence_status") or wf.get("visible_evidence_status") or "not_captured"
        observed = wf.get("observed_demonstration") or {}
        if isinstance(observed, dict):
            vis = observed.get("dom_evidence_status") or observed.get("visible_evidence_status") or vis
        top_snippets = wf.get("top_result_snippets") or []
        if isinstance(observed, dict):
            top_snippets = top_snippets or observed.get("top_result_snippets") or []
        actions = len(wf.get("demonstrated_actions") or [])
        dom_text = " ".join([
            str(wf.get("page_context_summary") or ""),
            str(wf.get("demonstrated_actions") or ""),
            str(top_snippets or ""),
            str(observed or ""),
        ])
        if context and dom_text.strip():
            rel = validate_evidence_relevance(context, "DOM visible evidence", dom_text)
            if rel.mismatch_detected:
                return EvidenceSourceResult(
                    "dom_visible_evidence", "missing", 10, _SOURCE_WEIGHTS["dom_visible_evidence"],
                    notes=rel.explanation,
                )
        if vis == "available" and actions > 3:
            return EvidenceSourceResult("dom_visible_evidence", "pass", 80, _SOURCE_WEIGHTS["dom_visible_evidence"])
        if vis in ("available", "partial") or actions > 0 or top_snippets:
            return EvidenceSourceResult("dom_visible_evidence", "partial", 50, _SOURCE_WEIGHTS["dom_visible_evidence"])
        return EvidenceSourceResult("dom_visible_evidence", "missing", 10, _SOURCE_WEIGHTS["dom_visible_evidence"])

    def _score_video_keyframes(self, kf_count: int) -> EvidenceSourceResult:
        if kf_count >= 3:
            return EvidenceSourceResult("video_keyframes", "pass", 90, _SOURCE_WEIGHTS["video_keyframes"])
        if kf_count >= 1:
            return EvidenceSourceResult("video_keyframes", "partial", 60, _SOURCE_WEIGHTS["video_keyframes"])
        return EvidenceSourceResult("video_keyframes", "not_run", 0, _SOURCE_WEIGHTS["video_keyframes"])

    def _score_ocr(
        self,
        wf: dict[str, Any] | None,
        context: ProjectContext | None = None,
    ) -> EvidenceSourceResult:
        if wf is None:
            return EvidenceSourceResult("ocr", "not_run", 0, _SOURCE_WEIGHTS["ocr"])
        ocr_summary = wf.get("frame_ocr_evidence_summary") or {}
        if isinstance(ocr_summary, dict) and ocr_summary.get("detected_page_context") == "filtered_non_target_frame":
            return EvidenceSourceResult("ocr", "not_run", 0, _SOURCE_WEIGHTS["ocr"],
                                        notes="non-target frames excluded from scoring")

        ocr_text = str(ocr_summary)
        if context and ocr_text.strip() and ocr_text != "{}":
            rel = validate_evidence_relevance(context, "OCR text", ocr_text)
            if rel.mismatch_detected:
                return EvidenceSourceResult("ocr", "missing", 10, _SOURCE_WEIGHTS["ocr"], notes=rel.explanation)

        status = wf.get("visual_analysis_status", "not_configured")
        if status == "analyzed":
            return EvidenceSourceResult("ocr", "pass", 80, _SOURCE_WEIGHTS["ocr"])

        # Root-cause fix: frame_ocr_evidence_summary can be populated from Qwen/video
        # frame analysis even when the traditional OCR provider (PaddleOCR/EasyOCR/
        # Tesseract) was not configured.  Check it before returning "not_run".
        if isinstance(ocr_summary, dict) and (
            ocr_summary.get("has_ocr_evidence") or
            len(ocr_summary.get("top_ocr_snippets") or []) > 0
        ):
            return EvidenceSourceResult("ocr", "partial", 50, _SOURCE_WEIGHTS["ocr"],
                                        notes="frame text evidence from video/Qwen analysis")

        if status in ("not_configured", "not_available"):
            return EvidenceSourceResult("ocr", "not_run", 0, _SOURCE_WEIGHTS["ocr"],
                                        notes="OCR not configured")
        return EvidenceSourceResult("ocr", "partial", 40, _SOURCE_WEIGHTS["ocr"])

    def _load_visual_reasoning_from_frames(
        self, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        """Re-query per-frame visual_reasoning_json from the frame evidence table.

        The GET /analysis/workflow endpoint always re-derives visual_reasoning_summary
        from per-frame data via _enrich_visual_reasoning_summary() and bypasses the
        cached value on the workflow_analysis_results row.  The final evaluator reads
        the raw row and may see a null/stale stored summary.  This helper performs the
        same per-frame query so the scorer sees current data.

        Returns a minimal vrs-compatible dict or None when no frames have reasoning.
        """
        _FRAME_TABLE = "workflow_visual_frame_evidence"
        try:
            if isinstance(self._db, dict):
                rows = [
                    row for row in self._db.get(_FRAME_TABLE, {}).values()
                    if (
                        str(row.get("user_id")) == user_id
                        and str(row.get("proof_session_id")) == session_id
                        and row.get("frame_type") == "video_keyframe"
                        and row.get("visual_reasoning_json") is not None
                    )
                ]
            else:
                resp = (
                    self._db.table(_FRAME_TABLE)
                    .select("visual_reasoning_json, timestamp_ms")
                    .eq("user_id", user_id)
                    .eq("proof_session_id", session_id)
                    .eq("frame_type", "video_keyframe")
                    .not_.is_("visual_reasoning_json", "null")
                    .order("timestamp_ms", desc=False)
                    .limit(10)
                    .execute()
                )
                rows = resp.data or []
        except Exception:
            return None

        if not rows:
            return None

        observations: list[dict[str, Any]] = []
        for row in rows:
            reasoning_json = row.get("visual_reasoning_json")
            if isinstance(reasoning_json, dict) and reasoning_json.get("status") == "analyzed":
                observations.append(reasoning_json)

        if not observations:
            return None

        return {
            "status": "analyzed",
            "frames_analyzed": len(observations),
            "observations": observations,
            "supported_signals": list(dict.fromkeys(
                sig
                for obs in observations
                for sig in (obs.get("supported_skills") or [])
            )),
        }

    @staticmethod
    def _qwen_obs_chatbot_score(vrs: dict[str, Any]) -> int:
        """Return partial score if Qwen observations describe chatbot/chat-UI content."""
        _CHATBOT_TERMS: frozenset[str] = frozenset({
            "huggingchat", "chat window", "chat ui", "chat interface", "input field",
            "chatbot", "assistant", "conversation", "typed", "message input",
            "prompt", "ai response", "model response", "generated response",
        })
        observations = vrs.get("observations") or []
        for obs in observations:
            text = " ".join([
                str(obs.get("visual_summary", "")),
                " ".join(str(x) for x in (obs.get("visible_ui_elements") or [])),
                str(obs.get("detected_user_action", "")),
            ]).lower()
            if sum(1 for t in _CHATBOT_TERMS if t in text) >= 1:
                return 50  # partial evidence — target chatbot UI observed
        return 0

    def _score_qwen(
        self,
        wf: dict[str, Any] | None,
        user_id: str = "",
        session_id: str = "",
        context: ProjectContext | None = None,
    ) -> EvidenceSourceResult:
        if wf is None:
            return EvidenceSourceResult("qwen_visual_reasoning", "not_run", 0, _SOURCE_WEIGHTS["qwen_visual_reasoning"])
        vrs = wf.get("visual_reasoning_summary") or {}
        if isinstance(vrs, str):
            try:
                import json as _json
                vrs = _json.loads(vrs)
            except Exception:
                vrs = {}
        if not isinstance(vrs, dict):
            vrs = {}

        # Root-cause fix: the GET /analysis/workflow endpoint always re-queries
        # visual_reasoning_summary from per-frame data (bypassing the stored value
        # which may be null or stale when Qwen ran after the initial analysis).
        # If stored summary is absent or disabled, fall back to per-frame data.
        qwen_status = vrs.get("status", "disabled")
        if qwen_status in ("disabled", "not_configured") and user_id and session_id:
            per_frame = self._load_visual_reasoning_from_frames(user_id, session_id)
            if per_frame:
                vrs = per_frame
                qwen_status = "analyzed"
        if qwen_status == "analyzed":
            if context:
                rel = validate_evidence_relevance(context, "Qwen visual reasoning", str(vrs))
                if rel.mismatch_detected:
                    return EvidenceSourceResult(
                        "qwen_visual_reasoning",
                        "missing",
                        20,
                        _SOURCE_WEIGHTS["qwen_visual_reasoning"],
                        notes=rel.explanation,
                    )
            frames = int(vrs.get("frames_analyzed") or 0)
            score = min(90, 50 + frames * 15)
            return EvidenceSourceResult("qwen_visual_reasoning", "pass", score, _SOURCE_WEIGHTS["qwen_visual_reasoning"])
        if qwen_status == "filtered_non_target_frame":
            # Still check whether observations describe target chatbot content.
            # Filtering may have been too aggressive if Qwen saw HuggingChat / chat UI.
            chatbot_score = self._qwen_obs_chatbot_score(vrs)
            if chatbot_score > 0:
                return EvidenceSourceResult(
                    "qwen_visual_reasoning",
                    "partial",
                    chatbot_score,
                    _SOURCE_WEIGHTS["qwen_visual_reasoning"],
                    notes="Qwen detected chatbot target content; extension events were limited",
                )
            return EvidenceSourceResult(
                "qwen_visual_reasoning",
                "not_run",
                0,
                _SOURCE_WEIGHTS["qwen_visual_reasoning"],
                notes="non-target frames excluded from scoring",
            )
        if qwen_status in ("pending", "skipped_no_frames"):
            # pending: Qwen configured, no frames yet (transient).
            # skipped_no_frames: no video was recorded, Qwen cannot run (terminal).
            # Neither is a penalty — treat as not_run with an informative note.
            note = (
                "No video keyframes found — Qwen skipped. Record a video to enable visual analysis."
                if qwen_status == "skipped_no_frames"
                else "processing — refresh after Qwen analysis completes"
            )
            return EvidenceSourceResult("qwen_visual_reasoning", "not_run", 0, _SOURCE_WEIGHTS["qwen_visual_reasoning"],
                                        notes=note)
        if qwen_status == "disabled":
            return EvidenceSourceResult("qwen_visual_reasoning", "not_available", 0, _SOURCE_WEIGHTS["qwen_visual_reasoning"],
                                        notes="VISUAL_REASONING_ENABLED=false")
        if qwen_status == "not_configured":
            # Enabled in config but packages not installed — distinct from "disabled"
            return EvidenceSourceResult("qwen_visual_reasoning", "not_available", 0, _SOURCE_WEIGHTS["qwen_visual_reasoning"],
                                        notes="Qwen packages not installed — VISUAL_REASONING_ENABLED=true but model unavailable")
        if qwen_status == "skipped":
            return EvidenceSourceResult("qwen_visual_reasoning", "not_run", 0, _SOURCE_WEIGHTS["qwen_visual_reasoning"],
                                        notes="frames skipped (resource limit)")
        return EvidenceSourceResult("qwen_visual_reasoning", "missing", 20, _SOURCE_WEIGHTS["qwen_visual_reasoning"])

    def _score_github(self, gh: dict[str, Any] | None) -> EvidenceSourceResult:
        if gh is None:
            return EvidenceSourceResult("github", "not_run", 0, _SOURCE_WEIGHTS["github"])
        if gh.get("status") == "success":
            score = _clamp(int((gh.get("confidence_score") or 0) * 100))
            matched = len(gh.get("matched_claimed_skills") or [])
            combined = min(100, score + matched * 5)
            return EvidenceSourceResult("github", "pass" if combined >= 50 else "partial",
                                        combined, _SOURCE_WEIGHTS["github"])
        return EvidenceSourceResult("github", "missing", 10, _SOURCE_WEIGHTS["github"])

    def _score_live_website(self, lw: dict[str, Any] | None) -> EvidenceSourceResult:
        if lw and str(lw.get("status") or "") == "not_applicable":
            return EvidenceSourceResult(
                "live_website_check",
                "not_applicable",
                None,
                _SOURCE_WEIGHTS["live_website_check"],
                notes=str(lw.get("recruiter_summary") or local_private_live_check_note()),
            )
        if lw is None:
            return EvidenceSourceResult("live_website_check", "not_run", 0, _SOURCE_WEIGHTS["live_website_check"])
        if lw.get("is_reachable"):
            return EvidenceSourceResult("live_website_check", "pass", 90, _SOURCE_WEIGHTS["live_website_check"])
        return EvidenceSourceResult("live_website_check", "missing", 20, _SOURCE_WEIGHTS["live_website_check"])

    def _score_live_website_for_workflow(
        self,
        lw: dict[str, Any] | None,
        wf: dict[str, Any] | None,
    ) -> EvidenceSourceResult:
        scored = self._score_live_website(lw)
        if lw is not None or scored.status != "not_run":
            return scored
        target_url = str((wf or {}).get("target_website") or (wf or {}).get("original_url") or "")
        classification = classify_website_url(target_url)
        if target_url and classification.is_local_or_private:
            return EvidenceSourceResult(
                "live_website_check",
                "not_applicable",
                None,
                _SOURCE_WEIGHTS["live_website_check"],
                notes=local_private_live_check_note(),
            )
        return scored

    def _score_project_defense(
        self,
        pd: dict[str, Any] | None,
        claimed_skills: list[str] | None = None,
        wf: dict[str, Any] | None = None,
        gh: dict[str, Any] | None = None,
        context: ProjectContext | None = None,
    ) -> EvidenceSourceResult:
        if pd is None:
            return EvidenceSourceResult("project_defense", "not_run", 0, _SOURCE_WEIGHTS["project_defense"])
        analysis_status = pd.get("analysis_status", "not_started")
        transcript = _project_defense_text(pd)
        rel = validate_evidence_relevance(
            context or extract_project_context(claimed_skills or [], wf, gh),
            "project defense transcript",
            transcript,
        )
        if transcript and rel.mismatch_detected:
            return EvidenceSourceResult(
                "project_defense",
                "partial",
                min(20, rel.relevance_score),
                _SOURCE_WEIGHTS["project_defense"],
                notes=f"transcript appears unrelated to submitted proof; {rel.explanation}",
            )
        raw_score = pd.get("overall_score")
        if raw_score is None:
            raw_score = pd.get("overall_defense_score")
        if raw_score is None:
            dims = [
                pd.get("consistency_with_evidence_score"),
                pd.get("explanation_clarity_score"),
                pd.get("ownership_signal_score"),
                pd.get("technical_depth_score"),
            ]
            dim_vals = [int(v) for v in dims if v is not None]
            if dim_vals:
                raw_score = round(sum(dim_vals) / len(dim_vals))
        if raw_score is None and analysis_status == "analyzed" and len(transcript) > 50:
            raw_score = 40
        if raw_score is not None:
            score_val = _clamp(int(raw_score or 0))
            return EvidenceSourceResult("project_defense", "pass" if score_val >= 60 else "partial",
                                        score_val, _SOURCE_WEIGHTS["project_defense"])
        if len(transcript) > 50:
            return EvidenceSourceResult("project_defense", "partial", 40, _SOURCE_WEIGHTS["project_defense"])
        return EvidenceSourceResult("project_defense", "not_run", 0, _SOURCE_WEIGHTS["project_defense"])

    def _score_optional(
        self,
        rows: list[dict[str, Any]],
        source_type: str,
        key: EvidenceSourceKey,
        claimed_skills: list[str] | None = None,
        wf: dict[str, Any] | None = None,
        gh: dict[str, Any] | None = None,
        context: ProjectContext | None = None,
    ) -> EvidenceSourceResult:
        matching = [r for r in rows if r.get("source_type") == source_type]
        if not matching:
            return EvidenceSourceResult(key, "not_available", 0, _SOURCE_WEIGHTS[key],
                                        notes="Optional — can strengthen your profile")
        relevant_matching: list[dict[str, Any]] = []
        unrelated_found = False
        for row in matching:
            evidence_text = " ".join([
                str(row.get("analysis_summary") or ""),
                str(row.get("analysis_json") or ""),
                str(row.get("evidence_objects") or ""),
            ])
            rel = validate_evidence_relevance(
                context or extract_project_context(claimed_skills or [], wf, gh),
                source_type,
                evidence_text,
            )
            if rel.is_relevant and not rel.mismatch_detected:
                relevant_matching.append(row)
            else:
                unrelated_found = True
        if unrelated_found and not relevant_matching:
            return EvidenceSourceResult(
                key,
                "partial",
                0,
                _SOURCE_WEIGHTS[key],
                notes="document appears unrelated to submitted proof; not used as score booster",
            )
        matching = relevant_matching or matching
        ev_count = sum(len(r.get("evidence_objects") or []) for r in matching)
        if ev_count > 0:
            return EvidenceSourceResult(key, "pass", min(90, 55 + ev_count * 8), _SOURCE_WEIGHTS[key])
        if any(r.get("status") in ("needs_review", "url_added") for r in matching):
            return EvidenceSourceResult(key, "partial", 55, _SOURCE_WEIGHTS[key],
                                        notes="needs stronger evidence")
        return EvidenceSourceResult(key, "partial", 45, _SOURCE_WEIGHTS[key],
                                    notes="optional evidence submitted but weak")

    def _filter_relevant_optional_rows(
        self,
        rows: list[dict[str, Any]],
        claimed_skills: list[str],
        wf: dict[str, Any] | None,
        gh: dict[str, Any] | None,
        context: ProjectContext | None = None,
    ) -> list[dict[str, Any]]:
        ctx = context or extract_project_context(claimed_skills, wf, gh)
        relevant_rows: list[dict[str, Any]] = []
        for row in rows:
            evidence_text = " ".join([
                str(row.get("analysis_summary") or ""),
                str(row.get("analysis_json") or ""),
                str(row.get("evidence_objects") or ""),
            ])
            rel = validate_evidence_relevance(ctx, str(row.get("source_type") or "document"), evidence_text)
            if rel.is_relevant and not rel.mismatch_detected:
                relevant_rows.append(row)
        return relevant_rows

    # ── Score combination ─────────────────────────────────────────────────────

    def _combine_scores(self, sources: list[EvidenceSourceResult]) -> int:
        """Weighted average over core sources, with optional sources as bonus only."""
        run_sources = [s for s in sources if s.status not in ("not_run", "not_available", "not_applicable")]
        core_sources = [s for s in run_sources if s.key not in _OPTIONAL_BOOSTER_KEYS]
        optional_sources = [s for s in run_sources if s.key in _OPTIONAL_BOOSTER_KEYS]
        if not core_sources:
            if not optional_sources:
                return 0
            best_optional = max(s.score or 0 for s in optional_sources)
            return _clamp(min(60, best_optional))
        total_weight = sum(s.weight for s in core_sources)
        if total_weight == 0:
            return 0
        weighted_sum = sum((s.score or 0) * s.weight for s in core_sources)
        raw = weighted_sum / total_weight
        # Bonus if multiple source types agree (breadth bonus up to +5)
        pass_count = sum(1 for s in core_sources if s.status == "pass")
        bonus = min(5, pass_count)
        base_score = _clamp(int(raw + bonus))

        optional_bonus = 0
        for s in optional_sources:
            if s.status == "pass" and (s.score or 0) >= 80:
                optional_bonus = max(optional_bonus, 3)
            elif s.status == "pass" and (s.score or 0) >= 65:
                optional_bonus = max(optional_bonus, 2)
            elif s.status == "partial" and (s.score or 0) >= 55:
                optional_bonus = max(optional_bonus, 1)

        return _clamp(base_score + optional_bonus)

    def _confidence_label(
        self,
        final_score: int,
        sources_used: list[EvidenceSourceKey],
    ) -> Literal["high", "medium", "low"]:
        n = len(sources_used)
        if n >= 4 and final_score >= 70:
            return "high"
        if n >= 2 and final_score >= 50:
            return "medium"
        return "low"

    # ── Per-skill scoring ─────────────────────────────────────────────────────

    def _per_skill_scores(
        self,
        claimed_skills: list[str],
        wf: dict[str, Any] | None,
        gh: dict[str, Any] | None,
        optional_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        supported = set(s.lower() for s in (wf or {}).get("supported_skills") or [])
        partial   = set(s.lower() for s in (wf or {}).get("weakly_supported_skills") or [])
        gh_matched = set(s.lower() for s in (gh or {}).get("matched_claimed_skills") or []) if gh else set()
        gh_weak    = set(s.lower() for s in (gh or {}).get("weakly_matched_claimed_skills") or []) if gh else set()

        gh_sce: list[dict[str, Any]] = [
            d for d in ((gh or {}).get("skill_code_evidence") or []) if isinstance(d, dict)
        ] if gh and (gh or {}).get("status") == "success" else []

        for skill in claimed_skills:
            key = skill.lower()
            base = 0
            if key in supported:
                base += 60
            elif key in partial:
                base += 35
            if key in gh_matched:
                base += 25
            elif key in gh_weak:
                base += 12
            # For visual/graphics skills, OCR cannot read rendered content so
            # supported_skills/gh_matched may be empty.  Credit GitHub code
            # evidence directly so the score is not forced to zero.
            if base == 0 and _is_visual_graphics_skill(skill) and gh_sce:
                if any(_github_code_evidence_matches_skill(ev, skill) for ev in gh_sce):
                    base = 35
            for row in optional_rows or []:
                for ev in row.get("evidence_objects") or []:
                    if str(ev.get("skill_name") or "").lower() == key:
                        base += 10 if ev.get("confidence") == "high" else 7 if ev.get("confidence") == "medium" else 3
            result[skill] = _clamp(base)
        return result

    # ── Detected Skill Profile inference ─────────────────────────────────────

    def _collect_all_evidence_skills(
        self,
        claimed_skills: list[str],
        wf: dict[str, Any] | None,
        gh: dict[str, Any] | None,
        pd: dict[str, Any] | None = None,
        optional_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, DetectedSkillEntry]:
        """Collect all skills from evidence sources, keyed by lowercase skill name."""
        entries: dict[str, DetectedSkillEntry] = {}
        claimed_lower = {s.lower() for s in claimed_skills}

        def _add(skill: str, confidence: Literal["high", "medium", "low"],
                 support: str, source: str) -> None:
            key = skill.lower()
            is_inferred = key not in claimed_lower
            if key in entries:
                existing = entries[key]
                if source not in existing.sources:
                    existing.sources.append(source)
                if confidence == "high" and existing.confidence != "high":
                    entries[key] = DetectedSkillEntry(
                        skill=existing.skill, confidence="high",
                        evidence_support=support, sources=existing.sources,
                        is_inferred=is_inferred,
                    )
            else:
                entries[key] = DetectedSkillEntry(
                    skill=skill, confidence=confidence,
                    evidence_support=support, sources=[source],
                    is_inferred=is_inferred,
                )

        # ── Claimed skills themselves ──────────────────────────────────────
        for s in claimed_skills:
            _add(s, "low", "Student self-claimed", "claimed")

        # ── Workflow evidence ──────────────────────────────────────────────
        if wf:
            for s in (wf.get("supported_skills") or []):
                _add(s, "high", "Supported by workflow recording and AI analysis", "workflow")
            for s in (wf.get("weakly_supported_skills") or []):
                _add(s, "medium", "Partially supported by workflow recording", "workflow")

            # Qwen visual reasoning signals
            vrs = wf.get("visual_reasoning_summary") or {}
            if isinstance(vrs, str):
                try:
                    import json as _j
                    vrs = _j.loads(vrs)
                except Exception:
                    vrs = {}
            if isinstance(vrs, dict) and vrs.get("status") == "analyzed":
                for sig in (vrs.get("supported_signals") or []):
                    _add(str(sig), "medium", "Evidence suggests this skill from visual frame analysis", "Qwen")

            # OCR skill signals
            ocr_summary = wf.get("frame_ocr_evidence_summary") or {}
            if isinstance(ocr_summary, dict):
                for sig in (ocr_summary.get("skill_signals") or []):
                    if isinstance(sig, dict) and sig.get("ocr_support") == "partial":
                        _add(
                            str(sig.get("skill", "")),
                            "medium",
                            sig.get("reasoning", "Partially supported by OCR text analysis")[:120],
                            "OCR",
                        )

            # ── Visual/graphics skill upgrade via Qwen observation ─────────
            # For canvas/WebGL/GPU-rendered skills, OCR cannot extract the
            # skill name from the rendered output.  If Qwen analyzed frames
            # and observed visual/graphics rendering, promote claimed visual
            # skills from "low" confidence so they are not marked missing
            # solely because OCR found no matching text.
            if isinstance(vrs, dict) and vrs.get("status") == "analyzed":
                _qwen_vis_text = str(vrs.get("summary", "")).lower()
                for _obs in (vrs.get("observations") or []):
                    if isinstance(_obs, dict):
                        _qwen_vis_text += " " + str(_obs.get("description", "")).lower()
                _qwen_vis_hits = sum(
                    1 for kw in _QWEN_VISUAL_RENDER_INDICATORS if kw in _qwen_vis_text
                )
                if _qwen_vis_hits >= 2:
                    for _sv in claimed_skills:
                        if not _is_visual_graphics_skill(_sv):
                            continue
                        _ek = _sv.lower()
                        if _ek not in entries:
                            continue
                        _ve = entries[_ek]
                        if "Qwen" not in _ve.sources:
                            _ve.sources.append("Qwen")
                        if _ve.confidence == "low":
                            _ve.confidence = "medium"
                            _ve.evidence_support = (
                                "Visual rendering observed by Qwen — "
                                "OCR is limited on canvas/WebGL/graphics pages"
                            )

        # ── GitHub evidence ────────────────────────────────────────────────
        if gh and gh.get("status") == "success":
            raw_skill_code_evidence = [
                d for d in (gh.get("skill_code_evidence") or [])
                if isinstance(d, dict)
            ]
            for s in (gh.get("matched_claimed_skills") or []):
                _add(s, "high", "Supported by GitHub repository analysis", "GitHub")
            for s in (gh.get("weakly_matched_claimed_skills") or []):
                _add(s, "medium", "Partially supported by GitHub repository", "GitHub")
            for s in claimed_skills:
                if any(_github_code_evidence_matches_skill(ev, s) for ev in raw_skill_code_evidence):
                    _add(s, "high", "Supported by exact GitHub code evidence", "GitHub")
            for ev in raw_skill_code_evidence:
                ev_skill = str(ev.get("skill") or "").strip()
                if ev_skill:
                    _add(ev_skill, "high", "Supported by exact GitHub code evidence", "GitHub")
            # Tech stack detected from repo (may not be in claimed skills)
            for tech in (gh.get("detected_stack") or []):
                if tech and len(tech) <= 40:
                    _add(tech, "medium", "Detected in GitHub repository tech stack", "GitHub")

        # ── Optional booster evidence ──────────────────────────────────────
        for opt in optional_rows or []:
            src_type = str(opt.get("source_type") or "")
            source_label = {
                "document": "document",
                "linkedin_profile": "linkedin_profile",
                "certificate_transcript": "certificate_transcript",
            }.get(src_type)
            if not source_label:
                continue
            for ev in opt.get("evidence_objects") or []:
                if not isinstance(ev, dict):
                    continue
                skill = str(ev.get("skill_name") or "").strip()
                if not skill:
                    continue
                conf = str(ev.get("confidence") or "medium")
                confidence: Literal["high", "medium", "low"] = (
                    "high" if conf == "high" else "low" if conf == "low" else "medium"
                )
                support = str(ev.get("reason") or f"Supported by {src_type.replace('_', ' ')} evidence")
                if src_type == "certificate_transcript" and confidence == "high":
                    confidence = "medium"
                _add(skill, confidence, support[:140], source_label)

        # ── Project Defense transcript skill inference ───────────────────────
        if pd:
            pd_text_for_skills = str(pd.get("transcript_text") or "").lower()
            if pd_text_for_skills:
                transcript_skill_terms = [
                    ("Natural Language Processing", ("natural language processing", "nlp", "text processing")),
                    ("Large Language Models", ("large language model", "large language models", "llm", "llms", "model response")),
                    ("Chatbot UI", ("chatbot", "chat ui", "chat interface", "message input", "conversation")),
                    ("AI Product Design", ("ai product", "prompt", "assistant response", "user experience", "chat workflow")),
                ]
                for skill_name, terms in transcript_skill_terms:
                    if any(term in pd_text_for_skills for term in terms):
                        _add(skill_name, "medium", "Partially supported by project defense transcript", "transcript")

        # ── Post-process: proof references, status labels, category, evidence_objects ──
        kf_status = (wf or {}).get("video_keyframe_status")
        kf_count = int((wf or {}).get("video_keyframe_count") or 0)
        kf_timestamps: list[int] = (wf or {}).get("video_keyframe_timestamps_ms") or []
        gh_stack: list[str] = [str(s) for s in ((gh or {}).get("detected_stack") or [])]
        gh_matched: set[str] = {s.lower() for s in ((gh or {}).get("matched_claimed_skills") or [])}
        gh_evidence_files: list[str] = [str(f) for f in ((gh or {}).get("evidence_files") or [])]
        gh_repo_url: str = str((gh or {}).get("github_url") or (gh or {}).get("repo_url") or "")
        # Deep line-level code evidence (added by the extended analyzer)
        gh_skill_code_evidence: list[dict[str, Any]] = [
            d for d in ((gh or {}).get("skill_code_evidence") or [])
            if isinstance(d, dict)
        ]
        gh_repo_name = str((gh or {}).get("repo_name") or "") or _github_repo_name(gh_repo_url)
        recording_sources = {"workflow", "Qwen", "OCR"}

        # Qwen reasoning summary for per-skill evidence objects
        vrs_for_obj: dict[str, Any] = {}
        if wf:
            _vrs = wf.get("visual_reasoning_summary") or {}
            if isinstance(_vrs, str):
                try:
                    import json as _jj
                    _vrs = _jj.loads(_vrs)
                except Exception:
                    _vrs = {}
            if isinstance(_vrs, dict):
                vrs_for_obj = _vrs

        for entry in entries.values():
            in_claimed = entry.skill.lower() in claimed_lower

            # Category
            entry.category = _skill_category(entry.skill)

            # Source labels
            entry.source_labels = _sources_to_labels(entry.sources)

            # Status label — recruiter-safe wording
            if in_claimed:
                if entry.confidence == "high":
                    entry.status_label = "claimed — strongly supported"
                elif entry.confidence == "medium":
                    entry.status_label = "claimed — partially supported"
                else:
                    entry.status_label = "claimed"
            else:
                if entry.confidence == "high":
                    entry.status_label = "inferred — strongly supported"
                elif entry.confidence == "medium":
                    entry.status_label = "inferred from evidence"
                else:
                    entry.status_label = "inferred (low confidence)"

            # Keyframe proof references + evidence objects
            if any(s in recording_sources for s in entry.sources):
                if kf_count > 0 and kf_status == "extracted":
                    ts_labels = [f"{ts / 1000:.1f}s" for ts in kf_timestamps[:3]]
                    ts_str = ", ".join(ts_labels)
                    entry.keyframe_evidence.append(
                        f"Recording keyframes captured — {kf_count} frame{'s' if kf_count != 1 else ''}"
                        + (f" (at {ts_str})" if ts_str else "")
                    )
                    for ts_ms in kf_timestamps[:3]:
                        entry.evidence_objects.append(EvidenceObject(
                            evidence_type="recording_keyframe",
                            source_name="Recording",
                            confidence=entry.confidence,
                            short_summary=f"Keyframe at {ts_ms / 1000:.1f}s — workflow evidence captured",
                            timestamp_seconds=ts_ms / 1000.0,
                            keyframe_url=None,
                            provenance="Video / Keyframe Evidence",
                            evidence_kind="direct_workflow",
                            skill_support_level="partial",
                            trace_action="view_keyframe",
                            action_available=False,
                            recruiter_safe=True,
                        ))
                elif kf_count > 0:
                    entry.keyframe_evidence.append(f"Video frames captured ({kf_count})")
                    entry.evidence_objects.append(EvidenceObject(
                        evidence_type="recording_keyframe",
                        source_name="Recording",
                        confidence="medium",
                        short_summary=f"Keyframe evidence captured — screenshot preview coming soon",
                        provenance="Video / Keyframe Evidence",
                        evidence_kind="direct_workflow",
                        skill_support_level="partial",
                        trace_action="view_keyframe",
                        action_available=False,
                        recruiter_safe=True,
                    ))
                else:
                    entry.keyframe_evidence.append(
                        "Keyframe evidence captured — screenshot preview coming soon"
                    )

            # OCR evidence objects
            if "OCR" in entry.sources:
                ocr_summary = (wf or {}).get("frame_ocr_evidence_summary") or {}
                if isinstance(ocr_summary, dict):
                    for i_sig, sig in enumerate(ocr_summary.get("skill_signals") or []):
                        if isinstance(sig, dict) and sig.get("skill", "").lower() == entry.skill.lower():
                            snippet = str(sig.get("reasoning", ""))[:120]
                            keywords = [str(t) for t in (sig.get("ocr_terms_found") or [])[:6]]
                            ts_ms = kf_timestamps[i_sig] if i_sig < len(kf_timestamps) else None
                            ts_sec = ts_ms / 1000.0 if ts_ms is not None else None
                            ts_label = f" at {ts_sec:.1f}s" if ts_sec is not None else ""
                            entry.evidence_objects.append(EvidenceObject(
                                evidence_type="ocr_text",
                                source_name="OCR",
                                confidence="medium",
                                short_summary=snippet or f"OCR text analysis detected relevant terms{ts_label}",
                                text_snippet=snippet or None,
                                timestamp_seconds=ts_sec,
                                matched_keywords=keywords,
                                provenance="OCR Evidence",
                                evidence_kind="direct_workflow",
                                skill_support_level="partial",
                                trace_action="view_ocr",
                                action_available=False,
                                recruiter_safe=True,
                            ))

            # For visual/graphics skills where OCR ran but found no text:
            # add a clear explanation rather than showing no evidence at all.
            # OCR is structurally unable to read canvas/WebGL-rendered content.
            elif _is_visual_graphics_skill(entry.skill) and wf:
                _ocr_ran = (wf or {}).get("visual_analysis_status") == "analyzed"
                _ocr_had_signals = bool(
                    isinstance((wf or {}).get("frame_ocr_evidence_summary"), dict)
                    and (wf or {}).get("frame_ocr_evidence_summary", {}).get("skill_signals")
                )
                if _ocr_ran or _ocr_had_signals:
                    entry.evidence_objects.append(EvidenceObject(
                        evidence_type="ocr_text",
                        source_name="OCR",
                        confidence="low",
                        short_summary=(
                            "OCR text was limited because this page uses canvas/WebGL/graphics "
                            "rendering. Visual reasoning and GitHub code evidence are stronger "
                            "for this skill."
                        ),
                        provenance="OCR Evidence",
                        evidence_kind="contextual_page",
                        skill_support_level="none",
                        trace_action="view_ocr",
                        action_available=False,
                        recruiter_safe=True,
                    ))

            # Qwen evidence objects — include evidence_kind classification
            if "Qwen" in entry.sources and vrs_for_obj.get("status") == "analyzed":
                # Derive evidence_kind from Qwen observations if available
                observations = vrs_for_obj.get("observations") or []
                ev_kind = "contextual_page"
                skill_support = "weak"
                qwen_summary = (
                    vrs_for_obj.get("summary", "")[:140]
                    or "Qwen visual frame analysis detected skill-related content"
                )
                # Check per-frame skill_evidence for direct evidence of this skill
                for obs in observations:
                    if not isinstance(obs, dict):
                        continue
                    stage = str(obs.get("detected_workflow_stage", ""))
                    skill_ev = obs.get("skill_evidence") or {}
                    ev_for_skill = skill_ev.get(entry.skill) or {}
                    verdict = str(ev_for_skill.get("verdict", ""))
                    if verdict == "supported":
                        ev_kind = "direct_workflow"
                        skill_support = "strong"
                        break
                    if verdict == "partial":
                        ev_kind = "direct_workflow"
                        skill_support = "partial"
                    if stage in ("model_training", "results_display", "prediction_output",
                                  "data_input", "processing") and ev_kind != "direct_workflow":
                        ev_kind = "direct_workflow"
                        skill_support = "partial"
                # For visual/graphics skills, Qwen observing rendered output is
                # direct evidence — the skill manifests as rendered content, not text.
                if _is_visual_graphics_skill(entry.skill) and ev_kind != "direct_workflow":
                    _skill_toks = _skill_match_tokens(entry.skill)
                    _qsum_lower = qwen_summary.lower()
                    _vis_indicator_hits = sum(
                        1 for kw in _QWEN_VISUAL_RENDER_INDICATORS if kw in _qsum_lower
                    )
                    _tok_hit = any(tok in _qsum_lower for tok in _skill_toks)
                    if _vis_indicator_hits >= 2 or _tok_hit:
                        ev_kind = "direct_workflow"
                        skill_support = "partial"
                entry.evidence_objects.append(EvidenceObject(
                    evidence_type="qwen_visual",
                    source_name="Qwen",
                    confidence="medium",
                    short_summary=qwen_summary,
                    provenance="Advanced Visual Reasoning",
                    evidence_kind=ev_kind,
                    skill_support_level=skill_support,
                    trace_action="view_qwen",
                    action_available=False,
                    recruiter_safe=True,
                ))

            # GitHub proof references + evidence objects
            if "GitHub" in entry.sources and gh and gh.get("status") == "success":
                is_direct_match = entry.skill.lower() in gh_matched

                # Filter deep code evidence to this skill, excluding generic meta files
                # (README.md etc. mentions are not line-level code proof)
                skill_ev_for_entry = sorted(
                    [
                        ev for ev in gh_skill_code_evidence
                        if _github_code_evidence_matches_skill(ev, entry.skill)
                        and str(ev.get("file_path") or "") not in _GENERIC_META_PATHS
                    ],
                    key=lambda ev: _github_code_evidence_sort_key(ev, entry.skill),
                )

                # Source-only evidence_files: exclude README.md/package.json/etc.
                # so the fallback never shows a README "Open GitHub file" button.
                source_evidence_files = [
                    fp for fp in gh_evidence_files
                    if fp not in _GENERIC_META_PATHS
                ]

                if skill_ev_for_entry:
                    # Prefer deep line-level code evidence over shallow evidence_files
                    for ev in skill_ev_for_entry[:3]:
                        fp = str(ev.get("file_path") or "")
                        ls: int | None = ev.get("line_start")
                        le: int | None = ev.get("line_end")
                        snippet = str(ev.get("code_snippet") or "")[:150]
                        reason = str(ev.get("reason") or f"Code evidence for {entry.skill}")
                        # Use the pre-built exact blob URL (includes #L anchor)
                        gh_blob_url: str | None = ev.get("github_url") or (
                            _build_github_blob_url(gh_repo_url, fp, ls, le) if fp and gh_repo_url else None
                        )
                        entry.evidence_objects.append(EvidenceObject(
                            evidence_type="github_file",
                            source_name="GitHub",
                            confidence="high",
                            short_summary=reason[:120],
                            file_path=fp or None,
                            repo_name=str(ev.get("repo_name") or "") or gh_repo_name,
                            line_start=ls,
                            line_end=le,
                            github_url=gh_blob_url,
                            code_snippet=snippet or None,
                            provenance="GitHub Code Evidence",
                            evidence_kind="direct_workflow",
                            skill_support_level="strong",
                            trace_action="open_github",
                            action_available=bool(gh_blob_url),
                            route_url=gh_repo_url or None,
                            recruiter_safe=True,
                        ))
                elif is_direct_match and source_evidence_files:
                    entry.github_evidence.append("Repository source files analyzed for evidence")
                    # Fallback: real source files only (no line numbers)
                    for fp in source_evidence_files[:3]:
                        gh_blob_url = _build_github_blob_url(gh_repo_url, fp) if gh_repo_url and fp else None
                        entry.evidence_objects.append(EvidenceObject(
                            evidence_type="github_file",
                            source_name="GitHub",
                            confidence="high",
                            short_summary=f"GitHub file: {fp}",
                            file_path=fp,
                            repo_name=gh_repo_name,
                            line_start=None,
                            line_end=None,
                            github_url=gh_blob_url,
                            provenance="GitHub Evidence",
                            evidence_kind="direct_workflow",
                            skill_support_level="strong",
                            trace_action="open_github",
                            action_available=bool(gh_blob_url),
                            route_url=gh_repo_url or None,
                            recruiter_safe=True,
                        ))
                elif is_direct_match:
                    entry.github_evidence.append("Skill directly matched in GitHub repository analysis")
                    # Skill directly matched but no specific evidence files — repo-level only.
                    # Label: "Open GitHub repo" (file_path=None → frontend shows repo label).
                    entry.evidence_objects.append(EvidenceObject(
                        evidence_type="github_file",
                        source_name="GitHub",
                        confidence="high",
                        short_summary="Skill matched in GitHub repository — repository-level evidence",
                        repo_name=gh_repo_name,
                        github_url=gh_repo_url or None,
                        provenance="GitHub Evidence",
                        evidence_kind="direct_workflow",
                        skill_support_level="strong",
                        trace_action="open_github",
                        action_available=bool(gh_repo_url),
                        route_url=gh_repo_url or None,
                        recruiter_safe=True,
                    ))
                elif gh_stack:
                    entry.github_evidence.append(
                        f"Tech stack detected: {', '.join(gh_stack[:5])}"
                    )
                    # Skill inferred from tech stack (not directly matched).
                    # When evidence files are available, link to the first file (file-level).
                    # When no files, fall back to repo-level link.
                    stack_fallback_files = source_evidence_files or [
                        fp for fp in gh_evidence_files
                        if fp.lower() not in ("readme.md", "readme.rst")
                    ]
                    if stack_fallback_files and gh_repo_url:
                        fp = stack_fallback_files[0]
                        gh_blob_url = _build_github_blob_url(gh_repo_url, fp)
                        entry.evidence_objects.append(EvidenceObject(
                            evidence_type="github_file",
                            source_name="GitHub",
                            confidence="medium",
                            short_summary=(
                                f"Inferred from GitHub tech stack ({', '.join(gh_stack[:3])}) "
                                f"— {fp}"
                            ),
                            file_path=fp,
                            repo_name=gh_repo_name,
                            line_start=None,
                            line_end=None,
                            github_url=gh_blob_url or gh_repo_url or None,
                            provenance="GitHub Evidence",
                            evidence_kind="contextual_page",
                            skill_support_level="partial",
                            trace_action="open_github",
                            action_available=bool(gh_blob_url or gh_repo_url),
                            route_url=gh_repo_url or None,
                            recruiter_safe=True,
                        ))
                    else:
                        # No evidence files — repo-level only.
                        entry.evidence_objects.append(EvidenceObject(
                            evidence_type="github_file",
                            source_name="GitHub",
                            confidence="medium",
                            short_summary=f"Inferred from GitHub tech stack: {', '.join(gh_stack[:3])}",
                            repo_name=gh_repo_name,
                            github_url=gh_repo_url or None,
                            provenance="GitHub Evidence",
                            evidence_kind="contextual_page",
                            skill_support_level="partial",
                            trace_action="open_github",
                            action_available=bool(gh_repo_url),
                            route_url=gh_repo_url or None,
                            recruiter_safe=True,
                        ))

        # ── Project Defense transcript quote evidence ──────────────────────────
        if pd:
            pd_text = str(pd.get("transcript_text") or "")
            pd_segments: list[dict[str, Any]] = []
            raw_segs = pd.get("transcript_segments")
            if isinstance(raw_segs, list):
                pd_segments = raw_segs

            if pd_text:
                for entry in entries.values():
                    quotes = _find_transcript_quotes(entry.skill, pd_text, pd_segments)
                    for q in quotes:
                        if "transcript" not in entry.sources:
                            entry.sources.append("transcript")
                            entry.source_labels = _sources_to_labels(entry.sources)
                            if entry.confidence == "low":
                                entry.evidence_support = "Partially supported by transcript"
                                entry.confidence = "medium"

                        has_ts = q.get("has_timestamp", False)
                        start = float(q.get("start_time") or 0.0)
                        end = float(q.get("end_time") or 0.0)
                        ts_range = (
                            f"{_fmt_ts(start)}–{_fmt_ts(end)}"
                            if has_ts and end > start
                            else None
                        )
                        short = (
                            f"Project Defense ({ts_range}): \"{q['text'][:80]}\""
                            if ts_range
                            else f"Project Defense transcript: \"{q['text'][:80]}\""
                        )
                        entry.evidence_objects.append(EvidenceObject(
                            evidence_type="transcript_quote",
                            source_name="Project Defense",
                            confidence="medium",
                            short_summary=short,
                            text_snippet=q["text"][:200],
                            timestamp_seconds=start if has_ts else None,
                            line_range=ts_range,
                            provenance="Project Defense Transcript",
                            evidence_kind="direct_workflow",
                            skill_support_level="partial",
                            trace_action="view_transcript",
                            action_available=False,
                            recruiter_safe=True,
                        ))

        # ── Optional document/profile/certificate snippet evidence ───────────
        for entry in entries.values():
            for opt in optional_rows or []:
                src_type = str(opt.get("source_type") or "")
                for raw_obj in opt.get("evidence_objects") or []:
                    if not isinstance(raw_obj, dict):
                        continue
                    if str(raw_obj.get("skill_name") or "").lower() != entry.skill.lower():
                        continue
                    conf_raw = str(raw_obj.get("confidence") or "medium")
                    confidence: Literal["high", "medium", "low"] = (
                        "high" if conf_raw == "high" else "low" if conf_raw == "low" else "medium"
                    )
                    snippet = str(raw_obj.get("snippet") or "")
                    ev_type = str(raw_obj.get("evidence_type") or "document_snippet")
                    provenance = {
                        "document": "Documents/PDF",
                        "linkedin_profile": "LinkedIn/Profile",
                        "certificate_transcript": "Certificates/Transcript",
                    }.get(src_type, "Documents/PDF")
                    source_name = {
                        "document": "Document",
                        "linkedin_profile": "LinkedIn/Profile",
                        "certificate_transcript": "Certificate/Transcript",
                    }.get(src_type, "Document")
                    support_level = "partial" if src_type == "certificate_transcript" else (
                        "strong" if confidence == "high" else "partial" if confidence == "medium" else "weak"
                    )
                    entry.evidence_objects.append(EvidenceObject(
                        evidence_type=ev_type,
                        source_name=source_name,
                        confidence=confidence,
                        short_summary=str(raw_obj.get("reason") or snippet or "Optional evidence snippet")[:160],
                        text_snippet=snippet[:280] or None,
                        source_type=src_type,
                        page_number=raw_obj.get("page_number"),
                        profile_url=raw_obj.get("profile_url"),
                        section_label=raw_obj.get("section_label"),
                        issuer=raw_obj.get("issuer"),
                        title=raw_obj.get("title"),
                        date=raw_obj.get("date"),
                        file_path=raw_obj.get("file_path"),
                        provenance=provenance,
                        evidence_kind="contextual_page" if src_type == "certificate_transcript" else "direct_workflow",
                        skill_support_level=support_level,
                        trace_action="view_document",
                        action_available=False,
                        recruiter_safe=True,
                    ))

        return entries

    def _build_grouped_skill_evidence(
        self,
        all_skill_entries: dict[str, DetectedSkillEntry],
    ) -> list[GroupedSkillEvidence]:
        """Group detected skills by category for the grouped skill evidence UI."""
        if not all_skill_entries:
            return []

        # Only include skills with at least medium confidence OR claimed skills
        visible = [
            e for e in all_skill_entries.values()
            if e.confidence in ("high", "medium") or not e.is_inferred
        ]

        # Group by category
        by_category: dict[str, list[DetectedSkillEntry]] = {}
        for entry in visible:
            by_category.setdefault(entry.category, []).append(entry)

        groups: list[GroupedSkillEvidence] = []
        for category, skills in by_category.items():
            # Sort within group: high confidence first, then claimed
            skills.sort(key=lambda e: (
                0 if e.confidence == "high" else 1 if e.confidence == "medium" else 2,
                1 if e.is_inferred else 0,
                e.skill,
            ))

            # Group confidence: computed from evidence strength, not just skill confidence.
            # strong GitHub code file + direct recording output → high
            # only OCR homepage words or inferred stack → medium
            # only live website check / claimed with no evidence → low
            all_ev_objs = [obj for sk in skills for obj in sk.evidence_objects]
            has_strong_github = any(
                obj.evidence_type == "github_file" and obj.skill_support_level == "strong"
                for obj in all_ev_objs
            )
            has_direct_workflow = any(
                obj.evidence_kind == "direct_workflow" and obj.skill_support_level in ("strong", "partial")
                for obj in all_ev_objs
            )
            has_contextual_only = all_ev_objs and all(
                obj.evidence_kind in ("contextual_page", "deployment_only", "")
                for obj in all_ev_objs
            )

            if has_strong_github and has_direct_workflow:
                best_conf: Literal["high", "medium", "low"] = "high"
            elif has_strong_github or has_direct_workflow:
                best_conf = "medium"
            elif has_contextual_only:
                best_conf = "low"
            else:
                # Fall back to best skill confidence
                best_conf = "low"
                for sk in skills:
                    if sk.confidence == "high":
                        best_conf = "high"
                        break
                    if sk.confidence == "medium":
                        best_conf = "medium"

            # Aggregate source labels across all skills in group
            all_source_labels: list[str] = []
            seen_labels: set[str] = set()
            for sk in skills:
                for lbl in sk.source_labels:
                    if lbl not in seen_labels:
                        seen_labels.add(lbl)
                        all_source_labels.append(lbl)

            # Total evidence objects across group
            total_evidence = sum(sk.evidence_count for sk in skills)

            # Group name: use the first (highest confidence) skill name as label,
            # or build a readable name from the category
            _CATEGORY_DISPLAY: dict[str, str] = {
                "DATA":          "Data & Visualization",
                "FRONTEND":      "JavaScript / Frontend",
                "AI/ML":         "AI / Machine Learning",
                "DOCUMENTATION": "Technical Documentation",
                "OPEN_SOURCE":   "GitHub / Open Source",
                "BACKEND":       "Backend / API Development",
                "DEVOPS":        "DevOps / Deployment",
                "PRODUCT":       "Product Demo / Workflow",
                "OTHER":         "General Skills",
            }
            group_name = _CATEGORY_DISPLAY.get(category, category)

            groups.append(GroupedSkillEvidence(
                group_name=group_name,
                category=category,
                confidence=best_conf,
                evidence_count=total_evidence,
                sources_count=len(all_source_labels),
                source_labels=all_source_labels,
                skills=skills,
            ))

        # Sort groups: high confidence first, then by evidence count desc
        groups.sort(key=lambda g: (
            0 if g.confidence == "high" else 1 if g.confidence == "medium" else 2,
            -g.evidence_count,
        ))
        return groups

    def _infer_skill_profile(
        self,
        claimed_skills: list[str],
        all_skill_entries: dict[str, DetectedSkillEntry],
    ) -> DetectedCapability | None:
        """Map observed skills to a high-level role capability."""
        if not all_skill_entries:
            return None

        all_names_lower = list(all_skill_entries.keys())

        best_role: str | None = None
        best_primary_count = 0
        best_secondary_count = 0

        for role_title, primary_kws, secondary_kws, _ in _ROLE_PROFILES:
            pri = sum(
                1 for kw in primary_kws
                if any(kw in name for name in all_names_lower)
            )
            sec = sum(
                1 for kw in secondary_kws
                if any(kw in name for name in all_names_lower)
            )
            if (pri > best_primary_count or
                    (pri == best_primary_count and sec > best_secondary_count)):
                best_primary_count = pri
                best_secondary_count = sec
                best_role = role_title

        if best_role is None or best_primary_count == 0:
            return None

        # Confidence
        if best_primary_count >= 3:
            confidence: Literal["high", "medium", "low"] = "high"
        elif best_primary_count >= 1:
            confidence = "medium"
        else:
            confidence = "low"

        # Build "why detected" reasons
        why: list[str] = []
        high_skills = [e for e in all_skill_entries.values() if e.confidence == "high"]
        medium_skills = [e for e in all_skill_entries.values() if e.confidence == "medium"]

        if any("workflow" in e.sources for e in high_skills):
            why.append("Student demonstrated a relevant workflow in the browser recording.")
        if any("Qwen" in e.sources for e in (high_skills + medium_skills)):
            why.append("Visual frame analysis detected skill-related content on screen.")
        if any("OCR" in e.sources for e in (high_skills + medium_skills)):
            why.append("OCR analysis found relevant technical terminology in screen text.")
        if any("GitHub" in e.sources for e in (high_skills + medium_skills)):
            why.append("GitHub repository evidence supports code-level skill demonstration.")
        if any("document" in e.sources for e in (high_skills + medium_skills)):
            why.append("Submitted documents or reports provide traceable skill evidence.")
        if any("linkedin_profile" in e.sources for e in (high_skills + medium_skills)):
            why.append("Profile text provides additional professional context for skills.")
        if any("certificate_transcript" in e.sources for e in (high_skills + medium_skills)):
            why.append("Certificate or transcript evidence supports learning credentials.")
        if not why:
            why.append("Evidence suggests this capability based on observed workflow patterns.")

        # Supporting skills: include all with medium+ confidence
        supporting = [
            e for e in all_skill_entries.values()
            if e.confidence in ("high", "medium")
        ]
        # Sort: high confidence first, then claimed, then alpha
        supporting.sort(key=lambda e: (
            0 if e.confidence == "high" else 1,
            1 if e.is_inferred else 0,
            e.skill,
        ))

        return DetectedCapability(
            role_title=best_role,
            confidence=confidence,
            why_detected=why[:5],
            supporting_skills=supporting[:12],
        )

    # ── Next Best Action engine ───────────────────────────────────────────────

    def _next_best_actions(
        self,
        sources: list[EvidenceSourceResult],
        claimed_skills: list[str],
        github_url: str | None,
        final_score: int,
        detected_skills: dict[str, DetectedSkillEntry] | None = None,
    ) -> list[NextBestAction]:
        """Return up to 5 prioritised next best actions.

        Never always-records; recording is the last resort if no other action applies.
        """
        actions: list[NextBestAction] = []
        source_map = {s.key: s for s in sources}

        # ── GitHub gap ────────────────────────────────────────────────────────
        gh = source_map.get("github")
        code_skills = [s for s in claimed_skills
                       if any(kw in s.lower() for kw in ("javascript", "python", "code", "typescript",
                                                          "open source", "github", "programming",
                                                          "react", "vue", "angular", "node", "java",
                                                          "c++", "rust", "go", "swift"))]

        if gh and gh.status in ("not_run", "missing") and code_skills:
            if github_url:
                actions.append(NextBestAction(
                    action_type="run_github_analysis",
                    target_skill=code_skills[0],
                    reason=(
                        f"{code_skills[0]} evidence is weak because the repository "
                        "has not been analyzed yet."
                    ),
                    objective="Analyze the GitHub repository to extract code evidence for claimed skills.",
                    button_label="Run GitHub Evidence Analysis",
                    priority="high",
                    is_recording=False,
                ))
            else:
                actions.append(NextBestAction(
                    action_type="add_github_url",
                    target_skill=code_skills[0],
                    reason=(
                        f"{code_skills[0]} is claimed but no GitHub repository URL was provided."
                    ),
                    objective="Add a public GitHub repository URL to enable code evidence analysis.",
                    button_label="Add GitHub URL",
                    priority="high",
                    is_recording=False,
                ))

        # ── Live website gap ──────────────────────────────────────────────────
        lw = source_map.get("live_website_check")
        deploy_skills = [s for s in claimed_skills
                         if any(kw in s.lower() for kw in ("deploy", "hosting", "live", "production",
                                                            "web dev", "website", "web application",
                                                            "full stack", "fullstack", "saas"))]
        if lw and lw.status in ("not_run",) and (deploy_skills or len(actions) == 0):
            target = deploy_skills[0] if deploy_skills else (claimed_skills[0] if claimed_skills else "Website")
            actions.append(NextBestAction(
                action_type="run_live_website_check",
                target_skill=target,
                reason="Live website accessibility has not been verified.",
                objective="Confirm the site is publicly reachable and returns a valid HTTP response.",
                button_label="Run Live Website Check",
                priority="medium",
                is_recording=False,
            ))

        # ── Project defense / transcript gap ──────────────────────────────────
        pd = source_map.get("project_defense")
        if pd and pd.status == "not_run" and len(actions) < 5:
            defense_skills = [s for s in claimed_skills
                              if any(kw in s.lower() for kw in (
                                  "civil", "mechanical", "structural", "design",
                                  "cad", "simulation", "presentation", "defense",
                                  "explanation", "communication",
                              ))]
            target = defense_skills[0] if defense_skills else None
            if target:
                actions.append(NextBestAction(
                    action_type="record_presentation",
                    target_skill=target,
                    reason=f"{target} evidence is stronger with a project defense or verbal explanation.",
                    objective="Record a short verbal walkthrough of your project or skill demonstration.",
                    button_label="Add Project Defense",
                    priority="medium",
                    is_recording=True,
                    recommended_duration="2–5 minutes",
                ))

        # ── Document / PDF gap (project reports and technical write-ups) ──────
        def _document_supports(skill: str) -> bool:
            if not detected_skills:
                return False
            wanted = skill.lower().strip()
            for entry in detected_skills.values():
                name = entry.skill.lower().strip()
                if "document" not in entry.sources:
                    continue
                if name == wanted or name in wanted or wanted in name:
                    return True
            return False

        doc_skills = [s for s in claimed_skills
                      if any(kw in s.lower() for kw in (
                          "research", "report", "analysis", "academic", "thesis",
                          "documentation", "technical writing",
                      ))
                      and not _document_supports(s)]
        if doc_skills and len(actions) < 5:
            actions.append(NextBestAction(
                action_type="upload_document",
                target_skill=doc_skills[0],
                reason=f"{doc_skills[0]} is better supported by uploading a document or report.",
                objective="Upload a PDF report, project document, research paper, or technical write-up.",
                button_label="Upload Document",
                priority="medium",
                is_recording=False,
            ))

        # ── CAD / simulation gap ──────────────────────────────────────────────
        cad_skills = [s for s in claimed_skills
                      if any(kw in s.lower() for kw in (
                          "cad", "solidworks", "autocad", "fusion", "ansys",
                          "mechanical", "electrical", "circuit", "simulation",
                          "finite element", "matlab",
                      ))]
        if cad_skills and len(actions) < 5:
            actions.append(NextBestAction(
                action_type="record_cad_proof",
                target_skill=cad_skills[0],
                reason=f"{cad_skills[0]} evidence is much stronger with a CAD file or simulation walkthrough.",
                objective="Upload or screen-record a CAD model, simulation, or engineering design artifact.",
                button_label="Upload CAD / Simulation",
                priority="medium",
                is_recording=False,
            ))

        # ── Camera / physical proof gap ───────────────────────────────────────
        physical_skills = [s for s in claimed_skills
                           if any(kw in s.lower() for kw in (
                               "hardware", "electronics", "robotics", "physical",
                               "lab", "manufacturing", "3d print", "prototype",
                               "embedded", "iot", "sensor",
                           ))]
        if physical_skills and len(actions) < 5:
            actions.append(NextBestAction(
                action_type="record_camera_proof",
                target_skill=physical_skills[0],
                reason=f"{physical_skills[0]} needs physical evidence that a screen recording cannot provide.",
                objective="Record a short video showing the physical device, hardware, or real-world output.",
                button_label="Record Camera Proof",
                priority="medium",
                is_recording=True,
                recommended_duration="1–3 minutes",
            ))

        # ── Detected-skill-aware gap actions ─────────────────────────────────
        if detected_skills and len(actions) < 5:
            gh_src = source_map.get("github")
            # Inferred skills with low confidence where GitHub would help
            oss_detected = [
                e for e in detected_skills.values()
                if e.is_inferred and e.confidence == "low"
                and any(kw in e.skill.lower() for kw in (
                    "open source", "github", "javascript", "python", "code",
                    "typescript", "react", "programming",
                ))
            ]
            if oss_detected and gh_src and gh_src.status in ("not_run", "missing") and not github_url:
                actions.append(NextBestAction(
                    action_type="add_github_url",
                    target_skill=oss_detected[0].skill,
                    reason=(
                        f"{oss_detected[0].skill} was detected in evidence but needs "
                        "GitHub repository analysis for stronger support."
                    ),
                    objective="Add a public GitHub repository URL so VeriBridge can analyze your code.",
                    button_label="Add GitHub URL",
                    priority="medium",
                    is_recording=False,
                ))

            # Weak chart/visualization → focused recording
            viz_low = [
                e for e in detected_skills.values()
                if e.confidence == "low"
                and any(kw in e.skill.lower() for kw in ("chart", "visualization", "plot", "data viz"))
            ]
            if viz_low and len(actions) < 5:
                already = any(a.action_type == "record_followup_proof" for a in actions)
                if not already:
                    actions.append(NextBestAction(
                        action_type="record_followup_proof",
                        target_skill=viz_low[0].skill,
                        reason=(
                            f"{viz_low[0].skill} was detected but evidence is weak. "
                            "A focused recording would significantly strengthen this skill."
                        ),
                        objective=(
                            "Record a focused chart explanation showing axes, marks, trends, "
                            "and any interactive behavior or parameter change."
                        ),
                        button_label="Record Focused Chart Demo",
                        priority="medium",
                        is_recording=True,
                        recommended_duration="30–60 seconds",
                    ))

        # ── Visual / workflow gap → recording (last resort) ───────────────────
        wf = source_map.get("website_workflow")
        if wf and wf.status in ("missing", "partial") and len(actions) < 5:
            target_skill = claimed_skills[0] if claimed_skills else "workflow"
            skill_lower = target_skill.lower()
            if "chart" in skill_lower or "visualization" in skill_lower or "plot" in skill_lower:
                objective = "Open one chart, explain axes/marks/trend, and show a chart interaction or parameter change."
            elif "javascript" in skill_lower or "code" in skill_lower:
                objective = "Open one code example and explain how it works step by step."
            elif "interactive" in skill_lower or "documentation" in skill_lower:
                objective = "Open an interactive example, change a parameter, and explain what changed."
            else:
                objective = f"Record a focused demonstration of {target_skill} showing clear output."

            # Skip if a followup proof action was already added by detected-skill logic
            already = any(a.action_type == "record_followup_proof" for a in actions)
            if not already:
                actions.append(NextBestAction(
                    action_type="record_followup_proof",
                    target_skill=target_skill,
                    reason=f"{target_skill} visual evidence is weak or missing from the current recording.",
                    objective=objective,
                    button_label="Record Follow-up Proof",
                    priority="medium",
                    is_recording=True,
                    recommended_duration="30–60 seconds",
                ))

        # Deduplicate by action_type
        seen: set[str] = set()
        unique: list[NextBestAction] = []
        for a in actions:
            if a.action_type not in seen:
                seen.add(a.action_type)
                unique.append(a)

        return unique[:5]

    # ── Final recommendations ────────────────────────────────────────────────

    def _evidence_text(
        self,
        claimed_skills: list[str],
        detected_skills: dict[str, DetectedSkillEntry],
        wf: dict[str, Any] | None,
        gh: dict[str, Any] | None,
        pd: dict[str, Any] | None,
        optional_rows: list[dict[str, Any]],
    ) -> str:
        parts: list[str] = list(claimed_skills)
        parts.extend(e.skill for e in detected_skills.values())
        parts.extend(e.category or "" for e in detected_skills.values())
        if wf:
            parts.extend(str(x) for x in wf.get("supported_skills") or [])
            parts.extend(str(x) for x in wf.get("weakly_supported_skills") or [])
            parts.append(str(wf.get("recruiter_summary") or ""))
            parts.append(str(wf.get("student_summary") or ""))
            parts.append(str(wf.get("visual_reasoning_summary") or ""))
            parts.append(str(wf.get("frame_ocr_evidence_summary") or ""))
        if gh:
            parts.extend(str(x) for x in gh.get("detected_stack") or [])
            parts.extend(str(x) for x in gh.get("matched_claimed_skills") or [])
            parts.extend(str(x.get("skill") or "") for x in gh.get("skill_code_evidence") or [] if isinstance(x, dict))
        if pd:
            parts.append(str(pd.get("transcript_text") or ""))
            parts.append(str(pd.get("summary") or ""))
        for row in optional_rows:
            parts.append(str(row.get("source_type") or ""))
            parts.append(str(row.get("analysis_summary") or ""))
            parts.append(str(row.get("evidence_objects") or ""))
        return " ".join(parts).lower()

    def _project_type(self, evidence_text: str, grouped: list[GroupedSkillEvidence]) -> str:
        group_text = " ".join((g.category + " " + g.group_name) for g in grouped).lower()
        text = evidence_text + " " + group_text
        checks: list[tuple[str, tuple[str, ...]]] = [
            ("3d_graphics_webgl", ("three.js", "threejs", "webgl", "mesh", "geometry", "shader", "canvas 3d", "babylon")),
            ("data_visualization", ("d3", "chart", "visualization", "tooltip", "plot", "dashboard", "graph", "data viz")),
            ("nlp_llm_rag", ("llm", "rag", "retrieval", "embedding", "vector", "prompt", "langchain", "nlp", "chatbot")),
            ("ml_deep_learning", ("machine learning", "deep learning", "model", "neural", "classifier", "confusion matrix", "roc", "tensorflow", "pytorch", "sklearn")),
            ("devops_mlops", ("docker", "kubernetes", "ci/cd", "pipeline", "terraform", "monitoring", "deployment", "mlops")),
            ("backend_api", ("api", "backend", "fastapi", "express", "django", "flask", "database", "postgres", "auth")),
            ("frontend_fullstack", ("react", "next.js", "frontend", "full stack", "fullstack", "typescript", "javascript", "ui")),
        ]
        for project_type, keywords in checks:
            if any(k in text for k in keywords):
                return project_type
        return "frontend_fullstack"

    def _learning_templates(self, project_type: str, source_reason: str) -> list[RecommendationAction]:
        templates: dict[str, list[RecommendationAction]] = {
            "3d_graphics_webgl": [
                RecommendationAction("Add interactive geometry controls", "This proves the 3D output is parameter-driven, not just static rendering.", "Add a slider or segmented control that changes simplification ratio, material, or lighting in real time.", "UI state management, Three.js geometry processing, WebGL rendering", "Show the original mesh, adjust the control, then show the changed mesh.", "intermediate", "1–2 hr", "medium", source_reason, "learning_3d_controls"),
                RecommendationAction("Add performance metrics", "Graphics projects are stronger when optimization is measurable.", "Display vertex count, face count, FPS, and render time before and after a change.", "performance profiling, graphics optimization", "Show metrics changing as the mesh or scene complexity changes.", "intermediate", "1–2 hr", "medium", source_reason, "learning_3d_metrics"),
                RecommendationAction("Explain the rendering pipeline", "Recruiters trust visual proof more when the student can explain the source code path.", "Open the render loop, geometry update, or simplifier function and add a short defense explanation.", "technical communication, code reading, rendering pipeline understanding", "Record a short project defense explaining the key function and rendered output.", "beginner", "30 min", "low", source_reason, "learning_code_explanation"),
            ],
            "data_visualization": [
                RecommendationAction("Add interactive filters", "Filtering proves the visualization responds to user intent and data state.", "Add category, date, or range filters that update the chart without a page refresh.", "D3/data state joins, UI state management", "Show the baseline chart, change a filter, and explain how the marks update.", "intermediate", "1–2 hr", "medium", source_reason, "learning_chart_filters"),
                RecommendationAction("Add tooltip details", "Hover details make the chart easier to inspect and prove data-to-mark mapping.", "Add accessible tooltips with exact values, labels, and the selected datum.", "D3 events, data binding, interaction design", "Hover over several marks and show the tooltip values matching the chart.", "beginner", "30 min", "medium", source_reason, "learning_chart_tooltips"),
                RecommendationAction("Add a dynamic dataset switcher", "Changing datasets shows the visualization logic generalizes beyond one static example.", "Let users upload a CSV or switch between two bundled datasets.", "data parsing, schema validation, reusable chart rendering", "Switch datasets and show the chart redraw with updated axes and labels.", "advanced", "1 day", "low", source_reason, "learning_dataset_switcher"),
            ],
            "ml_deep_learning": [
                RecommendationAction("Add an evaluation dashboard", "Model projects need measurable quality, not just a working prediction.", "Show accuracy, precision, recall, F1, and validation loss for the trained model.", "model evaluation, metric interpretation", "Run a prediction and show the evaluation metrics used to judge the model.", "intermediate", "1–2 hr", "medium", source_reason, "learning_ml_metrics"),
                RecommendationAction("Add confusion matrix or ROC view", "Error analysis proves you understand where the model succeeds and fails.", "Render a confusion matrix for classification or ROC curve when class probabilities exist.", "diagnostic evaluation, visualization for ML", "Show the chart and explain one false positive or false negative pattern.", "intermediate", "1–2 hr", "medium", source_reason, "learning_ml_error_analysis"),
                RecommendationAction("Add inference monitoring", "Monitoring turns the model into a more production-ready project.", "Log inference latency, input count, prediction distribution, and failed requests.", "model monitoring, production ML operations", "Show live inference metrics changing after several test predictions.", "advanced", "1 day", "low", source_reason, "learning_ml_monitoring"),
            ],
            "nlp_llm_rag": [
                RecommendationAction("Add retrieval quality checks", "RAG projects need proof that answers are grounded in retrieved sources.", "Show retrieved chunks, similarity scores, and citations beside each answer.", "retrieval evaluation, grounding, citation design", "Ask a question and show the retrieved context used for the answer.", "intermediate", "1–2 hr", "medium", source_reason, "learning_rag_grounding"),
                RecommendationAction("Add prompt/version experiments", "Comparing prompts teaches systematic LLM evaluation instead of one-off demos.", "Save two prompt variants and compare answer quality on the same test questions.", "prompt evaluation, experiment tracking", "Show both prompt outputs and explain which version performs better.", "beginner", "1–2 hr", "low", source_reason, "learning_prompt_eval"),
                RecommendationAction("Add safety and fallback handling", "LLM apps are stronger when they handle uncertainty and bad inputs clearly.", "Add refusal/fallback behavior for missing context, irrelevant questions, or low retrieval confidence.", "LLM guardrails, UX for uncertain output", "Ask an out-of-scope question and show the fallback response.", "intermediate", "1–2 hr", "low", source_reason, "learning_llm_guardrails"),
            ],
            "backend_api": [
                RecommendationAction("Add API tests and examples", "Backend proof is stronger when behavior is verified outside the UI.", "Add endpoint tests plus a small request/response example collection.", "API testing, contract validation", "Run the tests and show one request returning the expected response.", "beginner", "1–2 hr", "medium", source_reason, "learning_api_tests"),
                RecommendationAction("Add auth and permission checks", "Real backend projects should prove protected actions cannot be misused.", "Add role-based checks or ownership checks around a sensitive endpoint.", "authentication, authorization, backend security", "Show allowed and denied requests for the same endpoint.", "intermediate", "1 day", "medium", source_reason, "learning_api_auth"),
                RecommendationAction("Add observability", "Logs and health checks make the API easier to operate and debug.", "Add structured logs, a health endpoint, and basic error tracking for key routes.", "operability, production debugging", "Trigger one successful and one failed request and show the logged result.", "intermediate", "1–2 hr", "low", source_reason, "learning_api_observability"),
            ],
            "frontend_fullstack": [
                RecommendationAction("Add polished empty and loading states", "Frontend projects feel more complete when async states are handled intentionally.", "Add loading, empty, and error states for the main workflow.", "frontend UX, async state management", "Show the page loading, an empty state, and a successful result.", "beginner", "1–2 hr", "medium", source_reason, "learning_frontend_states"),
                RecommendationAction("Add end-to-end workflow tests", "Tests prove the core user journey still works after changes.", "Add an E2E test for the main happy path and one error path.", "E2E testing, regression prevention", "Run the test and show the browser exercising the workflow.", "intermediate", "1 day", "medium", source_reason, "learning_e2e_tests"),
                RecommendationAction("Add accessibility improvements", "Accessible UI shows professional frontend judgment beyond visuals.", "Add semantic labels, keyboard navigation, focus states, and contrast fixes.", "accessibility, semantic HTML, UI quality", "Navigate the workflow by keyboard and show labels/focus states.", "intermediate", "1–2 hr", "low", source_reason, "learning_accessibility"),
            ],
            "devops_mlops": [
                RecommendationAction("Add a CI quality gate", "Automation proves the project can be safely changed and deployed.", "Run tests, linting, or build checks in CI before deployment.", "CI/CD, release discipline", "Show a passing CI run for a code change.", "intermediate", "1–2 hr", "medium", source_reason, "learning_ci_gate"),
                RecommendationAction("Add deployment rollback notes", "Deployment projects are stronger when failure recovery is planned.", "Document the deploy command, required env vars, health check, and rollback step.", "deployment operations, incident readiness", "Show the health check and the rollback instructions in the repo or docs.", "beginner", "30 min", "low", source_reason, "learning_deploy_runbook"),
                RecommendationAction("Add runtime monitoring", "Monitoring shows the deployed system can be operated after launch.", "Track uptime, latency, error rate, or model drift depending on the project.", "observability, production operations", "Show a dashboard or log output changing after test traffic.", "advanced", "1 day", "low", source_reason, "learning_runtime_monitoring"),
            ],
        }
        return templates.get(project_type, templates["frontend_fullstack"])

    def _build_recommendations(
        self,
        final_score: int,
        sources: list[EvidenceSourceResult],
        next_actions: list[NextBestAction],
        claimed_skills: list[str],
        detected_skills: dict[str, DetectedSkillEntry],
        grouped: list[GroupedSkillEvidence],
        wf: dict[str, Any] | None,
        gh: dict[str, Any] | None,
        pd: dict[str, Any] | None,
        optional_rows: list[dict[str, Any]],
    ) -> FinalRecommendations:
        source_map = {s.key: s for s in sources}
        evidence_text = self._evidence_text(claimed_skills, detected_skills, wf, gh, pd, optional_rows)
        project_type = self._project_type(evidence_text, grouped)

        def src_reason(key: str) -> str:
            s = source_map.get(key)
            if not s:
                return "Triggered by combined final evidence analysis."
            label = key.replace("_", " ")
            score_text = "not applicable" if s.score is None else f"{s.score}/100"
            return f"Triggered by {label} evidence: status={s.status}, score={score_text}. {s.notes}".strip()

        proof_actions: list[RecommendationAction] = []
        for a in next_actions:
            key = "website_workflow"
            if "github" in a.action_type:
                key = "github"
            elif "live_website" in a.action_type:
                key = "live_website_check"
            elif "document" in a.action_type:
                key = "uploaded_documents"
            elif "presentation" in a.action_type:
                key = "project_defense"
            evidence_to_record = "No recording required; run or upload the missing evidence source."
            if a.is_recording:
                evidence_to_record = a.objective
            proof_actions.append(RecommendationAction(
                title=a.button_label,
                reason=a.reason,
                action=a.objective,
                skill_learned=a.target_skill,
                evidence_to_record=evidence_to_record,
                difficulty="beginner",
                estimated_time="30 min",
                priority=a.priority,
                source_reason=src_reason(key),
                action_type=a.action_type,
            ))

        if final_score < 80 and project_type == "nlp_llm_rag" and len(proof_actions) < 4:
            wf_src = source_map.get("website_workflow")
            if wf_src and wf_src.status in ("missing", "partial"):
                proof_actions.append(RecommendationAction(
                    "Record prompt and response proof",
                    "Chatbot evidence is strongest when the target site shows a prompt being submitted and an assistant response returning.",
                    "Record a focused follow-up on the submitted chatbot URL: type one prompt, send it, show the generated response, then briefly explain the prompt-to-response flow.",
                    "Natural Language Processing, Large Language Models, Chatbot UI",
                    "Show the target chatbot page, entered prompt, assistant response, and message history. Avoid unrelated tabs.",
                    "beginner",
                    "30 min",
                    "high",
                    src_reason("website_workflow"),
                    "record_followup_proof",
                ))

        if final_score < 80 and len(proof_actions) < 4:
            wf_src = source_map.get("website_workflow")
            if wf_src and wf_src.status in ("missing", "partial"):
                proof_actions.append(RecommendationAction(
                    "Record focused target-site proof",
                    "Workflow evidence is weak for the submitted website.",
                    "Record a focused follow-up proof on the target website only, showing the exact demo page and one clear interaction or output change.",
                    "targeted workflow demonstration",
                    "Show only the submitted website, interact with the feature, and avoid unrelated tabs.",
                    "beginner",
                    "30 min",
                    "high",
                    src_reason("website_workflow"),
                    "record_followup_proof",
                ))

        if final_score < 80 and len(proof_actions) < 4:
            pd_src = source_map.get("project_defense")
            if pd_src and pd_src.status in ("not_run", "missing", "partial"):
                proof_actions.append(RecommendationAction(
                    "Add a project defense explanation",
                    "Ownership and explanation evidence is weak or missing.",
                    "Record a short walkthrough explaining what you built, the key technical choices, and one hard problem you solved.",
                    "technical communication, project ownership",
                    "Record a 2–5 minute defense tied to the same project.",
                    "beginner",
                    "30 min",
                    "medium",
                    src_reason("project_defense"),
                    "record_presentation",
                ))

        if final_score < 80 and not proof_actions:
            weakest = min(
                (s for s in sources if s.key not in _OPTIONAL_BOOSTER_KEYS),
                key=lambda s: s.score if s.score is not None else 100,
                default=None,
            )
            proof_actions.append(RecommendationAction(
                "Strengthen weakest proof source",
                "Final score is below 80, so a proof-strengthening action is needed before optional learning goals.",
                "Review the lowest-scoring source in the Final Evidence Score card and add focused proof for that source.",
                "evidence quality improvement",
                "Record or add evidence that directly addresses the weakest source.",
                "beginner",
                "30 min",
                "high",
                src_reason(weakest.key) if weakest else "Triggered by final score below 80.",
                "record_followup_proof",
            ))

        project_label = project_type.replace("_", "/")
        learning = self._learning_templates(
            project_type,
            f"Triggered by detected project type: {project_label}; evidence came from analyzed skills and available source text.",
        )

        if final_score < 80 and project_type == "nlp_llm_rag":
            chatbot_actions = [a for a in proof_actions if a.title == "Record prompt and response proof"]
            if chatbot_actions:
                proof_actions = [
                    a for a in proof_actions
                    if a.action_type != "record_followup_proof" or a.title == "Record prompt and response proof"
                ]

        seen: set[str] = set()
        unique_proof: list[RecommendationAction] = []
        for action in proof_actions:
            if action.action_type in seen:
                continue
            seen.add(action.action_type)
            unique_proof.append(action)

        if final_score < 80:
            return FinalRecommendations("proof_repair", unique_proof[:4], learning[:2])
        return FinalRecommendations("project_growth", [], learning[:5])

    # ── Summaries ─────────────────────────────────────────────────────────────

    def _build_summaries(
        self,
        final_score: int,
        claimed_skills: list[str],
        sources: list[EvidenceSourceResult],
        per_skill: dict[str, int],
        actions: list[NextBestAction],
    ) -> tuple[str, str]:
        skill_str = ", ".join(claimed_skills[:4]) if claimed_skills else "claimed skills"
        source_count = sum(1 for s in sources if s.status not in ("not_run", "not_available"))
        has_unrelated_evidence = any(s.notes and "unrelated" in s.notes.lower() for s in sources)
        has_unrelated_transcript = any(
            s.key == "project_defense" and s.notes and "unrelated" in s.notes.lower()
            for s in sources
        )
        mismatch_warning = ""
        if has_unrelated_transcript:
            mismatch_warning = " Warning: transcript appears unrelated to the submitted proof and was not used as a booster."
        elif has_unrelated_evidence:
            mismatch_warning = " Warning: unrelated evidence was detected and was not used as a booster."

        if final_score >= 80:
            recruiter = (
                f"Strong proof with a combined evidence score of {final_score}/100 across "
                f"{source_count} evidence source(s). Skills covered: {skill_str}. "
                "Evidence is consistent across workflow recording and supplementary sources."
            ) + mismatch_warning
            student = (
                f"Your proof scores {final_score}/100. This is strong evidence — good job. "
                "Optional: run GitHub analysis or live website check to add further depth."
            )
        elif final_score >= 60:
            top_action = actions[0].reason if actions else "Strengthen the weakest specific proof source."
            recruiter = (
                f"Moderate proof with a combined score of {final_score}/100. "
                f"Skills partially covered: {skill_str}. "
                f"Additional evidence recommended: {top_action}"
            ) + mismatch_warning
            student = (
                f"Your proof scores {final_score}/100. It is partially strong but has gaps. "
                f"Recommended: {top_action}"
            )
        else:
            top_action = actions[0].reason if actions else "Record a clearer demonstration."
            recruiter = (
                f"Weak proof with a combined score of {final_score}/100. "
                f"Skills: {skill_str}. Evidence sources run: {source_count}. "
                f"Significant gaps: {top_action}"
            ) + mismatch_warning
            student = (
                f"Your proof scores {final_score}/100. Evidence is insufficient. "
                f"Most important next step: {top_action}"
            )

        return recruiter, student

    # ── Main entry point ──────────────────────────────────────────────────────

    def evaluate(
        self,
        user_id: str,
        session_id: str,
        claimed_skills: list[str] | None = None,
        github_url: str | None = None,
    ) -> FinalEvaluationResult:
        """Run the full final evaluation and return structured results."""
        skills = claimed_skills or []

        wf = self._enrich_workflow_for_final(
            self._load_workflow_analysis(user_id, session_id),
            user_id,
            session_id,
        )
        gh = self._load_github_analysis(user_id, session_id)
        lw = self._load_live_website_check(user_id, session_id)
        pd = self._load_project_defense(user_id, session_id)
        opt = self._load_optional_evidence(user_id, session_id)
        project_opt = [row for row in opt if row.get("source_type") == "document"]
        project_context = extract_project_context(skills, wf, gh)
        relevant_project_opt = self._filter_relevant_optional_rows(project_opt, skills, wf, gh, project_context)
        kf_count = self._count_video_keyframes(user_id, session_id)

        sources: list[EvidenceSourceResult] = [
            self._score_workflow(wf, project_context),
            self._score_dom(wf, project_context),
            self._score_video_keyframes(kf_count),
            self._score_ocr(wf, project_context),
            self._score_qwen(wf, user_id=user_id, session_id=session_id, context=project_context),
            self._score_github(gh),
            self._score_live_website_for_workflow(lw, wf),
            self._score_project_defense(pd, skills, wf, gh, project_context),
            self._score_optional(project_opt, "document", "uploaded_documents", skills, wf, gh, project_context),
        ]

        final_score = self._combine_scores(sources)

        sources_used:    list[EvidenceSourceKey] = [s.key for s in sources if s.status not in ("not_run", "not_available", "not_applicable")]
        sources_missing: list[EvidenceSourceKey] = [s.key for s in sources if s.status in ("not_run", "missing")]

        confidence = self._confidence_label(final_score, sources_used)
        per_skill = self._per_skill_scores(skills, wf, gh, relevant_project_opt)

        # Detected skill profile (inferred from all evidence, including beyond claimed)
        relevant_pd = pd
        if pd:
            pd_rel = validate_evidence_relevance(project_context, "project defense transcript", _project_defense_text(pd))
            if pd_rel.mismatch_detected:
                relevant_pd = None
        all_skill_entries = self._collect_all_evidence_skills(skills, wf, gh, relevant_pd, relevant_project_opt)
        detected_capability = self._infer_skill_profile(skills, all_skill_entries)
        detected_additional = [
            e for e in all_skill_entries.values() if e.is_inferred
        ]
        grouped_skill_evidence = self._build_grouped_skill_evidence(all_skill_entries)

        actions = self._next_best_actions(
            sources, skills, github_url, final_score,
            detected_skills=all_skill_entries,
        )
        recommendations = self._build_recommendations(
            final_score, sources, actions, skills, all_skill_entries,
            grouped_skill_evidence, wf, gh, relevant_pd, relevant_project_opt,
        )

        recruiter_summary, student_summary = self._build_summaries(
            final_score, skills, sources, per_skill, actions
        )

        return FinalEvaluationResult(
            proof_session_id=session_id,
            final_score=final_score,
            confidence=confidence,
            evidence_sources_used=sources_used,
            evidence_sources_missing=sources_missing,
            per_skill_scores=per_skill,
            evidence_source_breakdown=[
                {
                    "key": s.key,
                    "status": s.status,
                    "score": s.score,
                    "weight": s.weight,
                    "notes": s.notes,
                }
                for s in sources
            ],
            final_recruiter_summary=recruiter_summary,
            final_student_summary=student_summary,
            next_best_actions=[a.to_dict() for a in actions],
            recommendations=recommendations,
            strong_proof=final_score >= 80,
            detected_capability=detected_capability,
            detected_additional_skills=detected_additional,
            grouped_skill_evidence=grouped_skill_evidence,
        )
