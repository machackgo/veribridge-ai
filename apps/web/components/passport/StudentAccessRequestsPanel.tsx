"use client"

/**
 * StudentAccessRequestsPanel
 *
 * Self-contained student-facing UI for reviewing recruiter evidence access
 * requests. Supports approve / deny / revoke with confirmation modals.
 *
 * Can be used with either:
 *  - real API data (pass `requests` prop)
 *  - mock/local state (omit `requests` prop — uses built-in mock data)
 *
 * Privacy rules:
 *  - Never renders media_storage_path, private storage URLs, access tokens,
 *    admin notes, debug metadata, or raw private risk metadata.
 *  - Displayed text is always student-safe / recruiter-safe.
 */

import { useState } from "react"

// ── Types ─────────────────────────────────────────────────────────────────────

export type AccessRequestStatus = "pending" | "approved" | "denied" | "revoked"

export type StudentAccessRequest = {
  id: string
  requester_name: string
  requester_email: string
  requester_organization?: string | null
  requester_role?: string | null
  requested_sections: string[]
  request_reason?: string | null
  optional_message?: string | null
  status: AccessRequestStatus
  requested_at: string
}

// ── Evidence section labels ────────────────────────────────────────────────────

const SECTION_LABELS: Record<string, string> = {
  workflow_recordings: "Workflow recordings",
  project_defense: "Project defense media / transcript",
  documents: "Uploaded documents / reports",
  detailed_skill_evidence: "Detailed skill evidence",
  github_analysis: "GitHub repository analysis",
  ai_domain_review: "AI domain review",
  workflow_analysis: "Workflow analysis",
  readiness_report: "Readiness report",
}

function sectionLabel(s: string) {
  return SECTION_LABELS[s] ?? s.replace(/_/g, " ")
}

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_REQUESTS: StudentAccessRequest[] = [
  {
    id: "req-stripe-001",
    requester_name: "Stripe Early Talent",
    requester_email: "recruiter@stripe.com",
    requester_organization: "Stripe",
    requester_role: "Early Talent / AI Intern Hiring",
    requested_sections: ["workflow_recordings", "project_defense", "detailed_skill_evidence"],
    request_reason: "Reviewing your profile for an AI internship role on our applied ML team.",
    optional_message: "Hi! We're excited about your browser ML project and would love to see the full evidence.",
    status: "pending",
    requested_at: "2026-05-28T10:30:00Z",
  },
  {
    id: "req-wpi-002",
    requester_name: "WPI Faculty Reviewer",
    requester_email: "faculty@wpi.edu",
    requester_organization: "Worcester Polytechnic Institute",
    requester_role: "Faculty / Academic Reviewer",
    requested_sections: ["documents", "detailed_skill_evidence"],
    request_reason: "Portfolio review for graduate program research credit assessment.",
    status: "approved",
    requested_at: "2026-05-20T14:00:00Z",
  },
  {
    id: "req-acme-003",
    requester_name: "Acme Robotics",
    requester_email: "recruiter@acme.com",
    requester_organization: "Acme Robotics",
    requester_role: "Engineering Recruiter",
    requested_sections: ["workflow_recordings"],
    request_reason: "Evaluating candidates for a robotics software internship.",
    status: "denied",
    requested_at: "2026-05-15T09:00:00Z",
  },
]

// ── Design tokens ─────────────────────────────────────────────────────────────

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
  amber: "#d97706",
  amberSoft: "#fffbeb",
  rose: "#e11d48",
  roseSoft: "#fff1f2",
}

function statusColor(s: AccessRequestStatus) {
  return s === "approved" ? C.emerald : s === "pending" ? C.amber : C.rose
}
function statusBg(s: AccessRequestStatus) {
  return s === "approved" ? C.emeraldSoft : s === "pending" ? C.amberSoft : C.roseSoft
}
function statusBorder(s: AccessRequestStatus) {
  return s === "approved" ? "#bbf7d0" : s === "pending" ? "#fde68a" : "#fecaca"
}
function statusLabel(s: AccessRequestStatus) {
  return s === "revoked" ? "Revoked" : s === "denied" ? "Denied" : s === "approved" ? "Approved" : "Pending"
}

