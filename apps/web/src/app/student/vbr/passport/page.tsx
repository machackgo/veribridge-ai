"use client"

import { PageHeader } from "../../../../../components/passport/shared"
import { PrivatePassportView } from "./PrivatePassportView"

export default function Page() {
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <PageHeader
        eyebrow="Verified Work Passport · v1"
        title="Your Work Passport"
        description="Your private evidence wallet — every project, grouped skill, and proof source. Publish a recruiter-safe public Passport that links only to the VBR reports you choose to share."
      />
      <PrivatePassportView />
    </div>
  )
}
