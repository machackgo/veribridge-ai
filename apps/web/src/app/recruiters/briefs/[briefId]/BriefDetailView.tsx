"use client"

/**
 * Hiring Brief detail — the role's workspace.
 *
 * One brief = one hiring need: the requirement plan (deterministically
 * parsed, shown as editable chips), the ROLE-SCOPED candidate pool
 * (status + private note per (brief, candidate) — shortlisting here never
 * leaks to other briefs), a live evidence comparison matrix (closed cell
 * states, transparent counts, never a score), and brief-scoped search
 * driven by the stored plan. Every evaluation re-runs against live public
 * evidence — nothing is snapshotted.
 */

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"

import {
  Badge,
  Btn,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
  type BadgeTone,
} from "../../../../../components/passport/shared"
import {
  addBriefCandidates,
  BriefApiError,
  briefSearch,
  CANDIDATE_STAGE_ORDER,
  getBrief,
  getBriefComparison,
  listBriefCandidates,
  removeBriefCandidate,
  updateBrief,
  updateBriefCandidate,
  type BriefCandidate,
  type BriefCandidateStatus,
  type BriefCandidatesResponse,
  type BriefComparisonResponse,
  type BriefStatus,
  type BriefStatusCounts,
  type HiringBrief,
  type MatrixCell,
  type RequirementsView,
} from "@/lib/recruiter-briefs-api"
import {
  listConnections,
  type RecruiterConnection,
} from "@/lib/recruiter-connections-api"
import type { RecruiterSearchResponse } from "@/lib/recruiter-search-api"
import { BRIEF_STATUS_LABEL } from "../BriefsListView"

export const CANDIDATE_STATUS_LABEL: Record<BriefCandidateStatus, string> = {
  saved: "Saved",
  reviewing: "Reviewing",
  shortlisted: "Shortlisted",
  contacted: "Contacted",
  interview: "Interview",
  decision: "Decision",
  hired: "Hired",
  passed: "Passed",
  archived: "Archived",
}

// Tones are calm and never carry meaning alone — the text label is always
// rendered beside them.
export const CANDIDATE_STATUS_TONE: Record<BriefCandidateStatus, BadgeTone> = {
  saved: "slate",
  reviewing: "sky",
  shortlisted: "emerald",
  contacted: "purple",
  interview: "indigo",
  decision: "amber",
  hired: "emerald",
  passed: "rose",
  archived: "slate",
}

/** Fresh all-zero role-scoped stage counts (client-side recompute base). */
function emptyStatusCounts(): BriefStatusCounts {
  return Object.fromEntries(
    CANDIDATE_STAGE_ORDER.map((status) => [status, 0]),
  ) as unknown as BriefStatusCounts
}

type Tab = "candidates" | "compare" | "search"

function chipStyle(kind: "required" | "preferred" | "excluded" | "evidence") {
  const palette = {
    required: { bg: TOKEN.indigoSoft, color: TOKEN.indigo },
    preferred: { bg: "#f5f3ff", color: "#7c3aed" },
    excluded: { bg: "#fef2f2", color: "#b91c1c" },
    evidence: { bg: "#ecfdf5", color: "#047857" },
  }[kind]
  return {
    padding: "4px 10px",
    borderRadius: 999,
    background: palette.bg,
    color: palette.color,
    fontSize: 12,
    fontWeight: 600 as const,
  }
}

