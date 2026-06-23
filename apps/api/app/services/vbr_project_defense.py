"""Phase 1 — Individual Project Defense service.

Deterministic, non-LLM logic for:
  - creating a project-defense project identity (vbr_projects + metadata)
  - generating deterministic defense questions (vbr_session_questions)
  - saving manual/pasted defense answers as a transcript + segments
    (vbr_transcripts / vbr_transcript_segments)
  - running deterministic transcript analysis and storing the result in
    vbr_verification_sessions.telemetry.project_defense_analysis

Phase 1 is individual-student proof only. Team proof, live screen/camera
recording, speaker diarization, and final public report publishing are out
of scope.

``vbr_projects.repo_url`` is required by the existing schema (NOT NULL).
Phase 1 therefore requires a ``repo_url`` either directly or derived from an
attached GitHub proof — see ``_resolve_repo_url_and_proof``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.vbr_project_defense import (
    ProjectDefenseCreateRequest,
    SubmitDefenseAnswersRequest,
)
from app.services.github_evidence_service import parse_github_repo_url
from app.services.github_proof_service import GitHubProofNotFoundError, GitHubProofService
from app.services.optional_evidence_service import OptionalEvidenceService
from app.services.project_defense_analysis_service import analyze_defense_transcript
from app.services.project_defense_evidence_chips import build_evidence_chips
from app.services.website_proof_summary_service import get_website_proof_summary
from app.services.vbr_question_generation import (
    _create_session,
    _delete_session_questions,
    _insert_questions,
    get_active_session,
    list_session_questions,
)
from app.services.vbr_session_recording import update_session_telemetry

_PROJECTS_TABLE = "vbr_projects"
_TRANSCRIPTS_TABLE = "vbr_transcripts"
_TRANSCRIPT_SEGMENTS_TABLE = "vbr_transcript_segments"
_QUESTIONS_TABLE = "vbr_session_questions"

_MAX_SKILL_QUESTIONS = 5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(text: str | None, max_len: int = 300) -> str:
    if not text:
        return ""
    return str(text)[:max_len]


def _clean_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            out.append(text)
    return list(dict.fromkeys(out))


# ── Project identity creation ────────────────────────────────────────────────


def _resolve_repo_url_and_proof(
    db: Any, user_id: str, body: ProjectDefenseCreateRequest
) -> tuple[str, dict[str, Any] | None]:
    """Resolve ``repo_url`` for the new project.

    Priority: explicit ``body.repo_url`` > repo_url from an attached GitHub
    proof > ``body.attached_proofs.repo_url`` fallback. Raises ``ValueError``
    with a known code if no repo_url can be resolved or the referenced GitHub
    proof is not owned by ``user_id``.
    """
    repo_url = (body.repo_url or "").strip()
    github_summary: dict[str, Any] | None = None

    github_proof_id = (body.attached_proofs.github_proof_id or "").strip() or None
    if github_proof_id:
        try:
            proof = GitHubProofService(db).get_github_proof(user_id, github_proof_id)
        except GitHubProofNotFoundError as exc:
            raise ValueError("github_proof_not_found") from exc

        if not repo_url:
            repo_url = (proof.repo_url or "").strip()

        github_summary = {
            "github_proof_id": github_proof_id,
            "repo_url": proof.repo_url,
            "repo_owner": proof.repo_owner,
            "repo_name": proof.repo_name,
            "status": proof.status,
            "detected_skills": _clean_list(proof.detected_skills),
            "public_safe_summary": _truncate(proof.public_safe_summary or "", 300),
        }

    if not repo_url:
        repo_url = (body.attached_proofs.repo_url or "").strip()

    if not repo_url:
        raise ValueError("repo_url_required")

    return repo_url, github_summary


def _validate_skill_pipeline_ownership(pipeline_db: Any, user_id: str, skill_pipeline_ids: list[str]) -> None:
    """Validate that every ``skill_pipeline_ids`` entry belongs to ``user_id``.

    Raises ``ValueError("skill_pipeline_not_found")`` if any ID is missing or
    owned by another user.
    """
    from app.services.skill_evidence_pipeline_service import (
        PipelineNotFoundError,
        SkillEvidencePipelineService,
    )

    svc = SkillEvidencePipelineService(pipeline_db)
    for pipeline_id in skill_pipeline_ids:
        try:
            svc.get_pipeline(pipeline_id, user_id)
        except PipelineNotFoundError as exc:
            raise ValueError("skill_pipeline_not_found") from exc


def _safe_document_skills(row: dict[str, Any]) -> list[str]:
    """Safe, deduped skill names a document *explicitly* evidences.

    Read only from the analyzer's structured ``evidence_objects`` (skill names
    only — never raw snippets, page text, file paths, or numeric scores). When a
    document has no structured skill evidence this returns ``[]`` so the report
    treats it as project-level context rather than per-skill proof.
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in row.get("evidence_objects") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("skill_name") or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _document_summaries(db: Any, user_id: str, document_evidence_ids: list[str]) -> list[dict[str, Any]]:
    """Return safe summaries for attached document proofs.

    Raises ``ValueError("document_evidence_not_found")`` if any ID is not
    owned by ``user_id``.
    """
    svc = OptionalEvidenceService(db)
    summaries: list[dict[str, Any]] = []
    for doc_id in document_evidence_ids:
        doc_id = str(doc_id).strip()
        if not doc_id:
            continue
        row = svc.get_by_id(user_id=user_id, evidence_id=doc_id)
        if row is None:
            raise ValueError("document_evidence_not_found")
        analysis_json = row.get("analysis_json") or {}
        title = analysis_json.get("title") or row.get("title") or row.get("file_path") or "Document"
        summaries.append(
            {
                "document_evidence_id": doc_id,
                "title": _truncate(str(title), 120),
                "source_type": row.get("source_type"),
                "status": row.get("status"),
                # Safe skill names the analyzer matched in this document. Used by
                # the report to map the document to ONLY these skills (never to
                # every claimed skill); empty ⇒ project-level evidence.
                "skills": _safe_document_skills(row),
            }
        )
    return summaries


