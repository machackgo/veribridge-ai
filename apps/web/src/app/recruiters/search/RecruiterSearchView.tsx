"use client"

/**
 * Recruiter Search & Discovery V1.5 — natural-language, requirement-verified
 * candidate search.
 *
 * The recruiter describes who they need (typed or spoken); the API parses
 * that into explicit requirements (shown back as "Understood as" chips —
 * interpretation is never a silent guess), verifies every requirement
 * against PUBLISHED Work Passport evidence, and returns EXACT matches
 * (every requirement evidenced) separated from CLOSE matches (missing
 * requirements stated explicitly). Explanations trace to real published
 * data — never scores, never fabricated qualifications.
 *
 * Voice search is a progressive enhancement over the browser's native
 * speech recognition: mic starts only on click, one utterance, transcript
 * lands visibly in the search box (editable) — no audio ever reaches a
 * VeriBridge server.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../components/passport/shared"
import {
  AddToBriefButton,
  AddToPoolButton,
} from "../../../../components/recruiter/AddToListButtons"
import {
  EvidenceItemBlock,
  RequirementRow,
} from "../../../../components/recruiter/EvidenceProofDrawer"
import { RecruiterNav } from "../../../../components/recruiter/RecruiterNav"
import {
  listConnections,
  saveCandidate,
} from "@/lib/recruiter-connections-api"
import {
  createSavedSearch,
  type SavedSearchListItem,
} from "@/lib/recruiter-saved-searches-api"
import {
  searchCandidates,
  type AvailabilityFilter,
  type EvidenceFilter,
  type EvidenceResults,
  type MatchedReason,
  type QueryInterpretation,
  type RecruiterSearchResponse,
  type SearchResultCandidate,
} from "@/lib/recruiter-search-api"
import { useSpeechRecognition } from "@/lib/use-speech-recognition"

const EVIDENCE_OPTIONS: { key: EvidenceFilter; label: string }[] = [
  { key: "github", label: "GitHub code" },
  { key: "live_site", label: "Live deployed site" },
  { key: "documents", label: "Documents" },
  { key: "project_defense", label: "Project defense" },
  { key: "video", label: "Video evidence" },
]

const AVAILABILITY_OPTIONS: { key: AvailabilityFilter; label: string }[] = [
  { key: "seeking_internship", label: "Seeking internship" },
  { key: "seeking_full_time", label: "Seeking full-time" },
  { key: "open_to_opportunities", label: "Open to opportunities" },
]

const EXAMPLE_QUERIES = [
  "AI engineer with Python and NLP who has deployed a project",
  "Show me proof of machine learning",
  "Which project proves FastAPI",
]

function initialsOf(name: string | null): string {
  if (!name) return "✓"
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? "")
      .join("") || "✓"
  )
}

/** Human sentence for one structured match reason (lexical-mode results). */
function reasonText(reason: MatchedReason): string {
  switch (reason.type) {
    case "skill": {
      const sources = (reason.evidence_sources ?? []).slice(0, 3).join(", ")
      return `${reason.label} — ${reason.skill_status ?? "verified"}${sources ? ` · ${sources}` : ""}`
    }
    case "technology":
      return `${reason.label} — used in ${reason.project_title || "a public project"} (claimed)`
    case "name":
      return `Name matches “${reason.term ?? ""}”`
    case "headline":
      return `Headline: ${reason.label}`
    case "role_area":
      return `Focus area: ${reason.label}`
    case "project":
      return `Project: ${reason.label}`
    case "education":
      return `Education: ${reason.label}`
    case "location":
      return `Location: ${reason.label}`
    default:
      return reason.label
  }
}

function reasonTone(reason: MatchedReason): "emerald" | "indigo" | "slate" {
  if (reason.type === "skill") return "emerald"
  if (reason.type === "technology") return "indigo"
  return "slate"
}

type SaveState = "idle" | "saving" | "saved" | "error"

