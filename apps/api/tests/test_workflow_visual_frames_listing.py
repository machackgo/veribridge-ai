"""Tests for the owner-safe captured-frame listing endpoint.

Coverage:
1. Owner listing returns safe frame descriptors (id / type / timestamp / label /
   has_thumbnail) ordered by the query, capped by the response limit.
2. The response NEVER contains storage paths, raw bytes, OCR text, or
   visual-reasoning JSON — only the safe descriptor fields.
3. The query is always filtered to the authenticated caller's own user_id, so a
   foreign session id can only ever yield an empty list (no existence leak).
4. A database error fails soft to an empty list — never a 500 with internals.
5. ``has_thumbnail`` is a presence bool derived from the storage-path column;
   the path itself never appears in the response.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.workflow_visual_frames import (
    SessionVisualFramesResponse,
    list_session_visual_frames,
)

USER_ID = "00000000-0000-0000-0000-000000000099"
SESSION_ID = "session-abc-123"


def _make_db(
    rows: list[dict[str, Any]] | Exception, *, owned: bool = True
) -> MagicMock:
    """Build a db mock with two independent table chains.

    The listing endpoint now fails closed through an ownership gate before it
    ever reads frames, so the mock must model BOTH accesses separately:

      1. ``extension_proof_sessions`` — the owner gate
         (``.select().eq(user_id).eq(id).maybe_single().execute()``).  When
         ``owned`` is True it returns the caller's own session row so the gate
         passes; when False it returns no row so the gate raises 404.
      2. ``workflow_visual_frame_evidence`` — the frame listing query
         (``.select().eq(user_id).eq(proof_session_id).order().limit().execute()``).

    Routing each table to its own mock (instead of a single shared
    ``db.table.return_value``) lets each query's scoping be asserted in
    isolation, so the ownership gate can no longer mask the frame-query scope.
    """
    db = MagicMock()

    # ── Ownership gate: extension_proof_sessions ──────────────────────────────
    sessions_tbl = MagicMock(name="extension_proof_sessions")
    owner_exec = (
        sessions_tbl.select.return_value
        .eq.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute
    )
    owner_resp = MagicMock()
    owner_resp.data = {"id": SESSION_ID, "user_id": USER_ID} if owned else None
    owner_exec.return_value = owner_resp

    # ── Frame listing: workflow_visual_frame_evidence ─────────────────────────
    frames_tbl = MagicMock(name="workflow_visual_frame_evidence")
    frame_exec = (
        frames_tbl.select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute
    )
    if isinstance(rows, Exception):
        frame_exec.side_effect = rows
    else:
        resp = MagicMock()
        resp.data = rows
        frame_exec.return_value = resp

    tables = {
        "extension_proof_sessions": sessions_tbl,
        "workflow_visual_frame_evidence": frames_tbl,
    }
    db.table.side_effect = lambda name: tables[name]
    # Expose the per-table mocks so tests can assert each query's scoping.
    db.sessions_tbl = sessions_tbl
    db.frames_tbl = frames_tbl
    return db


def test_owner_listing_returns_safe_descriptors():
    rows = [
        {
            "id": "frame-1",
            "frame_type": "video_keyframe",
            "timestamp_ms": 0,
            "frame_thumbnail_storage_path": f"frame-evidence/{USER_ID}/{SESSION_ID}/frame-1_thumb.jpg",
        },
        {
            "id": "frame-2",
            "frame_type": "after_click",
            "timestamp_ms": 65_000,
            "frame_thumbnail_storage_path": None,
        },
    ]
    result = list_session_visual_frames(SESSION_ID, user_id=USER_ID, db=_make_db(rows))

    assert isinstance(result, SessionVisualFramesResponse)
    assert result.session_id == SESSION_ID
    assert result.frame_count == 2
    first, second = result.frames
    assert first.frame_id == "frame-1"
    assert first.frame_type == "video_keyframe"
    assert first.timestamp_label == "0:00"
    assert first.has_thumbnail is True
    assert second.frame_id == "frame-2"
    assert second.timestamp_label == "1:05"
    assert second.has_thumbnail is False


def test_response_never_contains_storage_paths():
    rows = [
        {
            "id": "frame-1",
            "frame_type": "video_keyframe",
            "timestamp_ms": 1_000,
            "frame_thumbnail_storage_path": "frame-evidence/secret/path_thumb.jpg",
            # Extra private columns must never survive into the response model.
            "frame_storage_path": "frame-evidence/secret/path.jpg",
            "ocr_text": "private on-screen text",
            "visual_reasoning_json": {"provider": "qwen"},
        }
    ]
    result = list_session_visual_frames(SESSION_ID, user_id=USER_ID, db=_make_db(rows))

    dumped = result.model_dump()
    flat = str(dumped)
    assert "frame-evidence" not in flat
    assert "path_thumb" not in flat
    assert "ocr" not in flat.lower() or "ocr_text" not in flat
    assert "visual_reasoning_json" not in flat
    assert set(dumped["frames"][0].keys()) == {
        "frame_id",
        "frame_type",
        "timestamp_ms",
        "timestamp_label",
        "has_thumbnail",
    }


def test_query_is_scoped_to_caller_user_id():
    db = _make_db([])
    list_session_visual_frames(SESSION_ID, user_id=USER_ID, db=db)

    # Both the ownership gate and the frame listing must be reached, each on its
    # own table.
    db.table.assert_any_call("extension_proof_sessions")
    db.table.assert_any_call("workflow_visual_frame_evidence")

    # ── Ownership gate must be scoped to the CALLER's user_id AND session id ───
    owner_select = db.sessions_tbl.select
    owner_select.return_value.eq.assert_called_once_with("user_id", USER_ID)
    owner_select.return_value.eq.return_value.eq.assert_called_once_with(
        "id", SESSION_ID
    )

    # ── Frame query must be scoped to the CALLER's user_id AND proof_session_id.
    # Because it is gated behind ownership AND filtered by user_id, a foreign
    # session id can never yield another user's frames.
    frame_select = db.frames_tbl.select
    frame_select.return_value.eq.assert_called_once_with("user_id", USER_ID)
    frame_select.return_value.eq.return_value.eq.assert_called_once_with(
        "proof_session_id", SESSION_ID
    )
    # And the selected columns never include raw-byte / OCR / reasoning columns.
    selected = frame_select.call_args[0][0]
    assert "frame_storage_path" not in selected.replace("frame_thumbnail_storage_path", "")
    assert "ocr_text" not in selected
    assert "visual_reasoning_json" not in selected


def test_foreign_session_is_rejected_before_any_frame_read():
    """A session the caller does not own fails closed at the ownership gate —
    404, and the frame table is never queried (no existence/data leak)."""
    db = _make_db([], owned=False)

    with pytest.raises(HTTPException) as exc_info:
        list_session_visual_frames(SESSION_ID, user_id=USER_ID, db=db)

    assert exc_info.value.status_code == 404
    # The frame listing query must never run for a non-owned session.
    db.frames_tbl.select.assert_not_called()


def test_db_error_fails_soft_to_empty_list():
    result = list_session_visual_frames(
        SESSION_ID, user_id=USER_ID, db=_make_db(RuntimeError("boom"))
    )
    assert result.frame_count == 0
    assert result.frames == []
