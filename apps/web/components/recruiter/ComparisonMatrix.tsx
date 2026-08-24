"use client"

/**
 * The shared recruiter evidence-comparison matrix.
 *
 * Extracted from the Hiring Brief detail view so a Talent Pool can render
 * the SAME matrix from the SAME deterministic engine rather than growing a
 * second, divergent comparison UI.
 *
 * What this component is, and is not:
 *
 *   * It compares EVIDENCE, never candidates. There is no score, no
 *     percentage, no ranking, no "best candidate" — only the closed cell
 *     vocabulary (proven / claimed / none / unavailable), the candidate's
 *     own qualitative skill status, and transparent counts.
 *   * Nuanced verification states survive. A cell is never flattened to a
 *     tick: "Demonstrated" and "Evidence observed" render as themselves, a
 *     project-technology claim is labelled "Claimed — not verified
 *     evidence", and a requirement satisfied by a more specific skill says
 *     so ("Satisfied by FastAPI evidence").
 *   * Absence is stated as absence. "No published X evidence" is a fact
 *     about what VeriBridge holds — never "weak", "poor" or "unqualified".
 *     Adjacent skills appear only as "Related (not proof)".
 *   * Every proven cell stays traceable: skill report → project → Verified
 *     Build Report → the underlying proof, expandable in place, so the
 *     recruiter can always walk from a summary back to the evidence.
 */

import { useState } from "react"

import { Badge, TOKEN } from "../passport/shared"
import type {
  ComparisonMatrix as ComparisonMatrixData,
  MatrixCell,
  MatrixColumn,
} from "@/lib/recruiter-briefs-api"

/** Per-column extras a host view can render into the sticky header. */
export type ColumnAccessory = (column: MatrixColumn) => React.ReactNode

