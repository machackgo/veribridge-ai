"use client"

/**
 * EvidenceAccessRequestModal
 *
 * Recruiter-facing modal for requesting access to a student's protected evidence.
 * Supports both a real submission path (via onSubmit prop) and a mock/dev path
 * (when onSubmit is omitted, simulates success after a short delay).
 *
 * Privacy rules:
 *  - No media_storage_path, private storage URLs, access tokens, raw transcripts,
 *    admin notes, debug metadata, or private risk metadata are ever rendered.
 *  - All displayed text is recruiter-safe.
 */

import { useState } from "react"

// ── Types ─────────────────────────────────────────────────────────────────────

export type EvidenceAccessFormData = {
  requester_name: string
  requester_email: string
  company: string
  role: string
  reason: string
  requested_sections: string[]
  message_to_student: string
}

export type EvidenceAccessRequestModalProps = {
  /** Candidate display name shown in the modal title. */
  candidateName?: string | null
  /** Pre-fill recruiter fields (e.g. from a saved recruiter session). */
  defaultRequester?: Partial<Pick<EvidenceAccessFormData, "requester_name" | "requester_email" | "company" | "role">>
  /** Called with form data when recruiter submits.
   *  If omitted, the modal uses a mock submission (dev/preview mode). */
  onSubmit?: (data: EvidenceAccessFormData) => Promise<void>
  /** Called when the modal should close (cancel or after success close). */
  onClose: () => void
}

// ── Evidence section options ───────────────────────────────────────────────────

const EVIDENCE_OPTIONS: { id: string; label: string; description: string }[] = [
  {
    id: "workflow_recordings",
    label: "Workflow recordings",
    description: "Screen-captured browser workflow videos and keyframes",
  },
  {
    id: "project_defense",
    label: "Project defense media / transcript",
    description: "Defense recording summary and skill ownership analysis",
  },
  {
    id: "documents",
    label: "Uploaded documents / reports",
    description: "Project reports, technical write-ups, and certificates",
  },
  {
    id: "detailed_skill_evidence",
    label: "Detailed skill evidence",
    description: "Full evidence breakdown per skill with source attribution",
  },
]

// ── Styling constants ─────────────────────────────────────────────────────────

const C = {
  ink: "#0f172a",
  inkSoft: "#334155",
  muted: "#64748b",
  line: "#e2e8f0",
  bg: "#f8fafc",
  paper: "#ffffff",
  indigo: "#4f46e5",
  indigoSoft: "#eef2ff",
  emerald: "#059669",
  emeraldSoft: "#f0fdf4",
  rose: "#e11d48",
}

// ── Input field helper ────────────────────────────────────────────────────────

function Field({
  label,
  value,
  onChange,
  placeholder,
  required,
  type = "text",
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  required?: boolean
  type?: "text" | "email"
}) {
  return (
    <div>
      <label style={{
        fontSize: 12, fontWeight: 600, color: C.inkSoft,
        display: "block", marginBottom: 4,
      }}>
        {label}{required && <span style={{ color: C.rose, marginLeft: 2 }}>*</span>}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%",
          padding: "9px 12px",
          border: `1px solid ${C.line}`,
          borderRadius: 8,
          fontSize: 13,
          background: C.paper,
          color: C.ink,
          boxSizing: "border-box",
          outline: "none",
        }}
      />
    </div>
  )
}

// ── Success state ─────────────────────────────────────────────────────────────

