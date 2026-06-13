"use client"

import Link from "next/link"
import { ProjectDefensePanel } from "../../../../../components/passport/ProjectDefensePanel"
import { PageHeader, TOKEN } from "../../../../../components/passport/shared"

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
        description="Explain your individual contribution to a project, in your own words. VeriBridge generates deterministic defense questions from your attached proof and turns your answers into supporting evidence for your Skill Graph."
      />

      <ProjectDefensePanel />
    </div>
  )
}
