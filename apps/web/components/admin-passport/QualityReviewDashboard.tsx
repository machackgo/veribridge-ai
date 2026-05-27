"use client"

import { useEffect, useState } from "react"
import {
  listAdminQualityReviewCases,
  getAdminQualityReviewCase,
  updateAdminQualityReviewCase,
  listAdminQualityReviewEvents,
  runAdminQualityReviewScan,
  type AdminQualityReviewCaseResponse,
  type AdminQualityReviewEventResponse,
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
} from "../passport/shared"

const CASE_STATUSES = ["open", "under_review", "needs_student_action", "escalated", "resolved", "closed"]
const PRIORITIES = ["urgent", "high", "normal", "low"]

function CaseEventRow({ event }: { event: AdminQualityReviewEventResponse }) {
  const icons: Record<string, string> = {
    case_opened: "📂",
    status_changed: "🔄",
    decision_made: "⚖️",
    note_added: "📝",
    student_action_requested: "📢",
    resolved: "✅",
    escalated: "🚨",
  }
  return (
    <div style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: `1px solid ${TOKEN.line}`, alignItems: "flex-start" }}>
      <span style={{ fontSize: 14, flexShrink: 0 }}>{icons[event.event_type] ?? "📋"}</span>
      <div style={{ flex: 1 }}>
        <p style={{ fontSize: 13, color: TOKEN.ink, margin: "0 0 2px", fontWeight: 500 }}>{event.summary}</p>
        {event.notes && <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>{event.notes}</p>}
        <Mono style={{ fontSize: 10, color: TOKEN.muted, marginTop: 2 }}>
          {new Date(event.created_at).toLocaleString()} · {event.actor_type}
        </Mono>
      </div>
    </div>
  )
}

