"use client"

import { useEffect, useState } from "react"
import {
  listAccessRequests,
  approveAccessRequest,
  denyAccessRequest,
  type EvidenceAccessRequestResponse,
  type EvidenceAccessGrantResponse,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  StatusBadge,
  TOKEN,
} from "./shared"

function requesterTypeIcon(role: string | null | undefined) {
  if (!role) return "👤"
  const r = role.toLowerCase()
  if (r.includes("recruiter") || r.includes("hiring")) return "🎯"
  if (r.includes("faculty") || r.includes("professor")) return "🎓"
  if (r.includes("mentor")) return "🌟"
  if (r.includes("domain") || r.includes("expert")) return "🔬"
  if (r.includes("company") || r.includes("reviewer")) return "🏢"
  return "👤"
}

function SectionTag({ section }: { section: string }) {
  const labels: Record<string, string> = {
    workflow: "Workflow Evidence",
    github: "GitHub Analysis",
    project_defense: "Project Defense",
    ai_domain_review: "AI Domain Review",
    evidence: "Evidence",
    "evidence/github": "GitHub Evidence",
    all: "All Evidence",
  }
  return (
    <Badge tone="sky">{labels[section] ?? section.replace(/_/g, " ")}</Badge>
  )
}

function AccessRequestCard({
  request,
  onApprove,
  onDeny,
  loadingState,
}: {
  request: EvidenceAccessRequestResponse
  onApprove: (id: string) => void
  onDeny: (id: string) => void
  loadingState: Record<string, boolean>
}) {
  const [decisionNotes, setDecisionNotes] = useState("")
  const [showNotesInput, setShowNotesInput] = useState<"approve" | "deny" | null>(null)

  const isPending = request.status === "pending"
  const isApproving = loadingState[`approve-${request.id}`]
  const isDenying = loadingState[`deny-${request.id}`]

  const handleApprove = () => {
    if (showNotesInput === "approve") {
      onApprove(request.id)
      setShowNotesInput(null)
    } else {
      setShowNotesInput("approve")
    }
  }

  const handleDeny = () => {
    if (showNotesInput === "deny") {
      onDeny(request.id)
      setShowNotesInput(null)
    } else {
      setShowNotesInput("deny")
    }
  }

  const statusTone =
    request.status === "approved"
      ? "emerald"
      : request.status === "denied" || request.status === "revoked"
      ? "rose"
      : request.status === "pending"
      ? "amber"
      : "slate"

  return (
    <Card style={{ padding: "16px 18px" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <div style={{ fontSize: 22, flexShrink: 0 }}>
          {requesterTypeIcon(request.requester_role)}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>
              {request.requester_name}
            </span>
            <Badge tone={statusTone}>{request.status}</Badge>
            {request.requester_role && (
              <Badge tone="slate">{request.requester_role}</Badge>
            )}
          </div>

          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 8px" }}>
            {request.requester_email}
            {request.requester_organization ? ` · ${request.requester_organization}` : ""}
          </p>

          {request.request_reason && (
            <div
              style={{
                padding: "8px 10px",
                background: TOKEN.bg,
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
                marginBottom: 10,
              }}
            >
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", display: "block", marginBottom: 2 }}>
                Reason
              </Mono>
              <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
                {request.request_reason}
              </p>
            </div>
          )}

          {/* Requested sections */}
          {request.requested_sections.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", display: "block", marginBottom: 4 }}>
                Requested Evidence
              </Mono>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {request.requested_sections.map((s: string) => (
                  <SectionTag key={s} section={s} />
                ))}
              </div>
            </div>
          )}

          {/* Decision notes (if already decided) */}
          {request.decision_notes && (
            <p style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}>
              Note: {request.decision_notes}
            </p>
          )}

          {/* Notes input for approve/deny */}
          {showNotesInput && isPending && (
            <div style={{ marginBottom: 10 }}>
              <textarea
                placeholder={`Optional notes for your ${showNotesInput} decision…`}
                value={decisionNotes}
                onChange={(e) => setDecisionNotes(e.target.value)}
                rows={2}
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  border: `1px solid ${TOKEN.line}`,
                  borderRadius: 8,
                  fontSize: 12,
                  resize: "vertical",
                  boxSizing: "border-box",
                }}
              />
            </div>
          )}

          {/* Actions */}
          {isPending && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Btn
                size="sm"
                variant="primary"
                onClick={handleApprove}
                disabled={isApproving}
                style={{ background: TOKEN.emerald }}
              >
                {isApproving ? "Approving…" : showNotesInput === "approve" ? "Confirm Approve" : "Approve"}
              </Btn>
              <Btn
                size="sm"
                variant="danger"
                onClick={handleDeny}
                disabled={isDenying}
              >
                {isDenying ? "Denying…" : showNotesInput === "deny" ? "Confirm Deny" : "Deny"}
              </Btn>
              {showNotesInput && (
                <Btn size="sm" variant="ghost" onClick={() => setShowNotesInput(null)}>
                  Cancel
                </Btn>
              )}
            </div>
          )}

          <Mono style={{ fontSize: 10, color: TOKEN.muted, marginTop: 8, display: "block" }}>
            Requested: {new Date(request.created_at).toLocaleDateString()}
            {request.decided_at && ` · Decided: ${new Date(request.decided_at).toLocaleDateString()}`}
          </Mono>
        </div>
      </div>
    </Card>
  )
}

