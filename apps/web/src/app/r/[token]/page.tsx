"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { getPublicVBRReport, type VBRPublicReportResponse } from "@/lib/vbr-api"

const JUDGMENT_LABELS: Record<string, string> = {
  demonstrated: "Demonstrated",
  partially_demonstrated: "Partially demonstrated",
  not_assessed: "Not assessed",
  insufficient_evidence: "Insufficient evidence",
}

const JUDGMENT_COLORS: Record<string, string> = {
  demonstrated: "#059669",
  partially_demonstrated: "#d97706",
  not_assessed: "#64748b",
  insufficient_evidence: "#dc2626",
}

function formatDate(value: string | null): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })
}

/** Strict shape guard for the canonical redirect target — same-origin
 * `/vbr/report/{token}` only, so a tampered payload can never turn an old
 * shared link into an open redirect. */
function safeCanonicalReportPath(path: unknown): string | null {
  return typeof path === "string" && /^\/vbr\/report\/[A-Za-z0-9_-]+$/.test(path) ? path : null
}

export default function PublicVBRReportPage() {
  const params = useParams()
  const router = useRouter()
  const token = typeof params.token === "string" ? params.token : Array.isArray(params.token) ? params.token[0] : ""

  const [report, setReport] = useState<VBRPublicReportResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (!token) return
    setLoading(true)
    setError(null)
    setNotFound(false)
    getPublicVBRReport(token)
      .then((data) => {
        if (!data) {
          setNotFound(true)
          return
        }
        // Legacy → canonical migration: when this report's project has an
        // active canonical public report, send the recruiter there instead of
        // rendering the legacy view. The old URL keeps working either way.
        const canonical = safeCanonicalReportPath(data.canonical_report_path)
        if (canonical) {
          router.replace(canonical)
          return
        }
        setReport(data)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load report."))
      .finally(() => setLoading(false))
  }, [token, router])

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#f8fafc",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        color: "#0f172a",
      }}
    >
      <div
        style={{
          background: "#0a0e1a",
          padding: "14px 24px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 7,
            background: "linear-gradient(135deg,#4f46e5,#8b5cf6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span style={{ color: "#fff", fontSize: 14, fontWeight: 800 }}>V</span>
        </div>
        <span style={{ color: "#fff", fontWeight: 700, fontSize: 14 }}>VeriBridge AI</span>
        <span style={{ color: "#475569", fontSize: 13 }}>Verified Build Report</span>
      </div>

      <div style={{ maxWidth: 720, margin: "0 auto", padding: "32px 24px 48px" }}>
        {!token && (
          <p style={{ color: "#dc2626" }}>Invalid report link.</p>
        )}

        {token && loading && (
          <p style={{ color: "#64748b", fontSize: 14 }}>Loading report…</p>
        )}

        {token && !loading && error && (
          <div
            style={{
              padding: "16px 20px",
              background: "#fef2f2",
              border: "1px solid #fecaca",
              borderRadius: 10,
              color: "#991b1b",
              fontSize: 14,
            }}
          >
            Something went wrong while loading this report. Please try again later.
          </div>
        )}

        {token && !loading && !error && notFound && (
          <div
            style={{
              padding: "32px 24px",
              background: "#fff",
              border: "1px solid #e2e8f0",
              borderRadius: 12,
              textAlign: "center",
            }}
          >
            <h1 style={{ fontSize: 20, fontWeight: 700, margin: "0 0 8px" }}>Report unavailable</h1>
            <p style={{ fontSize: 14, color: "#64748b", margin: 0 }}>
              This link may be expired, unpublished, or incorrect. If you believe this is a mistake, ask the
              student to share an updated link.
            </p>
          </div>
        )}

        {token && !loading && !error && !notFound && report && (
          <>
            <h1 style={{ fontSize: 28, fontWeight: 800, margin: "8px 0 4px", letterSpacing: "-0.02em" }}>
              {report.project_title ?? "Verified Build Report"}
            </h1>
            {report.repo_full_name && (
              <p style={{ fontSize: 13, color: "#64748b", margin: "0 0 4px" }}>{report.repo_full_name}</p>
            )}
            {formatDate(report.published_at) && (
              <p style={{ fontSize: 12, color: "#94a3b8", margin: "0 0 24px" }}>
                Published {formatDate(report.published_at)}
              </p>
            )}

            <div
              style={{
                display: "flex",
                gap: 16,
                marginBottom: 24,
              }}
            >
              <div
                style={{
                  flex: 1,
                  padding: "14px 16px",
                  background: "#fff",
                  border: "1px solid #e2e8f0",
                  borderRadius: 10,
                }}
              >
                <p style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 4px" }}>
                  Claims reviewed
                </p>
                <p style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{report.claim_count}</p>
              </div>
              {report.evidence_count != null && (
                <div
                  style={{
                    flex: 1,
                    padding: "14px 16px",
                    background: "#fff",
                    border: "1px solid #e2e8f0",
                    borderRadius: 10,
                  }}
                >
                  <p style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 4px" }}>
                    Evidence items
                  </p>
                  <p style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{report.evidence_count}</p>
                </div>
              )}
            </div>

            <div
              style={{
                padding: "14px 16px",
                background: "#eef2ff",
                border: "1px solid #c7d2fe",
                borderRadius: 10,
                marginBottom: 24,
                fontSize: 13,
                color: "#3730a3",
                lineHeight: 1.6,
              }}
            >
              <p style={{ margin: "0 0 6px" }}>
                Evidence reviewed from repo, walkthrough, transcript, and verification checks.
              </p>
              <p style={{ margin: 0, fontWeight: 600 }}>
                This report does not guarantee employment or identity.
              </p>
            </div>

            {report.claims.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 12px" }}>Claims &amp; evidence</h2>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {report.claims.map((claim, idx) => {
                    const judgmentKey = claim.judgment ?? ""
                    const label = JUDGMENT_LABELS[judgmentKey] ?? judgmentKey
                    const color = JUDGMENT_COLORS[judgmentKey] ?? "#64748b"
                    return (
                      <div
                        key={idx}
                        style={{
                          padding: "12px 14px",
                          background: "#fff",
                          border: "1px solid #e2e8f0",
                          borderRadius: 10,
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
                          <p style={{ fontSize: 13, fontWeight: 600, margin: 0, flex: 1 }}>{claim.claim_text}</p>
                          {label && (
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 700,
                                color,
                                whiteSpace: "nowrap",
                              }}
                            >
                              {label}
                            </span>
                          )}
                        </div>
                        {claim.rationale && (
                          <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 4px", lineHeight: 1.5 }}>
                            {claim.rationale}
                          </p>
                        )}
                        <p style={{ fontSize: 11, color: "#94a3b8", margin: 0 }}>
                          {claim.evidence_count} evidence item{claim.evidence_count === 1 ? "" : "s"}
                        </p>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {report.methodology.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 8px" }}>Methodology</h2>
                <ul style={{ fontSize: 12, color: "#64748b", lineHeight: 1.7, margin: 0, paddingLeft: 18 }}>
                  {report.methodology.map((line, idx) => (
                    <li key={idx}>{line}</li>
                  ))}
                </ul>
              </div>
            )}

            <div
              style={{
                padding: "12px 14px",
                background: "#f1f5f9",
                border: "1px solid #e2e8f0",
                borderRadius: 8,
                marginBottom: 16,
                fontSize: 11,
                color: "#64748b",
                lineHeight: 1.6,
              }}
            >
              {report.verification_note}
            </div>

            <div style={{ textAlign: "center", padding: "8px 0 24px" }}>
              <span style={{ fontSize: 10, color: "#94a3b8" }}>Verified by VeriBridge AI</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