function ResultSaveButton({
  slug,
  query,
  initiallySaved,
}: {
  slug: string
  query: string
  initiallySaved: boolean
}) {
  // Callers key this component on slug + initiallySaved, so a change in the
  // saved-state mark remounts it — no prop→state syncing effect needed.
  const [state, setState] = useState<SaveState>(initiallySaved ? "saved" : "idle")
  const [message, setMessage] = useState<string | null>(null)

  const save = async () => {
    setState("saving")
    setMessage(null)
    try {
      // Reuses the existing idempotent connection model — repeat saves can
      // never duplicate. Attribution: source=search plus the query used.
      await saveCandidate(slug, "search", {
        passport_slug: slug,
        ...(query ? { query } : {}),
      })
      setState("saved")
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to save candidate.")
      setState("error")
    }
  }

  if (state === "saved") {
    return (
      <span
        data-testid="search-result-saved"
        style={{
          padding: "8px 14px",
          borderRadius: 8,
          background: TOKEN.emeraldSoft,
          color: TOKEN.emerald,
          fontSize: 12.5,
          fontWeight: 600,
        }}
      >
        Saved ✓
      </span>
    )
  }

  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 4 }}>
      <button
        type="button"
        data-testid="search-result-save"
        onClick={() => void save()}
        disabled={state === "saving"}
        style={{
          padding: "8px 14px",
          borderRadius: 8,
          border: "none",
          background: state === "saving" ? TOKEN.indigoSoft : TOKEN.indigo,
          color: state === "saving" ? TOKEN.indigo : "#fff",
          fontSize: 12.5,
          fontWeight: 600,
          cursor: state === "saving" ? "wait" : "pointer",
        }}
      >
        {state === "saving" ? "Saving…" : "Save Candidate"}
      </button>
      {state === "error" && (
        <span data-testid="search-result-save-error" role="alert" style={{ fontSize: 11.5, color: TOKEN.rose }}>
          {message ?? "Failed to save."}
        </span>
      )}
    </span>
  )
}

