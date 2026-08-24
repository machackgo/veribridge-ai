"""Project Defense — Recruiter Inspection Cards.

A first-class *inspection layer* for Project Defense, parallel to GitHub /
Website / Document inspection. Each card projects one already-built, already-safe
:mod:`defense_answer_evidence_service` object into the recruiter-facing shape
that answers, for one defended question:

1. What question was asked?              → ``question_text`` / ``question_kind``
2. What did the student explain?         → ``safe_answer_summary``
3. Which skill/project claim it supports → ``mapped_skill`` / ``project_title`` / ``claim_type``
4. What safe clip locator exists?        → ``timestamp_label`` / ``clip_*`` / ``clip_available``
5. What corroborates the answer?         → ``corroborates_*`` / ``corroboration_summary``
6. What does the answer demonstrate?     → ``what_this_demonstrates``
7. What does it NOT prove by itself?     → ``limitation``

Framing rule (product): Project Defense is explanation / corroboration evidence.
Nothing here claims verified implementation, runtime behavior, or authorship —
the wording stays conservative ("student explained", "answer supports",
"partially demonstrated"). No numeric scores.

Safety:
    - Input objects are already sanitized (deterministic question text, bounded
      privacy-scrubbed answer summaries, fixed taxonomies). This module adds no
      new answer-derived text beyond what those objects already carry.
    - The clip locator is a time-range + label only. It is threaded from the
      matching :mod:`project_defense_evidence_chips` video chip (matched by
      ``question_id`` then ``related_skill``) and is dropped whenever the card is
      not public-safe — it never carries raw transcript, media paths, or URLs.
    - ``public_safe`` mirrors the source object's ``public_shareable`` + clean
      ``privacy_status``; the fail-closed *public* projection lives in
      ``public_report_safety_service.public_safe_project_defense_inspection``.
    - Pure: no DB, no LLM, no I/O.
"""

from __future__ import annotations

from typing import Any

from app.services.project_defense_evidence_chips import _format_timestamp

__all__ = [
    "build_project_defense_inspection_cards",
    "PROJECT_DEFENSE_INSPECTION_LIMITATION",
    "RECORDING_PLAYABLE_NOTE",
    "RECORDING_EXISTS_NO_PLAYBACK_NOTE",
    "RECORDING_NONE_NOTE",
    "DEFENSE_PRIVATE_WITHHELD_NOTE",
    "TRANSCRIPT_EXCERPT_NOTE",
    "TRANSCRIPT_NONE_NOTE",
]

# Fixed, honest closing limitation shown on every inspection card. Project
# Defense is explanation evidence; it must be read alongside the other proofs.
PROJECT_DEFENSE_INSPECTION_LIMITATION = (
    "Project Defense is explanation evidence. It should be read with GitHub "
    "Proof for implementation, Website Proof for runtime behavior, and Document "
    "Proof for written project evidence."
)

# ── Access notes (recording + transcript) — fixed, safe, human-readable ───────
#
# Never a storage path, signed URL, or internal id — just a short status line the
# card renders when there is no playable URL / no excerpt to show.
RECORDING_PLAYABLE_NOTE = (
    "Your defense recording is available to play here. This recording is private "
    "to you."
)
RECORDING_EXISTS_NO_PLAYBACK_NOTE = (
    "A defense recording exists, but a safe playback link is not available from "
    "this view yet."
)
RECORDING_NONE_NOTE = "No defense recording is available for this answer yet."
# Fixed public withheld message (recording + transcript both private).
DEFENSE_PRIVATE_WITHHELD_NOTE = (
    "Defense recording and transcript are private. Recruiters see only verified "
    "summary and timestamp labels."
)
TRANSCRIPT_EXCERPT_NOTE = (
    "Safe excerpt shown around the cited moment. The full transcript stays "
    "private."
)
TRANSCRIPT_NONE_NOTE = "No transcript excerpt is available for this answer."

_CLEAN_PRIVACY_STATUSES = frozenset({"clean"})

# Statuses that reflect a genuine, targeted explanation (mirrors the answer
# engine's ``_EXPLAINED_STATUSES``). Only these earn "demonstrates" wording that
# names the claim; everything else is framed as project context / not assessed.
_EXPLAINED_STATUSES = frozenset({"Explained with evidence", "Partially explained"})


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


