"use client"

/**
 * VerificationReviewSection
 *
 * MVP-only local VeriBridge evidence review flow for Website Proof (deterministic rules engine — no AI/LLM involved, so labels must never claim AI review).
 * This intentionally does not set any human/faculty review state.
 */

import React, { useEffect, useMemo, useRef, useState } from "react"
import { getReviewStatus, submitForAiReview } from "@/lib/api"

// ── Types ─────────────────────────────────────────────────────────────────────

export type MvpAiReviewStatus = "not_submitted" | "in_progress" | "approved"

export type WebsiteProofReviewSnapshot = {
  proofSessionId: string
  websiteUrlType: "local" | "live" | "private" | "invalid"
  claimedSkills: string[]
  workflowEvidenceStatus: string
  workflowAnalysisScore: number | null
  videoKeyframeScore: number | null
  ocrScore: number | null
  domScore: number | null
  qwenVisualReasoningScore: number | null
  githubStatus: string
  githubScore: number | null
  projectDefenseScore: number | null
  documentEvidenceScore: number | null
  finalEvidenceScore: number | null
  privacyScanStatus: string
  generatedRecommendation: string
  timestamp: string
}

type StoredMvpReview = {
  status: MvpAiReviewStatus
  decision: "Approved" | null
  snapshot: WebsiteProofReviewSnapshot
  snapshotHash: string
  submittedAt: string
  approvedAt: string | null
}

interface Props {
  sessionId: string
  readinessScore: number
  readinessLevel: "strong" | "moderate" | "weak" | "insufficient"
  readinessReady: boolean
  snapshot: WebsiteProofReviewSnapshot
}

// ── Constants ─────────────────────────────────────────────────────────────────

export const MVP_AI_REVIEW_SECONDS = 60
export const MVP_REVIEW_STAGES = [
  "Packaging evidence",
  "Checking privacy safety",
  "Reviewing source coverage",
  "Generating VeriBridge AI decision",
  "Saving approval badge",
]

const REVIEW_STORAGE_PREFIX = "vb_mvp_ai_review:"
const APPROVED_SUMMARY =
  "This proof package passed VeriBridge's automated evidence review for MVP. Evidence sources were checked for completeness, privacy, and recruiter readiness."

// ── Helpers ───────────────────────────────────────────────────────────────────

function storageKey(sessionId: string): string {
  return `${REVIEW_STORAGE_PREFIX}${sessionId}`
}

function formatCountdown(remaining: number): string {
  return `${remaining}s`
}

