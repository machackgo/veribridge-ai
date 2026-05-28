"""
Transcript Correction Service — ASR spelling and term correction for project defense transcripts.

Raw speech-to-text transcripts from Whisper or OpenAI Whisper commonly mis-hear:
  - Student names        ("muhammoh" → "Mohammed", "Mahamakobashiruddin Faras" → "Mohammed Mubashir Uddin Faraz")
  - Technical terms      ("First API" → "FastAPI", "Golmaps API" → "Google Maps API")
  - Product names        ("very brief" → "VeriBridge", "stimulates" → "Streamlit")
  - Project-specific names ("Boschach Mut" → "Boston Smart")

This service CORRECTS those errors — it does NOT rewrite, polish, summarize, or paraphrase.

Design principles
-----------------
- NEVER overwrite the raw transcript — always preserve it unchanged.
- NEVER rewrite sentences, change sentence order, or alter the student's speaking style.
- NEVER replace words with "similar meaning" alternatives — only fix clear term/spelling errors.
- NEVER invent achievements, skills, or project names not supported by context.
- NEVER expose private URLs, tokens, or credentials in the result.
- Only replace words or short phrases when they clearly match known names, product names,
  project names, or technical glossary terms.
- correction_summary lists every substitution made (for audit/transparency), including
  unapplied low-confidence suggestions.
- transcript_needs_review is set True when confidence < 0.7, corrections > 10, or any
  low-confidence suggestion was NOT applied.
- When the Anthropic API is not configured, falls back to a pure rules-based engine.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# General tech glossary: common terms that ASR often mangles.
# Each entry: (pattern_to_match, canonical_form)
# Pattern is matched case-insensitively; replacement preserves case of canonical_form.
_BASE_TECH_GLOSSARY: list[tuple[str, str]] = [
    # Frameworks / runtimes
    (r"\bfirst\s*api\b",              "FastAPI"),
    (r"\bfast\s*api\b",               "FastAPI"),
    (r"\bfastapi\b",                  "FastAPI"),
    (r"\breact\s*js\b",               "React"),
    (r"\bnext\s*js\b",                "Next.js"),
    (r"\bnode\s*js\b",                "Node.js"),
    (r"\bvue\s*js\b",                 "Vue.js"),
    (r"\bflask\b",                    "Flask"),
    (r"\bdjango\b",                   "Django"),
    (r"\bspring\s*boot\b",            "Spring Boot"),
    (r"\bexpress\s*js\b",             "Express.js"),
    # Data / ML tools
    (r"\bstimulate[sd]?\b",           "Streamlit"),   # ASR mis-hear of "Streamlit"
    (r"\bstream\s*lit\b",             "Streamlit"),
    (r"\bstreamlit\b",                "Streamlit"),
    # Platform / product names
    (r"\bvery\s*br(?:ief|idge|dge)\b", "VeriBridge"),  # ASR mis-hear of "VeriBridge"
    (r"\bveri\s*bridge\b",            "VeriBridge"),
    (r"\bveribridge\b",               "VeriBridge"),
    # Cloud / APIs
    (r"\bgolmaps?\s*api\b",           "Google Maps API"),
    (r"\bgoogle\s*map[s]?\s*api\b",   "Google Maps API"),
    (r"\bgoogle\s*cloud\s*run\b",     "Google Cloud Run"),
    (r"\bgoogle\s*cloud\b",           "Google Cloud"),
    (r"\baws\s*lambda\b",             "AWS Lambda"),
    (r"\bfirebase\b",                 "Firebase"),
    (r"\bsupa\s*base\b",              "Supabase"),
    (r"\bvercel\b",                   "Vercel"),
    # Databases
    (r"\bpost\s*gres(?:ql|sql)?\b",   "PostgreSQL"),
    (r"\bmy\s*sql\b",                 "MySQL"),
    (r"\bmongo\s*db\b",               "MongoDB"),
    (r"\bsqlite\b",                   "SQLite"),
    (r"\bredis\b",                    "Redis"),
    # Languages / tools
    (r"\btype\s*script\b",            "TypeScript"),
    (r"\bjavascript\b",               "JavaScript"),
    (r"\bpython\b",                   "Python"),
    (r"\bjupyter\b",                  "Jupyter"),
    (r"\btensor\s*flow\b",            "TensorFlow"),
    (r"\bpytorch\b",                  "PyTorch"),
    (r"\bscikit.?learn\b",            "scikit-learn"),
    (r"\bpandas\b",                   "pandas"),
    (r"\bnumpy\b",                    "NumPy"),
    (r"\bdocker\b",                   "Docker"),
    (r"\bkubernetes\b",               "Kubernetes"),
    (r"\bgit\s*hub\b",                "GitHub"),
    (r"\bgit\s*lab\b",                "GitLab"),
    # Common locations / generic terms
    (r"\bfront\s*end\b",              "frontend"),
    (r"\bback\s*end\b",               "backend"),
    (r"\bfull\s*stack\b",             "full-stack"),
    (r"\brest\s*ful\b",               "RESTful"),
    (r"\brest\s*api\b",               "REST API"),
    (r"\bgraph\s*ql\b",               "GraphQL"),
    (r"\bjson\b",                     "JSON"),
    (r"\bhtml\b",                     "HTML"),
    (r"\bcss\b",                      "CSS"),
    (r"\bci\s*/?\s*cd\b",             "CI/CD"),
    (r"\bopen\s*ai\b",                "OpenAI"),
    (r"\bjwt\b",                      "JWT"),
    (r"\boauth\b",                    "OAuth"),
    (r"\bwebsocket[s]?\b",            "WebSocket"),
    (r"\bapi\b",                      "API"),
    (r"\burl\b",                      "URL"),
    (r"\bhttp[s]?\b",                 "HTTPS"),
    (r"\bui\b",                       "UI"),
    (r"\bux\b",                       "UX"),
    (r"\bml\b",                       "ML"),
    (r"\bai\b",                       "AI"),
    (r"\bllm\b",                      "LLM"),
]

# Compiled patterns for base glossary
_BASE_GLOSSARY_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), canonical)
    for pat, canonical in _BASE_TECH_GLOSSARY
]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RefinementResult:
    """Output of the transcript correction pipeline.

    Field names intentionally kept as 'refined_transcript' / 'refinement_method'
    for backward compatibility with existing DB schema and API responses.
    The behavior is correction-only (not essay-style refinement).
    """

    raw_transcript: str
    refined_transcript: str          # The corrected transcript (term/name corrections only)
    correction_summary: list[dict[str, Any]] = field(default_factory=list)
    glossary_matches: list[str] = field(default_factory=list)
    confidence: float = 1.0          # 0.0 – 1.0 overall confidence
    needs_review: bool = False
    refinement_method: str = "rules" # "rules" | "llm"
    error: str | None = None         # set if correction failed gracefully


# ── Public entry point ────────────────────────────────────────────────────────

def refine_project_defense_transcript(
    raw_transcript: str,
    *,
    student_profile: dict[str, Any] | None = None,
    project_context: str | None = None,
    claimed_skills: list[str] | None = None,
    website_url: str | None = None,
    github_url: str | None = None,
) -> RefinementResult:
    """
    Correct ASR spelling and term recognition errors in a raw project defense transcript.

    This function performs CORRECTION ONLY — it does not rewrite, polish, summarize,
    or paraphrase. Only misspelled names, product names, project names, and technical
    terms are replaced; all other wording is preserved exactly.

    Parameters
    ----------
    raw_transcript:   The unmodified ASR output to correct.
    student_profile:  Dict with student info (name, email, …).
    project_context:  Free-text proof objective / project title.
    claimed_skills:   Skills the student listed on their proof session.
    website_url:      Project website — used to infer project name.
    github_url:       Project GitHub repo — used to infer repo/project name.

    Returns
    -------
    RefinementResult  with raw_transcript preserved unchanged.
    """
    if not raw_transcript or not raw_transcript.strip():
        return RefinementResult(
            raw_transcript=raw_transcript or "",
            refined_transcript="",
            correction_summary=[],
            glossary_matches=[],
            confidence=1.0,
            needs_review=False,
        )

    # ── Try LLM correction first (if Anthropic is configured) ─────────────────
    if settings.anthropic_configured:
        try:
            return _refine_with_llm(
                raw_transcript=raw_transcript,
                student_profile=student_profile,
                project_context=project_context,
                claimed_skills=claimed_skills,
                website_url=website_url,
                github_url=github_url,
            )
        except Exception as exc:
            logger.warning(
                "LLM transcript correction failed (%s); falling back to rules-based.", exc
            )
            # Fall through to rules-based

    # ── Rules-based fallback ──────────────────────────────────────────────────
    return _refine_with_rules(
        raw_transcript=raw_transcript,
        student_profile=student_profile,
        project_context=project_context,
        claimed_skills=claimed_skills,
        website_url=website_url,
        github_url=github_url,
    )


# ── LLM-based correction (Anthropic) ─────────────────────────────────────────

def _refine_with_llm(
    raw_transcript: str,
    *,
    student_profile: dict[str, Any] | None,
    project_context: str | None,
    claimed_skills: list[str] | None,
    website_url: str | None,
    github_url: str | None,
) -> RefinementResult:
    """
    Use Claude to correct ASR term/spelling errors in the raw transcript.

    The prompt instructs Claude to:
    - ONLY correct misspelled names, product names, project names, technical terms.
    - NEVER rewrite sentences, change order, improve style, or add information.
    - Preserve the student's first-person voice, sentence structure, and spoken style.
    - Return structured JSON with per-correction confidence and applied flag.
    - Only apply high-confidence (>= 0.85) corrections to corrected_transcript.
    - Mark low-confidence suggestions as applied=false (leaves original in transcript).
    """
    import anthropic
    import json as _json

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
    )

    # Build context block for the prompt
    context_parts: list[str] = []

    if student_profile:
        name = _safe_name(student_profile)
        if name:
            context_parts.append(f"Student name: {name}")

    if claimed_skills:
        skills_str = ", ".join(s for s in claimed_skills if s and s.strip())
        if skills_str:
            context_parts.append(f"Claimed skills / technologies: {skills_str}")

    if project_context and project_context.strip():
        context_parts.append(f"Project description / proof objective: {project_context.strip()}")

    if website_url and website_url.strip():
        safe_url = _safe_url(website_url)
        if safe_url:
            context_parts.append(f"Project website: {safe_url}")

    if github_url and github_url.strip():
        safe_gh = _safe_url(github_url)
        if safe_gh:
            context_parts.append(f"GitHub repository: {safe_gh}")

    context_block = "\n".join(context_parts) if context_parts else "(no extra context provided)"

    system_prompt = (
        "You are a specialized speech-to-text post-processor for VeriBridge, a student "
        "work-verification platform. Your task is to correct ASR (automatic speech recognition) "
        "spelling and term recognition errors in a student's project defense transcript.\n\n"
        "CORRECTION RULES — what you ARE allowed to do:\n"
        "1. Correct misspelled student names using the provided student name.\n"
        "2. Correct mis-heard technical terms, product names, and project names when "
        "   clearly supported by context (e.g. 'First API' → 'FastAPI', "
        "   'Golmaps API' → 'Google Maps API', 'stimulates' → 'Streamlit', "
        "   'very brief' → 'VeriBridge').\n"
        "3. Only replace a word or short phrase when you are confident it is a specific "
        "   known term/name being mispronounced or mis-transcribed.\n\n"
        "CORRECTION RULES — what you are NOT allowed to do:\n"
        "4. Do NOT rewrite full sentences or change sentence order.\n"
        "5. Do NOT improve grammar broadly or polish the transcript.\n"
        "6. Do NOT replace words with 'similar meaning' alternatives unless it is clearly "
        "   a term/spelling correction (e.g. do not replace 'works well' with 'functions correctly').\n"
        "7. Do NOT add new information, remove the student's original meaning, "
        "   or convert the transcript into a scripted paragraph.\n"
        "8. Do NOT change informal spoken language, filler words (um, uh), or sentence structure.\n\n"
        "CONFIDENCE RULE:\n"
        "- Only apply corrections to corrected_transcript when confidence >= 0.85.\n"
        "- For corrections with confidence < 0.85: keep the original word in corrected_transcript "
        "  (do NOT change it) but include the suggestion in corrections with applied=false.\n"
        "- Set transcript_needs_review=true if any corrections have applied=false.\n\n"
        "Return ONLY valid JSON (no markdown fences) in this exact shape:\n"
        "{\n"
        '  "corrected_transcript": "...",\n'
        '  "corrections": [\n'
        '    {\n'
        '      "original": "...",\n'
        '      "corrected": "...",\n'
        '      "correction_type": "name|technical_term|product_name|project_name|spelling",\n'
        '      "confidence": 0.0,\n'
        '      "applied": true,\n'
        '      "reason": "..."\n'
        '    }\n'
        "  ],\n"
        '  "confidence": 0.0,\n'
        '  "transcript_needs_review": false\n'
        "}\n\n"
        "confidence (overall) is a float 0 (many uncertain corrections) to 1 (highly confident).\n"
        "Per-correction confidence: 0.85+ = high (apply), below 0.85 = do not apply."
    )

    user_message = (
        f"Context about this student and project:\n{context_block}\n\n"
        f"Raw auto-transcript to correct:\n{raw_transcript}"
    )

    response = client.messages.create(
        model=settings.ai_reviewer_model or "claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_json = (response.content[0].text or "").strip()
    # Strip any accidental markdown fences
    raw_json = re.sub(r"^```json\s*", "", raw_json, flags=re.MULTILINE)
    raw_json = re.sub(r"^```\s*$", "", raw_json, flags=re.MULTILINE)

    parsed: dict[str, Any] = {}
    try:
        parsed = _json.loads(raw_json)
    except _json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc

    # Accept both new "corrected_transcript" and legacy "refined_transcript" keys
    refined = str(
        parsed.get("corrected_transcript")
        or parsed.get("refined_transcript")
        or raw_transcript
    ).strip()
    corrections_raw = parsed.get("corrections") or []
    confidence = float(parsed.get("confidence", 0.8))
    confidence = max(0.0, min(1.0, confidence))
    llm_needs_review = bool(parsed.get("transcript_needs_review", False))

    # Validate corrections structure
    corrections: list[dict[str, Any]] = []
    glossary_matches: list[str] = []
    has_unapplied = False

    for item in corrections_raw:
        if not isinstance(item, dict):
            continue
        if not item.get("original") or not item.get("corrected"):
            continue

        item_confidence = float(item.get("confidence", 0.85))
        item_confidence = max(0.0, min(1.0, item_confidence))
        applied = bool(item.get("applied", item_confidence >= 0.85))

        entry: dict[str, Any] = {
            "original": str(item["original"]),
            "corrected": str(item["corrected"]),
            "correction_type": str(item.get("correction_type") or "technical_term"),
            "confidence": round(item_confidence, 2),
            "applied": applied,
            "reason": str(item.get("reason") or "ASR correction"),
        }
        corrections.append(entry)

        if applied:
            glossary_matches.append(str(item["corrected"]))
        else:
            has_unapplied = True

    needs_review = (
        confidence < 0.7
        or len(corrections) > 10
        or llm_needs_review
        or has_unapplied
    )

    return RefinementResult(
        raw_transcript=raw_transcript,
        refined_transcript=refined,
        correction_summary=corrections,
        glossary_matches=list(dict.fromkeys(glossary_matches)),
        confidence=confidence,
        needs_review=needs_review,
        refinement_method="llm",
    )


# ── Rules-based correction ────────────────────────────────────────────────────

def _refine_with_rules(
    raw_transcript: str,
    *,
    student_profile: dict[str, Any] | None,
    project_context: str | None,
    claimed_skills: list[str] | None,
    website_url: str | None,
    github_url: str | None,
) -> RefinementResult:
    """
    Pure regex + dictionary rules-based correction.
    Used when the Anthropic API is not configured or when the LLM fails.
    Only corrects known term/spelling patterns — never rewrites sentences.
    """
    text = raw_transcript

    corrections: list[dict[str, Any]] = []
    glossary_matches: list[str] = []

    # ── 1. Build project-specific glossary ────────────────────────────────────
    project_glossary: list[tuple[re.Pattern[str], str]] = []
    name_glossary: list[tuple[re.Pattern[str], str]] = []

    # Student name correction
    if student_profile:
        name = _safe_name(student_profile)
        if name:
            name_variants = _build_name_variants(name)
            for variant_pat in name_variants:
                try:
                    name_glossary.append(
                        (re.compile(variant_pat, re.IGNORECASE), name)
                    )
                except re.error:
                    pass

    # Claimed skills → add to glossary (exact matches)
    for skill in (claimed_skills or []):
        if not skill or not skill.strip():
            continue
        canonical = skill.strip()
        try:
            project_glossary.append(
                (re.compile(r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE), canonical)
            )
        except re.error:
            pass

    # Project title from context
    if project_context and project_context.strip():
        _add_title_variants(project_context.strip(), project_glossary)

    # Repo name from GitHub URL
    if github_url and github_url.strip():
        repo_name = _extract_repo_name(github_url)
        if repo_name:
            _add_title_variants(repo_name, project_glossary)

    # ── 2. Apply base tech glossary first ─────────────────────────────────────
    text, base_corrections = _apply_glossary(
        text, _BASE_GLOSSARY_COMPILED,
        default_correction_type="technical_term",
        default_confidence=0.92,
    )
    corrections.extend(base_corrections)
    glossary_matches.extend(c["corrected"] for c in base_corrections)

    # ── 3. Apply name-specific glossary ───────────────────────────────────────
    if name_glossary:
        text, name_corrections = _apply_glossary(
            text, name_glossary,
            default_correction_type="name",
            default_confidence=0.90,
        )
        corrections.extend(name_corrections)
        glossary_matches.extend(c["corrected"] for c in name_corrections)

    # ── 4. Apply project-specific glossary ────────────────────────────────────
    text, proj_corrections = _apply_glossary(
        text, project_glossary,
        default_correction_type="technical_term",
        default_confidence=0.88,
    )
    corrections.extend(proj_corrections)
    glossary_matches.extend(c["corrected"] for c in proj_corrections)

    # ── 5. Light punctuation cleanup (no grammar rewriting) ───────────────────
    text = _light_punctuation_fix(text)

    # ── 6. Confidence / needs_review ──────────────────────────────────────────
    n_corrections = len(corrections)
    confidence = max(0.4, 1.0 - (n_corrections * 0.03))
    needs_review = confidence < 0.7 or n_corrections > 10

    return RefinementResult(
        raw_transcript=raw_transcript,
        refined_transcript=text,
        correction_summary=corrections,
        glossary_matches=list(dict.fromkeys(glossary_matches)),
        confidence=round(confidence, 2),
        needs_review=needs_review,
        refinement_method="rules",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_glossary(
    text: str,
    glossary: list[tuple[re.Pattern[str], str]],
    *,
    default_correction_type: str = "technical_term",
    default_confidence: float = 0.92,
) -> tuple[str, list[dict[str, Any]]]:
    """Apply each (pattern, canonical) pair to text; record substitutions."""
    corrections: list[dict[str, Any]] = []
    for pattern, canonical in glossary:
        def _replace_fn(
            m: re.Match,
            _canonical: str = canonical,
            _type: str = default_correction_type,
            _conf: float = default_confidence,
        ) -> str:
            original_match = m.group(0)
            if original_match != _canonical:
                corrections.append({
                    "original": original_match,
                    "corrected": _canonical,
                    "correction_type": _type,
                    "confidence": _conf,
                    "applied": True,
                    "reason": "ASR correction via glossary",
                })
            return _canonical
        new_text = pattern.sub(_replace_fn, text)
        text = new_text
    return text, corrections


def _light_punctuation_fix(text: str) -> str:
    """Minimal mechanical punctuation cleanup — never changes meaning or wording."""
    # Ensure space after sentence-ending punctuation before capital letter
    text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Capitalize first letter of transcript
    if text:
        text = text[0].upper() + text[1:]
    return text.strip()


def _safe_name(profile: dict[str, Any]) -> str:
    """Extract a student's full name from a profile dict, safely."""
    for key in ("full_name", "name", "display_name", "first_name"):
        val = profile.get(key)
        if val and isinstance(val, str) and val.strip():
            if key == "first_name":
                last = profile.get("last_name", "")
                return f"{val.strip()} {last.strip()}".strip() if last else val.strip()
            return val.strip()
    return ""