function CellProvenance({ cell }: { cell: MatrixCell }) {
  const [open, setOpen] = useState(false)
  const hasTrail = cell.projects.length > 0 || cell.traces.length > 0
  if (!hasTrail) return null

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <button
        type="button"
        data-testid="matrix-cell-trace-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{
          alignSelf: "flex-start",
          background: "none",
          border: "none",
          padding: 0,
          fontSize: 11,
          fontWeight: 600,
          color: TOKEN.indigo,
          cursor: "pointer",
        }}
      >
        {open ? "Hide evidence trail" : "Where is this from?"}
      </button>
      {open && (
        <div
          data-testid="matrix-cell-trace"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 6,
            background: TOKEN.bg,
            borderRadius: 8,
            padding: "7px 9px",
          }}
        >
          {cell.projects.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ fontSize: 10, color: TOKEN.muted, fontWeight: 700, letterSpacing: "0.4px", textTransform: "uppercase" }}>
                Demonstrated in
              </span>
              {cell.projects.map((project, index) => (
                <span key={`${project.title}-${index}`} style={{ fontSize: 11.5, color: TOKEN.inkSoft, lineHeight: 1.45 }}>
                  {project.public_report_path ? (
                    <a
                      data-testid="matrix-cell-project-link"
                      href={project.public_report_path}
                      style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
                    >
                      {project.title ?? "Verified project"}
                    </a>
                  ) : (
                    <span style={{ fontWeight: 600 }}>{project.title ?? "Verified project"}</span>
                  )}
                  {project.skill_status && (
                    <span style={{ color: TOKEN.muted }}> · {project.skill_status}</span>
                  )}
                  {project.proof_types.length > 0 && (
                    <span style={{ color: TOKEN.muted }}> · {project.proof_types.join(", ")}</span>
                  )}
                </span>
              ))}
            </div>
          )}
          {cell.traces.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ fontSize: 10, color: TOKEN.muted, fontWeight: 700, letterSpacing: "0.4px", textTransform: "uppercase" }}>
                Underlying proof
              </span>
              {cell.traces.map((trace, index) => (
                <span key={`${trace.source_title}-${index}`} style={{ fontSize: 11.5, color: TOKEN.inkSoft, lineHeight: 1.45, overflowWrap: "anywhere" }}>
                  {trace.public_url ? (
                    <a
                      data-testid="matrix-cell-trace-link"
                      href={trace.public_url}
                      style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
                    >
                      {trace.source_type ?? "Proof"}
                    </a>
                  ) : (
                    <span style={{ fontWeight: 600 }}>{trace.source_type ?? "Proof"}</span>
                  )}
                  {trace.source_title && <span style={{ color: TOKEN.muted }}> · {trace.source_title}</span>}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function MatrixCellView({ cell }: { cell: MatrixCell }) {
  if (cell.state === "proven") {
    return (
      <div data-testid="matrix-cell-proven" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
          <Badge tone="emerald">Proven</Badge>
          {/* The candidate's own verification state — never flattened away. */}
          {cell.skill_status && (
            <span data-testid="matrix-cell-skill-status" style={{ fontSize: 10.5, color: TOKEN.muted, fontWeight: 600 }}>
              {cell.skill_status}
            </span>
          )}
        </div>
        {cell.note && <span style={{ fontSize: 11, color: TOKEN.muted }}>{cell.note}</span>}
        {cell.proof_path && (
          <a
            data-testid="matrix-cell-proof-link"
            href={cell.proof_path}
            style={{ fontSize: 11.5, color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
          >
            View proof →
          </a>
        )}
        <CellProvenance cell={cell} />
      </div>
    )
  }
  if (cell.state === "claimed") {
    return (
      <div data-testid="matrix-cell-claimed" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <Badge tone="amber">Claimed</Badge>
        <span style={{ fontSize: 11, color: TOKEN.muted }}>{cell.note ?? "Not verified evidence"}</span>
      </div>
    )
  }
  return (
    <div data-testid="matrix-cell-none" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      {/* Absence of VeriBridge evidence is NOT evidence of absence of
          ability — the label says what is missing, never what the person is. */}
      <Badge tone="slate">No evidence</Badge>
      {cell.note && <span style={{ fontSize: 11, color: TOKEN.muted }}>{cell.note}</span>}
      {cell.related.length > 0 && (
        <span style={{ fontSize: 11, color: TOKEN.muted }}>
          Related (not proof): {cell.related.join(", ")}
        </span>
      )}
    </div>
  )
}

export function ComparisonMatrixView({
  matrix,
  columnAccessory,
  testid = "comparison-matrix",
}: {
  matrix: ComparisonMatrixData
  columnAccessory?: ColumnAccessory
  testid?: string
}) {
  // Requirement rows the recruiter asked for come first; rows derived from
  // the candidates' own evidence are grouped after them under their own
  // heading, so an "observed" row is never mistaken for a stated requirement.
  const planRows = matrix.requirements.filter((r) => r.origin !== "observed")
  const observedRows = matrix.requirements.filter((r) => r.origin === "observed")

  const renderRow = (req: (typeof matrix.requirements)[number]) => (
    <tr key={req.key}>
      <th
        scope="row"
        style={{
          textAlign: "left",
          padding: "10px 12px",
          fontSize: 12.5,
          color: TOKEN.ink,
          fontWeight: 600,
          borderBottom: `1px solid ${TOKEN.line}`,
          verticalAlign: "top",
          position: "sticky",
          left: 0,
          background: "#fff",
          zIndex: 1,
        }}
      >
        {req.display}
        {req.origin === "plan" && !req.required && (
          <span style={{ display: "block", fontSize: 10.5, color: TOKEN.muted, fontWeight: 500 }}>
            Preferred
          </span>
        )}
      </th>
      {matrix.columns.map((column) => {
        const cell = column.cells[req.key]
        return (
          <td key={column.user_id} style={{ padding: "10px 12px", borderBottom: `1px solid ${TOKEN.line}`, verticalAlign: "top" }}>
            {column.available && cell ? (
              <MatrixCellView cell={cell} />
            ) : (
              <span data-testid="matrix-cell-unavailable" style={{ fontSize: 11.5, color: TOKEN.muted }}>
                —
              </span>
            )}
          </td>
        )
      })}
    </tr>
  )

  const sectionHeading = (label: string, hint: string) => (
    <tr key={label}>
      <td
        colSpan={matrix.columns.length + 1}
        data-testid="comparison-section-heading"
        style={{ padding: "10px 12px", background: TOKEN.bg, borderBottom: `1px solid ${TOKEN.line}` }}
      >
        <span style={{ fontSize: 11, color: TOKEN.ink, fontWeight: 700, letterSpacing: "0.3px", textTransform: "uppercase" }}>
          {label}
        </span>
        <span style={{ display: "block", fontSize: 11.5, color: TOKEN.muted, fontWeight: 500, marginTop: 2 }}>
          {hint}
        </span>
      </td>
    </tr>
  )

  return (
    <div data-testid="comparison-view" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {matrix.notes.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {matrix.notes.map((note) => (
            <p key={note} data-testid="comparison-note" style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
              {note}
            </p>
          ))}
        </div>
      )}
      <div style={{ overflowX: "auto", border: `1px solid ${TOKEN.line}`, borderRadius: 12 }}>
        <table data-testid={testid} style={{ borderCollapse: "collapse", width: "100%", minWidth: 640 }}>
          <thead>
            <tr>
              <th
                style={{
                  textAlign: "left",
                  padding: "10px 12px",
                  fontSize: 12,
                  color: TOKEN.muted,
                  borderBottom: `1px solid ${TOKEN.line}`,
                  background: TOKEN.bg,
                  minWidth: 170,
                  position: "sticky",
                  left: 0,
                  zIndex: 2,
                }}
              >
                Evidence
              </th>
              {matrix.columns.map((column) => (
                <th key={column.user_id} style={{ textAlign: "left", padding: "10px 12px", borderBottom: `1px solid ${TOKEN.line}`, background: TOKEN.bg, minWidth: 170 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    <span data-testid="comparison-column-name" style={{ fontSize: 13, color: TOKEN.ink, fontWeight: 700 }}>
                      {column.display_name ?? "Verified candidate"}
                    </span>
                    <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {!column.available && <Badge tone="rose">Unavailable</Badge>}
                      {columnAccessory?.(column)}
                    </span>
                    <span style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 500 }}>
                      {column.available
                        ? summariseCounts(column)
                        : column.unavailable_note ?? ""}
                    </span>
                    {column.passport_path && (
                      <a
                        data-testid="comparison-column-passport"
                        href={column.passport_path}
                        style={{ fontSize: 11.5, color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
                      >
                        Passport →
                      </a>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {planRows.map(renderRow)}
            {observedRows.length > 0 &&
              sectionHeading(
                "Published evidence across the selected candidates",
                "Derived from what these candidates have published — not requirements anyone asked for.",
              )}
            {observedRows.map(renderRow)}
          </tbody>
        </table>
      </div>
      {matrix.summaries.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {matrix.summaries.map((summary) => (
            <p key={summary} data-testid="comparison-summary" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
              {summary}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

/** Transparent counts only — never a percentage or a composite score. */
function summariseCounts(column: MatrixColumn): string {
  const { counts } = column
  if (counts.required_total > 0) {
    return `${counts.required_proven} of ${counts.required_total} required proven`
  }
  if (counts.observed_total > 0) {
    return `evidence for ${counts.observed_proven} of ${counts.observed_total} compared skills`
  }
  if (counts.preferred_total > 0) {
    return `${counts.preferred_proven} of ${counts.preferred_total} preferred proven`
  }
  return ""
}
