"""Project Defense — Answer Evidence Engine.

Builds deterministic, claim-level *defense answer evidence* objects from a
Project Defense session's targeted questions (``vbr_session_questions`` rows
carrying ``target_ref``), the student's per-question answers (transcript
segments carrying ``question_id``), the project's claimed skills, and the safe
attached-proof summaries stored in ``vbr_projects.metadata.attached_proofs``.

This replaces "global transcript keyword analysis" as the primary way Project
Defense maps answers to skills: the mapping is grounded in the question's
``question_id`` / ``target_ref`` (kind + skill / document / website / repo),
never in broad keyword overlap. A generic or untargeted answer produces an
honest ``unknown_or_generic`` / ``insufficient_or_generic`` object and never
promotes a skill.

Evidence framing (product rule): Project Defense is self-explanation /
understanding / corroboration evidence. It explains and corroborates GitHub,
Website, and Document proofs — it is never, by itself, proof of implementation
or authorship, and nothing built here may claim otherwise.

Safety:
    - ``safe_answer_summary`` is a short, sanitized snippet (storage paths,
      URLs, tokens, env pairs, local paths redacted) — never the full answer.
    - Objects carry only IDs / labels already safe for the private report;
      the public projection lives in ``public_report_safety_service``
      (:func:`public_safe_defense_answer_evidence`) and fails closed.
    - No numeric scores — qualitative statuses only.
    - This module is pure (no DB, no LLM calls).
"""

from __future__ import annotations

import re
from typing import Any

from app.services.project_defense_evidence_chips import _sanitize_transcript_text

__all__ = [
    "ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE",
    "ANSWER_STATUS_PARTIALLY_EXPLAINED",
    "ANSWER_STATUS_GENERIC",
    "ANSWER_STATUS_NOT_EXPLAINED",
    "ANSWER_STATUS_NEEDS_REVIEW",
    "ANSWER_STATUS_WITHHELD",
    "DEFENSE_EVIDENCE_ROLE_NOTE",
    "MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION",
    "build_defense_answer_evidence",
    "explained_skills_from_answer_evidence",
]


# ── Qualitative answer statuses (never numeric) ──────────────────────────────

ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE = "Explained with evidence"
ANSWER_STATUS_PARTIALLY_EXPLAINED = "Partially explained"
ANSWER_STATUS_GENERIC = "Generic explanation"
ANSWER_STATUS_NOT_EXPLAINED = "Not explained"
ANSWER_STATUS_NEEDS_REVIEW = "Needs review"
ANSWER_STATUS_WITHHELD = "Withheld for privacy"

# Statuses that count as a genuine, targeted explanation of a skill. Generic
# mentions and unanswered questions never promote a skill.
_EXPLAINED_STATUSES = frozenset(
    {ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE, ANSWER_STATUS_PARTIALLY_EXPLAINED}
)


# ── Question kinds / answer purposes ─────────────────────────────────────────

PURPOSE_ARCHITECTURE = "architecture_explanation"
PURPOSE_IMPLEMENTATION = "implementation_explanation"
PURPOSE_CONTRIBUTION = "contribution_explanation"
PURPOSE_SKILL = "skill_explanation"
PURPOSE_WEBSITE = "website_behavior_explanation"
PURPOSE_DOCUMENT = "document_explanation"
PURPOSE_CHALLENGE = "challenge_debugging"
PURPOSE_TRADEOFF = "tradeoff_decision"
PURPOSE_EVALUATION = "evaluation_result"
PURPOSE_IMPROVEMENT = "improvement_next_step"
PURPOSE_UNKNOWN = "unknown_or_generic"

# ``target_ref.kind`` (written by ``build_defense_question_specs``) → question
# kind. ``skill_repo_link`` questions are only generated when a GitHub proof is
# attached, so they are implementation-explanation questions; plain
# ``skill_link`` questions are skill-understanding questions.
_TARGET_KIND_TO_QUESTION_KIND: dict[str, str] = {
    "architecture": PURPOSE_ARCHITECTURE,
    "contribution": PURPOSE_CONTRIBUTION,
    "skill_link": PURPOSE_SKILL,
    "skill_repo_link": PURPOSE_IMPLEMENTATION,
    "live_demo_link": PURPOSE_WEBSITE,
    "document_link": PURPOSE_DOCUMENT,
    "challenge": PURPOSE_CHALLENGE,
    "tradeoff": PURPOSE_TRADEOFF,
    "evaluation": PURPOSE_EVALUATION,
    "improvement": PURPOSE_IMPROVEMENT,
}


