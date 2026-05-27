"use client"

import { useState } from "react"
import {
  createStudentExport,
  getLatestStudentExport,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Mono,
  TOKEN,
} from "./shared"

function ExportPayloadViewer({ payload }: { payload: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false)

  const safeFields = [
    "export_type",
    "export_format",
    "public_slug",
    "generated_at",
    "disclaimer",
    "overall_status",
    "status_label",
    "readiness_level",
    "recruiter_safe_summary",
  ]

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Summary fields */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
        }}
      >
        {safeFields
          .filter((key: string) => payload[key] != null)
          .map((key: string) => (
            <div
              key={key}
              style={{
                padding: "8px 10px",
                background: TOKEN.bg,
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
              }}
            >
              <Mono style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                {key.replace(/_/g, " ")}
              </Mono>
              <p style={{ fontSize: 12, color: TOKEN.ink, margin: "3px 0 0", fontWeight: 500 }}>
                {String(payload[key] as string | number | boolean)}
              </p>
            </div>
          ))}
      </div>

      {/* Disclaimer */}
      {!!payload.disclaimer && (
        <div
          style={{
            padding: "10px 12px",
            background: TOKEN.amberSoft,
            border: `1px solid #fde68a`,
            borderRadius: 8,
          }}
        >
          <Mono style={{ fontSize: 10, color: TOKEN.amber, textTransform: "uppercase", fontWeight: 700 }}>
            ⚠ Disclaimer
          </Mono>
          <p style={{ fontSize: 12, color: "#92400e", margin: "4px 0 0", lineHeight: 1.5 }}>
            {String(payload.disclaimer)}
          </p>
        </div>
      )}

      {/* Raw JSON (collapsed by default) */}
      <details>
        <summary
          style={{ fontSize: 12, color: TOKEN.muted, cursor: "pointer", padding: "4px 0", fontWeight: 600 }}
        >
          View full export JSON
        </summary>
        <pre
          style={{
            marginTop: 8,
            padding: "12px",
            background: "#0a0e1a",
            color: "#a5b4fc",
            borderRadius: 10,
            fontSize: 11,
            overflow: "auto",
            maxHeight: 320,
            fontFamily: "'JetBrains Mono', monospace",
            lineHeight: 1.5,
          }}
        >
          {JSON.stringify(payload, null, 2)}
        </pre>
      </details>
    </div>
  )
}

export function ExportPanel({ sessionId }: { sessionId: string }) {
  const [loading, setLoading] = useState(false)
  const [fetchingLatest, setFetchingLatest] = useState(false)
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleGenerate = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await createStudentExport(sessionId)
      setPayload(result)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Export failed")
    } finally {
      setLoading(false)
    }
  }

  const handleFetchLatest = async () => {
    setFetchingLatest(true)
    setError(null)
    try {
      const result = await getLatestStudentExport(sessionId)
      setPayload(result)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "No export found")
    } finally {
      setFetchingLatest(false)
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Work Passport Export</h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Generate a structured export of your verified Work Passport. PDF export coming soon.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn variant="secondary" size="sm" onClick={handleFetchLatest} disabled={fetchingLatest}>
            {fetchingLatest ? "Loading…" : "Load latest"}
          </Btn>
          <Btn variant="primary" onClick={handleGenerate} disabled={loading}>
            {loading ? "Generating…" : "Generate export"}
          </Btn>
        </div>
      </div>

      {/* Info card */}
      <Card style={{ background: TOKEN.indigoSoft, border: `1px solid #c7d2fe` }}>
        <div style={{ display: "flex", gap: 10 }}>
          <span style={{ fontSize: 18 }}>📄</span>
          <div>
            <p style={{ fontSize: 13, color: TOKEN.ink, margin: 0, fontWeight: 600 }}>Structured JSON export</p>
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: "3px 0 0", lineHeight: 1.5 }}>
              Exports include your verified skills, evidence timeline, AI review summary, and public-safe recruiter summary.
              Protected evidence sections are clearly marked. All data is safe to share.
            </p>
          </div>
        </div>
      </Card>

      {error && (
        <div style={{ padding: "10px 14px", background: TOKEN.roseSoft, border: `1px solid #fecdd3`, borderRadius: 8 }}>
          <p style={{ fontSize: 12, color: TOKEN.rose, margin: 0 }}>{error}</p>
        </div>
      )}

      {payload ? (
        <Card>
          <CardHeader
            title="Export Payload"
            eyebrow="Work passport"
            icon="📦"
            action={
              <div style={{ display: "flex", gap: 8 }}>
                <Badge tone="emerald">JSON</Badge>
                <Badge tone="slate">Public-safe</Badge>
              </div>
            }
          />
          <ExportPayloadViewer payload={payload} />
        </Card>
      ) : (
        !loading && !fetchingLatest && (
          <EmptyState
            icon="📦"
            title="No export yet"
            description="Click 'Generate export' to create a structured snapshot of your verified Work Passport."
            action={
              <Btn variant="primary" onClick={handleGenerate}>
                Generate export
              </Btn>
            }
          />
        )
      )}

      {(loading || fetchingLatest) && (
        <div style={{ padding: "24px 0", textAlign: "center", color: TOKEN.muted, fontSize: 13 }}>
          {loading ? "Generating export…" : "Loading latest export…"}
        </div>
      )}
    </div>
  )
}
