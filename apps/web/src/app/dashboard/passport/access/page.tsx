"use client"

import { useState } from "react"
import { AccessRequestManagerPanel } from "../../../../../components/passport/AccessRequestManager"
import { PageHeader, Btn, Card, TOKEN } from "../../../../../components/passport/shared"

const DEMO_SESSION_ID = typeof window !== "undefined"
  ? (new URLSearchParams(window.location.search).get("session_id") ?? "")
  : ""

export default function AccessRequestsPage() {
  const [sessionId, setSessionId] = useState(DEMO_SESSION_ID)
  const [manualSessionId, setManualSessionId] = useState("")

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Access Control"
        title="Evidence Access Requests"
        description="Review and manage who can access your protected evidence. You are always in control."
      />

      {!sessionId && (
        <Card style={{ marginBottom: 20, border: `1px dashed ${TOKEN.indigo}` }}>
          <p style={{ fontSize: 13, color: TOKEN.muted, marginBottom: 10 }}>
            Enter your proof session ID to manage access requests.
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
              Load
            </Btn>
          </div>
        </Card>
      )}

      {sessionId ? (
        <AccessRequestManagerPanel sessionId={sessionId} />
      ) : (
        <Card>
          <p style={{ fontSize: 13, color: TOKEN.muted, textAlign: "center", padding: "32px 0" }}>
            Enter a session ID above to manage access requests.
          </p>
        </Card>
      )}
    </div>
  )
}