function CaseDetailPanel({
  caseId,
  onClose,
}: {
  caseId: string
  onClose: () => void
}) {
  const [caseData, setCaseData] = useState<AdminQualityReviewCaseResponse | null>(null)
  const [events, setEvents] = useState<AdminQualityReviewEventResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [updateForm, setUpdateForm] = useState<{
    status?: string
    priority?: string
    decision?: string
    decision_notes?: string
  }>({})

  useEffect(() => {
    setLoading(true)
    Promise.all([
      getAdminQualityReviewCase(caseId),
      listAdminQualityReviewEvents(caseId),
    ])
      .then(([c, ev]) => {
        setCaseData(c)
        setEvents(ev)
        setUpdateForm({ status: c.status, priority: c.priority })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [caseId])

  const handleUpdate = async () => {
    setUpdating(true)
    try {
      const updated = await updateAdminQualityReviewCase(caseId, updateForm)
      setCaseData(updated)
    } catch {}
    setUpdating(false)
  }

  if (loading) return <LoadingState label="Loading case…" />
  if (!caseData) return <ErrorState message="Case not found." />

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase" }}>Case #{caseData.id.slice(0, 8)}</Mono>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: "4px 0" }}>{caseData.title}</h3>
          <div style={{ display: "flex", gap: 6 }}>
            <StatusBadge status={caseData.status} />
            <Badge tone={caseData.priority === "urgent" ? "rose" : caseData.priority === "high" ? "amber" : "slate"}>
              {caseData.priority}
            </Badge>
            <Badge tone="slate">{caseData.case_type.replace(/_/g, " ")}</Badge>
          </div>
        </div>
        <Btn variant="secondary" size="sm" onClick={onClose}>← Back</Btn>
      </div>

      {caseData.description && (
        <Card>
          <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}>{caseData.description}</p>
        </Card>
      )}

      {/* Student actions */}
      {caseData.requested_student_actions.length > 0 && (
        <Card style={{ background: TOKEN.amberSoft, border: `1px solid #fde68a` }}>
          <CardHeader title="Requested Student Actions" icon="📢" />
          <ul style={{ margin: 0, padding: "0 0 0 16px" }}>
            {caseData.requested_student_actions.map((action: string, i: number) => (
              <li key={i} style={{ fontSize: 13, color: "#92400e", marginBottom: 4 }}>{action}</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Update form */}
      <Card>
        <CardHeader title="Update Case" icon="✏️" />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted, display: "block", marginBottom: 3 }}>Status</label>
            <select
              value={updateForm.status ?? caseData.status}
              onChange={(e) => setUpdateForm((f) => ({ ...f, status: e.target.value }))}
              style={{ width: "100%", padding: "8px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12 }}
            >
              {CASE_STATUSES.map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted, display: "block", marginBottom: 3 }}>Priority</label>
            <select
              value={updateForm.priority ?? caseData.priority}
              onChange={(e) => setUpdateForm((f) => ({ ...f, priority: e.target.value }))}
              style={{ width: "100%", padding: "8px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12 }}
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted, display: "block", marginBottom: 3 }}>Decision Notes (admin-only)</label>
          <textarea
            placeholder="Internal notes for this decision…"
            value={updateForm.decision_notes ?? caseData.decision_notes ?? ""}
            onChange={(e) => setUpdateForm((f) => ({ ...f, decision_notes: e.target.value }))}
            rows={2}
            style={{ width: "100%", padding: "8px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12, resize: "vertical", boxSizing: "border-box" }}
          />
          <p style={{ fontSize: 10, color: TOKEN.muted, marginTop: 3 }}>⚠ Admin-only. Never shown to students.</p>
        </div>
        <Btn variant="primary" size="sm" onClick={handleUpdate} disabled={updating}>
          {updating ? "Updating…" : "Update case"}
        </Btn>
      </Card>

      {/* Event timeline */}
      <Card>
        <CardHeader title="Case Timeline" eyebrow={`${events.length} events`} icon="📋" />
        {events.length === 0 ? (
          <p style={{ fontSize: 12, color: TOKEN.muted }}>No events yet.</p>
        ) : (
          events.map((ev) => <CaseEventRow key={ev.id} event={ev} />)
        )}
      </Card>
    </div>
  )
}

export function AdminQualityReviewDashboard() {
  const [cases, setCases] = useState<AdminQualityReviewCaseResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>("open")
  const [scanning, setScanning] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    listAdminQualityReviewCases({ status: statusFilter === "all" ? undefined : statusFilter })
      .then(setCases)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [statusFilter])

  const handleScan = async () => {
    setScanning(true)
    try {
      await runAdminQualityReviewScan()
      load()
    } catch {}
    setScanning(false)
  }

  if (selectedCaseId) {
    return (
      <CaseDetailPanel
        caseId={selectedCaseId}
        onClose={() => setSelectedCaseId(null)}
      />
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Admin Quality Review</h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Moderation cases for passport quality and compliance.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn variant="secondary" size="sm" onClick={handleScan} disabled={scanning}>
            {scanning ? "Scanning…" : "Run quality scan"}
          </Btn>
          <Btn variant="secondary" size="sm" onClick={load}>Refresh</Btn>
        </div>
      </div>

      {/* Status filter */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {["all", "open", "under_review", "needs_student_action", "escalated", "resolved"].map((f) => (
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
            }}
          >
            {f.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {loading && <LoadingState label="Loading cases…" />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && cases.length === 0 && (
        <EmptyState
          icon="✅"
          title="No cases"
          description={`No ${statusFilter === "all" ? "" : statusFilter.replace(/_/g, " ")} quality review cases.`}
        />
      )}

      {!loading && !error && cases.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {cases.map((c) => (
            <Card
              key={c.id}
              style={{ cursor: "pointer" }}
              className="vb-card-hover"
            >
              <div
                onClick={() => setSelectedCaseId(c.id)}
                style={{ display: "flex", gap: 12, alignItems: "flex-start" }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                    <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>{c.title}</span>
                    <StatusBadge status={c.status} />
                    <Badge tone={c.priority === "urgent" ? "rose" : c.priority === "high" ? "amber" : "slate"}>
                      {c.priority}
                    </Badge>
                    <Badge tone="slate">{c.case_type.replace(/_/g, " ")}</Badge>
                  </div>
                  {c.description && (
                    <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 4px" }}>{c.description}</p>
                  )}
                  <Mono style={{ fontSize: 10, color: TOKEN.muted }}>
                    Created: {new Date(c.created_at).toLocaleDateString()}
                  </Mono>
                </div>
                <span style={{ color: TOKEN.muted, fontSize: 14 }}>→</span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
