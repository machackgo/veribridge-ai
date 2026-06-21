"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { WorkPassportStatusPanel } from "../../../../components/passport/WorkPassportStatus"
import { Btn, Card, EmptyState, LoadingState, Mono, PageHeader, TOKEN } from "../../../../components/passport/shared"
import {
  getStudentPassport,
  createOrUpdateStudentPassport,
  type PublicWorkPassportStudentResponse,
} from "@/lib/passport-api"

// Demo: In production this would come from session context / URL param
// For demo purposes, we try to load from the first available session
const DEMO_SESSION_ID = typeof window !== "undefined"
  ? (new URLSearchParams(window.location.search).get("session_id") ?? "")
  : ""

function PassportManagementCard({
  sessionId,
  passport,
  onPassportCreated,
}: {
  sessionId: string
  passport: PublicWorkPassportStudentResponse | null
  onPassportCreated: (p: PublicWorkPassportStudentResponse) => void
}) {
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCreate = async () => {
    if (!sessionId) return
    setCreating(true)
    setError(null)
    try {
      const p = await createOrUpdateStudentPassport(sessionId, {
        is_public: true,
        public_title: "Verified Work Passport",
      })
      onPassportCreated(p)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create passport")
    } finally {
      setCreating(false)
    }
  }

  if (!sessionId) {
    return (
      <Card>
        <EmptyState
          icon="🪪"
          title="No proof session found"
          description="Complete a proof submission first to generate your Work Passport."
        />
      </Card>
    )
  }

  if (!passport) {
    return (
      <Card>
        <EmptyState
          icon="🪪"
          title="No Work Passport yet"
          description="Create your public Work Passport to share your verified skills with recruiters and employers."
          action={
            <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
              {error && <p style={{ fontSize: 12, color: TOKEN.rose }}>{error}</p>}
              <Btn variant="primary" onClick={handleCreate} disabled={creating}>
                {creating ? "Creating…" : "Create Work Passport"}
              </Btn>
            </div>
          }
        />
      </Card>
    )
  }

  return (
    <Card style={{ background: TOKEN.emeraldSoft, border: `1px solid #a7f3d0` }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 20 }}>🪪</span>
            <span style={{ fontWeight: 700, fontSize: 14, color: "#065f46" }}>Work Passport Active</span>
          </div>
          <p style={{ fontSize: 12, color: "#065f46", margin: 0 }}>
            Public URL: <Mono style={{ fontWeight: 700 }}>/p/{passport.public_slug}</Mono>
          </p>
          {passport.field && (
            <p style={{ fontSize: 11, color: "#047857", margin: "2px 0 0" }}>Field: {passport.field}</p>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href={`/p/${passport.public_slug}`} target="_blank">
            <Btn variant="secondary" size="sm">View public page</Btn>
          </Link>
        </div>
      </div>
    </Card>
  )
}

export default function WorkPassportPage() {
  const [sessionId, setSessionId] = useState(DEMO_SESSION_ID)
  const [passport, setPassport] = useState<PublicWorkPassportStudentResponse | null>(null)
  const [passportLoading, setPassportLoading] = useState(false)
  const [manualSessionId, setManualSessionId] = useState("")

  useEffect(() => {
    if (!sessionId) return
    setPassportLoading(true)
    getStudentPassport(sessionId)
      .then(setPassport)
      .catch(() => setPassport(null))
      .finally(() => setPassportLoading(false))
  }, [sessionId])

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Work Passport"
        title="Your Verified Work Passport"
        description="A centralized view of your proof evidence, skill verification status, and recruiter access controls."
        action={
          passport && sessionId ? (
            <Link href={`/p/${passport.public_slug}`} target="_blank">
              <Btn variant="primary">View public passport</Btn>
            </Link>
          ) : undefined
        }
      />

      {/* Session ID input for demo */}
      {!sessionId && (
        <Card style={{ marginBottom: 20, border: `1px dashed ${TOKEN.indigo}` }}>
          <p style={{ fontSize: 13, color: TOKEN.muted, marginBottom: 10 }}>
            Enter your proof session ID to view your Work Passport status.
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

      {/* Passport management */}
      {passportLoading ? (
        <LoadingState label="Loading passport…" />
      ) : (
        <PassportManagementCard
          sessionId={sessionId}
          passport={passport}
          onPassportCreated={setPassport}
        />
      )}

      {/* Status panel */}
      {sessionId && (
        <div style={{ marginTop: 20 }}>
          <WorkPassportStatusPanel sessionId={sessionId} />
        </div>
      )}
    </div>
  )
}
