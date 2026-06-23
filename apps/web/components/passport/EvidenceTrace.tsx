"use client"

import { isSafePublicUrl, type EvidenceTrace } from "@/lib/vbr-api"
import { Badge, Mono, TOKEN, type BadgeTone } from "./shared"

const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

const STATUS_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Evidence observed": "emerald",
  "Supporting evidence": "sky",
  "Needs review": "rose",
  "Not assessed": "slate",
}

/**
 * One recruiter-readable claim→evidence trace: source, the skills it supports,
 * a safe explanation, a direct link (only when genuinely public — re-checked
 * here with isSafePublicUrl as defence in depth), and its limitation. Private
 * sources show a generic note instead of any raw evidence.
 */
export function EvidenceTraceItem({ trace }: { trace: EvidenceTrace }) {
  const openable = trace.is_publicly_openable && isSafePublicUrl(trace.public_url)

  return (
    <div
      data-testid="evidence-trace"
      data-source-type={trace.source_type}
      id={trace.evidence_anchor || undefined}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={SOURCE_TONE[trace.source_type] ?? "slate"}>{trace.source_type}</Badge>
        <Badge tone={STATUS_TONE[trace.qualitative_status] ?? "slate"}>{trace.qualitative_status}</Badge>
        {trace.timestamp && (
          <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{trace.timestamp}</Mono>
        )}
      </div>

      <div style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>{trace.source_title}</div>

      {trace.skill_names.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {trace.skill_names.map((skill) => (
            <Badge key={skill} tone="slate">
              {skill}
            </Badge>
          ))}
        </div>
      )}

      {trace.safe_summary && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{trace.safe_summary}</p>
      )}
      {trace.safe_detail && (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>{trace.safe_detail}</p>
      )}

      {openable ? (
        <a
          data-testid="evidence-trace-link"
          href={trace.public_url ?? undefined}
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
        >
          🔗 {trace.public_url_label ?? "Open public evidence"}
        </a>
      ) : (
        trace.private_evidence_note && (
          <div
            data-testid="evidence-trace-private-note"
            style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
          >
            🔒 {trace.private_evidence_note}
          </div>
        )
      )}

      {trace.limitation && (
        <div style={{ fontSize: 11, color: TOKEN.muted }}>
          <strong style={{ color: TOKEN.inkSoft }}>Limitation: </strong>
          {trace.limitation}
        </div>
      )}
    </div>
  )
}

/**
 * The "Evidence Traceability" list rendered in reports and passport skill
 * drilldowns. Renders nothing when there are no traces.
 */
export function EvidenceTraceList({ traces }: { traces?: EvidenceTrace[] | null }) {
  if (!traces || traces.length === 0) return null
  return (
    <div data-testid="evidence-traceability" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {traces.map((trace, i) => (
        <EvidenceTraceItem key={`${trace.trace_id}-${i}`} trace={trace} />
      ))}
    </div>
  )
}