def _build_name_variants(full_name: str) -> list[str]:
    """
    Build loose regex patterns for common ASR mis-hearings of a name.

    For "Mohammed Mubashir Uddin Faraz" we want patterns that catch things like:
    "muhammoh", "Mohamad Faras", "Mahamakobashiruddin Faras", etc.

    Strategy:
    - Two-word pattern: first and last token with 3-char prefix matching
    - Single-word pattern: first token (only for names >= 6 chars to avoid false positives)
    """
    tokens = [t for t in re.split(r"\s+", full_name.strip()) if len(t) >= 2]
    if not tokens:
        return []

    if len(tokens) < 2:
        return []

    first_prefix = re.escape(tokens[0][:3])
    last_prefix  = re.escape(tokens[-1][:3])

    patterns: list[str] = [
        # Two-word pattern: first + last token (e.g. "Mohamad Faras" → full name)
        rf"[a-zA-Z]*{first_prefix}[a-zA-Z]*\s+[a-zA-Z]*{last_prefix}[a-zA-Z]*",
    ]

    # Single-word first-name pattern for longer names (avoids false positives on short names)
    # e.g. "muhammoh" → "Mohammed" when first token is >= 6 chars
    # Uses [a-zA-Z]* (zero or more) so that names ending in the prefix also match
    # (e.g. "muhammoh" ends with "moh", so we need zero chars allowed after prefix)
    if len(tokens[0]) >= 6:
        patterns.append(rf"\b[a-zA-Z]*{first_prefix}[a-zA-Z]*\b")

    return patterns


