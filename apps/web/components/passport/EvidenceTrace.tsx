"use client"

import { isSafePublicUrl, matrixTraceLabel, type EvidenceTrace } from "@/lib/vbr-api"
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
      // tabIndex lets a matrix link move keyboard focus to the precise card.
      tabIndex={-1}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: "#fff",
        // Keep the anchored card clear of the sticky page header when a matrix
        // link scrolls to it, so it never lands hidden under the top chrome.
        scrollMarginTop: 96,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={SOURCE_TONE[trace.source_type] ?? "slate"}>{trace.source_type}</Badge>
        <Badge tone={STATUS_TONE[trace.qualitative_status] ?? "slate"}>{trace.qualitative_status}</Badge>
        {/* Proof-native location chip (e.g. "GitHub: repo-level", "Defense Q3"). */}
        {(trace.location_label || trace.location_type) && (
          <Mono data-testid="evidence-trace-location" style={{ fontSize: 11, color: TOKEN.muted }}>
            📍 {matrixTraceLabel(trace)}
          </Mono>
        )}
        {trace.timestamp && !trace.location_label && (
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

      {/* Project Defense question + (when available) a short safe answer excerpt. */}
      {trace.question_text && (
        <p data-testid="evidence-trace-question" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          <strong style={{ color: TOKEN.ink }}>Q: </strong>
          {trace.question_text}
        </p>
      )}
      {trace.answer_excerpt && (
        <p data-testid="evidence-trace-answer" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          <strong style={{ color: TOKEN.inkSoft }}>Answer: </strong>
          “{trace.answer_excerpt}”
        </p>
      )}

      {/* Document page locator + (only when safe) a short snippet. */}
      {typeof trace.page_number === "number" && (
        <div data-testid="evidence-trace-page" style={{ fontSize: 11, color: TOKEN.muted }}>
          📄 Page {trace.page_number}
        </div>
      )}
      {/* Document citation (matched section heading); safe on public surfaces. */}
      {trace.citation && (
        <div data-testid="evidence-trace-citation" style={{ fontSize: 11, color: TOKEN.muted }}>
          🔖 {trace.citation}
        </div>
      )}
      {trace.snippet && (
        <p data-testid="evidence-trace-snippet" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}>
          “{trace.snippet}”
        </p>
      )}

      {/* Safe file path + line/function locator for GitHub code traces. */}
      {trace.file_path && (
        <Mono data-testid="evidence-trace-file" style={{ fontSize: 11, color: TOKEN.muted }}>
          {trace.file_path}
          {typeof trace.line_start === "number" && (
            <span data-testid="evidence-trace-lines">
              {" "}· lines {trace.line_start}
              {typeof trace.line_end === "number" && trace.line_end !== trace.line_start ? `-${trace.line_end}` : ""}
            </span>
          )}
          {trace.function_name && (
            <span data-testid="evidence-trace-function">{" "}· {trace.function_name}()</span>
          )}
          {trace.commit_sha && (
            <span data-testid="evidence-trace-commit">{" "}@ {trace.commit_sha.slice(0, 7)}</span>
          )}
        </Mono>
      )}
      {/* Safe code snippet from a public GitHub file (private surfaces only). */}
      {trace.code_snippet && (
        <pre
          data-testid="evidence-trace-code"
          style={{
            margin: 0,
            padding: "8px 10px",
            background: "#0f172a",
            color: "#e2e8f0",
            borderRadius: 6,
            fontSize: 11,
            lineHeight: 1.45,
            overflowX: "auto",
            whiteSpace: "pre",
          }}
        >
          <code>{trace.code_snippet}</code>
        </pre>
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
      {/* When a matrix link scrolls to a trace card, briefly highlight it so the
          recruiter sees exactly which proof the link landed on. */}
      <style>{`[data-testid="evidence-trace"]:target{outline:2px solid ${TOKEN.indigo};outline-offset:2px;border-radius:8px}`}</style>
      {traces.map((trace, i) => (
        <EvidenceTraceItem key={`${trace.trace_id}-${i}`} trace={trace} />
      ))}
    </div>
  )
}
