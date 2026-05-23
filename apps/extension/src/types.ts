export interface WorkflowEvent {
  type: "page_visit" | "click" | "input_change"
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
}