export function AccessRequestManagerPanel({ sessionId }: { sessionId: string }) {
  const [requests, setRequests] = useState<EvidenceAccessRequestResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loadingState, setLoadingState] = useState<Record<string, boolean>>({})
  const [statusFilter, setStatusFilter] = useState<"all" | "pending" | "approved" | "denied">("all")

  const load = () => {
    setLoading(true)
    setError(null)
    listAccessRequests(sessionId)
      .then(setRequests)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [sessionId])

  const handleApprove = async (id: string) => {
    setLoadingState((prev) => ({ ...prev, [`approve-${id}`]: true }))
    try {
      await approveAccessRequest(id)
      setRequests((prev) =>
        prev.map((r) => (r.id === id ? { ...r, status: "approved" as const, decided_at: new Date().toISOString() } : r))
      )
    } catch {}
    setLoadingState((prev) => ({ ...prev, [`approve-${id}`]: false }))
  }

  const handleDeny = async (id: string) => {
    setLoadingState((prev) => ({ ...prev, [`deny-${id}`]: true }))
    try {
      await denyAccessRequest(id)
      setRequests((prev) =>
        prev.map((r) => (r.id === id ? { ...r, status: "denied" as const, decided_at: new Date().toISOString() } : r))
      )
    } catch {}
    setLoadingState((prev) => ({ ...prev, [`deny-${id}`]: false }))
  }

  const filtered = statusFilter === "all" ? requests : requests.filter((r) => r.status === statusFilter)
  const pendingCount = requests.filter((r) => r.status === "pending").length

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
            Access Requests
            {pendingCount > 0 && (
              <span
                style={{
                  marginLeft: 8,
                  fontSize: 12,
                  background: TOKEN.amber,
                  color: "#fff",
                  borderRadius: 999,
                  padding: "1px 8px",
                  fontWeight: 700,
                }}
              >
                {pendingCount} pending
              </span>
            )}
          </h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            You control who accesses your protected evidence. Approve or deny requests below.
          </p>
        </div>
        <Btn variant="secondary" size="sm" onClick={load}>Refresh</Btn>
      </div>

      {/* Trust copy */}
      <div
        style={{
          padding: "10px 14px",
          background: TOKEN.emeraldSoft,
          border: `1px solid #a7f3d0`,
          borderRadius: 10,
          display: "flex",
          gap: 8,
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 16 }}>🛡</span>
        <p style={{ fontSize: 12, color: "#065f46", margin: 0 }}>
          <strong>You are always in control.</strong> Protected evidence is only shared after you explicitly approve a request. Revoke access at any time.
        </p>
      </div>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 6 }}>
        {(["all", "pending", "approved", "denied"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            type="button"
            style={{
              padding: "5px 12px",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              border: `1px solid ${statusFilter === f ? TOKEN.indigo : TOKEN.line}`,
              background: statusFilter === f ? TOKEN.indigoSoft : TOKEN.paper,
              color: statusFilter === f ? TOKEN.indigo : TOKEN.muted,
              cursor: "pointer",
              textTransform: "capitalize",
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {loading && <LoadingState label="Loading access requests…" />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          icon="🔑"
          title={statusFilter === "all" ? "No access requests yet" : `No ${statusFilter} requests`}
          description={
            statusFilter === "all"
              ? "When recruiters or employers request access to your protected evidence, they'll appear here."
              : `No ${statusFilter} requests to show.`
          }
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((req) => (
            <AccessRequestCard
              key={req.id}
              request={req}
              onApprove={handleApprove}
              onDeny={handleDeny}
              loadingState={loadingState}
            />
          ))}
        </div>
      )}
    </div>
  )
}
