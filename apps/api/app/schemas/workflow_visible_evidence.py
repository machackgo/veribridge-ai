"""Schemas for Workflow Visible Evidence — DOM/text snapshots captured during recording.

These schemas cover:
  - The batch-ingest payload sent by the browser extension / recording client.
  - The DB row shape (internal).
  - The public-safe summary returned to the student for debugging.
  - The structured observations extracted for workflow analysis.

Privacy contract:
  - Raw visible_text_blocks / result_like_blocks are student-private only.
  - Recruiter-facing surfaces only receive the processed WorkflowAnalysisResponse;
    they never see the raw VisibleEvidenceSummary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums / Literals
# ---------------------------------------------------------------------------

VisibleEventType = Literal[
    "page_load",
    "click",
    "input_change",
    "file_upload",
    "form_submit",
    "dom_snapshot",
    "result_detected",
    "recording_end",
]

VisibleEvidenceStatus = Literal[
    "not_captured",   # old recording — extension did not send visible evidence
    "partial",        # some events captured but incomplete (e.g. no result snapshot)
    "available",      # full visible evidence captured; result values may be extractable
]


# ---------------------------------------------------------------------------
# Ingest: what the extension sends to the backend
# ---------------------------------------------------------------------------

class FileUploadMeta(BaseModel):
    """Safe metadata about a file upload — no local path, no private data."""
    file_category: str = Field(
        default="unknown",
        description="image | audio | video | document | other",
    )
    file_extension: str = Field(
        default="",
        description="Extension without leading dot, e.g. 'jpg', 'pdf'",
    )
    file_name_masked: str | None = Field(
        default=None,
        description="Hashed or masked filename — never the full local path",
    )


class VisibleEvidenceEventInput(BaseModel):
    """One DOM-snapshot / interaction event sent by the recording extension."""

    timestamp_ms: int | None = Field(
        default=None,
        description="Milliseconds since recording started",
    )
    event_type: VisibleEventType = Field(
        description="Classification of this capture moment",
    )
    event_id: str | None = Field(
        default=None,
        description="Optional correlation ID (matches workflow_events.id if available)",
    )
    url: str = Field(
        default="",
        description="Current page URL at time of capture",
    )
    page_title: str = Field(
        default="",
        description="Document title at time of capture",
    )
    # Visible text — already sanitized by extension before sending
    visible_text_blocks: list[str] = Field(
        default_factory=list,
        description=(
            "Visible text blocks from the page at this moment. "
            "Must be sanitized by the extension before sending: no passwords, API keys, "
            "tokens, local paths, or sensitive personal data."
        ),
        max_length=200,   # cap items; extension MAX_VE_BLOCKS=120, keep headroom
    )
    result_like_blocks: list[str] = Field(
        default_factory=list,
        description=(
            "Text blocks near result/output/prediction keywords. "
            "Extension should pre-filter for relevance."
        ),
        max_length=100,   # raised to 100 to allow headroom above extension's 30-item slice
    )
    input_snapshot: dict = Field(
        default_factory=dict,
        description=(
            "Sanitized form input values at this moment. "
            "Password and sensitive fields must be excluded by the extension."
        ),
    )
    action_snapshot: dict = Field(
        default_factory=dict,
        description="Clicked element metadata (text, aria-label, type, id) for click events.",
    )
    file_upload_meta: FileUploadMeta | None = Field(
        default=None,
        description="File metadata for file_upload events. Never include local paths.",
    )
    # Graphical rendering detection — captured by the extension
    canvas_count: int | None = Field(
        default=None,
        description="Number of <canvas> elements on the page at capture time.",
    )
    svg_count: int | None = Field(
        default=None,
        description="Number of <svg> elements on the page at capture time.",
    )


class VisibleEvidenceBatchRequest(BaseModel):
    """Batch of visible evidence events sent by the extension at end of recording."""
    events: list[VisibleEvidenceEventInput] = Field(
        default_factory=list,
        description="Ordered list of capture events from the recording session.",
        max_length=500,   # safety cap
    )


# ---------------------------------------------------------------------------
# Extracted observations (internal — used by workflow analysis)
# ---------------------------------------------------------------------------

class ExtractedResultValue(BaseModel):
    """A single extracted result/prediction value from visible text."""
    label: str
    value: str
    unit: str = ""          # e.g. "%", "score", ""
    raw_text: str = ""      # the original text fragment it came from
    source: str = "dom"     # dom | result_panel | table_row


class ExtractedObservations(BaseModel):
    """Structured observations extracted from the visible evidence events.

    Fed into workflow-analysis-v4 to populate detected_result_values and
    enrich the Observed Demonstration timeline.

    Status fields:
      visible_evidence_status  — DOM text capture (available/partial/not_captured)
      dom_evidence_status      — explicit alias for visible_evidence_status (clearer naming)
      visual_frame_analysis_status — OCR/frame analysis; always "not_available" until implemented
      ocr_status               — same as visual_frame_analysis_status

    Graphical rendering:
      has_graphical_rendering  — True when canvas or SVG elements were detected
      graphical_rendering_note — Human-readable note when outputs may be in charts/canvas/SVG
      top_result_snippets      — Top visible result-like text snippets for UI display
    """
    observed_inputs: list[str] = Field(default_factory=list)
    observed_actions: list[str] = Field(default_factory=list)
    observed_outputs: list[str] = Field(default_factory=list)
    detected_result_values: list[ExtractedResultValue] = Field(default_factory=list)
    demonstrated_features: list[str] = Field(default_factory=list)
    skill_support_reasoning: list[str] = Field(default_factory=list)
    # DOM capture status — what the browser extension collected
    visible_evidence_status: VisibleEvidenceStatus = "not_captured"
    dom_evidence_status: VisibleEvidenceStatus = "not_captured"
    # OCR/frame analysis — always not_available until implemented
    visual_frame_analysis_status: str = "not_available"
    ocr_status: str = "not_available"
    # Graphical rendering detection
    has_graphical_rendering: bool = False
    graphical_rendering_note: str | None = None
    # Top result snippets (for UI surface — limited, safe to display)
    top_result_snippets: list[str] = Field(default_factory=list)
    # Page context summary (DOM-derived description of the visited site)
    page_context_summary: str | None = None
    # Counts
    event_count: int = 0
    result_event_count: int = 0
    file_upload_count: int = 0
    form_submit_count: int = 0
    # Domain filtering: rows excluded because they belonged to a different domain.
    # Safe to surface as "N unrelated browser events filtered" without leaking titles.
    filtered_unrelated_count: int = 0


# ---------------------------------------------------------------------------
# Student-facing summary (GET endpoint — debug only, never public to recruiter)
# ---------------------------------------------------------------------------

class VisibleEvidenceSummaryEvent(BaseModel):
    """Public-safe summary of one captured event."""
    event_type: str
    timestamp_ms: int | None
    page_title: str
    result_block_count: int
    visible_block_count: int
    has_file_upload: bool
    privacy_flags: list[str]


class VisibleEvidenceSummaryResponse(BaseModel):
    """Student/debug summary of all captured visible evidence for a session.

    NOT exposed to recruiters. Only used by student dashboard debugging and
    VeriBridge admin tools.
    """
    proof_session_id: str
    event_count: int
    result_event_count: int
    file_upload_count: int
    visible_evidence_status: VisibleEvidenceStatus
    dom_evidence_status: VisibleEvidenceStatus = "not_captured"
    visual_frame_analysis_status: str = "not_available"
    ocr_status: str = "not_available"
    has_graphical_rendering: bool = False
    graphical_rendering_note: str | None = None
    top_result_snippets: list[str] = Field(default_factory=list)
    page_context_summary: str | None = None
    events_summary: list[VisibleEvidenceSummaryEvent]
    extracted_observations: ExtractedObservations
    filtered_unrelated_count: int = Field(
        default=0,
        description=(
            "Number of captured events excluded because they belonged to a domain "
            "other than the proof target (e.g. Supabase, GitHub, localhost). "
            "Safe to surface as 'N unrelated browser events filtered'."
        ),
    )
    privacy_note: str = (
        "This summary is only visible to the student who owns this session. "
        "Recruiters see only the processed, public-safe workflow analysis summary."
    )
