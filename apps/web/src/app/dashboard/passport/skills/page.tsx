"use client"

import { useState } from "react"
import { SkillEvidenceTimelinePanel } from "../../../../../components/passport/SkillEvidenceTimeline"
import { PageHeader, Btn, Card, TOKEN } from "../../../../../components/passport/shared"

const DEMO_SESSION_ID = typeof window !== "undefined"
  ? (new URLSearchParams(window.location.search).get("session_id") ?? "")
  : ""

export default function SkillEvidencePage() {
  const [sessionId, setSessionId] = useState(DEMO_SESSION_ID)
  const [manualSessionId, setManualSessionId] = useState("")

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Skill Evidence"
        title="Skill Evidence Timeline"
        description="A dynamic, evidence-grounded view of every verified skill — showing confidence levels, evidence sources, gaps, and recommended next steps."
      />

      {!sessionId && (
        <Card style={{ marginBottom: 20, border: `1px dashed ${TOKEN.indigo}` }}>
          <p style={{ fontSize: 13, color: TOKEN.muted, marginBottom: 10 }}>
            Enter your proof session ID to view your skill evidence timeline.
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
        <SkillEvidenceTimelinePanel sessionId={sessionId} />
      ) : (
        <Card>
          <p style={{ fontSize: 13, color: TOKEN.muted, textAlign: "center", padding: "32px 0" }}>
            Enter a session ID above to view your skill evidence timeline.
          </p>
        </Card>
      )}
    </div>
  )
}
