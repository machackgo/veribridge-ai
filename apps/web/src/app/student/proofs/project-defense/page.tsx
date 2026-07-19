"use client"

import { Suspense } from "react"
import Link from "next/link"
import { ProjectDefenseHome } from "../../../../../components/passport/ProjectDefenseHome"
import { LoadingState, PageHeader, TOKEN } from "../../../../../components/passport/shared"

export default function ProjectDefensePage() {
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <Link
        href="/student/vbr"
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
        eyebrow="Project Defense"
        title="Project Defense"
        description="Defend an existing project. VeriBridge already knows the project's GitHub, document, and website evidence — Project Defense adds grounded questions and your explanation as supporting evidence for your Skill Graph."
      />

      <Suspense fallback={<LoadingState label="Loading your projects…" />}>
        <ProjectDefenseHome />
      </Suspense>
    </div>
  )
}
