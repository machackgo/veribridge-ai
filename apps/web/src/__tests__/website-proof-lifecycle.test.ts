import { describe, expect, it } from "vitest"

import {
  InvalidWebsiteProofTransitionError,
  createWebsiteProofLifecycle,
  transitionWebsiteProofLifecycle,
  type WebsiteProofLifecycle,
  type WebsiteProofLifecycleEvent,
} from "@/lib/website-proof-lifecycle"

function run(events: WebsiteProofLifecycleEvent[]): WebsiteProofLifecycle {
  return events.reduce(
    (state, event) => transitionWebsiteProofLifecycle(state, event, { now: () => "2026-07-14T12:00:00Z" }),
    createWebsiteProofLifecycle(() => "2026-07-14T11:00:00Z"),
  )
}

describe("Website Proof lifecycle state machine", () => {
  it("runs the complete fresh-session lifecycle in order", () => {
    const lifecycle = run([
      "CREATE_REQUESTED",
      "SESSION_CREATED",
      "INITIALIZATION_REQUESTED",
      "EXTENSION_ACKNOWLEDGED",
      "TARGET_OPEN_REQUESTED",
      "TARGET_ACKNOWLEDGED",
      "RECORDING_STARTED",
      "STOP_REQUESTED",
      "UPLOAD_STARTED",
      "UPLOAD_ACCEPTED",
      "ANALYSIS_COMPLETED",
      "SAVE_READY",
      "SAVE_REQUESTED",
      "SAVE_COMPLETED",
    ])
    expect(lifecycle).toMatchObject({ state: "SAVED", last_event: "SAVE_COMPLETED", error_code: null })
  })

  it("forbids CREATED-to-recording without extension and target ACKs", () => {
    const created = run(["CREATE_REQUESTED", "SESSION_CREATED"])
    expect(() => transitionWebsiteProofLifecycle(created, "RECORDING_STARTED"))
      .toThrow(InvalidWebsiteProofTransitionError)
  })

  it("forbids opening the target before extension ACK", () => {
    const initializing = run(["CREATE_REQUESTED", "SESSION_CREATED"])
    expect(() => transitionWebsiteProofLifecycle(initializing, "TARGET_OPEN_REQUESTED")).toThrow()
  })

  it("forbids uploading-to-recording regression", () => {
    const uploading = run([
      "CREATE_REQUESTED", "SESSION_CREATED", "EXTENSION_ACKNOWLEDGED",
      "TARGET_OPEN_REQUESTED", "TARGET_ACKNOWLEDGED", "RECORDING_STARTED", "UPLOAD_STARTED",
    ])
    expect(() => transitionWebsiteProofLifecycle(uploading, "RECORDING_STARTED")).toThrow()
  })

  it("makes duplicate recording/upload/save deliveries harmless", () => {
    const recording = run([
      "CREATE_REQUESTED", "SESSION_CREATED", "EXTENSION_ACKNOWLEDGED",
      "TARGET_OPEN_REQUESTED", "TARGET_ACKNOWLEDGED", "RECORDING_STARTED", "RECORDING_STARTED",
    ])
    expect(recording.state).toBe("RECORDING")
    const saved = run([
      "CREATE_REQUESTED", "SESSION_CREATED", "EXTENSION_ACKNOWLEDGED",
      "TARGET_OPEN_REQUESTED", "TARGET_ACKNOWLEDGED", "RECORDING_STARTED",
      "UPLOAD_STARTED", "UPLOAD_STARTED", "UPLOAD_ACCEPTED", "UPLOAD_ACCEPTED",
      "ANALYSIS_COMPLETED", "SAVE_READY", "SAVE_REQUESTED", "SAVE_COMPLETED", "SAVE_COMPLETED",
    ])
    expect(saved.state).toBe("SAVED")
  })

  it("records a retryable diagnostic and retries initialization", () => {
    const failed = transitionWebsiteProofLifecycle(
      run(["CREATE_REQUESTED", "SESSION_CREATED"]),
      "RETRYABLE_FAILURE",
      { error_code: "extension_not_detected" },
    )
    expect(failed).toMatchObject({ state: "FAILED_RETRYABLE", error_code: "extension_not_detected" })
    expect(transitionWebsiteProofLifecycle(failed, "RETRY_INITIALIZATION").state)
      .toBe("INITIALIZING_EXTENSION")
  })

  it("reinitializes the recorder bridge for the same restored recording", () => {
    const recording = run(["RESTORE_RECORDING"])
    expect(transitionWebsiteProofLifecycle(recording, "INITIALIZATION_REQUESTED").state)
      .toBe("INITIALIZING_EXTENSION")
  })

  it("restores only an explicitly selected created session", () => {
    expect(run(["RESTORE_CREATED"]).state).toBe("INITIALIZING_EXTENSION")
  })

  it("restores processing, completed, and saved states without creating a session", () => {
    expect(run(["RESTORE_PROCESSING"]).state).toBe("PROCESSING")
    expect(run(["RESTORE_ANALYSIS_COMPLETE"]).state).toBe("READY_TO_SAVE")
    expect(run(["RESTORE_SAVED"]).state).toBe("SAVED")
  })

  it("follows an extension-driven upload retry out of FAILED_RETRYABLE", () => {
    // A failed proof upload (e.g. the screen recording was not finalized yet)
    // parks the page in FAILED_RETRYABLE. Clicking Retry on the floating bar
    // re-runs SEND_PROOF, which re-emits upload signals — the page must follow
    // the recovered upload rather than throw.
    const failed = run(["RESTORE_RECORDING", "RETRYABLE_FAILURE"])
    expect(failed.state).toBe("FAILED_RETRYABLE")
    const uploading = transitionWebsiteProofLifecycle(failed, "UPLOAD_STARTED")
    expect(uploading.state).toBe("UPLOADING")
    const processing = transitionWebsiteProofLifecycle(uploading, "UPLOAD_ACCEPTED")
    expect(processing.state).toBe("PROCESSING")
    // An acceptance broadcast that arrives without the started signal (page was
    // refreshed mid-retry) is equally valid.
    expect(transitionWebsiteProofLifecycle(failed, "UPLOAD_ACCEPTED").state).toBe("PROCESSING")
    // Stop from the floating bar while parked in failure is also a retry path.
    expect(transitionWebsiteProofLifecycle(failed, "STOP_REQUESTED").state).toBe("STOPPING")
  })

  it("follows late-arriving upload/analysis truth after a stale recording restore", () => {
    // A page restored from a stale resume candidate still believes the session
    // is recording, but the extension may have already finished the upload and
    // analysis may complete before any stop/upload signal reaches the page.
    const restored = run(["RESTORE_RECORDING"])
    expect(restored.state).toBe("RECORDING")
    expect(transitionWebsiteProofLifecycle(restored, "UPLOAD_ACCEPTED").state).toBe("PROCESSING")
    expect(transitionWebsiteProofLifecycle(restored, "ANALYSIS_COMPLETED").state).toBe("ANALYSIS_COMPLETE")
    // The same truth must be accepted from the stop/upload phases.
    const stopping = transitionWebsiteProofLifecycle(restored, "STOP_REQUESTED")
    expect(transitionWebsiteProofLifecycle(stopping, "ANALYSIS_COMPLETED").state).toBe("ANALYSIS_COMPLETE")
    const uploading = transitionWebsiteProofLifecycle(restored, "UPLOAD_STARTED")
    expect(transitionWebsiteProofLifecycle(uploading, "ANALYSIS_COMPLETED").state).toBe("ANALYSIS_COMPLETE")
  })

  it("forbids duplicate save from SAVED", () => {
    const saved = run(["RESTORE_SAVED"])
    const reconciling = transitionWebsiteProofLifecycle(saved, "SAVE_REQUESTED")
    expect(reconciling.state).toBe("SAVING")
    expect(transitionWebsiteProofLifecycle(reconciling, "SAVE_COMPLETED").state).toBe("SAVED")
  })

  it("allows reset from every non-new phase", () => {
    const phases = [
      run(["CREATE_REQUESTED"]),
      run(["CREATE_REQUESTED", "SESSION_CREATED"]),
      run(["RESTORE_RECORDING"]),
      run(["RESTORE_PROCESSING"]),
      run(["RESTORE_ANALYSIS_COMPLETE"]),
      run(["RESTORE_SAVED"]),
    ]
    for (const phase of phases) {
      expect(transitionWebsiteProofLifecycle(phase, "RESET").state).toBe("NEW")
    }
  })
})

