"use client"

import { useState } from "react"
import { AdminQualityReviewDashboard } from "../../../../../components/admin-passport/QualityReviewDashboard"
import { AdminRequesterVerificationPanel } from "../../../../../components/admin-passport/RequesterVerification"
import { PageHeader, TOKEN } from "../../../../../components/passport/shared"

type Tab = "quality-review" | "requester-verification"

export default function AdminPassportPage() {
  const [tab, setTab] = useState<Tab>("quality-review")

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Admin"
        title="Admin Passport Moderation"
        description="Quality review cases and recruiter/requester identity verification."
      />

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 6, marginBottom: 24 }}>
        {([
          { id: "quality-review", label: "Quality Review", icon: "🔍" },
          { id: "requester-verification", label: "Requester Verification", icon: "🧑‍💼" },
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

      {tab === "quality-review" && <AdminQualityReviewDashboard />}
      {tab === "requester-verification" && <AdminRequesterVerificationPanel />}
    </div>
  )
}
