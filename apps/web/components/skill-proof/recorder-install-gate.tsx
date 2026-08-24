"use client"

// Install / update / reconnect gate for the VeriBridge Website Proof
// recorder extension.
//
// Rendered when the recorder handshake fails for an extension-availability
// reason (not installed, outdated, or reloaded mid-session). While visible it
// silently re-probes the bridge — installing the extension injects the
// content script into already-open tabs, so detection usually succeeds
// without a page refresh. Once the extension is detected and compatible the
// student continues the SAME session with one click; selected project and
// form state are untouched.

import {
  RECORDER_EXTENSION_STORE_URL,
  detectRecorderBrowserSupport,
  isRecorderStoreListingLive,
} from "@/lib/recorder-extension-store"
import { emitInstallClicked } from "@/lib/recorder-extension-telemetry"
import { useRecorderExtensionDetection } from "@/lib/use-recorder-extension-detection"

export type RecorderGateReason = "not_installed" | "outdated" | "reload_needed"

/** Maps a recorder handshake diagnostic code to a gate reason, or null. */
export function recorderGateReasonFor(diagnosticCode: string | null): RecorderGateReason | null {
  switch (diagnosticCode) {
    case "WPR-EXTENSION-NOT-DETECTED":
      return "not_installed"
    case "WPR-EXTENSION-VERSION-INCOMPATIBLE":
      return "outdated"
    case "WPR-EXTENSION-CONTEXT-INVALIDATED":
      return "reload_needed"
    default:
      return null
  }
}

const RECHECK_INTERVAL_MS = 3_000

const PERMISSION_POINTS: Array<{ title: string; body: string }> = [
  {
    title: "Screen recording you start",
    body: "Records your demo only after you pick what to share in Chrome's own screen picker. Nothing is captured before you click record.",
  },
  {
    title: "Reads the page you demonstrate",
    body: "While a proof is recording, it captures what is visible on the demo website — page text, clicks, and screenshots — to build your evidence. Passwords and sensitive fields are masked before anything leaves your browser.",
  },
  {
    title: "Uploads to VeriBridge only",
    body: "Evidence is attached to the proof session you started and can only be sent to VeriBridge — never to any other server.",
  },
]

