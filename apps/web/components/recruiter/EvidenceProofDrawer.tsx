"use client"

/**
 * Shared "View proof" evidence drawer — the one way the recruiter product
 * expands the actual PUBLISHED evidence behind a verified requirement,
 * without a second search. Extracted from RecruiterSearchView (V1.6) so the
 * search results, brief-scoped search, and the V4 interview workspace all
 * render proof identically.
 *
 * Every field shown is a projection of PUBLIC Work Passport data — titles,
 * published report paths, closed proof-type labels, qualitative statuses,
 * sanitized public trace previews. Never private artifacts, never a score.
 */

import { useEffect, useRef, useState } from "react"

import { Badge, TOKEN } from "../passport/shared"
import {
  viewEvidence,
  type EvidenceItem,
  type RequirementMatch,
} from "@/lib/recruiter-search-api"

/** Qualitative status → badge tone (labels only — never numeric). */
function statusTone(status: string): "emerald" | "indigo" | "slate" {
  if (status === "Demonstrated") return "emerald"
  if (status === "Partially demonstrated" || status === "Evidence observed") {
    return "indigo"
  }
  return "slate"
}

/**
 * One proof unit: a skill's published evidence (or an explicitly-labeled
 * project technology claim), with the projects and sanitized trace previews
 * behind it, linking through to the real public artifacts.
 */
export function EvidenceItemBlock({ item }: { item: EvidenceItem }) {
  const claimed = item.tier === "claimed"
  return (
    <div
      data-testid="evidence-item"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "10px 12px",
        borderRadius: 10,
        border: `1px solid ${TOKEN.line}`,
        background: claimed ? "#fffdf5" : "#fafbff",
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        {item.requirement_display && item.requirement_display !== item.skill && (
          <span style={{ fontSize: 12, color: TOKEN.muted, fontWeight: 600 }}>
            {item.requirement_display} ·
          </span>
        )}
        <span style={{ fontSize: 13.5, color: TOKEN.ink, fontWeight: 700, overflowWrap: "anywhere" }}>
          {item.skill}
        </span>
        <Badge tone={claimed ? "slate" : statusTone(item.status)}>
          {claimed ? "Claimed — not verified evidence" : item.status}
        </Badge>
        {item.evidence_sources.slice(0, 4).map((source) => (
          <Badge key={source} tone="purple">
            {source}
          </Badge>
        ))}
      </div>
      {item.note && (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5, overflowWrap: "anywhere" }}>
          {item.note}
        </p>
      )}
      {item.projects.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {item.projects.map((project, index) => (
            <div
              key={`${project.title}-${index}`}
              style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", fontSize: 12.5 }}
            >
              <span style={{ color: TOKEN.inkSoft, fontWeight: 600, overflowWrap: "anywhere" }}>
                {project.title || "Published project"}
              </span>
              {project.proof_types.slice(0, 4).map((type) => (
                <span key={type} style={{ fontSize: 11, color: TOKEN.muted }}>
                  {type}
                </span>
              ))}
              {project.public_report_path && (
                <a
                  data-testid="evidence-open-project"
                  href={project.public_report_path}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap" }}
                >
                  Open project report →
                </a>
              )}
            </div>
          ))}
        </div>
      )}
      {item.traces.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {item.traces.map((trace, index) => (
            <p
              key={`${trace.source_title}-${index}`}
              style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5, overflowWrap: "anywhere" }}
            >
              <span style={{ fontWeight: 600, color: TOKEN.inkSoft }}>
                {trace.source_type}
                {trace.source_title ? ` · ${trace.source_title}` : ""}
              </span>
              {trace.summary ? ` — ${trace.summary}` : ""}
              {trace.public_url && (
                <>
                  {" "}
                  <a
                    href={trace.public_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
                  >
                    Open source ↗
                  </a>
                </>
              )}
            </p>
          ))}
        </div>
      )}
      {item.proof_path && (
        <a
          data-testid="evidence-view-full"
          href={item.proof_path}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            alignSelf: "flex-start",
            fontSize: 12.5,
            color: TOKEN.indigo,
            fontWeight: 700,
            textDecoration: "none",
          }}
        >
          View full evidence →
        </a>
      )}
    </div>
  )
}

/**
 * The proof drawer body: lazily loads the published evidence behind one
 * requirement concept for one candidate the first time it opens, keeps the
 * loaded items across close/reopen, and retries after an error on the next
 * open. Render it ALWAYS (it renders null while closed) so the cache lives
 * with the row, exactly like the original inline implementation.
 */
