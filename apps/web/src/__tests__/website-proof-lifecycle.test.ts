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

  it("restores only an explicitly selected created session", () => {
    expect(run(["RESTORE_CREATED"]).state).toBe("INITIALIZING_EXTENSION")
  })

  it("restores processing, completed, and saved states without creating a session", () => {
    expect(run(["RESTORE_PROCESSING"]).state).toBe("PROCESSING")
    expect(run(["RESTORE_ANALYSIS_COMPLETE"]).state).toBe("READY_TO_SAVE")
    expect(run(["RESTORE_SAVED"]).state).toBe("SAVED")
  })

  it("forbids duplicate save from SAVED", () => {
    const saved = run(["RESTORE_SAVED"])
    expect(() => transitionWebsiteProofLifecycle(saved, "SAVE_REQUESTED")).toThrow()
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
