"use client"

import { useState } from "react"
import { AccessRequestManagerPanel } from "../../../../../components/passport/AccessRequestManager"
import { StudentAccessRequestsPanel } from "../../../../../components/passport/StudentAccessRequestsPanel"
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

      {/* Mock preview panel — always shown when no live session is active */}
      {!sessionId && <StudentAccessRequestsPanel />}
    </div>
  )
}
