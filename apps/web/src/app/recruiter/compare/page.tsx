"use client"

import { CandidateComparisonPanel } from "../../../../components/recruiter-passport/CandidateComparison"
import { PageHeader } from "../../../../components/passport/shared"

export default function ComparePage() {
  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Recruiter Tools"
        title="Compare Candidates"
        description="AI match signal analysis across saved candidates. Not a hiring recommendation — your judgment always leads."
      />
      {/* savedPassportIds empty: user types their email to load their shortlist and compare */}
      <CandidateComparisonPanel savedPassportIds={[]} />
    </div>
  )
}
