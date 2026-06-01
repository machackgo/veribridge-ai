"use client"

import React, { useEffect, useRef, useState } from "react"
import type { LiveFeedbackResponse } from "@/lib/api"

// ── Types ─────────────────────────────────────────────────────────────────────

interface Props {
  sessionId: string
  /** Called periodically to fetch current live feedback from the backend. */
  onFetch: (sessionId: string) => Promise<LiveFeedbackResponse | null>
  /** Interval in ms between polls. Default: 5000 */
  pollIntervalMs?: number
}

// ── Evidence chip config ───────────────────────────────────────────────────────

const CHECKLIST_ITEMS: Array<{ key: keyof LiveFeedbackResponse["checklist"]; label: string }> = [
  { key: "website_loaded",        label: "Website loaded" },
  { key: "dom_text_seen",         label: "Page content" },
  { key: "interaction_seen",      label: "Interaction" },
  { key: "form_input_seen",       label: "Form/input" },
  { key: "output_or_result_seen", label: "Output/result" },
  { key: "chart_or_visual_seen",  label: "Chart/visual" },
  { key: "code_or_repo_seen",     label: "Code/repo" },
  { key: "github_seen",           label: "GitHub" },
]

// ── Sub-components ─────────────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const color  = score >= 70 ? "#166534" : score >= 40 ? "#92400e" : "#7c3aed"
  const bg     = score >= 70 ? "#f0fdf4"  : score >= 40 ? "#fefce8"  : "#f5f3ff"
  const border = score >= 70 ? "#bbf7d0"  : score >= 40 ? "#fde68a"  : "#ddd6fe"
  const fill   = score >= 70 ? "#22c55e"  : score >= 40 ? "#f59e0b"  : "#a78bfa"

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1, height: 6, borderRadius: 999,
          background: "#e5e7eb", overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${score}%`, height: "100%", borderRadius: 999,
            background: fill, transition: "width 0.4s ease",
          }}
        />
      </div>
      <span
        style={{
          fontSize: 11, fontWeight: 700, padding: "2px 8px",
          borderRadius: 999, background: bg, color, border: `1px solid ${border}`,
          flexShrink: 0,
        }}
      >
        {score}/100
      </span>
    </div>
  )
}

function EvidenceChip({ label, captured }: { label: string; captured: boolean }) {
  return (
    <span
      style={{
        fontSize: 10, fontWeight: 600, padding: "2px 8px",
        borderRadius: 999,
        background: captured ? "#f0fdf4" : "#f8fafc",
        color:      captured ? "#166534" : "#94a3b8",
        border:     `1px solid ${captured ? "#bbf7d0" : "#e2e8f0"}`,
        flexShrink: 0,
      }}
    >
      {captured ? "✓" : "○"} {label}
    </span>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function LiveProofCoach(_props: Props) {
  return null
}
