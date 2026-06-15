"use client"

import { useParams } from "next/navigation"
import { PageHeader } from "../../../../../../../components/passport/shared"
import { ProjectReportView } from "./ProjectReportView"

export default function Page() {
  const params = useParams<{ projectId: string }>()
  const projectId = Array.isArray(params.projectId) ? params.projectId[0] : params.projectId

  if (!projectId) return null

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <PageHeader
        eyebrow="Final VBR Report · v1"
        title="VBR Report Preview"
        description="A private preview of the evidence package collected for this project — for you, the student. Public recruiter sharing is not enabled yet."
      />
      <ProjectReportView projectId={projectId} />
    </div>
  )
}
