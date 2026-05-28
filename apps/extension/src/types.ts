export interface WorkflowEvent {
  type: "page_visit" | "click" | "input_change" | "tab_opened" | "navigation"
  timestamp: string
  page_url: string
  page_title: string
  element_tag?: string
  element_id?: string
  element_class?: string
  element_text?: string
  element_name?: string
  element_type?: string
  value?: string
}

// ── Visible Evidence types (v4) ───────────────────────────────────────────────

/** Safe file-upload metadata — never contains local paths. */
export interface FileUploadMeta {
  file_category: "image" | "document" | "video" | "audio" | "other"
  file_extension: string
  file_name_masked: string   // non-reversible hash of the original filename
}

/**
 * One DOM-snapshot / interaction event captured by the content script.
 * Matches the backend VisibleEvidenceEventInput schema exactly.
 *
 * Privacy invariant: all string fields must be sanitized by the content script
 * before emitting — no passwords, tokens, local paths, internal URLs.
 */
export interface VisibleEvidenceEvent {
  event_type:
    | "page_load"
    | "click"
    | "input_change"
    | "file_upload"
    | "form_submit"
    | "dom_snapshot"
    | "result_detected"
    | "recording_end"
  timestamp_ms: number
  event_id?: string
  url: string
  page_title: string
  target_domain: string
  visible_text_blocks: string[]
  result_like_blocks: string[]
  input_snapshot: Record<string, string>
  action_snapshot: Record<string, string>
  file_upload_meta?: FileUploadMeta | null
}

export interface VisibleEvidenceBatchPayload {
  events: VisibleEvidenceEvent[]
}

export type RecordingStatus =
  | "idle"
  | "ready"          // session auto-detected from page URL, not yet recording
  | "recording"
  | "stopped"
  | "uploading"
  | "uploaded"
  | "upload_failed"
  | "error"          // legacy alias kept for backward compat

export interface ExtensionState {
  sessionId: string
  apiUrl: string
  authToken: string
  isRecording: boolean
  eventCount: number
  startedAt: string | null
  stoppedAt: string | null
  status: RecordingStatus
  statusMessage: string
  lastUploadError: string | null
  // Session ID for which the upload-success bar was dismissed by the user.
  // When this equals sessionId, the floating bar stays hidden until a new recording.
  dismissedForSessionId: string
  // Tab tracking — IDs of tabs currently being recorded in this session.
  trackedTabIds: number[]
  originalTabId: number | null
}