function ResultCard({
  candidate,
  query,
  initiallySaved,
}: {
  candidate: SearchResultCandidate
  query: string
  initiallySaved: boolean
}) {
  const name = candidate.display_name ?? "Verified candidate"
  const educationLine = [candidate.degree, candidate.institution]
    .filter(Boolean)
    .join(" · ")
  const requirements = candidate.requirements ?? []
  const hasRequirements = requirements.length > 0
  const hasReasons = (candidate.matched_reasons ?? []).length > 0
  const skillsToShow = candidate.skills.slice(0, 6)
  const isClose = candidate.match_type === "close"

  return (
    <Card
      style={{
        padding: 18,
        ...(isClose ? { borderColor: TOKEN.line, opacity: 0.96 } : {}),
      }}
    >
      <div
        data-testid="search-result-card"
        data-match-type={candidate.match_type ?? "match"}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div
            aria-hidden
            style={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              background: TOKEN.indigoSoft,
              color: TOKEN.indigo,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 700,
              fontSize: 16,
              flexShrink: 0,
            }}
          >
            {initialsOf(candidate.display_name)}
          </div>
          {/* Basis keeps the identity block a readable width — when the
              actions don't fit beside it, THEY wrap below instead of
              crushing the name to a letter per line. */}
          <div style={{ minWidth: 0, flex: "1 1 200px" }}>
            <h3
              data-testid="search-result-name"
              style={{ fontSize: 16, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}
            >
              {name}
            </h3>
            {candidate.headline && (
              <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5, overflowWrap: "anywhere" }}>
                {candidate.headline}
              </p>
            )}
            {educationLine && (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "2px 0 0", overflowWrap: "anywhere" }}>
                {educationLine}
                {candidate.graduation_year ? ` · ${candidate.graduation_year}` : ""}
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <a
              data-testid="search-result-open"
              href={`/p/${encodeURIComponent(candidate.public_slug)}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.ink,
                fontSize: 12.5,
                fontWeight: 600,
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              Open Passport →
            </a>
            <ResultSaveButton
              key={`${candidate.public_slug}:${initiallySaved ? "saved" : "idle"}`}
              slug={candidate.public_slug}
              query={query}
              initiallySaved={initiallySaved}
            />
            <AddToPoolButton candidateSlug={candidate.public_slug} source="search" />
            <AddToBriefButton candidateSlug={candidate.public_slug} />
          </div>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {candidate.availability_label && <Badge tone="indigo">{candidate.availability_label}</Badge>}
          {candidate.location && <Badge tone="slate">{candidate.location}</Badge>}
          {candidate.role_areas.slice(0, 3).map((area) => (
            <Badge key={area} tone="purple">
              {area}
            </Badge>
          ))}
          <Badge tone="slate">
            {candidate.project_count} public {candidate.project_count === 1 ? "project" : "projects"}
          </Badge>
        </div>

        {hasRequirements ? (
          <div
            data-testid="search-result-requirements"
            style={{ display: "flex", flexDirection: "column", gap: 6 }}
          >
            <p
              style={{
                fontSize: 11,
                letterSpacing: "0.07em",
                textTransform: "uppercase",
                color: TOKEN.muted,
                margin: 0,
                fontWeight: 700,
              }}
            >
              Why this candidate matched
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {requirements.map((req, index) => (
                <RequirementRow
                  key={`${req.kind}-${req.requirement}-${index}`}
                  req={req}
                  candidateSlug={candidate.public_slug}
                />
              ))}
            </div>
          </div>
        ) : hasReasons ? (
          <div data-testid="search-result-reasons" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <p
              style={{
                fontSize: 11,
                letterSpacing: "0.07em",
                textTransform: "uppercase",
                color: TOKEN.muted,
                margin: 0,
                fontWeight: 700,
              }}
            >
              Match evidence
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {(candidate.matched_reasons ?? []).map((reason, index) => (
                <Badge
                  key={`${reason.type}-${reason.label}-${index}`}
                  tone={reasonTone(reason)}
                  // Reason chips carry real prose (headlines, education) —
                  // they must wrap on narrow screens, never overflow.
                  style={{ whiteSpace: "normal", overflowWrap: "anywhere", textAlign: "left" }}
                >
                  {reason.type === "skill" ? "✓ " : ""}
                  {reasonText(reason)}
                </Badge>
              ))}
            </div>
          </div>
        ) : (
          skillsToShow.length > 0 && (
            <div data-testid="search-result-skills" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <p
                style={{
                  fontSize: 11,
                  letterSpacing: "0.07em",
                  textTransform: "uppercase",
                  color: TOKEN.muted,
                  margin: 0,
                  fontWeight: 700,
                }}
              >
                Evidence-backed skills
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {skillsToShow.map((skill) => (
                  <Badge
                    key={skill.skill}
                    tone="emerald"
                    style={{ whiteSpace: "normal", overflowWrap: "anywhere", textAlign: "left" }}
                  >
                    ✓ {skill.skill} — {skill.status}
                  </Badge>
                ))}
              </div>
            </div>
          )
        )}

        {candidate.projects.length > 0 && (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5, overflowWrap: "anywhere" }}>
            Projects: {candidate.projects.map((p) => p.title).filter(Boolean).join(" · ")}
          </p>
        )}
      </div>
    </Card>
  )
}

/**
 * Evidence Discovery results: one card per candidate holding EVERY proof
 * item found for them (many proofs, one identity), plus explicit no-proof
 * statements and clearly-labeled related-evidence hints.
 */
function EvidenceResultsSection({
  evidence,
  query,
  savedSlugs,
}: {
  evidence: EvidenceResults
  query: string
  savedSlugs: Set<string>
}) {
  const hasProof = evidence.groups.length > 0
  return (
    <div data-testid="evidence-results" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p data-testid="evidence-result-count" style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
        {hasProof ? (
          <>
            <strong style={{ color: TOKEN.ink }}>
              {evidence.total_items} proof {evidence.total_items === 1 ? "item" : "items"}
            </strong>{" "}
            across {evidence.groups.length}{" "}
            {evidence.groups.length === 1 ? "candidate" : "candidates"}
            {query && (
              <>
                {" "}for <strong style={{ color: TOKEN.ink }}>“{query}”</strong>
              </>
            )}
          </>
        ) : (
          <>No published proof matches this request.</>
        )}
      </p>

      {evidence.notes.map((note) => (
        <p
          key={note}
          data-testid="evidence-note"
          style={{
            fontSize: 12.5,
            color: TOKEN.inkSoft,
            margin: 0,
            lineHeight: 1.6,
            padding: "10px 12px",
            borderRadius: 10,
            background: TOKEN.indigoSoft,
          }}
        >
          {note}
        </p>
      ))}

      {evidence.groups.map((group) => {
        const initiallySaved = savedSlugs.has(group.public_slug)
        return (
          <Card key={group.public_slug} style={{ padding: 18 }}>
            <div
              data-testid="evidence-group-card"
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                <div
                  aria-hidden
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: "50%",
                    background: TOKEN.emeraldSoft,
                    color: TOKEN.emerald,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                    fontSize: 16,
                    flexShrink: 0,
                  }}
                >
                  {initialsOf(group.display_name)}
                </div>
                <div style={{ minWidth: 0, flex: "1 1 200px" }}>
                  <p style={{ fontSize: 11, letterSpacing: "0.07em", textTransform: "uppercase", color: TOKEN.emerald, margin: 0, fontWeight: 700 }}>
                    Proof found
                  </p>
                  <h3
                    data-testid="evidence-group-name"
                    style={{ fontSize: 16, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}
                  >
                    {group.display_name ?? "Verified candidate"}
                  </h3>
                  {group.headline && (
                    <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5, overflowWrap: "anywhere" }}>
                      {group.headline}
                    </p>
                  )}
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <a
                    data-testid="evidence-open-passport"
                    href={group.passport_path}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      padding: "8px 14px",
                      borderRadius: 8,
                      border: `1px solid ${TOKEN.line}`,
                      background: "#fff",
                      color: TOKEN.ink,
                      fontSize: 12.5,
                      fontWeight: 600,
                      textDecoration: "none",
                      whiteSpace: "nowrap",
                    }}
                  >
                    Open Passport →
                  </a>
                  <ResultSaveButton
                    key={`${group.public_slug}:${initiallySaved ? "saved" : "idle"}`}
                    slug={group.public_slug}
                    query={query}
                    initiallySaved={initiallySaved}
                  />
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {group.items.map((item, index) => (
                  <EvidenceItemBlock key={`${item.skill_slug}-${item.requirement}-${index}`} item={item} />
                ))}
              </div>
            </div>
          </Card>
        )
      })}

      {evidence.unmatched.map((entry) => (
        <div
          key={entry.requirement}
          data-testid="evidence-unmatched"
          style={{
            padding: "12px 14px",
            borderRadius: 10,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
          }}
        >
          <p style={{ fontSize: 13, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
            {entry.display}: no published proof
          </p>
          <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: "4px 0 0", lineHeight: 1.5 }}>
            {entry.note}
          </p>
        </div>
      ))}

      {evidence.related.map((hint) => (
        <div
          key={`${hint.requirement_display}-${hint.related_display}`}
          data-testid="evidence-related"
          style={{
            padding: "12px 14px",
            borderRadius: 10,
            border: `1px dashed ${TOKEN.line}`,
            background: "#fafafa",
          }}
        >
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Related evidence — not {hint.requirement_display} proof
          </p>
          <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: "4px 0 0", lineHeight: 1.5 }}>
            {hint.note}
            {hint.candidate_names.length > 0 && (
              <> Published by: {hint.candidate_names.join(", ")}.</>
            )}
          </p>
        </div>
      ))}
    </div>
  )
}

/** "Understood as …" — the executed interpretation, shown transparently. */
/** The parser canonicalizes locations to lowercase ("Boston, MA" →
 * "massachusetts"); present them as place names. */
function titleCaseLocation(location: string): string {
  return location.replace(/\b[a-z]/g, (letter) => letter.toUpperCase())
}

function InterpretationPanel({ interp }: { interp: QueryInterpretation }) {
  const evidenceIntent =
    interp.intent === "evidence_search" || interp.intent === "project_search"
  const hasChips =
    evidenceIntent ||
    interp.required.length > 0 ||
    interp.preferred.length > 0 ||
    interp.excluded.length > 0 ||
    interp.evidence.length > 0 ||
    interp.preferred_evidence.length > 0 ||
    Boolean(interp.role) ||
    Boolean(interp.seniority) ||
    Boolean(interp.location) ||
    interp.residual_terms.length > 0
  if (!hasChips) return null
  return (
    <div
      data-testid="search-interpretation"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 6,
        alignItems: "center",
        padding: "10px 12px",
        borderRadius: 10,
        background: TOKEN.indigoSoft,
      }}
    >
      <span style={{ fontSize: 11.5, color: TOKEN.indigo, fontWeight: 700 }}>
        Understood as:
      </span>
      {evidenceIntent && (
        <span data-testid="interpretation-intent" style={{ display: "inline-flex" }}>
          <Badge tone="emerald">
            {interp.intent === "project_search" ? "Project proof search" : "Evidence search"}
          </Badge>
        </span>
      )}
      {interp.role && <Badge tone="purple">Role: {interp.role}</Badge>}
      {interp.seniority && <Badge tone="purple">{interp.seniority}</Badge>}
      {interp.location && (
        <Badge tone="slate">Near: {titleCaseLocation(interp.location)}</Badge>
      )}
      {interp.required.map((chip) => (
        <Badge key={`req-${chip.display}`} tone="indigo">
          {chip.display}
        </Badge>
      ))}
      {interp.evidence.map((chip) => (
        <Badge key={`ev-${chip.key}`} tone="emerald">
          {chip.display}
        </Badge>
      ))}
      {interp.preferred.map((chip) => (
        <Badge key={`pref-${chip.display}`} tone="slate">
          Preferred: {chip.display}
        </Badge>
      ))}
      {interp.preferred_evidence.map((chip) => (
        <Badge key={`prefev-${chip.key}`} tone="slate">
          Preferred: {chip.display}
        </Badge>
      ))}
      {interp.excluded.map((chip) => (
        <Badge key={`not-${chip.display}`} tone="rose">
          Not: {chip.display}
        </Badge>
      ))}
      {interp.residual_terms.length > 0 && (
        <p
          data-testid="search-residual-terms"
          style={{ fontSize: 12, color: TOKEN.muted, margin: 0, width: "100%" }}
        >
          Not understood (never silently used): {interp.residual_terms.join(", ")}
        </p>
      )}
    </div>
  )
}

function SectionHeader({
  title,
  count,
  hint,
  testid,
}: {
  title: string
  count: number
  hint?: string
  testid: string
}) {
  return (
    <div data-testid={testid} style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 4 }}>
      <p style={{ fontSize: 13, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
        {title}{" "}
        <span style={{ color: TOKEN.muted, fontWeight: 600 }}>({count})</span>
      </p>
      {hint && (
        <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          {hint}
        </p>
      )}
    </div>
  )
}

/**
 * "Save search" — persist the executed query as a Saved Search that keeps
 * watching published evidence. The panel restates exactly what will be
 * tracked (the structured interpretation, residual-term honesty included);
 * a search with no hard requirements is savable but honestly untracked.
 * Keyed on the executed query by the caller, so a new search resets it.
 */
function SaveSearchSection({
  query,
  interp,
  evidence,
  availability,
}: {
  query: string
  interp: QueryInterpretation
  evidence: EvidenceFilter[]
  availability: AvailabilityFilter | ""
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<SavedSearchListItem | null>(null)
  const [error, setError] = useState<string | null>(null)

  const tracked = interp.required.length > 0 || interp.evidence.length > 0

  const defaultName = (() => {
    if (interp.role) return [interp.seniority, interp.role].filter(Boolean).join(" ")
    if (interp.required.length > 0) {
      return interp.required.map((chip) => chip.display).join(", ").slice(0, 120)
    }
    return query.length > 60 ? `${query.slice(0, 57)}…` : query
  })()

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const item = await createSavedSearch({
        q: query,
        name: name.trim() || null,
        filters: { evidence, availability: availability || null },
      })
      setSaved(item)
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save the search.")
    } finally {
      setSaving(false)
    }
  }

  if (saved) {
    return (
      <p
        data-testid="search-save-success"
        style={{ fontSize: 12.5, color: TOKEN.emerald, margin: 0, fontWeight: 600 }}
      >
        Saved “{saved.name}”.{" "}
        <Link
          href={`/recruiters/saved-searches/${encodeURIComponent(saved.id)}`}
          style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
        >
          View saved search →
        </Link>
      </p>
    )
  }

  if (!open) {
    return (
      <div>
        <button
          type="button"
          data-testid="search-save-search"
          onClick={() => {
            setName(defaultName)
            setOpen(true)
          }}
          style={{
            padding: "7px 14px",
            borderRadius: 8,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
            color: TOKEN.indigo,
            fontSize: 12.5,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Save search
        </button>
      </div>
    )
  }

  return (
    <Card style={{ padding: 16 }}>
      <div
        data-testid="search-save-panel"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        <h2 style={{ fontSize: 14.5, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
          Save this search
        </h2>
        <input
          data-testid="search-save-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={120}
          aria-label="Saved search name"
          placeholder="Name this saved search"
          style={{
            padding: "9px 12px",
            borderRadius: 8,
            border: `1px solid ${TOKEN.line}`,
            fontSize: 13,
            color: TOKEN.ink,
            background: "#fff",
          }}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
            This saved search will track:
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {interp.required.map((chip) => (
              <Badge key={`save-req-${chip.display}`} tone="indigo">
                {chip.display}
              </Badge>
            ))}
            {interp.evidence.map((chip) => (
              <Badge key={`save-ev-${chip.key}`} tone="emerald">
                {chip.display}
              </Badge>
            ))}
            {evidence.map((key) => (
              <Badge key={`save-filter-${key}`} tone="emerald">
                Filter: {key.replace(/_/g, " ")}
              </Badge>
            ))}
            {availability && <Badge tone="slate">{availability.replace(/_/g, " ")}</Badge>}
            {interp.preferred.map((chip) => (
              <Badge key={`save-pref-${chip.display}`} tone="slate">
                Preferred: {chip.display}
              </Badge>
            ))}
          </div>
          {interp.residual_terms.length > 0 && (
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              Not understood (never silently used): {interp.residual_terms.join(", ")}
            </p>
          )}
          {!tracked && (
            <p
              data-testid="search-save-untracked-note"
              style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
            >
              This search has no required skills or evidence, so it will not
              track new candidates.
            </p>
          )}
        </div>
        {error && (
          <p role="alert" style={{ fontSize: 12, color: TOKEN.rose, margin: 0 }}>
            {error}
          </p>
        )}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            data-testid="search-save-submit"
            onClick={() => void save()}
            disabled={saving}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: "none",
              background: TOKEN.indigo,
              color: "#fff",
              fontSize: 12.5,
              fontWeight: 600,
              cursor: saving ? "wait" : "pointer",
            }}
          >
            {saving ? "Saving…" : "Save search"}
          </button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              background: "#fff",
              color: TOKEN.muted,
              fontSize: 12.5,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    </Card>
  )
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg
      aria-hidden
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke={active ? "#fff" : TOKEN.muted}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
      <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
      <line x1="12" y1="18" x2="12" y2="22" />
    </svg>
  )
}

export function RecruiterSearchView() {
  const [input, setInput] = useState("")
  const [evidence, setEvidence] = useState<EvidenceFilter[]>([])
  const [availability, setAvailability] = useState<AvailabilityFilter | "">("")
  const [response, setResponse] = useState<RecruiterSearchResponse | null>(null)
  const [results, setResults] = useState<SearchResultCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedSlugs, setSavedSlugs] = useState<Set<string>>(new Set())
  // The query the CURRENT results correspond to (for save attribution and
  // the results headline) — distinct from the live input value.
  const [activeQuery, setActiveQuery] = useState("")
  const requestSeq = useRef(0)

  const runSearch = useCallback(
    async (
      params: {
        q: string
        evidence: EvidenceFilter[]
        availability: AvailabilityFilter | ""
        page: number
      },
      append: boolean,
    ) => {
      const seq = ++requestSeq.current
      if (append) setLoadingMore(true)
      else setLoading(true)
      setError(null)
      try {
        const body = await searchCandidates({
          q: params.q,
          evidence: params.evidence,
          availability: params.availability || null,
          page: params.page,
        })
        if (seq !== requestSeq.current) return
        setResponse(body)
        setResults((current) => (append ? [...current, ...body.results] : body.results))
        setActiveQuery(params.q)
      } catch (err) {
        if (seq !== requestSeq.current) return
        setError(err instanceof Error ? err.message : "Search failed.")
      } finally {
        if (seq === requestSeq.current) {
          setLoading(false)
          setLoadingMore(false)
        }
      }
    },
    [],
  )

  // Voice search: transcript mirrors live into the (editable) input; a
  // completed utterance searches exactly that visible transcript.
  const { status: speechStatus, supported: speechSupported, start: startListening, stop: stopListening } =
    useSpeechRecognition({
      onTranscript: (text) => setInput(text),
      onFinal: (text) => {
        setInput(text)
        void runSearch(
          { q: text, evidence, availability, page: 1 },
          false,
        )
      },
    })
  const listening = speechStatus === "listening"

  // Initial load: the honest discoverable population (no fake density).
  // runSearch sets the (already-true-on-mount) loading flag before its async
  // fetch; the kick-off on mount is intentional and single-shot.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void runSearch({ q: "", evidence: [], availability: "", page: 1 }, false)
    // Saved state for “Saved ✓” marks — one listing call, not per-result
    // probes; one retry rides out a transient page-load network race.
    listConnections()
      .catch(() => listConnections())
      .then((connections) => {
        setSavedSlugs(
          new Set(
            connections
              .map((c) => c.candidate.public_slug)
              .filter((slug): slug is string => Boolean(slug)),
          ),
        )
      })
      .catch(() => {
        // Saved-state marks are cosmetic; saves themselves stay idempotent.
      })
  }, [runSearch])

  const submit = (overrides?: {
    q?: string
    evidence?: EvidenceFilter[]
    availability?: AvailabilityFilter | ""
  }) => {
    void runSearch(
      {
        q: overrides?.q ?? input,
        evidence: overrides?.evidence ?? evidence,
        availability: overrides?.availability ?? availability,
        page: 1,
      },
      false,
    )
  }

  const toggleEvidence = (key: EvidenceFilter) => {
    const next = evidence.includes(key)
      ? evidence.filter((e) => e !== key)
      : [...evidence, key]
    setEvidence(next)
    submit({ evidence: next })
  }

  const changeAvailability = (value: AvailabilityFilter | "") => {
    setAvailability(value)
    submit({ availability: value })
  }

  const clearAll = () => {
    setInput("")
    setEvidence([])
    setAvailability("")
    void runSearch({ q: "", evidence: [], availability: "", page: 1 }, false)
  }

  const loadMore = () => {
    if (!response?.has_more || loadingMore) return
    void runSearch(
      {
        q: activeQuery,
        evidence,
        availability,
        page: response.page + 1,
      },
      true,
    )
  }

  const hasActiveRefinement =
    activeQuery.trim().length > 0 || evidence.length > 0 || availability !== ""

  const interpretation = response?.interpretation
  const structured = interpretation?.mode === "structured"
  const exactResults = results.filter((r) => (r.match_type ?? "match") !== "close")
  const closeResults = results.filter((r) => r.match_type === "close")
  const showSections = structured && closeResults.length > 0

  const renderCard = (candidate: SearchResultCandidate) => (
    <ResultCard
      key={candidate.public_slug}
      candidate={candidate}
      query={activeQuery}
      initiallySaved={savedSlugs.has(candidate.public_slug)}
    />
  )

  return (
    <div
      data-testid="recruiter-search"
      style={{
        maxWidth: 880,
        margin: "0 auto",
        padding: "40px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 18,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <p style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
          Recruiter Workspace
        </p>
        <h1 style={{ fontSize: 26, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px" }}>
          Discover candidates
        </h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "2px 0 0", lineHeight: 1.5 }}>
          Describe who you need in plain language. Every requirement is verified
          against published Work Passport evidence — matches are explained, never scored.
        </p>
      </div>

      <RecruiterNav active="search" testidPrefix="search" />

      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
        style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
      >
        <div style={{ position: "relative", flex: "1 1 260px", display: "flex" }}>
          <input
            data-testid="search-input"
            type="search"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={
              listening
                ? "Listening…"
                : "Describe the candidate you're looking for…"
            }
            maxLength={320}
            aria-label="Describe the candidate you're looking for"
            style={{
              flex: 1,
              padding: "11px 44px 11px 14px",
              borderRadius: 10,
              border: `1px solid ${listening ? TOKEN.indigo : TOKEN.line}`,
              fontSize: 13.5,
              color: TOKEN.ink,
              background: "#fff",
              outline: "none",
            }}
          />
          {speechSupported && (
            <button
              type="button"
              data-testid="search-mic"
              aria-label={listening ? "Stop listening" : "Search by voice"}
              aria-pressed={listening}
              onClick={() => (listening ? stopListening() : startListening())}
              style={{
                position: "absolute",
                right: 6,
                top: "50%",
                transform: "translateY(-50%)",
                width: 32,
                height: 32,
                borderRadius: 8,
                border: "none",
                background: listening ? TOKEN.rose : "transparent",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
              }}
            >
              <MicIcon active={listening} />
            </button>
          )}
        </div>
        <button
          type="submit"
          data-testid="search-submit"
          style={{
            padding: "11px 20px",
            borderRadius: 10,
            border: "none",
            background: TOKEN.indigo,
            color: "#fff",
            fontSize: 13.5,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Search
        </button>
        {hasActiveRefinement && (
          <button
            type="button"
            data-testid="search-clear"
            onClick={clearAll}
            style={{
              padding: "11px 16px",
              borderRadius: 10,
              border: `1px solid ${TOKEN.line}`,
              background: "#fff",
              color: TOKEN.muted,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Clear
          </button>
        )}
      </form>

      {listening && (
        <p
          data-testid="search-listening"
          role="status"
          style={{ fontSize: 12, color: TOKEN.indigo, margin: "-8px 0 0", fontWeight: 600 }}
        >
          <span
            aria-hidden
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: TOKEN.rose,
              marginRight: 6,
              animation: "pulse 1.2s ease-in-out infinite",
            }}
          />
          Listening — speak naturally, then pause. Your words appear above and
          stay editable.
          <style>{`@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.35 } }`}</style>
        </p>
      )}
      {speechStatus === "denied" && (
        <p role="alert" style={{ fontSize: 12, color: TOKEN.rose, margin: "-8px 0 0" }}>
          Microphone access was blocked. Allow it in your browser&apos;s site
          settings, or keep typing — search works the same either way.
        </p>
      )}
      {speechStatus === "error" && (
        <p role="alert" style={{ fontSize: 12, color: TOKEN.muted, margin: "-8px 0 0" }}>
          Voice input hit a snag — typed search still works normally.
        </p>
      )}

      {!hasActiveRefinement && !listening && (
        <div
          data-testid="search-examples"
          style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginTop: -8 }}
        >
          <span style={{ fontSize: 11.5, color: TOKEN.muted, fontWeight: 600 }}>Try:</span>
          {EXAMPLE_QUERIES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setInput(example)
                submit({ q: example })
              }}
              style={{
                padding: "5px 10px",
                borderRadius: 999,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.inkSoft,
                fontSize: 11.5,
                cursor: "pointer",
              }}
            >
              “{example}”
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        <span style={{ fontSize: 11.5, color: TOKEN.muted, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Verified evidence
        </span>
        {EVIDENCE_OPTIONS.map((option) => {
          const active = evidence.includes(option.key)
          return (
            <button
              key={option.key}
              type="button"
              data-testid={`search-filter-${option.key}`}
              aria-pressed={active}
              onClick={() => toggleEvidence(option.key)}
              style={{
                padding: "6px 12px",
                borderRadius: 999,
                border: `1px solid ${active ? TOKEN.indigo : TOKEN.line}`,
                background: active ? TOKEN.indigoSoft : "#fff",
                color: active ? TOKEN.indigo : TOKEN.muted,
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {option.label}
            </button>
          )
        })}
        <select
          data-testid="search-filter-availability"
          value={availability}
          onChange={(event) => changeAvailability(event.target.value as AvailabilityFilter | "")}
          aria-label="Availability"
          style={{
            marginLeft: "auto",
            padding: "7px 10px",
            borderRadius: 8,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
            color: availability ? TOKEN.ink : TOKEN.muted,
            fontSize: 12.5,
            fontWeight: 600,
          }}
        >
          <option value="">Any availability</option>
          {AVAILABILITY_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <LoadingState label="Searching candidates…" />
      ) : error ? (
        <ErrorState message={error} onRetry={() => submit()} />
      ) : response?.evidence ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {interpretation && <InterpretationPanel interp={interpretation} />}
          <EvidenceResultsSection
            evidence={response.evidence}
            query={activeQuery}
            savedSlugs={savedSlugs}
          />
        </div>
      ) : results.length === 0 ? (
        <div data-testid="search-empty">
          {structured && interpretation && (
            <div style={{ marginBottom: 12 }}>
              <InterpretationPanel interp={interpretation} />
            </div>
          )}
          {activeQuery.trim() && interpretation && (
            <div style={{ marginBottom: 12 }}>
              <SaveSearchSection
                key={activeQuery}
                query={activeQuery}
                interp={interpretation}
                evidence={evidence}
                availability={availability}
              />
            </div>
          )}
          <EmptyState
            icon="🔍"
            title={hasActiveRefinement ? "No candidates match this search" : "No discoverable candidates yet"}
            description={
              hasActiveRefinement
                ? "No published Work Passport satisfies these requirements yet. Try removing a requirement — close matches show exactly what's missing."
                : "Candidates appear here as soon as they publish a Verified Work Passport."
            }
          />
          {hasActiveRefinement && (
            <p style={{ textAlign: "center", marginTop: 8 }}>
              <button
                type="button"
                onClick={clearAll}
                style={{ background: "none", border: "none", color: TOKEN.indigo, fontWeight: 600, cursor: "pointer", fontSize: 12.5 }}
              >
                Clear search and filters
              </button>
            </p>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {structured && interpretation && <InterpretationPanel interp={interpretation} />}
          {activeQuery.trim() && interpretation && (
            <SaveSearchSection
              key={activeQuery}
              query={activeQuery}
              interp={interpretation}
              evidence={evidence}
              availability={availability}
            />
          )}
          <p data-testid="search-result-count" style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
            {structured && showSections ? (
              <>
                <strong style={{ color: TOKEN.ink }}>{response?.exact_total ?? exactResults.length}</strong>{" "}
                exact {(response?.exact_total ?? exactResults.length) === 1 ? "match" : "matches"} ·{" "}
                {response?.close_total ?? closeResults.length} close{" "}
                {(response?.close_total ?? closeResults.length) === 1 ? "match" : "matches"}
                {activeQuery && (
                  <>
                    {" "}for <strong style={{ color: TOKEN.ink }}>“{activeQuery}”</strong>
                  </>
                )}
              </>
            ) : (
              <>
                {response?.total ?? results.length}{" "}
                {(response?.total ?? results.length) === 1 ? "candidate" : "candidates"}
                {activeQuery ? (
                  <>
                    {" "}matching <strong style={{ color: TOKEN.ink }}>“{activeQuery}”</strong>
                  </>
                ) : (
                  " with a published Work Passport"
                )}
              </>
            )}
          </p>

          {showSections ? (
            <>
              {exactResults.length > 0 && (
                <>
                  <SectionHeader
                    testid="search-section-exact"
                    title="Exact matches"
                    count={response?.exact_total ?? exactResults.length}
                    hint="Every requirement is backed by published evidence."
                  />
                  {exactResults.map(renderCard)}
                </>
              )}
              {exactResults.length === 0 && (
                <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
                  No candidate satisfies every requirement yet — the closest
                  candidates and exactly what they&apos;re missing:
                </p>
              )}
              <SectionHeader
                testid="search-section-close"
                title="Close matches"
                count={response?.close_total ?? closeResults.length}
                hint="Missing at least one requirement — each card states exactly which."
              />
              {closeResults.map(renderCard)}
            </>
          ) : (
            results.map(renderCard)
          )}

          {response?.has_more && (
            <button
              type="button"
              data-testid="search-load-more"
              onClick={loadMore}
              disabled={loadingMore}
              style={{
                alignSelf: "center",
                padding: "10px 20px",
                borderRadius: 10,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.indigo,
                fontSize: 13,
                fontWeight: 600,
                cursor: loadingMore ? "wait" : "pointer",
              }}
            >
              {loadingMore ? "Loading…" : "Load more candidates"}
            </button>
          )}
        </div>
      )}

      <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
        Search covers only what candidates have chosen to publish on their public Work
        Passport. Voice input stays in your browser — audio is never uploaded or stored.
        Evidence is described qualitatively — VeriBridge never reduces a person to a
        number or ranking.
      </p>
    </div>
  )
}
