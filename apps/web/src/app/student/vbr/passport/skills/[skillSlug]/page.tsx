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
        description="A recruiter-verifiable, connected-evidence report for one skill — GitHub, Website, Document, Project Defense, and Video proofs grouped into proof chains, with honest gaps. Documents appear as corroboration connected to your stronger evidence, never as a raw dump."
      />
      <SkillReportPageView skillSlug={skillSlug} />
    </div>
  )
}