function SuccessState({
  requestedSections,
  onClose,
}: {
  requestedSections: string[]
  onClose: () => void
}) {
  const sectionLabels = EVIDENCE_OPTIONS
    .filter((o) => requestedSections.includes(o.id))
    .map((o) => o.label)

  return (
    <div
      data-testid="access-request-success"
      style={{ display: "flex", flexDirection: "column", gap: 16, padding: "8px 0" }}
    >
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 44, marginBottom: 10 }}>📬</div>
        <p style={{ fontWeight: 700, fontSize: 16, color: C.emerald, margin: "0 0 6px" }}>
          Access request submitted for demo review
        </p>
        <p style={{ fontSize: 13, color: C.muted, margin: 0, lineHeight: 1.5 }}>
          Status: <strong style={{ color: C.inkSoft }}>Pending student approval</strong>
        </p>
      </div>

      {sectionLabels.length > 0 && (
        <div style={{
          padding: "12px 14px",
          background: C.indigoSoft,
          border: "1px solid #c7d2fe",
          borderRadius: 8,
        }}>
          <p style={{ fontSize: 11, fontWeight: 700, color: C.indigo, margin: "0 0 6px", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Requested evidence
          </p>
          <ul style={{ margin: 0, padding: "0 0 0 14px", display: "flex", flexDirection: "column", gap: 3 }}>
            {sectionLabels.map((lbl) => (
              <li key={lbl} style={{ fontSize: 12, color: C.inkSoft }}>{lbl}</li>
            ))}
          </ul>
        </div>
      )}

      <p style={{ fontSize: 12, color: C.muted, margin: 0, lineHeight: 1.5, textAlign: "center" }}>
        The student will be notified and must approve before any protected evidence is shared.
        You'll receive an email once they respond.
      </p>

      <button
        type="button"
        onClick={onClose}
        style={{
          background: C.indigo, color: "#fff",
          border: "none", borderRadius: 8,
          padding: "10px 20px", fontSize: 13, fontWeight: 700,
          cursor: "pointer", alignSelf: "center",
        }}
      >
        Close
      </button>
    </div>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────────

export function EvidenceAccessRequestModal({
  candidateName,
  defaultRequester,
  onSubmit,
  onClose,
}: EvidenceAccessRequestModalProps) {
  const [form, setForm] = useState<EvidenceAccessFormData>({
    requester_name: defaultRequester?.requester_name ?? "",
    requester_email: defaultRequester?.requester_email ?? "",
    company: defaultRequester?.company ?? "",
    role: defaultRequester?.role ?? "",
    reason: "",
    requested_sections: ["workflow_recordings", "project_defense", "detailed_skill_evidence"],
    message_to_student: "",
  })
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof EvidenceAccessFormData>(k: K, v: EvidenceAccessFormData[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  const toggleSection = (id: string) => {
    set(
      "requested_sections",
      form.requested_sections.includes(id)
        ? form.requested_sections.filter((s) => s !== id)
        : [...form.requested_sections, id],
    )
  }

  const canSubmit =
    form.requester_name.trim().length > 0 &&
    form.requester_email.trim().length > 0 &&
    form.requested_sections.length > 0

  const handleSubmit = async () => {
    if (!canSubmit || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      if (onSubmit) {
        await onSubmit(form)
      } else {
        // Dev/mock mode: simulate a short network delay
        await new Promise<void>((res) => setTimeout(res, 800))
      }
      setSubmitted(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Submission failed. Please try again.")
    } finally {
      setSubmitting(false)
    }
  }

  const name = candidateName ?? "this candidate"

  return (
    /* Backdrop */
    <div
      data-testid="access-request-modal"
      style={{
        position: "fixed", inset: 0,
        background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
        padding: "20px 16px",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      {/* Sheet */}
      <div style={{
        background: C.paper,
        borderRadius: 14,
        width: "100%",
        maxWidth: 540,
        maxHeight: "90vh",
        overflowY: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
        display: "flex",
        flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{
          padding: "20px 22px 16px",
          borderBottom: `1px solid ${C.line}`,
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
        }}>
          <span style={{ fontSize: 22, flexShrink: 0 }}>🔑</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontSize: 16, fontWeight: 800, color: C.ink, margin: "0 0 4px" }}>
              Request access to protected evidence
            </h2>
            <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
              For {name}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            style={{
              background: "none", border: "none",
              fontSize: 18, color: C.muted,
              cursor: "pointer", flexShrink: 0, padding: "2px 4px",
            }}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 16, flex: 1 }}>
          {submitted ? (
            <SuccessState requestedSections={form.requested_sections} onClose={onClose} />
          ) : (
            <>
              {/* Explanation */}
              <div style={{
                padding: "12px 14px",
                background: "#fef9c3",
                border: "1px solid #fde68a",
                borderRadius: 8,
              }}>
                <p style={{ fontSize: 12, color: "#78350f", margin: 0, lineHeight: 1.5 }}>
                  <strong>What requires access:</strong> Detailed workflow recordings, project defense media, raw transcripts, and private documents require student approval before viewing.
                </p>
              </div>

              {/* Privacy copy */}
              <div
                data-testid="privacy-consent-copy"
                style={{
                  padding: "10px 14px",
                  background: C.indigoSoft,
                  border: "1px solid #c7d2fe",
                  borderRadius: 8,
                }}
              >
                <p style={{ fontSize: 12, color: C.indigo, margin: "0 0 4px", fontWeight: 600 }}>
                  🛡 Students stay in control.
                </p>
                <p style={{ fontSize: 12, color: "#4338ca", margin: "0 0 4px", lineHeight: 1.5 }}>
                  VeriBridge will notify the student and only share protected evidence after approval.
                </p>
                <p style={{ fontSize: 11, color: "#6366f1", margin: 0 }}>
                  Public skill summaries remain visible without access.
                </p>
              </div>

              {/* Recruiter fields */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <Field
                  label="Your name" required
                  value={form.requester_name}
                  onChange={(v) => set("requester_name", v)}
                  placeholder="Jane Smith"
                />
                <Field
                  label="Work email" required type="email"
                  value={form.requester_email}
                  onChange={(v) => set("requester_email", v)}
                  placeholder="jane@company.com"
                />
                <Field
                  label="Company"
                  value={form.company}
                  onChange={(v) => set("company", v)}
                  placeholder="Acme Corp"
                />
                <Field
                  label="Role / hiring team"
                  value={form.role}
                  onChange={(v) => set("role", v)}
                  placeholder="Engineering Recruiter"
                />
              </div>

              {/* Evidence checkboxes */}
              <div>
                <p style={{ fontSize: 12, fontWeight: 600, color: C.inkSoft, margin: "0 0 8px" }}>
                  Evidence requested <span style={{ color: C.rose }}>*</span>
                </p>
                <div
                  data-testid="evidence-checkboxes"
                  style={{ display: "flex", flexDirection: "column", gap: 6 }}
                >
                  {EVIDENCE_OPTIONS.map((opt) => {
                    const checked = form.requested_sections.includes(opt.id)
                    return (
                      <label
                        key={opt.id}
                        style={{
                          display: "flex", alignItems: "flex-start", gap: 10,
                          padding: "8px 10px",
                          background: checked ? C.indigoSoft : C.bg,
                          border: `1px solid ${checked ? "#c7d2fe" : C.line}`,
                          borderRadius: 7,
                          cursor: "pointer",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleSection(opt.id)}
                          style={{ marginTop: 2, flexShrink: 0 }}
                        />
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: C.ink }}>
                            {opt.label}
                          </div>
                          <div style={{ fontSize: 11, color: C.muted, marginTop: 1 }}>
                            {opt.description}
                          </div>
                        </div>
                      </label>
                    )
                  })}
                </div>
              </div>

              {/* Reason */}
              <div>
                <label style={{ fontSize: 12, fontWeight: 600, color: C.inkSoft, display: "block", marginBottom: 4 }}>
                  Reason for request
                </label>
                <textarea
                  value={form.reason}
                  onChange={(e) => set("reason", e.target.value)}
                  placeholder="Briefly explain why you're requesting access…"
                  rows={2}
                  style={{
                    width: "100%", padding: "9px 12px",
                    border: `1px solid ${C.line}`, borderRadius: 8,
                    fontSize: 13, resize: "vertical",
                    boxSizing: "border-box", color: C.ink,
                  }}
                />
              </div>

              {/* Optional message */}
              <div>
                <label style={{ fontSize: 12, fontWeight: 600, color: C.inkSoft, display: "block", marginBottom: 4 }}>
                  Optional message to student
                </label>
                <textarea
                  value={form.message_to_student}
                  onChange={(e) => set("message_to_student", e.target.value)}
                  placeholder="Hi, I'm reviewing your profile for an AI internship role…"
                  rows={2}
                  style={{
                    width: "100%", padding: "9px 12px",
                    border: `1px solid ${C.line}`, borderRadius: 8,
                    fontSize: 13, resize: "vertical",
                    boxSizing: "border-box", color: C.ink,
                  }}
                />
              </div>

              {error && (
                <p style={{
                  fontSize: 12, color: C.rose,
                  background: "#fff1f2", padding: "8px 10px",
                  borderRadius: 6, margin: 0,
                }}>
                  {error}
                </p>
              )}

              {/* Actions */}
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", paddingTop: 4 }}>
                <button
                  type="button"
                  onClick={onClose}
                  style={{
                    background: C.bg, color: C.inkSoft,
                    border: `1px solid ${C.line}`, borderRadius: 8,
                    padding: "9px 18px", fontSize: 13, fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={!canSubmit || submitting}
                  style={{
                    background: canSubmit && !submitting ? C.indigo : "#94a3b8",
                    color: "#fff",
                    border: "none", borderRadius: 8,
                    padding: "9px 20px", fontSize: 13, fontWeight: 700,
                    cursor: canSubmit && !submitting ? "pointer" : "not-allowed",
                  }}
                >
                  {submitting ? "Submitting…" : "Submit request"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default EvidenceAccessRequestModal
