"use client"

/**
 * DEV PREVIEW ONLY — student access requests backed by the shared mock store.
 *
 * Requests submitted in /dev/recruiter-passport-preview appear here because
 * both pages read/write the same localStorage key via mock-evidence-access-store.
 *
 * URL: http://localhost:3000/dev/student-access-requests
 */

import { useEffect, useState } from "react"
import Link from "next/link"
import {
  listStudentAccessRequests,
  approveAccessRequest,
  denyAccessRequest,
  revokeAccessRequest,
  resetAccessRequestStore,
} from "../../../lib/mock-evidence-access-store"
import { StudentAccessRequestsPanel } from "../../../../components/passport/StudentAccessRequestsPanel"
import type { StudentAccessRequest } from "../../../../components/passport/StudentAccessRequestsPanel"
import type { EvidenceAccessRequest } from "../../../types/evidence-access"

/** Map from shared EvidenceAccessRequest to the panel's StudentAccessRequest. */
function toPanel(r: EvidenceAccessRequest): StudentAccessRequest {
  return {
    id: r.id,
    requester_name: r.requesterName,
    requester_email: r.requesterEmail,
    requester_organization: r.company ?? null,
    requester_role: r.role ?? null,
    requested_sections: r.requestedEvidenceTypes,
    request_reason: r.reason ?? null,
    optional_message: r.message ?? null,
    status: r.status,
    requested_at: r.requestedAt,
  }
}

export default function DevStudentAccessRequestsPage() {
  const [requests, setRequests] = useState<StudentAccessRequest[]>([])
  const [loaded, setLoaded] = useState(false)

  const reload = () => {
    setRequests(listStudentAccessRequests().map(toPanel))
    setLoaded(true)
  }

  useEffect(() => { reload() }, [])

  const handleApprove = (id: string, sections: string[]) => {
    approveAccessRequest(id, sections)
    reload()
  }

  const handleDeny = (id: string) => {
    denyAccessRequest(id)
    reload()
  }

  const handleRevoke = (id: string) => {
    revokeAccessRequest(id)
    reload()
  }

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
            Development preview — shared mock store
          </span>
          <span style={{ fontSize: 12, color: "#b45309" }}>
            Reads requests submitted in /dev/recruiter-passport-preview · localStorage
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            data-testid="student-dev-reset-btn"
            onClick={() => { resetAccessRequestStore(); reload() }}
            style={{
              fontSize: 11, fontWeight: 600, color: "#92400e",
              background: "#fef3c7", border: "1px solid #f59e0b",
              borderRadius: 6, padding: "4px 10px", cursor: "pointer",
            }}
          >
            Reset mock access requests
          </button>
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

        {loaded && (
          <StudentAccessRequestsPanel
            requests={requests}
            onApprove={handleApprove}
            onDeny={handleDeny}
            onRevoke={handleRevoke}
          />
        )}
      </div>
    </div>
  )
}