# ── "What this demonstrates" — positive, conservative, keyed by claim type ────
#
# Never claims verified implementation / authorship. A ``{skill}`` placeholder is
# filled with the mapped skill when present.

_DEMONSTRATES_BY_CLAIM: dict[str, str] = {
    "project_architecture": (
        "The student explained the project's architecture in their own words, "
        "demonstrating project understanding and communication."
    ),
    "personal_contribution": (
        "The student described their personal contribution, demonstrating "
        "ownership understanding of this part of the project."
    ),
    "skill_understanding": (
        "The student explained this {skill} claim in response to a project-"
        "specific question, demonstrating understanding and communication of "
        "the skill."
    ),
    "implementation_reasoning": (
        "The student explained the implementation approach behind this claim, "
        "demonstrating reasoning about how the project was built."
    ),
    "runtime_behavior_explanation": (
        "The student explained how the project behaves at runtime, demonstrating "
        "understanding of its live behavior."
    ),
    "document_claim_explanation": (
        "The student explained the attached document's claim in their own words, "
        "demonstrating understanding of the written project evidence."
    ),
    "challenge_resolution": (
        "The student explained a technical challenge and how they addressed it, "
        "demonstrating problem-solving understanding."
    ),
    "tradeoff_reasoning": (
        "The student explained a design tradeoff, demonstrating reasoning about "
        "the decisions behind the project."
    ),
    "evaluation_interpretation": (
        "The student explained how they interpreted the project's evaluation "
        "results, demonstrating understanding of the outcome."
    ),
    "future_improvement": (
        "The student described what they would improve next, demonstrating "
        "reflection on the project."
    ),
}

_DEMONSTRATES_NOT_ASSESSED = (
    "The answer was generic, so it is treated as project context only and this "
    "claim is not assessed by the defense."
)

# An explicit ownership denial is honest, valuable evidence: the candidate
# accurately delimited their contribution. It is presented as exactly that —
# never as an "authorship explanation" and never as suspicious behaviour.
_DEMONSTRATES_OWNERSHIP_DENIED = (
    "The student explicitly clarified that they did not build or contribute to "
    "this project. This is an honest ownership clarification: the answer can "
    "demonstrate understanding or analysis of the project, and it blocks any "
    "candidate implementation or authorship claim for this project."
)


def _what_this_demonstrates(
    claim_type: str, mapped_skill: str | None, status: str, ownership_stance: str = "none"
) -> str:
    if ownership_stance == "denied":
        return _DEMONSTRATES_OWNERSHIP_DENIED
    if status not in _EXPLAINED_STATUSES:
        return _DEMONSTRATES_NOT_ASSESSED
    template = _DEMONSTRATES_BY_CLAIM.get(
        claim_type, _DEMONSTRATES_BY_CLAIM["project_architecture"]
    )
    skill = (mapped_skill or "").strip() or "this"
    return template.replace("{skill}", skill)


# ── Corroboration summary — derived from the boolean flags only ───────────────


def _corroboration_summary(gh: bool, web: bool, doc: bool) -> str:
    present: list[str] = []
    if gh:
        present.append("GitHub Proof (implementation)")
    if web:
        present.append("Website Proof (runtime behavior)")
    if doc:
        present.append("Document Proof (written evidence)")
    if not present:
        return (
            "No attached GitHub, Website, or Document proof corroborates this "
            "defense answer yet — it stands as explanation evidence only."
        )
    if len(present) == 1:
        joined = present[0]
    else:
        joined = ", ".join(present[:-1]) + " and " + present[-1]
    return f"Corroborating defense evidence: {joined} for the same project."


# ── Safe clip locator — a time-range + label only (no content) ────────────────


