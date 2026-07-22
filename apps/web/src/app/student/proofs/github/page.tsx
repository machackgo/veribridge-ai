"use client"

import { useState } from "react"
import Link from "next/link"
import { GitHubProofPanel } from "../../../../../components/passport/GitHubProofPanel"
import { Btn, Card, PageHeader, TOKEN } from "../../../../../components/passport/shared"

const DEMO_SESSION_ID = typeof window !== "undefined"
  ? (new URLSearchParams(window.location.search).get("session_id") ?? "")
  : ""

export default function GitHubProofStudioPage() {
  const [sessionId, setSessionId] = useState(DEMO_SESSION_ID)
  const [manualSessionId, setManualSessionId] = useState("")

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <Link
        href="/student"
        style={{
          fontSize: 13,
          color: TOKEN.indigo,
          textDecoration: "none",
          display: "inline-block",
          marginBottom: 16,
        }}
      >
        ← Back to Proof Studio
      </Link>

      <PageHeader
        eyebrow="GitHub Proof"
        title="GitHub Repository Proof"
        description="Submit public GitHub repositories as verifiable evidence of your technical skills. Each repo is analyzed for detected skills, evidence strength, and confidence."
      />

      {!sessionId && (
        <Card style={{ marginBottom: 20, border: `1px dashed ${TOKEN.indigo}` }}>
          <p style={{ fontSize: 13, color: TOKEN.muted, marginBottom: 10 }}>
            Optionally enter a session ID to link proofs to a specific proof session.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              placeholder="Proof session ID (optional)"
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
              variant="secondary"
              onClick={() => setSessionId(manualSessionId.trim())}
            >
              Set session
            </Btn>
          </div>
        </Card>
      )}

      <GitHubProofPanel sessionId={sessionId || undefined} />
    </div>
  )
}