def _extract_repo_name(github_url: str) -> str:
    """Extract 'repo-name' from https://github.com/user/repo-name."""
    m = re.search(r"github\.com/[^/]+/([^/?#\s]+)", github_url)
    if m:
        return m.group(1).replace("-", " ").replace("_", " ").strip()
    return ""


def _add_title_variants(title: str, glossary: list[tuple[re.Pattern[str], str]]) -> None:
    """Add pattern variants for a project title to the glossary in place."""
    canonical = title.strip()
    if not canonical:
        return

    # 1. Exact multi-word match (case-insensitive)
    try:
        glossary.append(
            (re.compile(r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE), canonical)
        )
    except re.error:
        pass

    # 2. Word-by-word: each 5+ character word in the title
    words = [w for w in re.split(r"[\s/_-]+", canonical) if len(w) >= 5]
    for word in words:
        try:
            glossary.append(
                (re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE), word)
            )
        except re.error:
            pass


def _safe_url(url: str) -> str:
    """Return only the scheme+host+path of a URL, stripping tokens/query params."""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        safe = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        return safe if parsed.netloc else ""
    except Exception:
        return ""


# ── Utility for callers ───────────────────────────────────────────────────────

def build_correction_display_summary(corrections: list[dict[str, Any]]) -> str:
    """
    Build a short human-readable summary of corrections for display in the UI.

    e.g. 'Corrected likely speech-to-text spelling and technical term errors: FastAPI, …'
    """
    if not corrections:
        return ""
    # Only include applied corrections in the display summary
    applied = [c for c in corrections if c.get("applied", True)]
    if not applied:
        return ""
    unique_corrected = list(dict.fromkeys(
        c["corrected"] for c in applied if c.get("corrected")
    ))
    if not unique_corrected:
        return ""
    if len(unique_corrected) <= 5:
        terms = ", ".join(unique_corrected)
    else:
        terms = ", ".join(unique_corrected[:5]) + f", and {len(unique_corrected) - 5} more"
    return f"Corrected likely speech-to-text spelling and technical term errors: {terms}."