def _website_proof_summaries(db: Any, user_id: str, website_proof_session_ids: list[str]) -> list[dict[str, Any]]:
    """Return safe summaries for attached Website Proof sessions.

    Raises ``ValueError("website_proof_not_found")`` if any ID is not owned
    by ``user_id`` (or has no completed analysis).
    """
    summaries: list[dict[str, Any]] = []
    for proof_session_id in website_proof_session_ids:
        proof_session_id = str(proof_session_id).strip()
        if not proof_session_id:
            continue
        summary = get_website_proof_summary(db, user_id, proof_session_id)
        if summary is None:
            raise ValueError("website_proof_not_found")
        summaries.append(summary)
    return summaries


def create_project_defense(
    db: Any, pipeline_db: Any, user_id: str, body: ProjectDefenseCreateRequest
) -> dict[str, Any]:
    """Create a Phase 1 individual Project Defense project identity.

    Stores only IDs and safe summaries of attached proofs in
    ``vbr_projects.metadata.attached_proofs`` — never raw proof payloads.

    Raises ``ValueError("website_proof_not_found")`` if any
    ``website_proof_session_ids`` entry is not owned by ``user_id``, and
    ``ValueError("skill_pipeline_not_found")`` if any ``skill_pipeline_ids``
    entry is not owned by ``user_id``.
    """
    repo_url, github_summary = _resolve_repo_url_and_proof(db, user_id, body)

    repo_ref = parse_github_repo_url(repo_url)
    if repo_ref is None:
        raise ValueError("invalid_github_repo_url")
    repo_full_name = f"{repo_ref.owner}/{repo_ref.repo}"

    website_proof_session_ids = _clean_list(body.attached_proofs.website_proof_session_ids)
    website_proof_summaries = _website_proof_summaries(db, user_id, website_proof_session_ids)

    skill_pipeline_ids = _clean_list(body.attached_proofs.skill_pipeline_ids)
    if skill_pipeline_ids:
        _validate_skill_pipeline_ownership(pipeline_db, user_id, skill_pipeline_ids)

    document_summaries = _document_summaries(db, user_id, body.attached_proofs.document_evidence_ids)

    attached_proofs: dict[str, Any] = {}
    if github_summary:
        attached_proofs["github_proof"] = github_summary
    elif body.attached_proofs.github_proof_id:
        attached_proofs["github_proof_id"] = body.attached_proofs.github_proof_id

    if website_proof_summaries:
        attached_proofs["website_proofs"] = website_proof_summaries

    if document_summaries:
        attached_proofs["documents"] = document_summaries

    if skill_pipeline_ids:
        attached_proofs["skill_pipeline_ids"] = skill_pipeline_ids

    now = _now()
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "user_id": user_id,
        "title": body.title.strip(),
        "repo_url": repo_url,
        "repo_full_name": repo_full_name,
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": {
            "description": body.description.strip(),
            "claimed_skills": _clean_list(body.claimed_skills),
            "student_role": body.student_role.strip(),
            "individual_project_only": True,
            "attached_proofs": attached_proofs,
            "phase": "project_defense_mvp_v1",
        },
        "created_at": now,
        "updated_at": now,
    }

    if isinstance(db, dict):
        db.setdefault(_PROJECTS_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_PROJECTS_TABLE).insert(row).execute()
    inserted = getattr(result, "data", []) or []
    if not inserted:
        raise RuntimeError("vbr_projects insert returned no data.")
    return inserted[0]


