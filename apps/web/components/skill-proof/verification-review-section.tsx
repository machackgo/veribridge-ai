"use client"

/**
 * VerificationReviewSection
 *
 * Shown after the Verification Readiness Report in the extension proof panel.
 *
 * Track A — AI Review MVP:
 *   - Student clicks "Submit for VeriBridge AI Review"
 *   - 5-minute countdown UI (simulated; real timer for UX)
 *   - On complete: shows decision badge (Approved / Needs More Evidence / Privacy Flagged)
 *   - On re-submission: allowed when previous status was needs_more_evidence,
 *     manual_review_recommended, or privacy_flagged
 *
 * Track B — Human Review placeholders:
 *   - "Request Faculty Review" — disabled / Coming Soon
 *   - "Request Domain Expert Review" — disabled / Coming Soon
 *   - "Request Company/Mentor Review" — disabled / Coming Soon
 *   - Explanation: human review will be available once VeriBridge adds reviewers
 *
 * Wording enforced:
 *   - "VeriBridge AI Reviewed" for ai_approved_for_sharing
 *   - NEVER "Human Verified" from AI review alone
 *   - Honest labels for every status
 */

import React, { useEffect, useRef, useState } from "react"
import {
  AiReviewStatus,
  HumanReviewStatus,
  VerificationReviewResponse,
  getReviewStatus,
  submitForAiReview,
} from "@/lib/api"

// ── Types ─────────────────────────────────────────────────────────────────────

interface Props {
  sessionId: string
  /** Readiness score from the VerificationReadinessReport (0–100). */
  readinessScore: number
  /** Readiness level from the report. */
  readinessLevel: "strong" | "moderate" | "weak" | "insufficient"
  /**
   * Whether the readiness report is available (proof has been uploaded and
   * at least one analysis has run).  The review section is only shown when true.
   */
  readinessReady: boolean
}

// ── Constants ─────────────────────────────────────────────────────────────────

/** Simulated review window in seconds (5 minutes). */
const REVIEW_WINDOW_SECONDS = 300

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatCountdown(remaining: number): string {
  const m = Math.floor(remaining / 60)
  const s = remaining % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}

function aiStatusColor(status: AiReviewStatus): string {
  switch (status) {
    case "ai_approved_for_sharing":      return "#065f46"
    case "needs_more_evidence":          return "#92400e"
    case "manual_review_recommended":    return "#1e40af"
    case "privacy_flagged":              return "#991b1b"
    case "ai_review_in_progress":
    case "submitted_for_ai_review":      return "#1d4ed8"
    default:                             return "#374151"
  }
}

function aiStatusBg(status: AiReviewStatus): string {
  switch (status) {
    case "ai_approved_for_sharing":      return "#d1fae5"
    case "needs_more_evidence":          return "#fef3c7"
    case "manual_review_recommended":    return "#dbeafe"
    case "privacy_flagged":              return "#fee2e2"
    case "ai_review_in_progress":
    case "submitted_for_ai_review":      return "#eff6ff"
    default:                             return "#f3f4f6"
  }
}

function aiStatusIcon(status: AiReviewStatus): string {
  switch (status) {
    case "ai_approved_for_sharing":      return "✅"
    case "needs_more_evidence":          return "⚠️"
    case "manual_review_recommended":    return "🔍"
    case "privacy_flagged":              return "🔒"
    case "ai_review_in_progress":
    case "submitted_for_ai_review":      return "⏳"
    default:                             return "📋"
  }
}

/** Human-readable label for each AI review status. */
function aiStatusLabel(status: AiReviewStatus): string {
  const labels: Record<AiReviewStatus, string> = {
    not_submitted:               "Not Submitted",
    submitted_for_ai_review:     "Submitted — Queued for Review",
    ai_review_in_progress:       "VeriBridge AI Review In Progress…",
    ai_approved_for_sharing:     "VeriBridge AI Reviewed — Approved for Sharing",
    needs_more_evidence:         "Needs More Evidence",
    manual_review_recommended:   "Manual Review Recommended",
    privacy_flagged:             "Privacy Flag — Review Paused",
  }
  return labels[status] ?? status
}

