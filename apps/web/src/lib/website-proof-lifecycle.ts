export type WebsiteProofLifecycleState =
  | "NEW"
  | "CREATING_SESSION"
  | "INITIALIZING_EXTENSION"
  | "EXTENSION_READY"
  | "OPENING_TARGET"
  | "TARGET_READY"
  | "RECORDING"
  | "STOPPING"
  | "UPLOADING"
  | "PROCESSING"
  | "ANALYSIS_COMPLETE"
  | "READY_TO_SAVE"
  | "SAVING"
  | "SAVED"
  | "FAILED_RETRYABLE"
  | "FAILED_TERMINAL"

export type WebsiteProofLifecycleEvent =
  | "CREATE_REQUESTED"
  | "SESSION_CREATED"
  | "INITIALIZATION_REQUESTED"
  | "EXTENSION_ACKNOWLEDGED"
  | "TARGET_OPEN_REQUESTED"
  | "TARGET_ACKNOWLEDGED"
  | "RECORDING_STARTED"
  | "STOP_REQUESTED"
  | "UPLOAD_STARTED"
  | "UPLOAD_ACCEPTED"
  | "ANALYSIS_COMPLETED"
  | "SAVE_READY"
  | "SAVE_REQUESTED"
  | "SAVE_COMPLETED"
  | "RETRYABLE_FAILURE"
  | "TERMINAL_FAILURE"
  | "RETRY_INITIALIZATION"
  | "RESTORE_CREATED"
  | "RESTORE_RECORDING"
  | "RESTORE_PROCESSING"
  | "RESTORE_ANALYSIS_COMPLETE"
  | "RESTORE_SAVED"
  | "RESET"

export type WebsiteProofLifecycle = {
  state: WebsiteProofLifecycleState
  last_event: WebsiteProofLifecycleEvent | "INIT"
  error_code: string | null
  updated_at: string
}

export class InvalidWebsiteProofTransitionError extends Error {
  constructor(
    readonly from: WebsiteProofLifecycleState,
    readonly event: WebsiteProofLifecycleEvent,
  ) {
    super(`Website Proof transition ${from} -> ${event} is not allowed.`)
  }
}

