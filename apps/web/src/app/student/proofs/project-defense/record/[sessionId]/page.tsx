"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { VBRSessionRecorder } from "../../../../../../../components/vbr/VBRSessionRecorder"
import { PageHeader, TOKEN } from "../../../../../../../components/passport/shared"

export default function ProjectDefenseRecordPage() {
  const params = useParams<{ sessionId: string }>()
  const sessionId = Array.isArray(params.sessionId) ? params.sessionId[0] : params.sessionId

  if (!sessionId) return null

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <Link
        href="/student/proofs/project-defense"
        style={{
          fontSize: 13,
          color: TOKEN.indigo,
          textDecoration: "none",
          display: "inline-block",
          marginBottom: 16,
        }}
      >
        ← Back to Project Defense
      </Link>

      <PageHeader
        eyebrow="Project Defense"
        title="Project Defense Recording"
        description="Record your screen and microphone while answering your defense questions. Camera is optional and not required. This recording is protected evidence for your Skill Graph."
      />

      <VBRSessionRecorder sessionId={sessionId} variant="project_defense" />

      <p style={{ fontSize: 12, color: TOKEN.muted, textAlign: "center", marginTop: 16 }}>
        Prefer not to record? Go back to{" "}
        <Link href="/student/proofs/project-defense" style={{ color: TOKEN.indigo }}>
          Project Defense
        </Link>{" "}
        and paste your explanation instead.
      </p>
    </div>
  )
}