export function EvidenceProofDrawer({
  open,
  skill,
  candidateSlug,
  style,
}: {
  open: boolean
  /** The requirement concept to show proof for (stable identifier). */
  skill: string
  candidateSlug?: string
  style?: React.CSSProperties
}) {
  const [items, setItems] = useState<EvidenceItem[] | null>(null)
  const [drawerError, setDrawerError] = useState<string | null>(null)
  const [drawerLoading, setDrawerLoading] = useState(false)
  // One fetch attempt per open — closing and reopening after an error
  // retries (items is still null), matching the pre-extraction behavior.
  const attemptedRef = useRef(false)

  // Deps are ONLY the fetch identity (open/skill/candidate): including the
  // loading/items state would re-run the effect mid-fetch and its cleanup
  // would cancel the in-flight request, leaving the drawer loading forever.
  // The closure's `items` is fresh on every open toggle, which is the only
  // moment it is read.
  useEffect(() => {
    if (!open) {
      attemptedRef.current = false
      return
    }
    if (attemptedRef.current || items !== null) return
    attemptedRef.current = true
    let cancelled = false
    setDrawerLoading(true)
    setDrawerError(null)
    viewEvidence({ skill, candidate: candidateSlug })
      .then((res) => {
        if (cancelled) return
        setItems(res.evidence.groups.flatMap((group) => group.items))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setDrawerError(err instanceof Error ? err.message : "Could not load proof.")
      })
      .finally(() => {
        if (!cancelled) setDrawerLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see comment above
  }, [open, skill, candidateSlug])

  if (!open) return null
  return (
    <div
      data-testid="requirement-proof-drawer"
      style={{ display: "flex", flexDirection: "column", gap: 8, marginLeft: 18, ...style }}
    >
      {drawerLoading ? (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>Loading proof…</p>
      ) : drawerError ? (
        <p role="alert" style={{ fontSize: 12, color: TOKEN.rose, margin: 0 }}>
          {drawerError}
        </p>
      ) : items && items.length > 0 ? (
        items.map((item, index) => (
          <EvidenceItemBlock key={`${item.skill_slug}-${index}`} item={item} />
        ))
      ) : items ? (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
          No published evidence artifacts for this requirement.
        </p>
      ) : null}
    </div>
  )
}

/** Evidence citation line under one verified requirement. */
export function requirementDetail(req: RequirementMatch): string {
  if (!req.satisfied) return req.note ?? `No published ${req.display} evidence`
  const parts: string[] = []
  if (req.matched_label && req.matched_label !== req.display) {
    parts.push(`via ${req.matched_label}`)
  }
  if (req.skill_status) parts.push(req.skill_status)
  if (req.evidence_sources.length > 0) {
    parts.push(req.evidence_sources.slice(0, 3).join(" · "))
  }
  if (req.project_titles.length > 0) {
    parts.push(`in ${req.project_titles.slice(0, 2).join(", ")}`)
  }
  if (req.note && parts.length === 0) parts.push(req.note)
  return parts.join(" · ")
}

/**
 * One verified-requirement line (✓/✕ + evidence citation) with the
 * expandable proof drawer behind satisfied concept requirements.
 */
export function RequirementRow({
  req,
  candidateSlug,
}: {
  req: RequirementMatch
  candidateSlug?: string
}) {
  const satisfied = req.satisfied
  const detail = requirementDetail(req)
  // View proof: expand the actual published evidence behind a verified
  // requirement without a second search. Concept requirements only —
  // evidence expectations and soft context rows have no per-skill artifact.
  const canViewProof = Boolean(candidateSlug) && req.kind === "concept" && satisfied
  const [open, setOpen] = useState(false)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "baseline",
          fontSize: 12.5,
          lineHeight: 1.5,
        }}
      >
        <span
          aria-hidden
          style={{
            color: satisfied ? TOKEN.emerald : TOKEN.rose,
            fontWeight: 700,
            flexShrink: 0,
          }}
        >
          {satisfied ? "✓" : "✕"}
        </span>
        <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
          <span
            style={{
              color: satisfied ? TOKEN.ink : TOKEN.rose,
              fontWeight: 600,
            }}
          >
            {req.display}
            {!req.required && (
              <span style={{ color: TOKEN.muted, fontWeight: 500 }}> (preferred)</span>
            )}
          </span>
          {detail && (
            <span style={{ color: TOKEN.muted }}> — {detail}</span>
          )}
          {canViewProof && (
            <>
              {" "}
              <button
                type="button"
                data-testid="requirement-view-proof"
                aria-expanded={open}
                onClick={() => setOpen((current) => !current)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  color: TOKEN.indigo,
                  fontSize: 12,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                {open ? "Hide proof" : "View proof"}
              </button>
            </>
          )}
        </span>
      </div>
      {canViewProof && (
        <EvidenceProofDrawer
          open={open}
          skill={req.requirement}
          candidateSlug={candidateSlug}
        />
      )}
    </div>
  )
}