const TRANSITIONS: Record<WebsiteProofLifecycleState, Partial<Record<WebsiteProofLifecycleEvent, WebsiteProofLifecycleState>>> = {
  NEW: { CREATE_REQUESTED: "CREATING_SESSION", RESTORE_CREATED: "INITIALIZING_EXTENSION", RESTORE_RECORDING: "RECORDING", RESTORE_PROCESSING: "PROCESSING", RESTORE_ANALYSIS_COMPLETE: "READY_TO_SAVE", RESTORE_SAVED: "SAVED", RESET: "NEW" },
  CREATING_SESSION: { SESSION_CREATED: "INITIALIZING_EXTENSION", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  INITIALIZING_EXTENSION: { INITIALIZATION_REQUESTED: "INITIALIZING_EXTENSION", EXTENSION_ACKNOWLEDGED: "EXTENSION_READY", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  EXTENSION_READY: { TARGET_OPEN_REQUESTED: "OPENING_TARGET", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  OPENING_TARGET: { TARGET_ACKNOWLEDGED: "TARGET_READY", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  TARGET_READY: { RECORDING_STARTED: "RECORDING", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  // UPLOAD_ACCEPTED / ANALYSIS_COMPLETED from RECORDING/STOPPING/UPLOADING: a
  // page restored from a stale resume candidate can still believe the session
  // is recording while the extension has already finished the upload (and the
  // user may have run analysis before resuming). The page must follow that
  // later-arriving truth instead of throwing on it.
  RECORDING: { INITIALIZATION_REQUESTED: "INITIALIZING_EXTENSION", RECORDING_STARTED: "RECORDING", STOP_REQUESTED: "STOPPING", UPLOAD_STARTED: "UPLOADING", UPLOAD_ACCEPTED: "PROCESSING", ANALYSIS_COMPLETED: "ANALYSIS_COMPLETE", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  STOPPING: { STOP_REQUESTED: "STOPPING", UPLOAD_STARTED: "UPLOADING", UPLOAD_ACCEPTED: "PROCESSING", ANALYSIS_COMPLETED: "ANALYSIS_COMPLETE", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  UPLOADING: { STOP_REQUESTED: "UPLOADING", UPLOAD_STARTED: "UPLOADING", UPLOAD_ACCEPTED: "PROCESSING", ANALYSIS_COMPLETED: "ANALYSIS_COMPLETE", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  PROCESSING: { UPLOAD_STARTED: "PROCESSING", UPLOAD_ACCEPTED: "PROCESSING", ANALYSIS_COMPLETED: "ANALYSIS_COMPLETE", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  ANALYSIS_COMPLETE: { ANALYSIS_COMPLETED: "ANALYSIS_COMPLETE", SAVE_READY: "READY_TO_SAVE", SAVE_REQUESTED: "SAVING", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  READY_TO_SAVE: { ANALYSIS_COMPLETED: "READY_TO_SAVE", SAVE_READY: "READY_TO_SAVE", SAVE_REQUESTED: "SAVING", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  SAVING: { SAVE_COMPLETED: "SAVED", RETRYABLE_FAILURE: "FAILED_RETRYABLE", TERMINAL_FAILURE: "FAILED_TERMINAL", RESET: "NEW" },
  // A saved proof may be reconciled again. Canonical finalization is
  // idempotent and this transition lets historical saves repair downstream
  // projections (for example, a missing Skill Graph artifact) without
  // creating a duplicate Website Proof session.
  SAVED: { SAVE_REQUESTED: "SAVING", SAVE_COMPLETED: "SAVED", RESTORE_SAVED: "SAVED", RESET: "NEW" },
  // UPLOAD_STARTED / UPLOAD_ACCEPTED: a failed proof upload is retried from the
  // extension's floating bar — the page must follow the retry instead of
  // throwing on the recovered upload signals.
  FAILED_RETRYABLE: { CREATE_REQUESTED: "CREATING_SESSION", RETRY_INITIALIZATION: "INITIALIZING_EXTENSION", STOP_REQUESTED: "STOPPING", UPLOAD_STARTED: "UPLOADING", UPLOAD_ACCEPTED: "PROCESSING", SAVE_REQUESTED: "SAVING", RETRYABLE_FAILURE: "FAILED_RETRYABLE", RESET: "NEW", TERMINAL_FAILURE: "FAILED_TERMINAL" },
  FAILED_TERMINAL: { RESET: "NEW" },
}

export function createWebsiteProofLifecycle(
  now: () => string = () => new Date().toISOString(),
): WebsiteProofLifecycle {
  return { state: "NEW", last_event: "INIT", error_code: null, updated_at: now() }
}

export function transitionWebsiteProofLifecycle(
  lifecycle: WebsiteProofLifecycle,
  event: WebsiteProofLifecycleEvent,
  options: { error_code?: string | null; now?: () => string } = {},
): WebsiteProofLifecycle {
  const next = TRANSITIONS[lifecycle.state][event]
  if (!next) throw new InvalidWebsiteProofTransitionError(lifecycle.state, event)
  return {
    state: next,
    last_event: event,
    error_code: event === "RETRYABLE_FAILURE" || event === "TERMINAL_FAILURE"
      ? options.error_code ?? "unknown_error"
      : null,
    updated_at: (options.now ?? (() => new Date().toISOString()))(),
  }
}

export function websiteProofLifecycleReducer(
  lifecycle: WebsiteProofLifecycle,
  action: { event: WebsiteProofLifecycleEvent; error_code?: string | null },
): WebsiteProofLifecycle {
  return transitionWebsiteProofLifecycle(lifecycle, action.event, { error_code: action.error_code })
}