# ── Claim types ───────────────────────────────────────────────────────────────

CLAIM_PROJECT_ARCHITECTURE = "project_architecture"
CLAIM_PERSONAL_CONTRIBUTION = "personal_contribution"
CLAIM_SKILL_UNDERSTANDING = "skill_understanding"
CLAIM_IMPLEMENTATION_REASONING = "implementation_reasoning"
CLAIM_RUNTIME_BEHAVIOR = "runtime_behavior_explanation"
CLAIM_DOCUMENT_EXPLANATION = "document_claim_explanation"
CLAIM_CHALLENGE_RESOLUTION = "challenge_resolution"
CLAIM_TRADEOFF_REASONING = "tradeoff_reasoning"
CLAIM_EVALUATION_INTERPRETATION = "evaluation_interpretation"
CLAIM_FUTURE_IMPROVEMENT = "future_improvement"

_QUESTION_KIND_TO_CLAIM_TYPE: dict[str, str] = {
    PURPOSE_ARCHITECTURE: CLAIM_PROJECT_ARCHITECTURE,
    PURPOSE_CONTRIBUTION: CLAIM_PERSONAL_CONTRIBUTION,
    PURPOSE_SKILL: CLAIM_SKILL_UNDERSTANDING,
    PURPOSE_IMPLEMENTATION: CLAIM_IMPLEMENTATION_REASONING,
    PURPOSE_WEBSITE: CLAIM_RUNTIME_BEHAVIOR,
    PURPOSE_DOCUMENT: CLAIM_DOCUMENT_EXPLANATION,
    PURPOSE_CHALLENGE: CLAIM_CHALLENGE_RESOLUTION,
    PURPOSE_TRADEOFF: CLAIM_TRADEOFF_REASONING,
    PURPOSE_EVALUATION: CLAIM_EVALUATION_INTERPRETATION,
    PURPOSE_IMPROVEMENT: CLAIM_FUTURE_IMPROVEMENT,
    # An untargeted / generic answer is honest project-level context.
    PURPOSE_UNKNOWN: CLAIM_PROJECT_ARCHITECTURE,
}


# ── Evidence roles ────────────────────────────────────────────────────────────

ROLE_CANDIDATE_EXPLANATION = "candidate_explanation"
ROLE_IMPLEMENTATION_CONTEXT = "implementation_explanation_context"
ROLE_RUNTIME_BEHAVIOR_CONTEXT = "runtime_behavior_explanation_context"
ROLE_DOCUMENT_CORROBORATION_CONTEXT = "document_corroboration_context"
ROLE_PROCESS_REFLECTION = "process_reflection"
ROLE_CHALLENGE_TRADEOFF_CONTEXT = "challenge_tradeoff_context"
ROLE_GENERIC_PROJECT_CONTEXT = "generic_project_context"
ROLE_INSUFFICIENT_OR_GENERIC = "insufficient_or_generic"


# ── Honest framing / limitations ──────────────────────────────────────────────

DEFENSE_EVIDENCE_ROLE_NOTE = (
    "Project Defense explanation supports this claim as self-explanation and "
    "corroboration evidence; it is not standalone proof of implementation or "
    "authorship."
)
MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION = (
    "Defense explains the claim, but implementation evidence is not attached."
)
_NEEDS_REVIEW_LIMITATION = (
    "The answer may not align with the attached evidence; review it before "
    "relying on this explanation."
)

# Public-facing card wording is defined here; the fail-closed public projection
# in ``public_report_safety_service`` decides *whether* it may be shown.


# ── Answer-specificity signals (deterministic, no LLM) ───────────────────────
#
# Kept intentionally small and conservative. Depth vocabulary mirrors the
# analysis service's technical-depth signals; a couple of generic filler
# patterns mirror its vague-language signals. Matching any of these never
# promotes a skill by itself — it only grades how specific a *targeted*
# answer is.