function RequirementsSection({ view }: { view: RequirementsView }) {
  const rows: { label: string; kind: "required" | "preferred" | "excluded" | "evidence"; chips: string[] }[] = [
    { label: "Required", kind: "required", chips: view.required.map((c) => c.display) },
    {
      label: "Required evidence",
      kind: "evidence",
      chips: view.evidence.map((c) => c.display),
    },
    { label: "Preferred", kind: "preferred", chips: view.preferred.map((c) => c.display) },
    {
      label: "Preferred evidence",
      kind: "evidence",
      chips: view.preferred_evidence.map((c) => c.display),
    },
    { label: "Not", kind: "excluded", chips: view.excluded.map((c) => c.display) },
  ]
  const context = [
    view.role,
    view.seniority,
    view.location,
    view.remote ? "Remote" : null,
  ].filter(Boolean)
  const hasAny = rows.some((r) => r.chips.length > 0) || context.length > 0

  return (
    <div data-testid="brief-requirements" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {!hasAny && (
        <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
          No requirements yet — describe the role below to build them.
        </p>
      )}
      {rows
        .filter((row) => row.chips.length > 0)
        .map((row) => (
          <div key={row.label} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 11.5, color: TOKEN.muted, fontWeight: 700, minWidth: 120 }}>
              {row.label}
            </span>
            {row.chips.map((chip) => (
              <span key={chip} data-testid="requirement-chip" style={chipStyle(row.kind)}>
                {chip}
              </span>
            ))}
          </div>
        ))}
      {context.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 11.5, color: TOKEN.muted, fontWeight: 700, minWidth: 120 }}>Context</span>
          {context.map((item) => (
            <Badge key={String(item)} tone="slate">
              {String(item)}
            </Badge>
          ))}
        </div>
      )}
      {view.unrecognized_terms.length > 0 && (
        <p data-testid="brief-unrecognized" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
          Not understood (never silently used): {view.unrecognized_terms.join(", ")}
        </p>
      )}
    </div>
  )
}

function EvaluationLine({ candidate }: { candidate: BriefCandidate }) {
  const evaluation = candidate.evaluation
  if (!evaluation) return null
  if (!evaluation.available) {
    return (
      <p data-testid="brief-candidate-unavailable" style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
        Evidence no longer publicly available.
      </p>
    )
  }
  const { counts } = evaluation
  const parts: string[] = []
  if (counts.required_total > 0) {
    parts.push(`${counts.required_proven} of ${counts.required_total} required proven`)
    if (counts.required_claimed > 0) parts.push(`${counts.required_claimed} claimed`)
  }
  if (counts.preferred_total > 0) {
    parts.push(`${counts.preferred_proven} of ${counts.preferred_total} preferred`)
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <p data-testid="brief-candidate-evaluation" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, fontWeight: 600 }}>
        {parts.length ? parts.join(" · ") : "No requirements to evaluate yet"}
      </p>
      {evaluation.missing_required.length > 0 && (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
          Missing: {evaluation.missing_required.join(", ")}
        </p>
      )}
      {evaluation.excluded_hits.length > 0 && (
        <p style={{ fontSize: 12, color: "#b91c1c", margin: 0 }}>
          Has excluded: {evaluation.excluded_hits.join(", ")}
        </p>
      )}
    </div>
  )
}