function requesterIcon(role: string | null | undefined) {
  if (!role) return "👤"
  const r = role.toLowerCase()
  if (r.includes("recruiter") || r.includes("hiring") || r.includes("talent")) return "🎯"
  if (r.includes("faculty") || r.includes("professor") || r.includes("academic")) return "🎓"
  if (r.includes("mentor")) return "🌟"
  if (r.includes("domain") || r.includes("expert")) return "🔬"
  return "🏢"
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
  } catch {
    return iso
  }
}

// ── Confirmation Modal ────────────────────────────────────────────────────────

type ModalKind = "approve" | "deny" | "revoke"

function ConfirmModal({
  kind,
  requesterName,
  defaultSections,
  onConfirm,
  onCancel,
}: {
  kind: ModalKind
  requesterName: string
  defaultSections: string[]
  onConfirm: (sections: string[]) => void
  onCancel: () => void
}) {
  const [selected, setSelected] = useState<string[]>(
    kind === "approve" ? defaultSections : [],
  )

  const toggle = (s: string) =>
    setSelected((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
    )

  const isApprove = kind === "approve"
  const isDeny = kind === "deny"
  const isRevoke = kind === "revoke"

  return (
    <div
      data-testid={`confirm-modal-${kind}`}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000, padding: "20px 16px",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel() }}
    >
      <div style={{
        background: C.paper, borderRadius: 12,
        width: "100%", maxWidth: 480,
        boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{ padding: "18px 20px 14px", borderBottom: `1px solid ${C.line}` }}>
          <h2 style={{ fontSize: 15, fontWeight: 800, color: C.ink, margin: 0 }}>
            {isApprove && "Approve protected evidence access?"}
            {isDeny && "Deny access request?"}
            {isRevoke && "Revoke access?"}
          </h2>
          <p style={{ fontSize: 12, color: C.muted, margin: "4px 0 0" }}>
            For {requesterName}
          </p>
        </div>

        {/* Body */}
        <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
          {isApprove && (
            <>
              <p style={{ fontSize: 13, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
                This recruiter will be allowed to view the protected evidence types you select. You can revoke access later.
              </p>
              <div>
                <p style={{ fontSize: 12, fontWeight: 600, color: C.inkSoft, margin: "0 0 8px" }}>
                  Evidence to approve
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {defaultSections.map((s) => (
                    <label
                      key={s}
                      style={{
                        display: "flex", alignItems: "center", gap: 10,
                        padding: "7px 10px",
                        background: selected.includes(s) ? C.indigoSoft : C.bg,
                        border: `1px solid ${selected.includes(s) ? "#c7d2fe" : C.line}`,
                        borderRadius: 7, cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(s)}
                        onChange={() => toggle(s)}
                        style={{ flexShrink: 0 }}
                      />
                      <span style={{ fontSize: 12, fontWeight: 600, color: C.ink }}>
                        {sectionLabel(s)}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </>
          )}

          {isDeny && (
            <p style={{ fontSize: 13, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
              This recruiter will not be able to access your protected evidence. The request will be marked as denied.
            </p>
          )}

          {isRevoke && (
            <p style={{ fontSize: 13, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
              This recruiter will no longer be able to view protected evidence. Their access grant will be revoked immediately.
            </p>
          )}
        </div>

        {/* Actions */}
        <div style={{
          padding: "12px 20px 18px",
          display: "flex", gap: 8, justifyContent: "flex-end",
        }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              background: C.bg, color: C.inkSoft,
              border: `1px solid ${C.line}`, borderRadius: 7,
              padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm(selected)}
            disabled={isApprove && selected.length === 0}
            style={{
              background: isApprove ? C.emerald : C.rose,
              color: "#fff", border: "none", borderRadius: 7,
              padding: "8px 16px", fontSize: 13, fontWeight: 700,
              cursor: isApprove && selected.length === 0 ? "not-allowed" : "pointer",
              opacity: isApprove && selected.length === 0 ? 0.5 : 1,
            }}
          >
            {isApprove && "Approve selected access"}
            {isDeny && "Deny request"}
            {isRevoke && "Revoke access"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Request Card ──────────────────────────────────────────────────────────────

function RequestCard({
  request,
  onApprove,
  onDeny,
  onRevoke,
}: {
  request: StudentAccessRequest
  onApprove: (id: string, sections: string[]) => void
  onDeny: (id: string) => void
  onRevoke: (id: string) => void
}) {
  const [modal, setModal] = useState<ModalKind | null>(null)

  return (
    <>
      <div
        data-testid={`request-card-${request.id}`}
        style={{
          background: C.paper,
          border: `1px solid ${statusBorder(request.status)}`,
          borderRadius: 10,
          padding: "16px 18px",
        }}
      >
        {/* Header row */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 10 }}>
          <span style={{ fontSize: 22, flexShrink: 0 }}>
            {requesterIcon(request.requester_role)}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 2 }}>
              <span style={{ fontWeight: 700, fontSize: 14, color: C.ink }}>
                {request.requester_name}
              </span>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
                background: statusBg(request.status),
                color: statusColor(request.status),
                border: `1px solid ${statusBorder(request.status)}`,
              }}>
                {statusLabel(request.status)}
              </span>
            </div>
            <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
              {request.requester_email}
              {request.requester_organization ? ` · ${request.requester_organization}` : ""}
              {request.requester_role ? ` · ${request.requester_role}` : ""}
            </p>
          </div>
          <span style={{ fontSize: 11, color: C.muted, flexShrink: 0 }}>
            {formatDate(request.requested_at)}
          </span>
        </div>

        {/* Requested evidence */}
        {request.requested_sections.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase", margin: "0 0 4px", letterSpacing: "0.06em" }}>
              Requested evidence
            </p>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {request.requested_sections.map((s) => (
                <span key={s} style={{
                  fontSize: 10, fontWeight: 600, padding: "2px 7px",
                  background: C.indigoSoft, color: C.indigo,
                  border: "1px solid #c7d2fe", borderRadius: 4,
                }}>
                  {sectionLabel(s)}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Reason */}
        {request.request_reason && (
          <div style={{
            padding: "8px 10px", background: C.bg,
            border: `1px solid ${C.line}`, borderRadius: 7, marginBottom: 8,
          }}>
            <p style={{ fontSize: 11, color: C.muted, margin: "0 0 2px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Reason
            </p>
            <p style={{ fontSize: 12, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
              {request.request_reason}
            </p>
          </div>
        )}

        {/* Optional message */}
        {request.optional_message && (
          <p style={{ fontSize: 11, color: C.muted, fontStyle: "italic", margin: "0 0 8px" }}>
            Message: "{request.optional_message}"
          </p>
        )}

        {/* Actions */}
        {request.status === "pending" && (
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
            <button
              type="button"
              data-testid={`approve-btn-${request.id}`}
              onClick={() => setModal("approve")}
              style={{
                background: C.emerald, color: "#fff",
                border: "none", borderRadius: 7,
                padding: "7px 14px", fontSize: 12, fontWeight: 700, cursor: "pointer",
              }}
            >
              Approve access
            </button>
            <button
              type="button"
              data-testid={`deny-btn-${request.id}`}
              onClick={() => setModal("deny")}
              style={{
                background: C.bg, color: C.rose,
                border: `1px solid #fca5a5`, borderRadius: 7,
                padding: "7px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer",
              }}
            >
              Deny
            </button>
          </div>
        )}

        {request.status === "approved" && (
          <button
            type="button"
            data-testid={`revoke-btn-${request.id}`}
            onClick={() => setModal("revoke")}
            style={{
              background: C.bg, color: C.rose,
              border: `1px solid #fca5a5`, borderRadius: 7,
              padding: "7px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}
          >
            Revoke
          </button>
        )}

        {(request.status === "denied" || request.status === "revoked") && (
          <p style={{ fontSize: 11, color: C.muted, fontStyle: "italic", margin: 0 }}>
            No further action required.
          </p>
        )}
      </div>

      {/* Confirmation modals */}
      {modal === "approve" && (
        <ConfirmModal
          kind="approve"
          requesterName={request.requester_name}
          defaultSections={request.requested_sections}
          onConfirm={(sections) => { onApprove(request.id, sections); setModal(null) }}
          onCancel={() => setModal(null)}
        />
      )}
      {modal === "deny" && (
        <ConfirmModal
          kind="deny"
          requesterName={request.requester_name}
          defaultSections={[]}
          onConfirm={() => { onDeny(request.id); setModal(null) }}
          onCancel={() => setModal(null)}
        />
      )}
      {modal === "revoke" && (
        <ConfirmModal
          kind="revoke"
          requesterName={request.requester_name}
          defaultSections={[]}
          onConfirm={() => { onRevoke(request.id); setModal(null) }}
          onCancel={() => setModal(null)}
        />
      )}
    </>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function StudentAccessRequestsPanel({
  requests: externalRequests,
  onApprove: externalApprove,
  onDeny: externalDeny,
  onRevoke: externalRevoke,
}: {
  /** If omitted, uses mock data so the panel works without a backend. */
  requests?: StudentAccessRequest[]
  /** Optional external approve handler (receives id + approved sections). */
  onApprove?: (id: string, sections: string[]) => void
  /** Optional external deny handler. */
  onDeny?: (id: string) => void
  /** Optional external revoke handler. */
  onRevoke?: (id: string) => void
}) {
  const [requests, setRequests] = useState<StudentAccessRequest[]>(
    externalRequests ?? MOCK_REQUESTS,
  )

  // Sync when external requests change (e.g. after store reload).
  const prevExternal = externalRequests
  if (externalRequests !== prevExternal && externalRequests !== undefined) {
    // no-op: useState initialises once; external callers re-render by passing new array
  }

  const update = (id: string, status: AccessRequestStatus) =>
    setRequests((prev) => prev.map((r) => (r.id === id ? { ...r, status } : r)))

  const handleApprove = (id: string, sections: string[]) => {
    update(id, "approved")
    externalApprove?.(id, sections)
  }

  const handleDeny = (id: string) => {
    update(id, "denied")
    externalDeny?.(id)
  }

  const handleRevoke = (id: string) => {
    update(id, "revoked")
    externalRevoke?.(id)
  }

  const pending = requests.filter((r) => r.status === "pending")
  const approved = requests.filter((r) => r.status === "approved")
  const historical = requests.filter((r) => r.status === "denied" || r.status === "revoked")

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Privacy callout */}
      <div
        data-testid="privacy-callout"
        style={{
          padding: "12px 16px",
          background: "#eef2ff",
          border: "1px solid #c7d2fe",
          borderRadius: 10,
          display: "flex",
          gap: 10,
          alignItems: "flex-start",
        }}
      >
        <span style={{ fontSize: 18, flexShrink: 0 }}>🛡</span>
        <div>
          <p style={{ fontSize: 13, fontWeight: 700, color: "#3730a3", margin: "0 0 4px" }}>
            You control who sees your protected evidence.
          </p>
          <p style={{ fontSize: 12, color: "#4338ca", margin: 0, lineHeight: 1.5 }}>
            Public skill summaries remain visible, but protected recordings, raw transcripts, and private documents require your approval before sharing.
          </p>
        </div>
      </div>

      {/* Pending */}
      {pending.length > 0 && (
        <section>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <h2 style={{ fontSize: 13, fontWeight: 700, color: C.inkSoft, margin: 0, textTransform: "uppercase", letterSpacing: "0.07em" }}>
              Pending Requests
            </h2>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 999,
              background: C.amberSoft, color: C.amber, border: "1px solid #fde68a",
            }}>
              {pending.length}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {pending.map((r) => (
              <RequestCard
                key={r.id}
                request={r}
                onApprove={handleApprove}
                onDeny={handleDeny}
                onRevoke={handleRevoke}
              />
            ))}
          </div>
        </section>
      )}

      {/* Approved */}
      {approved.length > 0 && (
        <section>
          <h2 style={{ fontSize: 13, fontWeight: 700, color: C.inkSoft, margin: "0 0 10px", textTransform: "uppercase", letterSpacing: "0.07em" }}>
            Active Access
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {approved.map((r) => (
              <RequestCard
                key={r.id}
                request={r}
                onApprove={handleApprove}
                onDeny={handleDeny}
                onRevoke={handleRevoke}
              />
            ))}
          </div>
        </section>
      )}

      {/* Historical */}
      {historical.length > 0 && (
        <section>
          <h2 style={{ fontSize: 13, fontWeight: 700, color: C.inkSoft, margin: "0 0 10px", textTransform: "uppercase", letterSpacing: "0.07em" }}>
            Previous Requests
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {historical.map((r) => (
              <RequestCard
                key={r.id}
                request={r}
                onApprove={handleApprove}
                onDeny={handleDeny}
                onRevoke={handleRevoke}
              />
            ))}
          </div>
        </section>
      )}

      {requests.length === 0 && (
        <div style={{
          textAlign: "center", padding: "40px 20px",
          color: C.muted, fontSize: 13,
        }}>
          No access requests yet. Recruiters and reviewers can request access to your protected evidence through your public Work Passport.
        </div>
      )}
    </div>
  )
}

export default StudentAccessRequestsPanel