_DEPTH_RE = re.compile(
    r"\b(?:architecture|component|api|endpoint|database|model|algorithm|"
    r"deployment|caching|authentication|authorization|middleware|schema|"
    r"pipeline|workflow|interface|asynchronous|concurrency|scalability|"
    r"latency|throughput|refactor|optimi[sz]ation|validation|error handling|"
    r"unit test|integration test|data flow|design pattern|state management|"
    r"request|response|query|function|class|module|library|framework|hook|"
    r"route|migration|index|token|queue|cache|thread|container|"
    # model/prediction/training/evaluation detail — so a genuine ML answer
    # registers substance beyond merely naming "Machine Learning".
    r"training|trained|prediction|predict|inference|dataset|feature|"
    r"embedding|evaluation|evaluate|precision|recall|accuracy|"
    r"classification|regression|tokeniz|gradient|hyperparameter)\b",
    re.IGNORECASE,
)

_VAGUE_RE = re.compile(
    r"\b(?:very good project|amazing project|great app(?:lication)?|"
    r"good project|interesting project|used many technologies|"
    r"i learned a lot|it is nice|it works well)\b",
    re.IGNORECASE,
)

# Language that clearly disclaims authorship / contradicts the claim. Kept
# conservative: only explicit disclaimers flag an answer, and the outcome is a
# neutral "Needs review" — never an accusation.
_CONTRADICTION_RE = re.compile(
    r"\b(?:did not use|never used|did not build|didn't build|not mine|"
    r"not my work|i did not write|copy[- ]paste[d]?|borrowed code|"
    r"found online|downloaded from)\b",
    re.IGNORECASE,
)

_MIN_SPECIFIC_ANSWER_WORDS = 12

# A targeted answer must carry substantive technical explanation *beyond* the
# skill label to qualify as a real explanation. Naming (or repeating) the skill
# is not enough; neither is a single repeated technical word. Require at least
# this many *distinct* technical-depth signals in the answer once the skill's
# own words are removed.
_MIN_DISTINCT_DEPTH_TERMS = 2

