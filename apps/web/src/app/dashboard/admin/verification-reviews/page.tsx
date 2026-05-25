"use client"

/**
 * Admin: Verification Reviews Page
 * Route: /dashboard/admin/verification-reviews
 *
 * Shows all submitted verification review requests in an admin queue.
 * Displays:
 *   - Student proof session info
 *   - Readiness score + level
 *   - AI review status (Track A)
 *   - Human review status (Track B)
 *   - Privacy status
 *   - Action buttons (MVP: AI approval / request more evidence / flag privacy)
 *
 * Future placeholders (disabled):
 *   - Assign Faculty Reviewer
 *   - Assign Domain Expert
 *   - Assign Company Reviewer
 *
 * Wording enforced:
 *   - "AI Approved for Sharing" only for ai_approved_for_sharing
 *   - "Faculty Reviewed" only if reviewer_role = faculty_reviewer + completed
 *   - "Human Verified" only if actual human_review_status = human_verified
 *   - NEVER shows "Human Verified" for AI-only approved submissions
 */

import React, { useCallback, useEffect, useState } from "react"
import {
  type AdminReviewListItem,
  type AiReviewStatus,
  adminListReviews,
  adminSetDecision,
} from "@/lib/api"

// ── Helpers ───────────────────────────────────────────────────────────────────

function aiStatusColor(status: AiReviewStatus): string {
  switch (status) {
    case "ai_approved_for_sharing":    return "#065f46"
    case "needs_more_evidence":        return "#92400e"
    case "manual_review_recommended":  return "#1e40af"
    case "privacy_flagged":            return "#991b1b"
    case "ai_review_in_progress":
    case "submitted_for_ai_review":    return "#1d4ed8"
    default:                           return "#374151"
  }
}

function aiStatusBg(status: AiReviewStatus): string {
  switch (status) {
    case "ai_approved_for_sharing":    return "#d1fae5"
    case "needs_more_evidence":        return "#fef3c7"
    case "manual_review_recommended":  return "#dbeafe"
    case "privacy_flagged":            return "#fee2e2"
    case "ai_review_in_progress":
    case "submitted_for_ai_review":    return "#eff6ff"
    default:                           return "#f3f4f6"
  }
}

function aiStatusLabel(status: AiReviewStatus): string {
  const labels: Record<AiReviewStatus, string> = {
    not_submitted:               "Not Submitted",
    submitted_for_ai_review:     "Submitted",
    ai_review_in_progress:       "AI Review In Progress",
    ai_approved_for_sharing:     "AI Approved for Sharing",
    needs_more_evidence:         "Needs More Evidence",
    manual_review_recommended:   "Manual Review Recommended",
    privacy_flagged:             "Privacy Flagged",
  }
  return labels[status] ?? status
}

function readinessColor(level: string): string {
  switch (level) {
    case "strong":      return "#065f46"
    case "moderate":    return "#1e40af"
    case "weak":        return "#92400e"
    default:            return "#374151"
  }
}

function scoreBar(score: number) {
  const pct = Math.min(100, Math.max(0, score))
  const color = pct >= 80 ? "#059669" : pct >= 60 ? "#2563eb" : pct >= 40 ? "#d97706" : "#dc2626"
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          width: 80,
          height: 6,
          background: "#f3f4f6",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            borderRadius: 3,
            transition: "width 0.3s",
          }}
        />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color }}>{score}</span>
    </div>
  )
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

function shortId(id: string): string {
  return id.length > 18 ? `${id.slice(0, 8)}…` : id
}

// ── Action modal ──────────────────────────────────────────────────────────────

interface ActionModalProps {
  review: AdminReviewListItem
  onClose: () => void
  onDone: (updated: AdminReviewListItem) => void
}