# ── Deterministic defense question generation ───────────────────────────────


def build_defense_question_specs(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Build deterministic project-defense question specs from project context."""
    metadata = project.get("metadata") or {}
    title = project.get("title") or "this project"
    claimed_skills = _clean_list(metadata.get("claimed_skills") or [])
    student_role = str(metadata.get("student_role") or "").strip()
    attached = metadata.get("attached_proofs") or {}
    github_proof = attached.get("github_proof") if isinstance(attached, dict) else None

    specs: list[dict[str, Any]] = []

    specs.append(
        {
            "question_text": f'Explain the main architecture of "{title}" and why you designed it this way.',
            "target_ref": {"type": "project_defense", "kind": "architecture"},
        }
    )

    if student_role:
        specs.append(
            {
                "question_text": (
                    f'You described your role as: "{_truncate(student_role, 200)}". '
                    f'Walk through the part of "{title}" you personally built and explain how it reflects this role.'
                ),
                "target_ref": {"type": "project_defense", "kind": "contribution"},
            }
        )
    else:
        specs.append(
            {
                "question_text": f'Walk through the part of "{title}" you personally built and explain your specific contribution.',
                "target_ref": {"type": "project_defense", "kind": "contribution"},
            }
        )

    for skill in claimed_skills[:_MAX_SKILL_QUESTIONS]:
        if isinstance(github_proof, dict) and github_proof.get("repo_url"):
            specs.append(
                {
                    "question_text": (
                        f"Explain how this GitHub repository ({github_proof['repo_url']}) "
                        f"supports your claimed skill in {skill}."
                    ),
                    "target_ref": {"type": "project_defense", "kind": "skill_repo_link", "skill": skill},
                }
            )
        else:
            specs.append(
                {
                    "question_text": f'Explain how "{title}" demonstrates your claimed skill in {skill}.',
                    "target_ref": {"type": "project_defense", "kind": "skill_link", "skill": skill},
                }
            )

    website_proofs = attached.get("website_proofs") if isinstance(attached, dict) else None
    if isinstance(website_proofs, list) and website_proofs:
        specs.append(
            {
                "question_text": "Show or describe how the live/demo proof for this project connects to your implementation.",
                "target_ref": {"type": "project_defense", "kind": "live_demo_link"},
            }
        )

    documents = attached.get("documents") if isinstance(attached, dict) else None
    if isinstance(documents, list) and documents:
        first_doc = documents[0]
        doc_title = first_doc.get("title") or "your submitted document"
        specs.append(
            {
                "question_text": f'Explain how the document "{doc_title}" relates to "{title}" and what it demonstrates.',
                "target_ref": {
                    "type": "project_defense",
                    "kind": "document_link",
                    "document_evidence_id": first_doc.get("document_evidence_id"),
                },
            }
        )

    specs.append(
        {
            "question_text": "Explain one technical challenge you faced while building this project and how you solved it.",
            "target_ref": {"type": "project_defense", "kind": "challenge"},
        }
    )

    specs.append(
        {
            "question_text": "What would you improve next if you continued working on this project?",
            "target_ref": {"type": "project_defense", "kind": "improvement"},
        }
    )

    return specs


def generate_defense_questions(db: Any, project: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Create/reuse a verification session and save deterministic defense questions.

    Raises ``ValueError("active_session_already_started")`` if the project's
    active session has already progressed beyond ``created`` (e.g. a
    walkthrough recording is in progress).
    """
    project_id = str(project["id"])

    session = get_active_session(db, project_id)
    if session is not None and session.get("status") != "created":
        raise ValueError("active_session_already_started")
    if session is None:
        session = _create_session(db, project_id)

    _delete_session_questions(db, session["id"])

    specs = build_defense_question_specs(project)
    now = _now()
    rows = [
        {
            "id": str(uuid4()),
            "session_id": session["id"],
            "sort_order": sort_order,
            "question_text": spec["question_text"],
            "target_ref": spec["target_ref"],
            "claim_ids": [],
            "asked_at_s": None,
            "answered": False,
            "created_at": now,
        }
        for sort_order, spec in enumerate(specs)
    ]

    inserted = _insert_questions(db, rows)
    return str(session["id"]), inserted


# ── Manual transcript + analysis ─────────────────────────────────────────────


def _upsert_transcript(db: Any, session_id: str, full_text: str) -> dict[str, Any]:
    now = _now()
    if isinstance(db, dict):
        store = db.setdefault(_TRANSCRIPTS_TABLE, {})
        existing = next((r for r in store.values() if str(r.get("session_id")) == session_id), None)
        if existing is not None:
            existing["full_text"] = full_text
            existing["provider"] = "manual"
            existing["language"] = "en"
            existing["raw"] = {}
            return existing
        row = {
            "id": str(uuid4()),
            "session_id": session_id,
            "provider": "manual",
            "language": "en",
            "full_text": full_text,
            "raw": {},
            "created_at": now,
        }
        store[row["id"]] = row
        return row

    result = (
        db.table(_TRANSCRIPTS_TABLE)
        .upsert(
            {
                "session_id": session_id,
                "provider": "manual",
                "language": "en",
                "full_text": full_text,
                "raw": {},
            },
            on_conflict="session_id",
        )
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _replace_transcript_segments(db: Any, transcript_id: str, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        store = db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {})
        for key in [k for k, row in store.items() if str(row.get("transcript_id")) == transcript_id]:
            del store[key]
        now = _now()
        rows: list[dict[str, Any]] = []
        for seg in segments:
            row = {"id": str(uuid4()), "transcript_id": transcript_id, "created_at": now, **seg}
            store[row["id"]] = row
            rows.append(row)
        return rows

    db.table(_TRANSCRIPT_SEGMENTS_TABLE).delete().eq("transcript_id", transcript_id).execute()
    if not segments:
        return []
    rows_to_insert = [{"transcript_id": transcript_id, **seg} for seg in segments]
    result = db.table(_TRANSCRIPT_SEGMENTS_TABLE).insert(rows_to_insert).execute()
    return getattr(result, "data", []) or []


def _update_project_metadata(db: Any, project: dict[str, Any], patch: dict[str, Any]) -> None:
    """Merge ``patch`` into ``vbr_projects.metadata`` for ``project`` and persist it."""
    metadata = {**(project.get("metadata") or {}), **patch}
    now = _now()
    if isinstance(db, dict):
        row = db.setdefault(_PROJECTS_TABLE, {}).get(str(project["id"]))
        if row is not None:
            row["metadata"] = metadata
            row["updated_at"] = now
    else:
        db.table(_PROJECTS_TABLE).update({"metadata": metadata, "updated_at": now}).eq(
            "id", project["id"]
        ).execute()
    project["metadata"] = metadata


_AUTO_TRANSCRIPT_PROVIDERS = {"openai", "local_whisper"}


def _get_auto_generated_transcript(
    db: Any, session_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Return an existing auto-generated transcript (and its segments) for ``session_id``.

    Only matches transcripts produced by ``vbr_transcription.transcribe_session``
    (``provider`` in ``_AUTO_TRANSCRIPT_PROVIDERS``) — never a manually pasted
    transcript (``provider == "manual"``).
    """
    if isinstance(db, dict):
        transcript = next(
            (
                row
                for row in db.setdefault(_TRANSCRIPTS_TABLE, {}).values()
                if str(row.get("session_id")) == session_id
                and row.get("provider") in _AUTO_TRANSCRIPT_PROVIDERS
            ),
            None,
        )
        if transcript is None or not (transcript.get("full_text") or "").strip():
            return None
        transcript_id = str(transcript["id"])
        segments = [
            row
            for row in db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {}).values()
            if str(row.get("transcript_id")) == transcript_id
        ]
        return transcript, segments

    result = (
        db.table(_TRANSCRIPTS_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    transcript = getattr(result, "data", None) if result is not None else None
    if not transcript or transcript.get("provider") not in _AUTO_TRANSCRIPT_PROVIDERS:
        return None
    if not (transcript.get("full_text") or "").strip():
        return None

    seg_result = (
        db.table(_TRANSCRIPT_SEGMENTS_TABLE)
        .select("*")
        .eq("transcript_id", transcript["id"])
        .execute()
    )
    segments = getattr(seg_result, "data", []) or []
    return transcript, segments


def _mark_questions_answered(db: Any, question_ids: set[str]) -> None:
    ids = [qid for qid in question_ids if qid]
    if not ids:
        return
    if isinstance(db, dict):
        store = db.setdefault(_QUESTIONS_TABLE, {})
        for qid in ids:
            row = store.get(qid)
            if row is not None:
                row["answered"] = True
        return
    db.table(_QUESTIONS_TABLE).update({"answered": True}).in_("id", ids).execute()


def submit_defense_answers(
    db: Any, session: dict[str, Any], project: dict[str, Any], body: SubmitDefenseAnswersRequest
) -> dict[str, Any]:
    """Save pasted/manual defense answers as a transcript + segments and analyze.

    If neither ``body.answers`` nor ``body.combined_text`` contains any
    non-empty text, falls back to an existing auto-generated transcript (from
    ``vbr_transcription.transcribe_session``) as the analysis source, if one
    exists. Raises ``ValueError("no_answers_provided")`` if neither manual
    text nor an auto-generated transcript is available.
    """
    session_id = str(session["id"])
    questions = list_session_questions(db, session_id)
    questions_by_id = {str(q["id"]): q for q in questions}

    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    answered_question_ids: set[str] = set()

    for item in body.answers:
        answer_text = (item.answer_text or "").strip()
        if not answer_text:
            continue
        question = questions_by_id.get(str(item.question_id)) if item.question_id else None
        question_text = question.get("question_text") if question else None
        if question_text:
            text_parts.append(f"Q: {question_text}\nA: {answer_text}")
        else:
            text_parts.append(answer_text)

        idx = len(segments)
        segments.append(
            {
                "question_id": str(question["id"]) if question else None,
                "start_s": float(idx),
                "end_s": float(idx + 1),
                "text": answer_text,
            }
        )
        if question is not None:
            answered_question_ids.add(str(question["id"]))

    combined_text = (body.combined_text or "").strip()
    if combined_text:
        text_parts.append(combined_text)
        idx = len(segments)
        segments.append(
            {
                "question_id": None,
                "start_s": float(idx),
                "end_s": float(idx + 1),
                "text": combined_text,
            }
        )

    # Independent of which transcript source feeds the textual analysis
    # below, video evidence chips are always built from the real,
    # auto-generated video transcript (with meaningful timestamps) if one
    # exists — manual-answer segments use synthetic start_s/end_s indices.
    auto_video_transcript = _get_auto_generated_transcript(db, session_id)

    if segments:
        full_text = "\n\n".join(text_parts)
        transcript = _upsert_transcript(db, session_id, full_text)
        transcript_id = str(transcript["id"])
        saved_segments = _replace_transcript_segments(db, transcript_id, segments)
        _mark_questions_answered(db, answered_question_ids)
    else:
        if auto_video_transcript is None:
            raise ValueError("no_answers_provided")
        auto_transcript, saved_segments = auto_video_transcript
        transcript_id = str(auto_transcript["id"])
        full_text = auto_transcript.get("full_text") or ""

    metadata = project.get("metadata") or {}
    claimed_skills = _clean_list(metadata.get("claimed_skills") or [])
    attached = metadata.get("attached_proofs") or {}
    github_proof = attached.get("github_proof") if isinstance(attached, dict) else None
    github_summary = ""
    if isinstance(github_proof, dict):
        github_summary = str(github_proof.get("public_safe_summary") or "")

    analysis_result = analyze_defense_transcript(
        transcript_text=full_text,
        claimed_skills=claimed_skills,
        github_summary=github_summary,
    )
    analysis_dict = asdict(analysis_result)

    telemetry_update: dict[str, Any] = {"project_defense_analysis": analysis_dict}
    if auto_video_transcript is not None:
        # A real video transcript is available — (re)compute chips from it.
        # Note: if this run also persists manual answers (below),
        # _upsert_transcript may overwrite this transcript's row in place
        # (same session_id, single transcript per session), so the segments
        # captured here must be used now rather than re-fetched later.
        video_evidence_chips = build_evidence_chips(auto_video_transcript[1], claimed_skills, questions)
        telemetry_update["video_evidence_chips"] = video_evidence_chips
    else:
        # No (current) auto-generated video transcript — preserve any
        # previously computed chips rather than erasing them.
        video_evidence_chips = list((session.get("telemetry") or {}).get("video_evidence_chips") or [])

    update_session_telemetry(db, session, telemetry_update, merge=True)
    _update_project_metadata(db, project, {"project_defense_status": "analyzed"})

    return {
        "transcript_id": transcript_id,
        "segment_count": len(saved_segments),
        "answered_question_count": len(answered_question_ids),
        "analysis": analysis_dict,
        "video_evidence_chips": video_evidence_chips,
    }
