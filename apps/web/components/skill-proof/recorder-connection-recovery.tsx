"use client"

// Recovery panel for recorder RUNTIME failures — the "I have the extension but
// something went wrong" half of the state model.
//
// This is deliberately NOT an install surface. Installation problems
// (not detected / incompatible build / orphaned bridge) are owned by
// RecorderInstallGate via `recorderGateReasonFor`. This panel covers only the
// narrow family where the extension is present but the handshake with its MV3
// service worker did not complete, and its remedy is a retry — never an
// "install the extension" instruction.
//
// Every other diagnostic keeps its existing plain-alert rendering untouched.
// In particular WPR-DIFFERENT-SESSION-ACTIVE (another proof is recording),
// the target-attachment codes, session/revision mismatches, auth and replay
// codes are NOT handled here: they are distinct states with their own
// established recovery behavior.

import {
  RECORDER_EXTENSION_STORE_URL,
  isRecorderStoreListingLive,
} from "@/lib/recorder-extension-store"
import { emitRecorderExtensionEvent } from "@/lib/recorder-extension-telemetry"
import { useRecorderExtensionDetection } from "@/lib/use-recorder-extension-detection"

/**
 * Diagnostics meaning "the extension exists but VeriBridge could not complete
 * the handshake with it". Retrying is the correct remedy for all three.
 */
const CONNECTION_FAILURE_CODES = new Set([
  "WPR-EXTENSION-WORKER-UNREACHABLE",
  "WPR-INITIALIZATION-TIMEOUT",
  "WPR-STORAGE-WRITE-FAILED",
])

/** True when a diagnostic is a recorder connection failure (not an install problem). */
export function isRecorderConnectionFailure(diagnosticCode: string | null): boolean {
  return diagnosticCode !== null && CONNECTION_FAILURE_CODES.has(diagnosticCode)
}

export function RecorderConnectionRecovery({
  message,
  onRetry,
  retrying,
}: {
  /** The canonical recorder failure message, including its WPR-* code. */
  message: string
  /** Re-runs the recorder handshake for the SAME session. */
  onRetry: () => void | Promise<void>
  /** True while the parent is already re-running the handshake. */
  retrying: boolean
}) {
  // Only claim "detected" when the bridge actually answers — the panel must
  // never assert an installation state it has not verified.
  const { probe } = useRecorderExtensionDetection({ surface: "website_proof" })
  const confirmedInstalled = probe?.installed === true
  const storeLive = isRecorderStoreListingLive()

  return (
    <div
      data-testid="recorder-connection-recovery"
      role="alert"
      style={{
        border: "1px solid #fde68a",
        background: "#fffbeb",
        borderRadius: 12,
        padding: "14px 16px",
        display: "grid",
        gap: 8,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 700, color: "#92400e" }}>
        {confirmedInstalled
          ? "Recorder detected, but VeriBridge couldn't connect to it"
          : "VeriBridge couldn't connect to the recorder"}
      </div>
      <p style={{ margin: 0, fontSize: 12, color: "#7c2d12", lineHeight: 1.6 }}>
        {confirmedInstalled
          ? "The extension is installed — its background worker just didn't answer in time. Chrome suspends idle extension workers, so a retry normally succeeds immediately. Your proof session and form are saved."
          : "The extension's background worker didn't answer in time. Chrome suspends idle extension workers, so a retry normally succeeds immediately. Your proof session and form are saved."}
      </p>
      <p
        data-testid="recorder-connection-diagnostic"
        style={{ margin: 0, fontSize: 11.5, color: "#92400e", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}
      >
        {message}
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <button
          type="button"
          data-testid="recorder-connection-retry"
          onClick={() => { void onRetry() }}
          disabled={retrying}
          style={{
            background: "#4f46e5",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "9px 16px",
            fontSize: 13,
            fontWeight: 700,
            cursor: retrying ? "default" : "pointer",
            opacity: retrying ? 0.7 : 1,
          }}
        >
          {retrying ? "Reconnecting…" : "Retry connection"}
        </button>
        {storeLive && (
          <a
            data-testid="recorder-connection-store-link"
            href={RECORDER_EXTENSION_STORE_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => emitRecorderExtensionEvent("extension_listing_viewed", "website_proof", {
              reason: "connection_failure",
            })}
            aria-label="View the Website Proof Recorder in the Chrome Web Store — opens in a new tab"
            style={{
              background: "#fff",
              color: "#4f46e5",
              border: "1px solid #c7d2fe",
              borderRadius: 8,
              padding: "8px 14px",
              fontSize: 12.5,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            View extension ↗
          </a>
        )}
        <a
          href="/extension/support"
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 11.5, color: "#4f46e5", fontWeight: 600 }}
        >
          Troubleshooting
        </a>
      </div>
    </div>
  )
}