def _clip_locator(
    item: dict[str, Any], chips_by_question: dict[str, dict[str, Any]], mapped_skill: str | None
) -> dict[str, Any]:
    """Safe timestamp locator for one answered question, if any.

    Matches the answer object to a video evidence chip by ``question_id`` first
    (the chip is anchored to the same question), then falls back to the mapped
    skill. Returns only a label + rounded start/end seconds — never the chip's
    ``short_summary`` (answer content) or any media path.
    """
    chip: dict[str, Any] | None = None
    qid = str(item.get("question_id") or "")
    if qid and qid in chips_by_question:
        chip = chips_by_question[qid]
    elif mapped_skill:
        skill_key = _norm(mapped_skill)
        for candidate in chips_by_question.values():
            if _norm(candidate.get("related_skill")) == skill_key:
                chip = candidate
                break
    if not isinstance(chip, dict):
        return {"clip_available": False, "timestamp_label": None,
                "clip_start_seconds": None, "clip_end_seconds": None}

    try:
        start = float(chip.get("timestamp_start_s"))
    except (TypeError, ValueError):
        start = None
    try:
        end = float(chip.get("timestamp_end_s"))
    except (TypeError, ValueError):
        end = None
    label = str(chip.get("label") or "").strip() or (
        f"Video {_format_timestamp(start)}" if start is not None else None
    )
    return {
        "clip_available": True,
        "timestamp_label": label,
        "clip_start_seconds": round(start, 2) if start is not None else None,
        "clip_end_seconds": round(end, 2) if end is not None else None,
    }


