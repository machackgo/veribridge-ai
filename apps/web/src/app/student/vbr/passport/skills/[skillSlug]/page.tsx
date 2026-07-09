"use client"

import { use } from "react"

import { PageHeader } from "../../../../../../../components/passport/shared"
import { SkillReportPageView } from "./SkillReportView"

export default function Page({ params }: { params: Promise<{ skillSlug: string }> }) {
  const { skillSlug } = use(params)
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <PageHeader
        eyebrow="Verified Work Passport · Skill Report"
        title="Skill Report"
        description="A recruiter-verifiable evidence argument for one skill: the claim, the projects that demonstrate it, the exact proof behind each — with project-level, unmapped, and vault-only proof separated and honestly marked as not counted. Never a raw evidence dump."
      />
      <SkillReportPageView skillSlug={skillSlug} />
    </div>
  )
}
