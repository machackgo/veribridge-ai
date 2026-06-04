"use client"

/**
 * DEV PREVIEW ONLY — mock student access requests view.
 *
 * URL: http://localhost:3000/dev/student-access-requests
 */

import Link from "next/link"
import { StudentAccessRequestsPanel } from "../../../../components/passport/StudentAccessRequestsPanel"

export default function DevStudentAccessRequestsPage() {
  return (
    <div style={{
      minHeight: "100vh",
      background: "#f8fafc",
      fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
    }}>
      {/* Dev banner */}
      <div style={{
        background: "#fef3c7",
        borderBottom: "2px solid #fbbf24",
        padding: "10px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16 }}>🛠</span>
          <span style={{ fontWeight: 700, fontSize: 13, color: "#92400e" }}>
            Development preview — mock student access requests
          </span>
          <span style={{ fontSize: 12, color: "#b45309" }}>
            No backend call · Local state only
          </span>
        </div>
        <Link
          href="/dashboard/passport/access"
          style={{
            fontSize: 12, fontWeight: 600, color: "#92400e",
            background: "#fde68a", border: "1px solid #f59e0b",
            borderRadius: 6, padding: "5px 12px", textDecoration: "none",
          }}
        >
          ← Back to dashboard
        </Link>
      </div>

      {/* Page content */}
      <div style={{ maxWidth: 820, margin: "0 auto", padding: "32px 20px 60px" }}>
        <div style={{ marginBottom: 24 }}>
          <div style={{
            fontSize: 10, letterSpacing: "0.16em", color: "#64748b",
            textTransform: "uppercase", marginBottom: 6, fontFamily: "monospace",
          }}>
            Student Dashboard · Access Control
          </div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: "#0f172a", margin: "0 0 6px" }}>
            Evidence Access Requests
          </h1>
          <p style={{ fontSize: 13, color: "#64748b", margin: 0 }}>
            Review who wants access to your protected proof evidence. You control what gets shared.
          </p>
        </div>

        <StudentAccessRequestsPanel />
      </div>
    </div>
  )
}
