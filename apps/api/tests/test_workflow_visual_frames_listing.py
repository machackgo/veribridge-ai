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

from app.api.v1.endpoints.workflow_visual_frames import (
    SessionVisualFramesResponse,
    list_session_visual_frames,
)

USER_ID = "00000000-0000-0000-0000-000000000099"
SESSION_ID = "session-abc-123"


def _make_db(rows: list[dict[str, Any]] | Exception) -> MagicMock:
    db = MagicMock()
    chain = (
        db.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
    )
    if isinstance(rows, Exception):
        chain.execute.side_effect = rows
    else:
        resp = MagicMock()
        resp.data = rows
        chain.execute.return_value = resp
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

    select = db.table.return_value.select
    db.table.assert_called_once_with("workflow_visual_frame_evidence")
    # First .eq must scope to the CALLER's user_id — a foreign session id can
    # therefore only ever produce an empty list, never another user's frames.
    select.return_value.eq.assert_called_once_with("user_id", USER_ID)
    select.return_value.eq.return_value.eq.assert_called_once_with(
        "proof_session_id", SESSION_ID
    )
    # And the selected columns never include raw-byte / OCR / reasoning columns.
    selected = select.call_args[0][0]
    assert "frame_storage_path" not in selected.replace("frame_thumbnail_storage_path", "")
    assert "ocr_text" not in selected
    assert "visual_reasoning_json" not in selected


def test_db_error_fails_soft_to_empty_list():
    result = list_session_visual_frames(
        SESSION_ID, user_id=USER_ID, db=_make_db(RuntimeError("boom"))
    )
    assert result.frame_count == 0
    assert result.frames == []