def build_project_defense_inspection_cards(
    *,
    answer_evidence: list[dict[str, Any]] | None,
    video_chips: list[dict[str, Any]] | None = None,
    project_title: str = "",
    only_skill: str | None = None,
    answer_excerpts: dict[str, dict[str, Any]] | None = None,
    recording: dict[str, Any] | None = None,
    is_owner_view: bool = False,
) -> list[dict[str, Any]]:
    """Build owner/private Project Defense inspection cards.

    ``answer_evidence`` is the stored (or report-safe) list of defense answer
    evidence objects; ``video_chips`` are the session's safe
    ``video_evidence_chips``. Mapping is inherited verbatim from each answer
    object — a skill is attached only where that object already mapped it from
    its own targeted question, never from keyword overlap.

    ``only_skill`` scopes the cards to a single claimed skill (used by the
    skill-specific Proof Vault / Skill Report): only cards whose ``mapped_skill``
    matches are kept. Untargeted / generic answers (no mapped skill) never appear
    under a specific skill — they surface only in the unscoped owner view as
    generic project explanation.

    ``answer_excerpts`` (``question_id`` → ``{safe_transcript_excerpt, …}``) and
    ``recording`` (``{available, playback_url}``) are the *authorized, owner-only*
    playable-evidence inputs built by
    :mod:`defense_evidence_access_service`. They are attached to the card only
    when ``is_owner_view`` is set; the public projection re-derives its own cards
    and drops both. ``answer_excerpts`` carries only bounded, sanitized snippets —
    never the raw ``transcript_segments`` array.

    Returns plain dicts matching ``ProjectDefenseInspectionCard``; the public
    fail-closed projection is applied separately.
    """
    if not isinstance(answer_evidence, list) or not answer_evidence:
        return []

    chips_by_question: dict[str, dict[str, Any]] = {}
    for chip in video_chips or []:
        if not isinstance(chip, dict):
            continue
        qid = str(chip.get("question_id") or "")
        if qid and qid not in chips_by_question:
            chips_by_question[qid] = chip

    only_key = _norm(only_skill) if only_skill else None

    cards: list[dict[str, Any]] = []
    for index, item in enumerate(answer_evidence, start=1):
        if not isinstance(item, dict):
            continue
        mapped_skill = item.get("mapped_skill") or None

        if only_key is not None:
            # Skill-scoped view: keep only answers mapped to this exact skill.
            if not mapped_skill or _norm(mapped_skill) != only_key:
                continue

        status = str(item.get("qualitative_status") or "Not explained")
        claim_type = str(item.get("claim_type") or "project_architecture")
        ownership_stance = str(item.get("ownership_stance") or "none")
        contradiction_flag = bool(item.get("contradiction_flag"))
        gh = bool(item.get("corroborates_github"))
        web = bool(item.get("corroborates_website"))
        doc = bool(item.get("corroborates_document"))

        privacy_status = _norm(item.get("privacy_status"))
        public_safe = (
            bool(item.get("public_shareable"))
            and privacy_status in _CLEAN_PRIVACY_STATUSES
            and not item.get("contradiction_flag")
        )

        locator = _clip_locator(item, chips_by_question, mapped_skill)

        # ── Authorized owner playback + safe transcript excerpt ───────────────
        # Attached only in the owner view; the public projection re-derives its
        # own cards and never sees these.
        qid = str(item.get("question_id") or "")
        excerpt_info = (answer_excerpts or {}).get(qid) if (is_owner_view and answer_excerpts) else None

        recording_available = bool(is_owner_view and recording and recording.get("available"))
        playback_url = (
            str(recording.get("playback_url"))
            if is_owner_view and recording and recording.get("playback_url")
            else None
        )
        # A safe media-fragment clip URL only when there is a real playback URL
        # AND a bounded time range — same signed URL, just a #t=start,end anchor.
        clip_playback_url = None
        if playback_url and locator["clip_start_seconds"] is not None:
            start = locator["clip_start_seconds"]
            end = locator["clip_end_seconds"]
            clip_playback_url = (
                f"{playback_url}#t={start},{end}" if end is not None else f"{playback_url}#t={start}"
            )

        if playback_url:
            recording_access_note = RECORDING_PLAYABLE_NOTE
        elif recording_available:
            recording_access_note = RECORDING_EXISTS_NO_PLAYBACK_NOTE
        else:
            recording_access_note = RECORDING_NONE_NOTE

        if excerpt_info:
            transcript_excerpt_available = True
            safe_transcript_excerpt = str(excerpt_info.get("safe_transcript_excerpt") or "") or None
            transcript_excerpt_start_label = excerpt_info.get("transcript_excerpt_start_label")
            transcript_excerpt_end_label = excerpt_info.get("transcript_excerpt_end_label")
            transcript_access_note = TRANSCRIPT_EXCERPT_NOTE
        else:
            transcript_excerpt_available = False
            safe_transcript_excerpt = None
            transcript_excerpt_start_label = None
            transcript_excerpt_end_label = None
            transcript_access_note = TRANSCRIPT_NONE_NOTE

        cards.append(
            {
                "evidence_id_safe": str(
                    item.get("evidence_id_safe") or f"defense-inspection-{index}"
                ),
                "question_text": str(item.get("question_text") or ""),
                "question_kind": str(item.get("question_kind") or "unknown_or_generic"),
                "project_title": str(item.get("project_title") or project_title or ""),
                "mapped_skill": str(mapped_skill) if mapped_skill else None,
                "claim_type": claim_type,
                "answer_purpose": str(item.get("answer_purpose") or "unknown_or_generic"),
                "evidence_role": str(item.get("evidence_role") or "insufficient_or_generic"),
                "qualitative_status": status,
                "safe_answer_summary": str(item.get("safe_answer_summary") or ""),
                "evidence_basis_chips": [
                    str(c) for c in (item.get("evidence_basis_chips") or [])
                ][:8],
                "timestamp_label": locator["timestamp_label"],
                "clip_start_seconds": locator["clip_start_seconds"],
                "clip_end_seconds": locator["clip_end_seconds"],
                "clip_available": locator["clip_available"],
                "corroborates_github": gh,
                "corroborates_website": web,
                "corroborates_document": doc,
                # Candidate ownership stance + provenance-risk flag are carried
                # through so downstream claim synthesis can never mistake an
                # explicit denial (or a needs-review answer) for authorship
                # evidence.
                "ownership_stance": ownership_stance,
                "contradiction_flag": contradiction_flag,
                "corroboration_summary": _corroboration_summary(gh, web, doc),
                "what_this_demonstrates": _what_this_demonstrates(
                    claim_type, mapped_skill, status, ownership_stance
                ),
                "limitation": str(item.get("limitation") or "")
                or PROJECT_DEFENSE_INSPECTION_LIMITATION,
                "public_safe": public_safe,
                "withheld_reason": None,
                # Playable evidence + safe transcript excerpt (owner-only).
                "video_available": recording_available,
                "video_playback_url": playback_url,
                "clip_playback_url": clip_playback_url,
                "transcript_excerpt_available": transcript_excerpt_available,
                "safe_transcript_excerpt": safe_transcript_excerpt,
                "transcript_excerpt_start_label": transcript_excerpt_start_label,
                "transcript_excerpt_end_label": transcript_excerpt_end_label,
                "transcript_access_note": transcript_access_note,
                "recording_access_note": recording_access_note,
                "is_private_owner_view": is_owner_view,
                "is_public_share_safe": public_safe,
            }
        )
    return cards