/** Human-readable label for each human review status. */
function humanStatusLabel(status: HumanReviewStatus): string {
  const labels: Record<HumanReviewStatus, string> = {
    human_review_not_requested:     "Not Requested",
    human_review_requested:         "Requested",
    faculty_review_pending:         "Faculty Review Pending",
    company_review_pending:         "Company / Mentor Review Pending",
    domain_expert_review_pending:   "Domain Expert Review Pending",
    faculty_reviewed:               "Faculty Reviewed",
    company_reviewed:               "Company / Mentor Reviewed",
    domain_expert_reviewed:         "Domain Expert Reviewed",
    human_verified:                 "Human Verified",
    human_review_rejected:          "Human Review — Rejected",
  }
  return labels[status] ?? status
}

function canResubmit(status: AiReviewStatus): boolean {
  return ["needs_more_evidence", "manual_review_recommended", "privacy_flagged"].includes(status)
}

// ── Main component ────────────────────────────────────────────────────────────

export function VerificationReviewSection({
  sessionId,
  readinessScore,
  readinessLevel,
  readinessReady,
}: Props) {
  const [review, setReview] = useState<VerificationReviewResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [countdown, setCountdown] = useState<number | null>(null)
  const [loaded, setLoaded] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load existing review status on mount
  useEffect(() => {
    if (!sessionId || !readinessReady) return
    let cancelled = false
    getReviewStatus(sessionId)
      .then((r) => { if (!cancelled) { setReview(r); setLoaded(true) } })
      .catch(() => { if (!cancelled) setLoaded(true) })
    return () => { cancelled = true }
  }, [sessionId, readinessReady])

  // Countdown timer when review is in progress
  useEffect(() => {
    const status = review?.ai_review_status
    const inProgress = status === "submitted_for_ai_review" || status === "ai_review_in_progress"
    if (!inProgress) {
      if (timerRef.current) clearInterval(timerRef.current)
      return
    }
    setCountdown(REVIEW_WINDOW_SECONDS)
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev === null || prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current)
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [review?.ai_review_status])

  const handleSubmit = async () => {
    if (submitting) return
    setError(null)
    setSubmitting(true)
    try {
      const result = await submitForAiReview(sessionId, readinessScore, readinessLevel)
      setReview(result)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Submission failed. Please try again."
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!readinessReady) return null

  const aiStatus: AiReviewStatus = review?.ai_review_status ?? "not_submitted"
  const humanStatus: HumanReviewStatus = review?.human_review_status ?? "human_review_not_requested"
  const isInProgress = aiStatus === "submitted_for_ai_review" || aiStatus === "ai_review_in_progress"
  const isApproved = aiStatus === "ai_approved_for_sharing"
  const canSubmit =
    !isInProgress &&
    !isApproved &&
    (aiStatus === "not_submitted" || canResubmit(aiStatus))

  return (
    <div
      style={{
        border: "1px solid var(--line-2, #e5e7eb)",
        borderRadius: 14,
        padding: "20px 20px",
        marginTop: 4,
        background: "var(--bg-1, #fff)",
      }}
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 20 }}>🔍</span>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink, #111)" }}>
            Verification Review
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-2, #6b7280)", marginTop: 1 }}>
            VeriBridge AI review + optional human faculty/expert review
          </div>
        </div>
      </div>

      {/* ── Track A: AI Review Status ──────────────────────────────────────── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-3, #9ca3af)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
          AI Review Status
        </div>

        {aiStatus !== "not_submitted" && (
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: aiStatusBg(aiStatus),
              color: aiStatusColor(aiStatus),
              borderRadius: 8,
              padding: "6px 12px",
              fontSize: 13,
              fontWeight: 600,
              marginBottom: 10,
            }}
          >
            <span>{aiStatusIcon(aiStatus)}</span>
            <span>{aiStatusLabel(aiStatus)}</span>
          </div>
        )}

        {aiStatus === "not_submitted" && (
          <div
            style={{
              fontSize: 12,
              color: "var(--ink-3, #9ca3af)",
              marginBottom: 8,
            }}
          >
            Not yet submitted for review.
          </div>
        )}

        {/* Decision summary */}
        {review?.ai_decision_summary && aiStatus !== "not_submitted" && (
          <div
            style={{
              fontSize: 12,
              color: "var(--ink-2, #374151)",
              lineHeight: 1.6,
              background: "var(--bg-2, #f9fafb)",
              borderRadius: 8,
              padding: "8px 12px",
              marginBottom: 10,
            }}
          >
            {review.ai_decision_summary}
          </div>
        )}

        {/* Countdown timer when in progress */}
        {isInProgress && countdown !== null && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              borderRadius: 10,
              padding: "10px 14px",
              marginBottom: 10,
            }}
          >
            <span style={{ fontSize: 18 }}>⏱</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1e40af" }}>
                {countdown > 0 ? `Estimated time remaining: ${formatCountdown(countdown)}` : "Review completing…"}
              </div>
              <div style={{ fontSize: 11, color: "#3b82f6", marginTop: 2 }}>
                Your evidence package is under VeriBridge AI review. This usually takes around 5 minutes.
              </div>
            </div>
          </div>
        )}

        {/* In-progress explanation */}
        {isInProgress && (
          <div style={{ fontSize: 11, color: "var(--ink-3, #6b7280)", lineHeight: 1.6, marginBottom: 8 }}>
            If your evidence meets the readiness threshold and no privacy or risk issues are
            detected, it will be approved for sharing. Some submissions may still require
            human review.
          </div>
        )}

        {/* Approved detail */}
        {isApproved && (
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
              background: "#f0fdf4",
              border: "1px solid #bbf7d0",
              borderRadius: 10,
              padding: "10px 14px",
              marginBottom: 10,
            }}
          >
            <span style={{ fontSize: 18 }}>✅</span>
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#065f46" }}>
                AI Approved for Sharing
              </div>
              <div style={{ fontSize: 11, color: "#047857", marginTop: 2, lineHeight: 1.6 }}>
                This is a VeriBridge AI review. Human or faculty review has not yet been completed.
                Recruiters will see &quot;VeriBridge AI Reviewed&quot; — not &quot;Human Verified.&quot;
              </div>
            </div>
          </div>
        )}

        {/* Readiness snapshot */}
        {review && aiStatus !== "not_submitted" && (
          <div style={{ fontSize: 11, color: "var(--ink-3, #9ca3af)", marginTop: 4 }}>
            Reviewed at readiness score: <strong>{review.readiness_score}/100</strong> ({review.readiness_level})
          </div>
        )}
      </div>

      {/* ── Submit button ──────────────────────────────────────────────────── */}
      {canSubmit && (
        <div style={{ marginBottom: 16 }}>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting || !readinessReady}
            style={{
              background: submitting ? "var(--bg-3, #e5e7eb)" : "#1e40af",
              color: submitting ? "var(--ink-3, #6b7280)" : "#fff",
              border: "none",
              borderRadius: 10,
              padding: "10px 20px",
              fontWeight: 700,
              fontSize: 13,
              cursor: submitting ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            {submitting ? (
              <>
                <span style={{ display: "inline-block", animation: "spin 1s linear infinite" }}>⏳</span>
                Submitting…
              </>
            ) : (
              <>
                {aiStatus === "not_submitted" ? "🔍 Submit for VeriBridge AI Review" : "🔄 Resubmit for AI Review"}
              </>
            )}
          </button>

          {aiStatus === "not_submitted" && (
            <div style={{ fontSize: 11, color: "var(--ink-3, #9ca3af)", marginTop: 6, lineHeight: 1.5 }}>
              VeriBridge AI will review your evidence package. This usually takes around 5 minutes.
              No human reviewer has been assigned yet.
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          style={{
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 12,
            color: "#991b1b",
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      {/* ── Divider ───────────────────────────────────────────────────────── */}
      <div style={{ borderTop: "1px solid var(--line-2, #f3f4f6)", margin: "12px 0" }} />

      {/* ── Track B: Human Review Status ──────────────────────────────────── */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-3, #9ca3af)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
          Human / Faculty / Expert Review
        </div>

        {/* Current human status */}
        <div style={{ fontSize: 12, color: "var(--ink-2, #374151)", marginBottom: 10 }}>
          Current status:{" "}
          <strong>
            {humanStatus === "human_verified"
              ? "✅ Human Verified"
              : humanStatus === "faculty_reviewed"
              ? "👩‍🏫 Faculty Reviewed"
              : humanStatus === "company_reviewed"
              ? "🏢 Company / Mentor Reviewed"
              : humanStatus === "domain_expert_reviewed"
              ? "🎓 Domain Expert Reviewed"
              : humanStatus === "human_review_not_requested"
              ? "Not Requested"
              : humanStatusLabel(humanStatus)}
          </strong>
        </div>

        {/* Placeholder action buttons */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <HumanReviewPlaceholderButton
            icon="👩‍🏫"
            label="Request Faculty Review"
            description="Ask a WPI professor or faculty member to review your evidence."
          />
          <HumanReviewPlaceholderButton
            icon="🎓"
            label="Request Domain Expert Review"
            description="Request review from a domain expert in your field of work."
          />
          <HumanReviewPlaceholderButton
            icon="🏢"
            label="Request Company / Mentor Review"
            description="Ask your supervisor or company mentor to verify your work."
          />
        </div>

        {/* Explanation */}
        <div
          style={{
            background: "var(--bg-2, #f9fafb)",
            borderRadius: 8,
            padding: "10px 12px",
            marginTop: 12,
            fontSize: 11,
            color: "var(--ink-3, #6b7280)",
            lineHeight: 1.6,
          }}
        >
          <strong style={{ color: "var(--ink-2, #374151)" }}>About human review:</strong> Human review
          is optional and will become available as VeriBridge adds faculty, company, and domain expert
          reviewers. We are planning to invite WPI professors and field experts to join the program.
          A proof marked &quot;VeriBridge AI Reviewed&quot; has passed AI checks — human or faculty review
          is an additional layer and has not yet been completed.
        </div>

        {/* Recruiter display note */}
        <div
          style={{
            marginTop: 10,
            fontSize: 11,
            color: "var(--ink-3, #6b7280)",
            lineHeight: 1.5,
          }}
        >
          <strong style={{ color: "var(--ink-2, #374151)" }}>What recruiters see:</strong>{" "}
          {isApproved
            ? "\"VeriBridge AI Reviewed\" — honest and accurate. Human review will be shown separately once completed."
            : "No review badge yet. Submit for AI review to get your \"VeriBridge AI Reviewed\" badge."}
        </div>
      </div>
    </div>
  )
}

// ── Sub-component: placeholder human review button ────────────────────────────

function HumanReviewPlaceholderButton({
  icon,
  label,
  description,
}: {
  icon: string
  label: string
  description: string
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        background: "var(--bg-2, #f9fafb)",
        border: "1px solid var(--line-2, #e5e7eb)",
        borderRadius: 10,
        padding: "10px 14px",
        opacity: 0.7,
      }}
    >
      <span style={{ fontSize: 16 }}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-2, #374151)" }}>
          {label}
          <span
            style={{
              display: "inline-block",
              marginLeft: 8,
              fontSize: 10,
              fontWeight: 600,
              background: "#f3f4f6",
              color: "#6b7280",
              borderRadius: 4,
              padding: "1px 6px",
              verticalAlign: "middle",
            }}
          >
            Coming Soon
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--ink-3, #9ca3af)", marginTop: 1 }}>
          {description}
        </div>
      </div>
      <button
        type="button"
        disabled
        aria-disabled="true"
        style={{
          background: "var(--bg-3, #e5e7eb)",
          color: "var(--ink-3, #9ca3af)",
          border: "none",
          borderRadius: 8,
          padding: "6px 12px",
          fontWeight: 600,
          fontSize: 11,
          cursor: "not-allowed",
        }}
      >
        Request
      </button>
    </div>
  )
}