function PoolCandidateCard({
  briefId,
  entry,
  stageError,
  onChanged,
  onRemoved,
  onStageError,
}: {
  briefId: string
  entry: BriefCandidate
  /** Stage-move failure for THIS candidate, held by the parent — a stage
   * change remounts the card in another section, so card-local state
   * would silently lose the message. */
  stageError: string | null
  onChanged: (candidate: BriefCandidate) => void
  onRemoved: (studentUserId: string) => void
  onStageError: (studentUserId: string, message: string | null) => void
}) {
  const [busy, setBusy] = useState(false)
  const [noteDraft, setNoteDraft] = useState(entry.note ?? "")
  const [noteOpen, setNoteOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const name = entry.candidate.display_name ?? "Verified candidate"

  const setStatus = async (status: BriefCandidateStatus) => {
    if (status === entry.status) return
    const previous = entry
    setError(null)
    onStageError(entry.student_user_id, null)
    // Optimistic: the card moves to its new stage immediately; a failed
    // request reverts it and says why.
    onChanged({ ...entry, status })
    try {
      const updated = await updateBriefCandidate(briefId, entry.student_user_id, { status })
      onChanged({ ...previous, ...updated, evaluation: previous.evaluation })
    } catch (err) {
      onChanged(previous)
      onStageError(
        entry.student_user_id,
        err instanceof Error ? err.message : "Failed to update the stage.",
      )
    }
  }

  const saveNote = async () => {
    setBusy(true)
    setError(null)
    try {
      const trimmed = noteDraft.trim()
      const updated = trimmed
        ? await updateBriefCandidate(briefId, entry.student_user_id, { note: trimmed })
        : await updateBriefCandidate(briefId, entry.student_user_id, { clear_note: true })
      onChanged({ ...entry, ...updated, evaluation: entry.evaluation })
      setNoteOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save note.")
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await removeBriefCandidate(briefId, entry.student_user_id)
      onRemoved(entry.student_user_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove candidate.")
      setBusy(false)
    }
  }

  return (
    <Card style={{ padding: 16, height: "100%", display: "flex", flexDirection: "column" }}>
      <div data-testid="brief-candidate-card" style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h3 data-testid="brief-candidate-name" style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}>
              {name}
            </h3>
            {entry.candidate.headline && (
              <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.45 }}>
                {entry.candidate.headline}
              </p>
            )}
          </div>
          <span data-testid="brief-candidate-status-badge">
            <Badge tone={CANDIDATE_STATUS_TONE[entry.status]}>
              {CANDIDATE_STATUS_LABEL[entry.status]}
            </Badge>
          </span>
        </div>

        <EvaluationLine candidate={entry} />

        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: TOKEN.muted, fontWeight: 600 }}>
          Stage
          <select
            data-testid="brief-candidate-stage-select"
            value={entry.status}
            onChange={(event) => void setStatus(event.target.value as BriefCandidateStatus)}
            style={{
              flex: 1,
              minWidth: 0,
              padding: "6px 10px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              fontSize: 12.5,
              color: TOKEN.ink,
              background: "#fff",
            }}
          >
            {CANDIDATE_STAGE_ORDER.map((status) => (
              <option key={status} value={status}>
                {CANDIDATE_STATUS_LABEL[status]}
              </option>
            ))}
          </select>
        </label>

        {entry.note && !noteOpen && (
          <p data-testid="brief-candidate-note" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5, background: TOKEN.bg, borderRadius: 8, padding: "8px 10px" }}>
            {entry.note}
          </p>
        )}
        {noteOpen && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <textarea
              data-testid="brief-candidate-note-input"
              value={noteDraft}
              onChange={(event) => setNoteDraft(event.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="Private note for this role only — the candidate never sees it."
              style={{
                padding: "8px 10px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                fontSize: 12.5,
                color: TOKEN.ink,
                resize: "vertical",
                lineHeight: 1.5,
              }}
            />
            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                data-testid="brief-candidate-note-save"
                onClick={() => void saveNote()}
                disabled={busy}
                style={{ padding: "6px 12px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer" }}
              >
                Save note
              </button>
              <button
                type="button"
                onClick={() => {
                  setNoteOpen(false)
                  setNoteDraft(entry.note ?? "")
                }}
                style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {(error || stageError) && (
          <p role="alert" style={{ fontSize: 12, color: "#b91c1c", margin: 0 }}>
            {error ?? stageError}
          </p>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, borderTop: `1px solid ${TOKEN.line}`, paddingTop: 10, marginTop: "auto" }}>
          {!noteOpen && (
            <button
              type="button"
              data-testid="brief-candidate-note-toggle"
              onClick={() => setNoteOpen(true)}
              style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
            >
              {entry.note ? "Edit note" : "Add note"}
            </button>
          )}
          <button
            type="button"
            data-testid="brief-candidate-remove"
            onClick={() => void remove()}
            disabled={busy}
            style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: busy ? "wait" : "pointer" }}
          >
            Remove from role
          </button>
          <Link
            data-testid="brief-candidate-interview-link"
            href={`/recruiters/briefs/${encodeURIComponent(briefId)}/interview/${encodeURIComponent(entry.student_user_id)}`}
            style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.indigo, fontSize: 12, fontWeight: 600, textDecoration: "none" }}
          >
            Interview prep →
          </Link>
          {entry.candidate.public_slug ? (
            <a
              data-testid="brief-candidate-open"
              href={`/p/${encodeURIComponent(entry.candidate.public_slug)}`}
              style={{ marginLeft: "auto", padding: "6px 12px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12, fontWeight: 600, textDecoration: "none" }}
            >
              Open Passport →
            </a>
          ) : (
            <span style={{ marginLeft: "auto" }}>
              <Badge tone="amber">Passport currently private</Badge>
            </span>
          )}
        </div>
      </div>
    </Card>
  )
}

