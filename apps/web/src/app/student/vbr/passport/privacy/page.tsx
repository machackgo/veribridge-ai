"use client"

import { PageHeader } from "../../../../../../components/passport/shared"
import { PrivacyCenterView } from "./PrivacyCenterView"

export default function Page() {
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <PageHeader
        eyebrow="Work Passport · Privacy"
        title="Privacy & Sharing"
        description="Control exactly what recruiters can see and inspect on your public Passport. Hidden items never appear anywhere — recruiters see no trace of them."
      />
      <PrivacyCenterView />
    </div>
  )
}
