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

      {/* Demo preview card */}
      <a
        href="/dev/recruiter-passport-preview"
        data-testid="recruiter-demo-preview-link"
        style={{ textDecoration: "none", display: "block", marginBottom: 24 }}
      >
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "16px 20px",
          background: "#fefce8",
          border: "1px solid #fde68a",
          borderRadius: 10,
          cursor: "pointer",
        }}>
          <span style={{ fontSize: 24, flexShrink: 0 }}>🪪</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: "#78350f", marginBottom: 3 }}>
              Preview sample Work Passport
            </div>
            <div style={{ fontSize: 12, color: "#92400e", lineHeight: 1.5, marginBottom: 6 }}>
              Open a recruiter-safe mock Work Passport to review evidence-backed skills, project proof cards, interview questions, and protected evidence access.
            </div>
            <span style={{
              display: "inline-block",
              fontSize: 10,
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: 4,
              background: "#fef08a",
              color: "#713f12",
              border: "1px solid #fde047",
            }}>
              Demo preview — mock recruiter-safe data
            </span>
          </div>
          <span style={{
            fontSize: 13,
            fontWeight: 700,
            color: "#fff",
            background: "#d97706",
            padding: "7px 14px",
            borderRadius: 7,
            flexShrink: 0,
            whiteSpace: "nowrap",
          }}>
            Open preview →
          </span>
        </div>
      </a>

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
