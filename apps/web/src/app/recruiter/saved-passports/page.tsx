"use client"

import { RecruiterSavedCandidatesPanel } from "../../../../components/recruiter-passport/SavedCandidates"
import { PageHeader } from "../../../../components/passport/shared"

export default function SavedPassportsPage() {
  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Recruiter Tools"
        title="Saved Candidates"
        description="Manage your shortlisted Work Passports. Private notes are never shown to students."
      />
      <RecruiterSavedCandidatesPanel />
    </div>
  )
}