_SUMMARY_MAX_LEN = 220


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _safe_summary(text: str, max_len: int = _SUMMARY_MAX_LEN) -> str:
    collapsed = " ".join(_sanitize_transcript_text(str(text or "")).split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[:max_len].rstrip() + "…"


def _target_terms(skill: str | None) -> list[re.Pattern[str]]:
    """Match patterns for the targeted skill's words (>= 3 chars), if any."""
    words = [w for w in re.split(r"[\s/._-]+", str(skill or "")) if len(w) >= 3]
    if not words and skill:
        words = [str(skill)]
    return [re.compile(rf"\b{re.escape(w)}", re.IGNORECASE) for w in words]


def _grade_answer(answer_text: str, mapped_skill: str | None) -> str:
    """Grade one *targeted* answer's specificity — qualitative label only.

    Conservative by design. Naming the targeted skill is never, by itself, an
    explanation: the skill label's own words are stripped before the answer is
    scored for technical substance, so an answer that only repeats the skill
    name ("Python Python Python…") or merely restates it ("Machine Learning")
    carries no depth signal and grades as "Generic explanation". A targeted
    answer earns "Partially explained" only when it contains substantive
    technical explanation *beyond* the skill label — at least
    :data:`_MIN_DISTINCT_DEPTH_TERMS` distinct technical-depth signals such as an
    implementation mechanism, data flow, API/route/service behavior,
    model/training/evaluation detail, or debugging/tradeoff reasoning. An empty
    answer is "Not explained"; a short, filler-dominated, or skill-name-only
    answer is "Generic explanation". The upgrade to "Explained with evidence"
    happens only in :func:`build_defense_answer_evidence` when an attached proof
    corroborates the same claim.
    """
    text = (answer_text or "").strip()
    if not text:
        return ANSWER_STATUS_NOT_EXPLAINED

    words = text.split()
    if len(words) < _MIN_SPECIFIC_ANSWER_WORDS:
        return ANSWER_STATUS_GENERIC

    # Strip the targeted skill's own words before scoring depth, so merely
    # naming or repeating the skill name can never masquerade as substance.
    residual = text
    for pat in _target_terms(mapped_skill):
        residual = pat.sub(" ", residual)

    depth_terms = {m.lower() for m in _DEPTH_RE.findall(residual)}
    vague_hits = len(_VAGUE_RE.findall(text))

    # The skill name alone, vague filler, or a single repeated technical word is
    # not an explanation — require multiple *distinct* technical-depth signals.
    if len(depth_terms) < _MIN_DISTINCT_DEPTH_TERMS:
        return ANSWER_STATUS_GENERIC
    if vague_hits >= 2 and len(depth_terms) <= _MIN_DISTINCT_DEPTH_TERMS:
        return ANSWER_STATUS_GENERIC
    return ANSWER_STATUS_PARTIALLY_EXPLAINED


# ── Attached-proof context ────────────────────────────────────────────────────


def _attached_context(attached_proofs: dict[str, Any] | None) -> dict[str, Any]:
    """Safe view of the attached-proof summaries relevant to corroboration."""
    attached = attached_proofs if isinstance(attached_proofs, dict) else {}
    github = attached.get("github_proof")
    github = github if isinstance(github, dict) else None
    websites = [w for w in (attached.get("website_proofs") or []) if isinstance(w, dict)]
    documents = [d for d in (attached.get("documents") or []) if isinstance(d, dict)]

    github_skills = {_norm(s) for s in (github.get("detected_skills") or [])} if github else set()
    website_skills: set[str] = set()
    for wp in websites:
        website_skills.update(_norm(s) for s in (wp.get("supported_skills") or []))
    document_skills: set[str] = set()
    doc_titles: dict[str, str] = {}
    for doc in documents:
        document_skills.update(_norm(s) for s in (doc.get("skills") or []))
        doc_id = str(doc.get("document_evidence_id") or "")
        if doc_id:
            doc_titles[doc_id] = str(doc.get("title") or "Document")

    return {
        "has_github": github is not None,
        "has_website": bool(websites),
        "has_document": bool(documents),
        "github_skills": github_skills,
        "website_skills": website_skills,
        "document_skills": document_skills,
        "document_titles": doc_titles,
    }


def _corroborations(
    question_kind: str, mapped_skill: str | None, ctx: dict[str, Any]
) -> tuple[bool, bool, bool]:
    """Conservative high-level corroboration flags for one answered question.

    A flag is set only when (a) the matching proof source is actually attached
    AND (b) the question targets that source, or targets a skill that source's
    saved summary explicitly supports. No line/frame citations are invented —
    corroboration is stated at proof-summary level only.
    """
    skill_key = _norm(mapped_skill)

    corroborates_github = ctx["has_github"] and (
        question_kind == PURPOSE_IMPLEMENTATION
        or (question_kind == PURPOSE_SKILL and skill_key in ctx["github_skills"])
    )
    corroborates_website = ctx["has_website"] and (
        question_kind == PURPOSE_WEBSITE
        or (question_kind in (PURPOSE_SKILL, PURPOSE_IMPLEMENTATION) and skill_key in ctx["website_skills"])
    )
    corroborates_document = ctx["has_document"] and (
        question_kind == PURPOSE_DOCUMENT
        or (question_kind == PURPOSE_SKILL and skill_key in ctx["document_skills"])
    )
    return corroborates_github, corroborates_website, corroborates_document


# ── Role / label mapping ──────────────────────────────────────────────────────


def _evidence_role(question_kind: str, status: str, ctx: dict[str, Any]) -> str:
    if status in (ANSWER_STATUS_GENERIC, ANSWER_STATUS_NOT_EXPLAINED):
        return ROLE_INSUFFICIENT_OR_GENERIC
    if question_kind == PURPOSE_IMPLEMENTATION:
        # Implementation-explanation context only while the GitHub evidence it
        # explains is actually attached; otherwise it is plain self-explanation.
        return ROLE_IMPLEMENTATION_CONTEXT if ctx["has_github"] else ROLE_CANDIDATE_EXPLANATION
    if question_kind == PURPOSE_WEBSITE:
        return ROLE_RUNTIME_BEHAVIOR_CONTEXT if ctx["has_website"] else ROLE_CANDIDATE_EXPLANATION
    if question_kind == PURPOSE_DOCUMENT:
        return ROLE_DOCUMENT_CORROBORATION_CONTEXT if ctx["has_document"] else ROLE_CANDIDATE_EXPLANATION
    if question_kind in (PURPOSE_CHALLENGE, PURPOSE_TRADEOFF):
        return ROLE_CHALLENGE_TRADEOFF_CONTEXT
    if question_kind in (PURPOSE_CONTRIBUTION, PURPOSE_IMPROVEMENT, PURPOSE_EVALUATION):
        return ROLE_PROCESS_REFLECTION
    if question_kind == PURPOSE_UNKNOWN:
        return ROLE_GENERIC_PROJECT_CONTEXT
    return ROLE_CANDIDATE_EXPLANATION


def _target_label(question_kind: str, target_ref: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Short, safe label for what the question targeted (never a raw URL/id)."""
    skill = str(target_ref.get("skill") or "").strip()
    if skill:
        return skill
    if question_kind == PURPOSE_DOCUMENT:
        doc_id = str(target_ref.get("document_evidence_id") or "")
        title = ctx["document_titles"].get(doc_id)
        return title or "Attached document"
    labels = {
        PURPOSE_ARCHITECTURE: "Project architecture",
        PURPOSE_CONTRIBUTION: "Personal contribution",
        PURPOSE_WEBSITE: "Live website behavior",
        PURPOSE_IMPLEMENTATION: "GitHub repository",
        PURPOSE_CHALLENGE: "Technical challenge",
        PURPOSE_TRADEOFF: "Design tradeoff",
        PURPOSE_EVALUATION: "Evaluation results",
        PURPOSE_IMPROVEMENT: "Future improvement",
    }
    return labels.get(question_kind, "Project overview")


def _basis_chips(
    *,
    targeted: bool,
    has_answer: bool,
    mapped_skill: str | None,
    claimed: set[str],
    question_kind: str,
    corroborates_github: bool,
    corroborates_website: bool,
    corroborates_document: bool,
) -> list[str]:
    chips: list[str] = []
    if targeted:
        chips.append("Targeted question")
    if has_answer:
        chips.append("Candidate answer")
    if mapped_skill and _norm(mapped_skill) in claimed:
        chips.append("Project skill claim")
    if corroborates_github:
        chips.append("Attached GitHub proof")
    if corroborates_website:
        chips.append("Attached Website proof")
    if corroborates_document:
        chips.append("Attached Document proof")
    if question_kind in (PURPOSE_CHALLENGE, PURPOSE_TRADEOFF):
        chips.append("Challenge/tradeoff explanation")
    chips.append("Privacy-safe summary")
    return chips


def _limitation(
    question_kind: str,
    status: str,
    contradiction: bool,
    ctx: dict[str, Any],
) -> str:
    if contradiction:
        return _NEEDS_REVIEW_LIMITATION
    # Skill / implementation claims without any attached implementation-style
    # proof (GitHub or Website) stay honest about the missing artifact evidence.
    if (
        question_kind in (PURPOSE_SKILL, PURPOSE_IMPLEMENTATION)
        and status in _EXPLAINED_STATUSES
        and not (ctx["has_github"] or ctx["has_website"])
    ):
        return MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION
    return DEFENSE_EVIDENCE_ROLE_NOTE


# ── Main builder ──────────────────────────────────────────────────────────────


def build_defense_answer_evidence(
    *,
    questions: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    claimed_skills: list[str],
    attached_proofs: dict[str, Any] | None,
    project_title: str = "",
    privacy_scan_status: str = "clean",
) -> list[dict[str, Any]]:
    """Build deterministic, claim-level defense answer evidence objects.

    ``questions`` are ``vbr_session_questions`` rows (``id`` / ``question_text``
    / ``target_ref`` / ``sort_order``); ``segments`` are transcript segments
    (``question_id`` / ``text``). Mapping is grounded in ``question_id`` +
    ``target_ref`` — a skill is mapped only when its own targeted question was
    answered; untargeted (``question_id``-less) text becomes at most one
    project-level ``unknown_or_generic`` object that maps no skill.

    Returns plain dicts safe for ``vbr_verification_sessions.telemetry``
    storage and the private report; the public projection is applied later by
    ``public_report_safety_service.public_safe_defense_answer_evidence``.
    """
    ctx = _attached_context(attached_proofs)
    claimed = {_norm(s) for s in claimed_skills or []}
    privacy_status = str(privacy_scan_status or "").strip().lower() or "unknown"
    privacy_clean = privacy_status == "clean"

    # question_id → concatenated answer text (a question may span segments).
    answers: dict[str, list[str]] = {}
    untargeted_parts: list[str] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        qid = seg.get("question_id")
        if qid:
            answers.setdefault(str(qid), []).append(text)
        else:
            untargeted_parts.append(text)

    items: list[dict[str, Any]] = []

    def _append(
        *,
        index: int,
        question_id: str | None,
        question_text: str,
        question_kind: str,
        target_ref_kind: str | None,
        target_label: str,
        mapped_skill: str | None,
        answer_text: str,
    ) -> None:
        status = _grade_answer(answer_text, mapped_skill)
        contradiction = bool(_CONTRADICTION_RE.search(answer_text or ""))
        if contradiction:
            status = ANSWER_STATUS_NEEDS_REVIEW

        # A generic / unanswered / contradicted answer never corroborates.
        if status in _EXPLAINED_STATUSES:
            gh, web, doc = _corroborations(question_kind, mapped_skill, ctx)
        else:
            gh = web = doc = False
        if status == ANSWER_STATUS_PARTIALLY_EXPLAINED and (gh or web or doc):
            status = ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE

        answer_purpose = (
            question_kind if status in _EXPLAINED_STATUSES else PURPOSE_UNKNOWN
        )
        role = _evidence_role(question_kind, status, ctx)
        items.append(
            {
                "evidence_id_safe": f"defense-answer-{index}",
                "question_id": question_id,  # private only; stripped publicly
                "question_kind": question_kind,
                "question_text": question_text,
                "target_ref_kind": target_ref_kind,
                "target_ref_label_safe": target_label,
                "project_title": str(project_title or ""),
                "mapped_skill": mapped_skill,
                "claim_type": _QUESTION_KIND_TO_CLAIM_TYPE.get(
                    question_kind, CLAIM_PROJECT_ARCHITECTURE
                ),
                "answer_purpose": answer_purpose,
                "evidence_role": role,
                "qualitative_status": status,
                "safe_answer_summary": _safe_summary(answer_text),
                "evidence_basis_chips": _basis_chips(
                    targeted=question_kind != PURPOSE_UNKNOWN,
                    has_answer=bool((answer_text or "").strip()),
                    mapped_skill=mapped_skill,
                    claimed=claimed,
                    question_kind=question_kind,
                    corroborates_github=gh,
                    corroborates_website=web,
                    corroborates_document=doc,
                ),
                "corroborates_github": gh,
                "corroborates_website": web,
                "corroborates_document": doc,
                "contradiction_flag": contradiction,
                "limitation": _limitation(question_kind, status, contradiction, ctx),
                "public_shareable": privacy_clean and not contradiction,
                "privacy_status": privacy_status,
            }
        )

    ordered = sorted(
        [q for q in questions or [] if isinstance(q, dict)],
        key=lambda q: q.get("sort_order", 0),
    )
    index = 0
    for question in ordered:
        qid = str(question.get("id") or "")
        answer_text = " ".join(answers.get(qid, [])).strip()
        if not answer_text:
            continue  # unanswered questions are covered by skills_missing lists
        target_ref = question.get("target_ref") if isinstance(question.get("target_ref"), dict) else {}
        kind_raw = str(target_ref.get("kind") or "").strip()
        question_kind = _TARGET_KIND_TO_QUESTION_KIND.get(kind_raw, PURPOSE_UNKNOWN)
        skill = str(target_ref.get("skill") or "").strip() or None
        # A skill is mapped only from the question's own target_ref — never
        # from keyword overlap — and only when the project claims it.
        mapped_skill = skill if (skill and _norm(skill) in claimed) else None
        index += 1
        _append(
            index=index,
            question_id=qid or None,
            question_text=str(question.get("question_text") or ""),
            question_kind=question_kind,
            target_ref_kind=kind_raw or None,
            target_label=_target_label(question_kind, target_ref, ctx),
            mapped_skill=mapped_skill,
            answer_text=answer_text,
        )

    if untargeted_parts:
        index += 1
        _append(
            index=index,
            question_id=None,
            question_text="",
            question_kind=PURPOSE_UNKNOWN,
            target_ref_kind=None,
            target_label="Project overview",
            mapped_skill=None,
            answer_text=" ".join(untargeted_parts).strip(),
        )

    return items


def explained_skills_from_answer_evidence(items: list[dict[str, Any]]) -> list[str]:
    """Skills genuinely explained via their own targeted question/answer.

    Only a mapped (question-targeted) skill whose answer graded as a real
    explanation counts — generic answers, untargeted text, and contradicted
    answers never promote a skill. Order is stable, first-explained first.
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        skill = item.get("mapped_skill")
        if not skill:
            continue
        if item.get("contradiction_flag"):
            continue
        if item.get("qualitative_status") not in _EXPLAINED_STATUSES:
            continue
        key = _norm(skill)
        if key in seen:
            continue
        seen.add(key)
        out.append(str(skill))
    return out
