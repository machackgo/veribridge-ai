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

export function LiveProofCoach({ sessionId, onFetch, pollIntervalMs = 5000 }: Props) {
  const [feedback, setFeedback] = useState<LiveFeedbackResponse | null>(null)
  const [waitingForSignals, setWaitingForSignals] = useState(true)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let mounted = true

    async function tick() {
      try {
        const result = await onFetch(sessionId)
        if (!mounted) return
        if (result) {
          setFeedback(result)
          setWaitingForSignals(result.live_score === 0 && result.claimed_skill_support.length === 0)
        }
      } catch {
        // silent — polling failure should not affect the proof panel
      }
    }

    void tick()
    intervalRef.current = setInterval(() => { void tick() }, pollIntervalMs)

    return () => {
      mounted = false
      if (intervalRef.current !== null) clearInterval(intervalRef.current)
    }
  }, [sessionId, onFetch, pollIntervalMs])

  return (
    <div
      style={{
        border: "1px solid #ddd6fe",
        borderRadius: 12,
        background: "#faf5ff",
        padding: "14px 16px",
        display: "grid",
        gap: 10,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 8, height: 8, borderRadius: "50%",
              background: "#7c3aed",
              animation: "pulse 1.2s ease-in-out infinite",
            }}
          />
          <span
            style={{
              fontSize: 11, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: "0.08em",
              color: "#7c3aed",
            }}
          >
            Live Proof Coach
          </span>
        </div>
        <span style={{ fontSize: 10, color: "#a78bfa" }}>
          Updates every {pollIntervalMs / 1000}s
        </span>
      </div>

      {waitingForSignals || !feedback ? (
        <div style={{ fontSize: 12, color: "#9ca3af", textAlign: "center", padding: "8px 0" }}>
          Waiting for live signals from the extension…
        </div>
      ) : (
        <>
          {/* Score bar */}
          <ScoreBar score={feedback.live_score} />

          {/* Privacy warning */}
          {feedback.sensitive_warning && (
            <div
              style={{
                fontSize: 11, fontWeight: 600, color: "#991b1b",
                background: "#fef2f2", border: "1px solid #fecaca",
                borderRadius: 7, padding: "6px 10px",
              }}
            >
              ⚠ Sensitive content detected — avoid showing tokens, passwords, API keys, SSNs, or payment info.
            </div>
          )}

          {/* Evidence chips */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {CHECKLIST_ITEMS.map(({ key, label }) => (
              <EvidenceChip
                key={key}
                label={label}
                captured={feedback.checklist[key] as boolean}
              />
            ))}
          </div>

          {/* Skill support */}
          {feedback.claimed_skill_support.length > 0 && (
            <div style={{ display: "grid", gap: 4 }}>
              {feedback.claimed_skill_support.map(s => {
                const color =
                  s.support_level === "likely"  ? "#166534" :
                  s.support_level === "partial" ? "#92400e" :
                  "#6b7280"
                const bg =
                  s.support_level === "likely"  ? "#f0fdf4" :
                  s.support_level === "partial" ? "#fefce8" :
                  "#f9fafb"
                const label =
                  s.support_level === "likely"  ? "Supported" :
                  s.support_level === "partial" ? "Partial"   :
                  "Missing"
                return (
                  <div
                    key={s.skill}
                    style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      gap: 8, background: bg, borderRadius: 7, padding: "5px 9px",
                    }}
                  >
                    <span style={{ fontSize: 11, color: "#374151", flex: 1 }}>{s.skill}</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color, flexShrink: 0 }}>
                      {label}
                    </span>
                  </div>
                )
              })}
            </div>
          )}

          {/* Suggestions */}
          {feedback.suggestions.length > 0 && (
            <div
              style={{
                borderTop: "1px solid #e9d5ff",
                paddingTop: 8,
                display: "grid",
                gap: 4,
              }}
            >
              {feedback.suggestions.map((s, i) => (
                <div
                  key={i}
                  style={{ fontSize: 11, color: "#6d28d9", lineHeight: 1.5 }}
                >
                  → {s}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