function ActionModal({ review, onClose, onDone }: ActionModalProps) {
  const [targetStatus, setTargetStatus] = useState<AiReviewStatus>(
    review.ai_review_status === "ai_approved_for_sharing"
      ? "needs_more_evidence"
      : "ai_approved_for_sharing"
  )
  const [note, setNote] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setLoading(true)
    setError(null)
    try {
      const updated = await adminSetDecision(review.id, targetStatus, note)
      onDone({
        ...review,
        ai_review_status: updated.ai_review_status,
        ai_decision_summary: updated.ai_decision_summary,
        ai_review_completed_at: updated.ai_review_completed_at ?? null,
        updated_at: updated.updated_at,
      })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to set decision.")
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 16,
          padding: 28,
          width: "min(96vw, 480px)",
          boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>Set AI Review Decision</div>
        <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 16 }}>
          Session: <code>{shortId(review.proof_session_id)}</code> · Score: {review.readiness_score}/100
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#374151", display: "block", marginBottom: 6 }}>
            Decision
          </label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {(
              [
                ["ai_approved_for_sharing", "✅ AI Approved for Sharing"],
                ["needs_more_evidence", "⚠️ Needs More Evidence"],
                ["manual_review_recommended", "🔍 Manual Review Recommended"],
                ["privacy_flagged", "🔒 Privacy Flagged"],
              ] as [AiReviewStatus, string][]
            ).map(([val, label]) => (
              <label
                key={val}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "7px 10px",
                  border: `1px solid ${targetStatus === val ? "#3b82f6" : "#e5e7eb"}`,
                  borderRadius: 8,
                  background: targetStatus === val ? "#eff6ff" : "#fff",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: targetStatus === val ? 600 : 400,
                }}
              >
                <input
                  type="radio"
                  name="decision"
                  value={val}
                  checked={targetStatus === val}
                  onChange={() => setTargetStatus(val)}
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#374151", display: "block", marginBottom: 6 }}>
            Admin Note (optional)
          </label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Explain the decision…"
            rows={3}
            style={{
              width: "100%",
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              padding: "8px 10px",
              fontSize: 12,
              resize: "vertical",
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* Wording reminder */}
        <div
          style={{
            background: "#fef3c7",
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 11,
            color: "#92400e",
            marginBottom: 14,
          }}
        >
          ⚠️ This sets the <strong>AI review decision</strong>. It does NOT set
          &quot;Human Verified&quot; — that requires an actual human reviewer action.
        </div>

        {error && (
          <div style={{ background: "#fee2e2", borderRadius: 8, padding: "7px 10px", fontSize: 12, color: "#991b1b", marginBottom: 12 }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            style={{ border: "1px solid #e5e7eb", background: "#fff", color: "#374151", borderRadius: 8, padding: "8px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={loading}
            style={{ background: loading ? "#9ca3af" : "#1e40af", color: "#fff", border: "none", borderRadius: 8, padding: "8px 18px", fontWeight: 700, fontSize: 13, cursor: loading ? "not-allowed" : "pointer" }}
          >
            {loading ? "Saving…" : "Save Decision"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Review row ────────────────────────────────────────────────────────────────

function ReviewRow({
  item,
  onAction,
}: {
  item: AdminReviewListItem
  onAction: (item: AdminReviewListItem) => void
}) {
  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: "16px 18px",
        background: "#fff",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {/* Row header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#111", fontFamily: "monospace" }}>
            Session {shortId(item.proof_session_id)}
          </div>
          <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>
            User: {shortId(item.user_id)} · Submitted: {formatDate(item.submitted_at)}
          </div>
        </div>

        {/* AI review badge */}
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            background: aiStatusBg(item.ai_review_status),
            color: aiStatusColor(item.ai_review_status),
            borderRadius: 8,
            padding: "4px 10px",
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {aiStatusLabel(item.ai_review_status)}
        </div>
      </div>

      {/* Stats row */}
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 10, color: "#9ca3af", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>Readiness</div>
          {scoreBar(item.readiness_score)}
          <div style={{ fontSize: 10, color: readinessColor(item.readiness_level), fontWeight: 600, marginTop: 2 }}>
            {item.readiness_level}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 10, color: "#9ca3af", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>Human Review</div>
          <div style={{ fontSize: 12, color: "#374151", fontWeight: 500 }}>
            {item.human_review_status === "human_verified"
              ? "✅ Human Verified"
              : item.human_review_status === "human_review_not_requested"
              ? "Not Requested"
              : item.human_review_status.replace(/_/g, " ")}
          </div>
        </div>

        {item.ai_review_completed_at && (
          <div>
            <div style={{ fontSize: 10, color: "#9ca3af", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>Reviewed At</div>
            <div style={{ fontSize: 11, color: "#374151" }}>{formatDate(item.ai_review_completed_at)}</div>
          </div>
        )}
      </div>

      {/* Decision summary */}
      {item.ai_decision_summary && (
        <div style={{ fontSize: 11, color: "#6b7280", lineHeight: 1.6, background: "#f9fafb", borderRadius: 8, padding: "7px 10px" }}>
          {item.ai_decision_summary}
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {/* MVP: set AI decision */}
        <button
          type="button"
          onClick={() => onAction(item)}
          style={{
            background: "#1e40af",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "7px 14px",
            fontWeight: 600,
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          Set AI Decision
        </button>

        {/* Future placeholder buttons */}
        <FuturePlaceholderButton label="Assign Faculty Reviewer" />
        <FuturePlaceholderButton label="Assign Domain Expert" />
        <FuturePlaceholderButton label="Assign Company Reviewer" />
      </div>
    </div>
  )
}

function FuturePlaceholderButton({ label }: { label: string }) {
  return (
    <button
      type="button"
      disabled
      aria-disabled="true"
      title="Coming soon — once VeriBridge has a reviewer program"
      style={{
        background: "#f3f4f6",
        color: "#9ca3af",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: "7px 12px",
        fontWeight: 600,
        fontSize: 11,
        cursor: "not-allowed",
      }}
    >
      {label}
    </button>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminVerificationReviewsPage() {
  const [items, setItems] = useState<AdminReviewListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeItem, setActiveItem] = useState<AdminReviewListItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await adminListReviews()
      setItems(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load reviews.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const handleDecisionDone = (updated: AdminReviewListItem) => {
    setItems((prev) =>
      prev.map((i) => (i.id === updated.id ? updated : i))
    )
    setActiveItem(null)
  }

  return (
    <div
      style={{
        maxWidth: 840,
        margin: "0 auto",
        padding: "32px 20px",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, margin: 0, color: "#111" }}>
            Verification Reviews
          </h1>
          <p style={{ fontSize: 13, color: "#6b7280", marginTop: 4, marginBottom: 0 }}>
            Admin queue — AI review decisions + future human reviewer program
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          style={{
            background: "#f3f4f6",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: "8px 16px",
            fontWeight: 600,
            fontSize: 13,
            cursor: loading ? "not-allowed" : "pointer",
            color: "#374151",
          }}
        >
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {/* Wording notice */}
      <div
        style={{
          background: "#fef3c7",
          border: "1px solid #fde68a",
          borderRadius: 10,
          padding: "10px 14px",
          fontSize: 12,
          color: "#78350f",
          marginBottom: 20,
          lineHeight: 1.6,
        }}
      >
        <strong>Wording policy:</strong> Show &quot;AI Approved for Sharing&quot; or &quot;VeriBridge AI Reviewed&quot; for
        AI-approved submissions. Show &quot;Faculty Reviewed&quot; / &quot;Company Reviewed&quot; / &quot;Domain Expert Reviewed&quot;
        only when an actual reviewer with that role has completed their review. Show &quot;Human Verified&quot;
        only when <code>human_review_status = human_verified</code> — never automatically.
      </div>

      {/* Stats row */}
      <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
        {(
          [
            ["Total", items.length, "#374151"],
            ["AI Approved", items.filter(i => i.ai_review_status === "ai_approved_for_sharing").length, "#065f46"],
            ["Needs Evidence", items.filter(i => i.ai_review_status === "needs_more_evidence").length, "#92400e"],
            ["Manual Review", items.filter(i => i.ai_review_status === "manual_review_recommended").length, "#1e40af"],
            ["Privacy Flagged", items.filter(i => i.ai_review_status === "privacy_flagged").length, "#991b1b"],
            ["Human Verified", items.filter(i => i.human_review_status === "human_verified").length, "#065f46"],
          ] as [string, number, string][]
        ).map(([label, count, color]) => (
          <div
            key={label}
            style={{
              background: "#fff",
              border: "1px solid #e5e7eb",
              borderRadius: 10,
              padding: "10px 16px",
              minWidth: 100,
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 20, fontWeight: 800, color }}>{count}</div>
            <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div style={{ background: "#fee2e2", borderRadius: 10, padding: "12px 16px", fontSize: 13, color: "#991b1b", marginBottom: 20 }}>
          {error}
        </div>
      )}

      {/* List */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 48, color: "#9ca3af", fontSize: 14 }}>
          Loading reviews…
        </div>
      ) : items.length === 0 ? (
        <div
          style={{
            textAlign: "center",
            padding: 48,
            background: "#f9fafb",
            borderRadius: 14,
            border: "1px solid #e5e7eb",
          }}
        >
          <div style={{ fontSize: 32, marginBottom: 8 }}>📋</div>
          <div style={{ fontSize: 14, color: "#6b7280" }}>No review requests yet.</div>
          <div style={{ fontSize: 12, color: "#9ca3af", marginTop: 4 }}>
            Reviews appear here once students submit their evidence for AI review.
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {items.map((item) => (
            <ReviewRow key={item.id} item={item} onAction={setActiveItem} />
          ))}
        </div>
      )}

      {/* Action modal */}
      {activeItem !== null && (
        <ActionModal
          review={activeItem}
          onClose={() => setActiveItem(null)}
          onDone={handleDecisionDone}
        />
      )}
    </div>
  )
}
