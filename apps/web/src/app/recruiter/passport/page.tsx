"use client"

import { useState } from "react"
import { RecruiterSavedCandidatesPanel } from "../../../../components/recruiter-passport/SavedCandidates"
import { CandidateComparisonPanel } from "../../../../components/recruiter-passport/CandidateComparison"
import { PageHeader, TOKEN } from "../../../../components/passport/shared"

type Tab = "saved" | "compare"

export default function RecruiterPassportPage() {
  const [tab, setTab] = useState<Tab>("saved")

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Recruiter Tools"
        title="Candidate Shortlist"
        description="View and manage saved Work Passports. Compare candidates against role requirements with AI-analyzed match signals."
      />

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 6, marginBottom: 24 }}>
        {([
          { id: "saved", label: "Saved Candidates", icon: "📌" },
          { id: "compare", label: "Compare Candidates", icon: "⚖️" },
        ] as const).map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            type="button"
            style={{
              padding: "8px 16px",
              borderRadius: 999,
              fontSize: 13,
              fontWeight: 600,
              border: `1px solid ${tab === id ? "#4f46e5" : "#e6e8ef"}`,
              background: tab === id ? "#eef0ff" : "#fff",
              color: tab === id ? "#4f46e5" : "#6b7280",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {icon} {label}
          </button>
        ))}
      </div>

      {tab === "saved" && <RecruiterSavedCandidatesPanel />}
      {tab === "compare" && <CandidateComparisonPanel savedPassportIds={[]} />}
    </div>
  )
}