export function RecorderInstallGate({
  reason,
  onContinue,
  continuing,
}: {
  reason: RecorderGateReason
  /** Re-runs the recorder handshake for the same session. */
  onContinue: () => void | Promise<void>
  /** True while the parent is already re-running the handshake. */
  continuing: boolean
}) {
  const browserSupport = detectRecorderBrowserSupport()
  const storeLive = isRecorderStoreListingLive()
  // Shared detection: probes on mount, on tab focus/visibility (the moment a
  // student returns from the Web Store tab), and on demand. This gate is
  // blocking, so it also opts into the slow background re-probe.
  const { probe, checking, recheck, markInstallClicked } = useRecorderExtensionDetection({
    surface: "website_proof",
    pollIntervalMs: RECHECK_INTERVAL_MS,
  })

  const detectedAndReady = probe?.ready === true

  const heading =
    reason === "not_installed"
      ? "Install the VeriBridge Recorder to continue"
      : reason === "outdated"
        ? "Update the VeriBridge Recorder to continue"
        : "Refresh this page to reconnect the recorder"

  const explanation =
    reason === "not_installed"
      ? "Website Proofs are recorded by the free VeriBridge Recorder browser extension. It runs only when you start a proof and records only what you choose to share."
      : reason === "outdated"
        ? "Your installed VeriBridge Recorder is older than this page supports. Chrome updates extensions automatically within a few hours — or you can force it from the store listing."
        : "The extension was updated or reloaded while this page was open, so the connection to it was lost. Refresh this page — your proof session is saved and will resume."

  return (
    <div
      data-testid="recorder-install-gate"
      role="region"
      aria-label="Recorder extension required"
      style={{
        border: "1px solid #c7d2fe",
        background: "#eef2ff",
        borderRadius: 12,
        padding: "14px 16px",
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 700, color: "#3730a3" }}>{heading}</div>
      <div style={{ fontSize: 12, color: "#374151", lineHeight: 1.55 }}>{explanation}</div>

      {browserSupport === "unsupported" && (
        <div
          role="alert"
          style={{ border: "1px solid #fde68a", background: "#fefce8", color: "#92400e", borderRadius: 8, padding: "8px 10px", fontSize: 12, lineHeight: 1.5 }}
        >
          This browser can&apos;t run the recorder yet. Please open this page in
          desktop <strong>Google Chrome</strong> (or another Chromium browser such as Microsoft
          Edge) to record a Website Proof.
        </div>
      )}

      {reason !== "reload_needed" && browserSupport !== "unsupported" && (
        <div style={{ display: "grid", gap: 6 }}>
          {PERMISSION_POINTS.map((point) => (
            <div key={point.title} style={{ fontSize: 11.5, color: "#4b5563", lineHeight: 1.5 }}>
              <strong style={{ color: "#1f2937" }}>{point.title}.</strong> {point.body}
            </div>
          ))}
          <a href="/extension/privacy" target="_blank" rel="noopener noreferrer" style={{ fontSize: 11.5, color: "#4f46e5" }}>
            Read the recorder privacy policy
          </a>
        </div>
      )}

      {detectedAndReady ? (
        <div style={{ display: "grid", gap: 8 }}>
          <div
            data-testid="recorder-detected-banner"
            style={{ border: "1px solid #bbf7d0", background: "#f0fdf4", color: "#166534", borderRadius: 8, padding: "8px 10px", fontSize: 12, fontWeight: 600 }}
          >
            ✓ VeriBridge Recorder detected{probe?.build_version ? ` (v${probe.build_version})` : ""} — you can continue.
          </div>
          <button
            type="button"
            data-testid="recorder-gate-continue"
            onClick={() => { void onContinue() }}
            disabled={continuing}
            style={{
              justifySelf: "start",
              background: "#4f46e5",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              padding: "9px 16px",
              fontSize: 13,
              fontWeight: 700,
              cursor: continuing ? "default" : "pointer",
              opacity: continuing ? 0.7 : 1,
            }}
          >
            {continuing ? "Reconnecting…" : "Continue Website Proof"}
          </button>
        </div>
      ) : reason === "reload_needed" ? (
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            justifySelf: "start",
            background: "#4f46e5",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "9px 16px",
            fontSize: 13,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Refresh this page
        </button>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          {storeLive && browserSupport !== "unsupported" ? (
            <a
              data-testid="recorder-gate-install-link"
              href={RECORDER_EXTENSION_STORE_URL}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => {
                markInstallClicked()
                emitInstallClicked("website_proof", { reason })
              }}
              aria-label={`${reason === "outdated" ? "Open the Chrome Web Store listing" : "Install VeriBridge Recorder"} — opens the Chrome Web Store in a new tab`}
              style={{
                background: "#4f46e5",
                color: "#fff",
                borderRadius: 8,
                padding: "9px 16px",
                fontSize: 13,
                fontWeight: 700,
                textDecoration: "none",
              }}
            >
              {reason === "outdated" ? "Open the Chrome Web Store listing" : "Install VeriBridge Recorder"}
            </a>
          ) : (
            <div
              data-testid="recorder-gate-pending-release"
              style={{ border: "1px solid #e5e7eb", background: "#f9fafb", color: "#4b5563", borderRadius: 8, padding: "8px 10px", fontSize: 12, lineHeight: 1.5 }}
            >
              The Chrome Web Store release is being reviewed. Existing approved
              testers can keep using their installed recorder; public
              installation opens as soon as the listing is live.
            </div>
          )}
          <button
            type="button"
            data-testid="recorder-gate-recheck"
            onClick={recheck}
            disabled={checking}
            style={{
              background: "#fff",
              color: "#4f46e5",
              border: "1px solid #c7d2fe",
              borderRadius: 8,
              padding: "8px 14px",
              fontSize: 12.5,
              fontWeight: 600,
              cursor: checking ? "default" : "pointer",
            }}
          >
            {checking ? "Checking…" : "I've installed it — check again"}
          </button>
          {probe?.installed && probe.outdated && (
            <span style={{ fontSize: 11.5, color: "#92400e" }}>
              Detected v{probe.build_version ?? "unknown"} — an update is required.
            </span>
          )}
        </div>
      )}
    </div>
  )
}