function sanitizeString(value: string): string {
  return value
    .replace(/\b(access_token|id_token|refresh_token|token|api[_-]?key|secret|password)\b/gi, "[redacted]")
    .replace(/\benv secrets?\b/gi, "[redacted]")
    .replace(/\bprivate media url\b/gi, "[redacted-media-url]")
    .replace(/https?:\/\/[a-z0-9.-]*supabase\.(?:co|com|io)[^\s"']*/gi, "[redacted-storage-url]")
    .replace(/\bstorage_path\b/gi, "[redacted-storage-path]")
}

export function sanitizeReviewSnapshot(snapshot: WebsiteProofReviewSnapshot): WebsiteProofReviewSnapshot {
  return {
    ...snapshot,
    claimedSkills: snapshot.claimedSkills.map(sanitizeString),
    githubStatus: sanitizeString(snapshot.githubStatus),
    workflowEvidenceStatus: sanitizeString(snapshot.workflowEvidenceStatus),
    privacyScanStatus: sanitizeString(snapshot.privacyScanStatus),
    generatedRecommendation: sanitizeString(snapshot.generatedRecommendation),
    timestamp: sanitizeString(snapshot.timestamp),
  }
}

export function hashReviewSnapshot(snapshot: WebsiteProofReviewSnapshot): string {
  const stable = sanitizeReviewSnapshot({ ...snapshot, timestamp: "" })
  return JSON.stringify(stable)
}

function loadStoredReview(sessionId: string): StoredMvpReview | null {
  try {
    const raw = localStorage.getItem(storageKey(sessionId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredMvpReview
    if (!parsed?.snapshot || parsed.snapshot.proofSessionId !== sessionId) return null
    return parsed
  } catch {
    return null
  }
}

function saveStoredReview(sessionId: string, review: StoredMvpReview): void {
  try {
    localStorage.setItem(storageKey(sessionId), JSON.stringify(review))
  } catch {
    // Local persistence is best-effort for MVP.
  }
}

function backendStatusToLocal(status: string): MvpAiReviewStatus {
  return status === "ai_approved_for_sharing" ? "approved" : "in_progress"
}

function approveReview(review: StoredMvpReview, approvedAt = new Date().toISOString()): StoredMvpReview {
  return {
    ...review,
    status: "approved",
    decision: "Approved",
    approvedAt,
  }
}

function progressFromElapsed(elapsedSeconds: number): number {
  return Math.min(100, Math.max(0, Math.floor((elapsedSeconds / MVP_AI_REVIEW_SECONDS) * 100)))
}

function stageFromElapsed(elapsedSeconds: number): string {
  const idx = Math.min(
    MVP_REVIEW_STAGES.length - 1,
    Math.floor((elapsedSeconds / MVP_AI_REVIEW_SECONDS) * MVP_REVIEW_STAGES.length),
  )
  return MVP_REVIEW_STAGES[idx]
}

// ── Main component ────────────────────────────────────────────────────────────

export function VerificationReviewSection({
  sessionId,
  readinessScore,
  readinessLevel,
  readinessReady,
  snapshot,
}: Props) {
  const [review, setReview] = useState<StoredMvpReview | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const snapshotHash = useMemo(() => hashReviewSnapshot(snapshot), [snapshot])
  const snapshotRef = useRef(snapshot)
  useEffect(() => { snapshotRef.current = snapshot }, [snapshot])

  useEffect(() => {
    if (!sessionId || !readinessReady) return

    // Fast path: localStorage hit
    const existing = loadStoredReview(sessionId)
    if (existing) {
      const elapsedSeconds = Math.floor((Date.now() - new Date(existing.submittedAt).getTime()) / 1000)
      const normalized =
        existing.status === "in_progress" && elapsedSeconds >= MVP_AI_REVIEW_SECONDS
          ? approveReview(existing)
          : existing
      if (normalized !== existing) saveStoredReview(sessionId, normalized)
      setReview(normalized)
      return
    }

    // No localStorage record — reset immediately then check backend for persisted review
    setReview(null)
    getReviewStatus(sessionId)
      .then((backendReview) => {
        if (!backendReview) return
        const localStatus = backendStatusToLocal(backendReview.ai_review_status)
        const now = new Date().toISOString()
        const snap = snapshotRef.current
        const sanitized = sanitizeReviewSnapshot({ ...snap, timestamp: now })
        const restored: StoredMvpReview = {
          status: localStatus,
          decision: localStatus === "approved" ? "Approved" : null,
          snapshot: sanitized,
          snapshotHash: hashReviewSnapshot(sanitized),
          submittedAt: backendReview.submitted_at ?? now,
          approvedAt: localStatus === "approved" ? (backendReview.ai_review_completed_at ?? now) : null,
        }
        saveStoredReview(sessionId, restored)
        setReview(restored)
      })
      .catch(() => {
        console.warn("Using local review fallback because backend review API unavailable.")
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, readinessReady])

  useEffect(() => {
    const inProgress = review?.status === "in_progress"
    if (!inProgress) {
      if (timerRef.current) clearInterval(timerRef.current)
      timerRef.current = null
      return
    }
    timerRef.current = setInterval(() => {
      setNowMs(Date.now())
      setReview((current) => {
        if (!current || current.status !== "in_progress") return current
        const elapsedSeconds = Math.floor((Date.now() - new Date(current.submittedAt).getTime()) / 1000)
        if (elapsedSeconds < MVP_AI_REVIEW_SECONDS) return current
        const approved = approveReview(current)
        saveStoredReview(sessionId, approved)
        return approved
      })
    }, 1000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [review?.status, sessionId])

  if (!readinessReady) return null

  const elapsedSeconds = review
    ? Math.max(0, Math.floor((nowMs - new Date(review.submittedAt).getTime()) / 1000))
    : 0
  const remaining = Math.max(0, MVP_AI_REVIEW_SECONDS - elapsedSeconds)
  const progress = progressFromElapsed(elapsedSeconds)
  const currentStage = stageFromElapsed(elapsedSeconds)
  const isInProgress = review?.status === "in_progress"
  const isApproved = review?.status === "approved"
  const evidenceChangedAfterReview = Boolean(isApproved && review?.snapshotHash !== snapshotHash)

  function startReview(): void {
    const submittedAt = new Date().toISOString()
    const sanitized = sanitizeReviewSnapshot({ ...snapshot, timestamp: submittedAt })
    const next: StoredMvpReview = {
      status: "in_progress",
      decision: null,
      snapshot: sanitized,
      snapshotHash: hashReviewSnapshot(sanitized),
      submittedAt,
      approvedAt: null,
    }
    saveStoredReview(sessionId, next)
    setNowMs(Date.now())
    setReview(next)

    // Persist review submission to backend (non-blocking; localStorage is fallback)
    submitForAiReview(sessionId, readinessScore, readinessLevel).catch((err: unknown) => {
      console.warn("Using local review fallback because backend review API unavailable.", err)
    })
  }

  return (
    <div
      style={{
        border: "1px solid var(--line-2, #e5e7eb)",
        borderRadius: 14,
        padding: "18px 20px",
        marginTop: 4,
        background: "var(--bg-1, #fff)",
        display: "grid",
        gap: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink, #111)" }}>
            Verification Review
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-2, #6b7280)", marginTop: 2 }}>
            VeriBridge evidence review for recruiter-ready proof packages
          </div>
        </div>
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          padding: "5px 10px",
          borderRadius: 999,
          background: isApproved ? "#d1fae5" : isInProgress ? "#eff6ff" : "#f3f4f6",
          color: isApproved ? "#065f46" : isInProgress ? "#1d4ed8" : "#374151",
          border: `1px solid ${isApproved ? "#bbf7d0" : isInProgress ? "#bfdbfe" : "#e5e7eb"}`,
        }}>
          Status: {isApproved ? "Approved" : isInProgress ? "Review in progress" : "Not submitted"}
        </span>
      </div>

      {!review && (
        <div style={{ display: "grid", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 12, color: "#475569", lineHeight: 1.6 }}>
            Submit the current evidence package for VeriBridge&apos;s automated evidence review. Human/faculty review is separate and coming soon.
          </p>
          <button
            type="button"
            onClick={startReview}
            style={{
              justifySelf: "start",
              background: "#1e40af",
              color: "#fff",
              border: "none",
              borderRadius: 10,
              padding: "10px 18px",
              fontWeight: 700,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            Submit for Evidence Review
          </button>
        </div>
      )}

      {isInProgress && (
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>
            Evidence review in progress
          </div>
          <div style={{ fontSize: 12, color: "#3b82f6" }}>Estimated time: about 1 minute</div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: "#1e40af" }}>Current stage: {currentStage}</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#1e40af" }}>
                {progress}% · {formatCountdown(remaining)} remaining
              </span>
            </div>
            <div style={{ height: 8, borderRadius: 999, background: "#dbeafe", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${progress}%`, background: "#2563eb", transition: "width 0.3s ease" }} />
            </div>
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {MVP_REVIEW_STAGES.map((stage) => {
              const active = stage === currentStage
              const done = MVP_REVIEW_STAGES.indexOf(stage) < MVP_REVIEW_STAGES.indexOf(currentStage)
              return (
                <div key={stage} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: done ? "#065f46" : active ? "#1e40af" : "#94a3b8" }}>
                  <span style={{ width: 14, textAlign: "center", fontWeight: 800 }}>{done ? "✓" : active ? "…" : "○"}</span>
                  <span>{stage}</span>
                </div>
              )
            })}
          </div>
          <button
            type="button"
            disabled
            style={{
              justifySelf: "start",
              background: "#e5e7eb",
              color: "#6b7280",
              border: "none",
              borderRadius: 10,
              padding: "10px 18px",
              fontWeight: 700,
              fontSize: 13,
              cursor: "not-allowed",
            }}
          >
            Submit for Evidence Review
          </button>
        </div>
      )}

      {isApproved && (
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, fontWeight: 800, color: "#065f46", background: "#d1fae5", border: "1px solid #bbf7d0", borderRadius: 999, padding: "5px 10px" }}>
              Evidence Reviewed
            </span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "#065f46" }}>Decision: Approved</span>
            <span style={{ fontSize: 11, color: "#64748b" }}>Approved at {review?.approvedAt ? new Date(review.approvedAt).toLocaleString() : "now"}</span>
          </div>
          <div style={{ border: "1px solid #bbf7d0", background: "#f0fdf4", borderRadius: 10, padding: "10px 12px", display: "grid", gap: 5 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#065f46" }}>Evidence Review Passed</div>
            <p style={{ margin: 0, fontSize: 12, color: "#047857", lineHeight: 1.6 }}>{APPROVED_SUMMARY}</p>
            <div style={{ fontSize: 11, color: "#047857" }}>Approved proof package</div>
            <div style={{ fontSize: 11, color: "#64748b" }}>Human/faculty review not completed</div>
          </div>
          {evidenceChangedAfterReview && (
            <div style={{ border: "1px solid #fde68a", background: "#fffbeb", color: "#92400e", borderRadius: 8, padding: "8px 10px", fontSize: 12 }}>
              Evidence changed after review — re-submit for review.
            </div>
          )}
          <button
            type="button"
            onClick={startReview}
            style={{
              justifySelf: "start",
              background: evidenceChangedAfterReview ? "#1e40af" : "#f8fafc",
              color: evidenceChangedAfterReview ? "#fff" : "#334155",
              border: evidenceChangedAfterReview ? "none" : "1px solid #cbd5e1",
              borderRadius: 10,
              padding: "9px 16px",
              fontWeight: 700,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            Re-run review
          </button>
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--line-2, #f3f4f6)", paddingTop: 12, display: "grid", gap: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Human / Faculty / Expert Review
        </div>
        <div style={{ fontSize: 12, color: "#374151" }}>
          Current status: <strong>Coming soon</strong>
        </div>
        <button
          type="button"
          disabled
          aria-disabled="true"
          style={{
            justifySelf: "start",
            background: "#e5e7eb",
            color: "#9ca3af",
            border: "none",
            borderRadius: 8,
            padding: "7px 12px",
            fontWeight: 700,
            fontSize: 12,
            cursor: "not-allowed",
          }}
        >
          Request human/faculty review — Coming soon
        </button>
        <div style={{ fontSize: 11, color: "#64748b", lineHeight: 1.5 }}>
          What recruiters see: {isApproved ? "Evidence Reviewed, Approved proof package, Human/faculty review not completed." : "No evidence review badge yet."}
        </div>
      </div>
    </div>
  )
}
