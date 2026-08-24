"use client"

// Compact pre-start readiness strip for the Website Proof entry form.
//
// The install gate covers the "recorder missing" case. This is its positive
// counterpart: once the bridge actually answers, the student gets explicit
// confirmation that recording will work before they fill the form in — rather
// than an install prompt that no longer applies, or silence.
//
// Renders nothing until detection is confirmed, so it can never claim a state
// it has not verified and never competes with the install gate.

import { useRecorderExtensionDetection } from "@/lib/use-recorder-extension-detection"

export function RecorderReadyBadge() {
  const { probe } = useRecorderExtensionDetection({ surface: "website_proof" })
  if (probe?.ready !== true) return null
  return (
    <div
      data-testid="recorder-ready-badge"
      style={{
        border: "1px solid #bbf7d0",
        background: "#f0fdf4",
        color: "#166534",
        borderRadius: 10,
        padding: "8px 12px",
        fontSize: 12,
        fontWeight: 600,
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 8,
      }}
    >
      <span aria-hidden="true">✓</span>
      <span aria-live="polite">
        VeriBridge Recorder detected{probe.build_version ? ` (v${probe.build_version})` : ""} — ready to record this
        Website Proof.
      </span>
    </div>
  )
}
