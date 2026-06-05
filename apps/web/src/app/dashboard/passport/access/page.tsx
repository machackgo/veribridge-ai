"use client"

import { useState, useEffect } from "react"
import { AccessRequestManagerPanel } from "../../../../../components/passport/AccessRequestManager"
import { StudentAccessRequestsPanel } from "../../../../../components/passport/StudentAccessRequestsPanel"
import type { StudentAccessRequest } from "../../../../../components/passport/StudentAccessRequestsPanel"
import { PageHeader, Btn, Card, TOKEN } from "../../../../../components/passport/shared"
import {
  listStudentAccessRequests,
  approveAccessRequest,
  denyAccessRequest,
  revokeAccessRequest,
  resetAccessRequestStore,
} from "../../../../lib/mock-evidence-access-store"
import type { EvidenceAccessRequest } from "../../../../types/evidence-access"

function toStudentRequest(r: EvidenceAccessRequest): StudentAccessRequest {
  return {
    id: r.id,
    requester_name: r.requesterName,
    requester_email: r.requesterEmail,
    requester_organization: r.company ?? undefined,
    requester_role: r.role ?? undefined,
    requested_sections: r.requestedEvidenceTypes,
    request_reason: r.reason ?? undefined,
    optional_message: r.message ?? undefined,
    status: r.status,
    requested_at: r.requestedAt,
  }
}

const DEMO_SESSION_ID = typeof window !== "undefined"
  ? (new URLSearchParams(window.location.search).get("session_id") ?? "")
  : ""

export default function AccessRequestsPage() {
  const [sessionId, setSessionId] = useState(DEMO_SESSION_ID)
  const [manualSessionId, setManualSessionId] = useState("")
  const [mockRequests, setMockRequests] = useState<StudentAccessRequest[]>([])
  const [mockLoaded, setMockLoaded] = useState(false)

  const reloadMock = () => {
    setMockRequests(listStudentAccessRequests().map(toStudentRequest))
    setMockLoaded(true)
  }

  useEffect(() => { reloadMock() }, [])

  const handleApprove = (id: string, sections: string[]) => {
    approveAccessRequest(id, sections)
    reloadMock()
  }

  const handleDeny = (id: string) => {
    denyAccessRequest(id)
    reloadMock()
  }

  const handleRevoke = (id: string) => {
    revokeAccessRequest(id)
    reloadMock()
  }

  const handleReset = () => {
    resetAccessRequestStore()
    reloadMock()
  }

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Access Control"
        title="Evidence Access Requests"
        description="Review and manage who can access your protected evidence. You are always in control."
      />

      {/* Session ID entry for live API */}
      <Card style={{ marginBottom: 20, border: `1px dashed ${TOKEN.indigo}` }}>
        <p style={{ fontSize: 13, color: TOKEN.muted, marginBottom: 10 }}>
          Enter your proof session ID to load live access requests, or use the mock preview below.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            placeholder="Proof session ID (UUID)"
            value={manualSessionId}
            onChange={(e) => setManualSessionId(e.target.value)}
            style={{
              flex: 1,
              padding: "8px 12px",
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 8,
              fontSize: 13,
              fontFamily: "monospace",
            }}
          />
          <Btn
            variant="primary"
            onClick={() => setSessionId(manualSessionId.trim())}
            disabled={!manualSessionId.trim()}
          >
            Load live requests
          </Btn>
          {sessionId && (
            <Btn variant="secondary" onClick={() => setSessionId("")}>
              Clear
            </Btn>
          )}
        </div>
      </Card>

      {/* Live API panel when session ID is provided */}
      {sessionId && <AccessRequestManagerPanel sessionId={sessionId} />}

      {/* Mock preview panel — reads from shared mock store */}
      {!sessionId && mockLoaded && (
        <>
          {/* Dev/demo label */}
          <div
            data-testid="mock-requests-banner"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
              marginBottom: 12,
              padding: "8px 12px",
              background: "#fef3c7",
              border: "1px solid #fbbf24",
              borderRadius: 8,
            }}
          >
            <span style={{ fontSize: 12, color: "#92400e", fontWeight: 600 }}>
              🛠 Development preview — showing mock local access requests
            </span>
            <button
              type="button"
              onClick={handleReset}
              style={{
                fontSize: 11, fontWeight: 600, color: "#92400e",
                background: "transparent", border: "1px solid #f59e0b",
                borderRadius: 5, padding: "3px 8px", cursor: "pointer",
              }}
            >
              Reset to samples
            </button>
          </div>

          <StudentAccessRequestsPanel
            requests={mockRequests}
            onApprove={handleApprove}
            onDeny={handleDeny}
            onRevoke={handleRevoke}
          />
        </>
      )}
    </div>
  )
}
