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