function MatrixCellView({ cell }: { cell: MatrixCell }) {
  if (cell.state === "proven") {
    return (
      <div data-testid="matrix-cell-proven" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <Badge tone="emerald">Proven</Badge>
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
      <Badge tone="slate">No evidence</Badge>
      {cell.related.length > 0 && (
        <span style={{ fontSize: 11, color: TOKEN.muted }}>
          Related (not proof): {cell.related.join(", ")}
        </span>
      )}
    </div>
  )
}

function ComparisonSection({ comparison }: { comparison: BriefComparisonResponse }) {
  const { matrix } = comparison
  return (
    <div data-testid="brief-comparison" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
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
        <table data-testid="comparison-matrix" style={{ borderCollapse: "collapse", width: "100%", minWidth: 640 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "10px 12px", fontSize: 12, color: TOKEN.muted, borderBottom: `1px solid ${TOKEN.line}`, background: TOKEN.bg, minWidth: 170 }}>
                Requirement
              </th>
              {matrix.columns.map((column) => (
                <th key={column.user_id} style={{ textAlign: "left", padding: "10px 12px", borderBottom: `1px solid ${TOKEN.line}`, background: TOKEN.bg, minWidth: 160 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    <span data-testid="comparison-column-name" style={{ fontSize: 13, color: TOKEN.ink, fontWeight: 700 }}>
                      {column.display_name ?? "Verified candidate"}
                    </span>
                    <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {column.brief_status && (
                        <Badge tone={CANDIDATE_STATUS_TONE[column.brief_status]}>
                          {CANDIDATE_STATUS_LABEL[column.brief_status]}
                        </Badge>
                      )}
                      {!column.available && <Badge tone="rose">Unavailable</Badge>}
                    </span>
                    <span style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 500 }}>
                      {column.available
                        ? `${column.counts.required_proven} of ${column.counts.required_total} required proven`
                        : column.unavailable_note ?? ""}
                    </span>
                    {column.passport_path && (
                      <a href={column.passport_path} style={{ fontSize: 11.5, color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}>
                        Passport →
                      </a>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.requirements.map((req) => (
              <tr key={req.key}>
                <td style={{ padding: "10px 12px", fontSize: 12.5, color: TOKEN.ink, fontWeight: 600, borderBottom: `1px solid ${TOKEN.line}`, verticalAlign: "top" }}>
                  {req.display}
                  {!req.required && (
                    <span style={{ display: "block", fontSize: 10.5, color: TOKEN.muted, fontWeight: 500 }}>
                      Preferred
                    </span>
                  )}
                </td>
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
            ))}
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

export function BriefDetailView({ briefId }: { briefId: string }) {
  const [brief, setBrief] = useState<HiringBrief | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>("candidates")

  const [pool, setPool] = useState<BriefCandidatesResponse | null>(null)
  const [poolLoading, setPoolLoading] = useState(true)
  const [poolError, setPoolError] = useState<string | null>(null)

  const [connections, setConnections] = useState<RecruiterConnection[]>([])

  const [roleTextDraft, setRoleTextDraft] = useState("")
  const [editingRequirements, setEditingRequirements] = useState(false)
  const [savingRequirements, setSavingRequirements] = useState(false)

  const [stageFilter, setStageFilter] = useState<BriefCandidateStatus | "all">("all")
  // Stage-move failures keyed by candidate: held here (not in the card)
  // because a stage change remounts the card in another section.
  const [stageErrors, setStageErrors] = useState<Record<string, string>>({})

  const [comparison, setComparison] = useState<BriefComparisonResponse | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState<string | null>(null)
  // Server-confirmed "not enough candidates" (defense in depth behind the
  // client-side comparableCount guard) — a calm empty state, never an error.
  const [comparisonTooFew, setComparisonTooFew] = useState(false)

  const [searchQ, setSearchQ] = useState("")
  const [searchResults, setSearchResults] = useState<RecruiterSearchResponse | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [addingSlug, setAddingSlug] = useState<string | null>(null)

  const loadBrief = useCallback(() => {
    setLoading(true)
    setError(null)
    getBrief(briefId)
      .then((loaded) => {
        setBrief(loaded)
        setRoleTextDraft(loaded.role_text ?? "")
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load the hiring brief."),
      )
      .finally(() => setLoading(false))
  }, [briefId])

  const loadPool = useCallback(() => {
    setPoolLoading(true)
    setPoolError(null)
    listBriefCandidates(briefId)
      .then(setPool)
      .catch((err: unknown) =>
        setPoolError(err instanceof Error ? err.message : "Failed to load the role's candidates."),
      )
      .finally(() => setPoolLoading(false))
  }, [briefId])

  useEffect(() => {
    loadBrief()
    loadPool()
    listConnections()
      .then(setConnections)
      .catch(() => setConnections([]))
  }, [loadBrief, loadPool])

  const loadComparison = useCallback(() => {
    setComparisonLoading(true)
    setComparisonError(null)
    setComparisonTooFew(false)
    getBriefComparison(briefId)
      .then(setComparison)
      .catch((err: unknown) => {
        if (err instanceof BriefApiError && err.code === "too_few_candidates") {
          // A valid small pool is an empty state, never "Something went wrong".
          setComparison(null)
          setComparisonTooFew(true)
          return
        }
        setComparisonError(err instanceof Error ? err.message : "Failed to load the comparison.")
      })
      .finally(() => setComparisonLoading(false))
  }, [briefId])

  // Comparison needs at least 2 candidates still in play for this role
  // (mirrors the server: archived candidates are excluded). Fetch only once
  // the pool is known and large enough — a small pool renders a calm empty
  // state without ever hitting the API.
  const comparableCount = (pool?.candidates ?? []).filter(
    (c) => c.status !== "archived",
  ).length

  useEffect(() => {
    if (tab === "compare" && !poolLoading && comparableCount >= 2) loadComparison()
  }, [tab, poolLoading, comparableCount, loadComparison])

  const saveRequirements = async () => {
    setSavingRequirements(true)
    try {
      const updated = await updateBrief(briefId, { role_text: roleTextDraft })
      setBrief(updated)
      setEditingRequirements(false)
      setComparison(null)
      loadPool()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update requirements.")
    } finally {
      setSavingRequirements(false)
    }
  }

  const setBriefStatus = async (status: BriefStatus) => {
    if (!brief || status === brief.status) return
    try {
      setBrief(await updateBrief(briefId, { status }))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update the brief.")
    }
  }

  const addConnection = async (connectionId: string) => {
    try {
      await addBriefCandidates(briefId, { connection_ids: [connectionId] })
      loadPool()
    } catch (err) {
      setPoolError(err instanceof Error ? err.message : "Failed to add the candidate.")
    }
  }

  const addFromSearch = async (slug: string) => {
    setAddingSlug(slug)
    try {
      await addBriefCandidates(briefId, { candidate_slugs: [slug] })
      loadPool()
      setSearchResults((current) =>
        current
          ? {
              ...current,
              results: current.results.map((r) =>
                r.public_slug === slug
                  ? { ...r, in_brief: true, brief_status: "saved" }
                  : r,
              ),
            }
          : current,
      )
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Failed to add the candidate.")
    } finally {
      setAddingSlug(null)
    }
  }

  const runSearch = async () => {
    setSearchLoading(true)
    setSearchError(null)
    try {
      setSearchResults(await briefSearch(briefId, { q: searchQ }))
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Search failed.")
    } finally {
      setSearchLoading(false)
    }
  }

  if (loading) {
    return (
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px" }}>
        <LoadingState label="Loading hiring brief…" />
      </div>
    )
  }
  if (error || !brief) {
    return (
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px" }}>
        <ErrorState message={error ?? "This role was not found."} onRetry={loadBrief} />
      </div>
    )
  }

  const inPoolConnectionIds = new Set(
    (pool?.candidates ?? [])
      .map((c) => c.connection_id)
      .filter((id): id is string => Boolean(id)),
  )
  const addableConnections = connections.filter((c) => !inPoolConnectionIds.has(c.id))

  return (
    <div
      data-testid="brief-detail"
      style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 10 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <p style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
            <Link href="/recruiters/briefs" data-testid="brief-back" style={{ color: TOKEN.muted, textDecoration: "none" }}>
              ← Hiring Briefs
            </Link>
          </p>
          <h1 data-testid="brief-title" style={{ fontSize: 26, color: TOKEN.ink, margin: "4px 0 0", letterSpacing: "-0.5px", overflowWrap: "anywhere" }}>
            {brief.title}
          </h1>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: TOKEN.muted, fontWeight: 600 }}>
          Status
          <select
            data-testid="brief-status-select"
            value={brief.status}
            onChange={(event) => void setBriefStatus(event.target.value as BriefStatus)}
            style={{ padding: "7px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 12.5, color: TOKEN.ink, background: "#fff" }}
          >
            {(Object.keys(BRIEF_STATUS_LABEL) as BriefStatus[]).map((status) => (
              <option key={status} value={status}>
                {BRIEF_STATUS_LABEL[status]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Card style={{ padding: 18 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h2 style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
              Role requirements
            </h2>
            <button
              type="button"
              data-testid="brief-edit-requirements"
              onClick={() => setEditingRequirements((open) => !open)}
              style={{ marginLeft: "auto", padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
            >
              {editingRequirements ? "Close" : "Edit role description"}
            </button>
          </div>
          <RequirementsSection view={brief.requirements_view} />
          {editingRequirements && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <textarea
                data-testid="brief-role-text-input"
                value={roleTextDraft}
                onChange={(event) => setRoleTextDraft(event.target.value)}
                maxLength={600}
                rows={3}
                style={{ padding: "10px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 13.5, color: TOKEN.ink, resize: "vertical", lineHeight: 1.5 }}
              />
              <div>
                <button
                  type="button"
                  data-testid="brief-role-text-save"
                  onClick={() => void saveRequirements()}
                  disabled={savingRequirements}
                  style={{ padding: "8px 16px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 700, border: "none", cursor: savingRequirements ? "wait" : "pointer" }}
                >
                  {savingRequirements ? "Updating…" : "Update requirements"}
                </button>
              </div>
            </div>
          )}
        </div>
      </Card>

      <nav style={{ display: "flex", gap: 8, flexWrap: "wrap" }} aria-label="Brief sections">
        {(
          [
            ["candidates", `Candidates (${pool?.total ?? brief.candidate_count})`],
            ["compare", "Compare evidence"],
            ["search", "Find candidates"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            data-testid={`brief-tab-${key}`}
            onClick={() => setTab(key)}
            aria-current={tab === key ? "page" : undefined}
            style={{
              padding: "7px 14px",
              borderRadius: 999,
              border: tab === key ? "none" : `1px solid ${TOKEN.line}`,
              background: tab === key ? TOKEN.indigo : "#fff",
              color: tab === key ? "#fff" : TOKEN.muted,
              fontSize: 12.5,
              fontWeight: tab === key ? 700 : 600,
              cursor: "pointer",
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "candidates" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {poolLoading ? (
            <LoadingState label="Loading candidates…" />
          ) : poolError ? (
            <ErrorState message={poolError} onRetry={loadPool} />
          ) : !pool || pool.total === 0 ? (
            <div data-testid="brief-pool-empty">
              <EmptyState
                icon="🎯"
                title="No candidates in this role yet"
                description="Add candidates from your saved list below, or use “Find candidates” to search with this role's requirements."
              />
            </div>
          ) : (
            (() => {
              const onCardChanged = (candidate: BriefCandidate) =>
                setPool((current) => {
                  if (!current) return current
                  const candidates = current.candidates.map((c) =>
                    c.student_user_id === candidate.student_user_id ? candidate : c,
                  )
                  const status_counts = emptyStatusCounts()
                  for (const c of candidates) status_counts[c.status] += 1
                  return { ...current, candidates, status_counts }
                })
              const onCardRemoved = (studentUserId: string) =>
                setPool((current) => {
                  if (!current) return current
                  const candidates = current.candidates.filter(
                    (c) => c.student_user_id !== studentUserId,
                  )
                  const status_counts = emptyStatusCounts()
                  for (const c of candidates) status_counts[c.status] += 1
                  return { ...current, candidates, status_counts, total: current.total - 1 }
                })
              const sections = CANDIDATE_STAGE_ORDER.filter(
                (status) => stageFilter === "all" || status === stageFilter,
              )
                .map((status) => ({
                  status,
                  entries: pool.candidates.filter((c) => c.status === status),
                }))
                .filter((section) => section.entries.length > 0)
              return (
                <>
                  {/* Stage summary bar: live counts, click to filter. */}
                  <div
                    data-testid="brief-stage-bar"
                    role="group"
                    aria-label="Pipeline stages"
                    style={{ display: "flex", flexWrap: "wrap", gap: 6 }}
                  >
                    {(
                      [
                        ["all", "All", pool.total] as const,
                        ...CANDIDATE_STAGE_ORDER.map(
                          (status) =>
                            [status, CANDIDATE_STATUS_LABEL[status], pool.status_counts[status]] as const,
                        ),
                      ]
                    ).map(([key, label, count]) => {
                      const active = stageFilter === key
                      return (
                        <button
                          key={key}
                          type="button"
                          data-testid={`brief-stage-pill-${key}`}
                          aria-pressed={active}
                          onClick={() =>
                            setStageFilter((current) =>
                              key === "all" || current === key ? "all" : key,
                            )
                          }
                          style={{
                            padding: "5px 11px",
                            borderRadius: 999,
                            border: `1px solid ${active ? TOKEN.indigo : TOKEN.line}`,
                            background: active ? TOKEN.indigoSoft : "#fff",
                            color: active ? TOKEN.indigo : TOKEN.muted,
                            fontSize: 12,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          {label} · {count}
                        </button>
                      )
                    })}
                  </div>

                  {sections.length === 0 ? (
                    <p
                      data-testid="brief-stage-filter-empty"
                      style={{ fontSize: 13, color: TOKEN.muted, margin: 0 }}
                    >
                      No candidates in{" "}
                      {stageFilter === "all" ? "this role" : CANDIDATE_STATUS_LABEL[stageFilter]}{" "}
                      yet.
                    </p>
                  ) : (
                    sections.map(({ status, entries }) => (
                      <section
                        key={status}
                        data-testid={`brief-stage-section-${status}`}
                        style={{ display: "flex", flexDirection: "column", gap: 10 }}
                      >
                        <h3 style={{ fontSize: 14, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                          {CANDIDATE_STATUS_LABEL[status]}{" "}
                          <span style={{ color: TOKEN.muted, fontWeight: 600 }}>
                            ({entries.length})
                          </span>
                        </h3>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 340px), 1fr))", gap: 14, alignItems: "stretch" }}>
                          {entries.map((entry) => (
                            <PoolCandidateCard
                              key={entry.student_user_id}
                              briefId={briefId}
                              entry={entry}
                              stageError={stageErrors[entry.student_user_id] ?? null}
                              onChanged={onCardChanged}
                              onRemoved={onCardRemoved}
                              onStageError={(studentUserId, message) =>
                                setStageErrors((current) => {
                                  const next = { ...current }
                                  if (message) next[studentUserId] = message
                                  else delete next[studentUserId]
                                  return next
                                })
                              }
                            />
                          ))}
                        </div>
                      </section>
                    ))
                  )}
                </>
              )
            })()
          )}

          {addableConnections.length > 0 && (
            <Card style={{ padding: 16 }}>
              <div data-testid="brief-add-saved" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <h3 style={{ fontSize: 14, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                  Add from saved candidates
                </h3>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {addableConnections.map((connection) => (
                    <div key={connection.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderBottom: `1px solid ${TOKEN.line}` }}>
                      <span style={{ fontSize: 13, color: TOKEN.ink, fontWeight: 600 }}>
                        {connection.candidate.display_name ?? "Verified candidate"}
                      </span>
                      {connection.candidate.headline && (
                        <span style={{ fontSize: 12, color: TOKEN.muted }}>{connection.candidate.headline}</span>
                      )}
                      <button
                        type="button"
                        data-testid="brief-add-connection"
                        onClick={() => void addConnection(connection.id)}
                        style={{ marginLeft: "auto", padding: "6px 12px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer" }}
                      >
                        Add to role
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          )}
        </div>
      )}

      {tab === "compare" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {poolLoading || comparisonLoading ? (
            <LoadingState label="Evaluating live evidence…" />
          ) : comparableCount < 2 || comparisonTooFew ? (
            <div data-testid="brief-comparison-empty">
              <EmptyState
                icon="⚖️"
                title={
                  comparableCount === 0
                    ? "No candidates to compare yet"
                    : "Only one candidate in this role"
                }
                description={
                  comparableCount === 0
                    ? "Find candidates using this role's requirements."
                    : "Add at least 2 candidates to compare evidence."
                }
                action={
                  <Btn variant="secondary" onClick={() => setTab("search")}>
                    Find candidates
                  </Btn>
                }
              />
            </div>
          ) : comparisonError ? (
            <div data-testid="brief-comparison-error">
              <ErrorState message={comparisonError} onRetry={loadComparison} />
            </div>
          ) : comparison ? (
            <ComparisonSection comparison={comparison} />
          ) : null}
          <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0 }}>
            Every cell is re-checked against live published evidence on load —
            proven, claimed (not verified), or no evidence. Never a score.
          </p>
        </div>
      )}

      {tab === "search" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void runSearch()
            }}
            style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
          >
            <input
              data-testid="brief-search-input"
              type="text"
              value={searchQ}
              onChange={(event) => setSearchQ(event.target.value)}
              placeholder="Optional refinement — e.g. “in Massachusetts or remote” (never changes the brief)"
              maxLength={600}
              style={{ flex: 1, minWidth: 220, padding: "10px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 13.5, color: TOKEN.ink }}
            />
            <button
              type="submit"
              data-testid="brief-search-submit"
              disabled={searchLoading}
              style={{ padding: "9px 18px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 13, fontWeight: 700, border: "none", cursor: searchLoading ? "wait" : "pointer" }}
            >
              {searchLoading ? "Searching…" : "Search with role requirements"}
            </button>
          </form>

          {searchError && <ErrorState message={searchError} onRetry={runSearch} />}

          {searchResults && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <p data-testid="brief-search-totals" style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
                {searchResults.exact_total} exact · {searchResults.close_total} close
              </p>
              {searchResults.results.length === 0 ? (
                <EmptyState
                  icon="🔍"
                  title="No candidates matched"
                  description="No published passport currently evidences these requirements. Try relaxing the refinement."
                />
              ) : (
                searchResults.results.map((result) => (
                  <Card key={result.public_slug} style={{ padding: 14 }}>
                    <div data-testid="brief-search-result" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <h3 style={{ fontSize: 14.5, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                            {result.display_name ?? "Verified candidate"}
                          </h3>
                          {result.headline && (
                            <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: "2px 0 0" }}>{result.headline}</p>
                          )}
                        </div>
                        <Badge tone={result.match_type === "exact" ? "emerald" : "amber"}>
                          {result.match_type === "exact" ? "Exact match" : result.match_type === "close" ? "Close match" : "Match"}
                        </Badge>
                        {result.in_brief && (
                          <span data-testid="brief-search-in-brief">
                            <Badge tone="indigo">
                              In role{result.brief_status && result.brief_status !== "saved" ? ` · ${CANDIDATE_STATUS_LABEL[result.brief_status as BriefCandidateStatus] ?? result.brief_status}` : ""}
                            </Badge>
                          </span>
                        )}
                      </div>
                      {result.missing_requirements.length > 0 && (
                        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                          Missing: {result.missing_requirements.join(", ")}
                        </p>
                      )}
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                        {!result.in_brief && (
                          <button
                            type="button"
                            data-testid="brief-search-add"
                            onClick={() => void addFromSearch(result.public_slug)}
                            disabled={addingSlug === result.public_slug}
                            style={{ padding: "6px 12px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer" }}
                          >
                            {addingSlug === result.public_slug ? "Adding…" : "Add to role"}
                          </button>
                        )}
                        <a
                          href={`/p/${encodeURIComponent(result.public_slug)}`}
                          style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, color: TOKEN.indigo, fontSize: 12, fontWeight: 600, textDecoration: "none" }}
                        >
                          Open Passport →
                        </a>
                      </div>
                    </div>
                  </Card>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