describe("recorderStatusLabel", () => {
  const base = { error_code: null, updated_at: "2026-07-21T00:00:00.000Z" } as const

  it("labels the resting post-create state as ready-to-start, not initializing", async () => {
    const { recorderStatusLabel } = await import("../lib/website-proof-lifecycle")
    expect(
      recorderStatusLabel({ ...base, state: "INITIALIZING_EXTENSION", last_event: "SESSION_CREATED" }, false),
    ).toBe("READY TO START — press Start Proof Demo")
    expect(
      recorderStatusLabel({ ...base, state: "INITIALIZING_EXTENSION", last_event: "RESTORE_CREATED" }, false),
    ).toBe("READY TO START — press Start Proof Demo")
  })

  it("keeps the in-flight init and other states verbatim", async () => {
    const { recorderStatusLabel } = await import("../lib/website-proof-lifecycle")
    expect(
      recorderStatusLabel({ ...base, state: "INITIALIZING_EXTENSION", last_event: "INITIALIZATION_REQUESTED" }, false),
    ).toBe("INITIALIZING EXTENSION")
    expect(
      recorderStatusLabel({ ...base, state: "FAILED_RETRYABLE", last_event: "RETRYABLE_FAILURE" }, false),
    ).toBe("FAILED RETRYABLE")
    expect(
      recorderStatusLabel({ ...base, state: "RECORDING", last_event: "RECORDING_STARTED" }, true),
    ).toBe("Recorder ready")
  })
})
