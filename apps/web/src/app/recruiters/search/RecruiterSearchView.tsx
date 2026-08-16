"use client"

/**
 * Recruiter Search & Discovery — the second candidate-acquisition path.
 *
 * Every result comes from the candidate's PUBLIC Work Passport projection
 * (the same data as `/p/{slug}`), matched deterministically and explained
 * with real evidence — never scores, never fabricated candidates. Saving a
 * result reuses the EXISTING idempotent connection system with
 * `source: "search"`, so search converges into the same workspace as QR
 * scans and shared links.
 */

import { useCallback, useEffect, useRef, useState } from "react"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../components/passport/shared"
import {
  listConnections,
  saveCandidate,
} from "@/lib/recruiter-connections-api"
import {
  searchCandidates,
  type AvailabilityFilter,
  type EvidenceFilter,
  type MatchedReason,
  type RecruiterSearchResponse,
  type SearchResultCandidate,
} from "@/lib/recruiter-search-api"

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

/** Human sentence for one structured match reason. */
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
  const hasReasons = candidate.matched_reasons.length > 0
  const skillsToShow = candidate.skills.slice(0, 6)

  return (
    <Card style={{ padding: 18 }}>
      <div
        data-testid="search-result-card"
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

        {hasReasons ? (
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
              {candidate.matched_reasons.map((reason, index) => (
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

  // Initial load: the honest discoverable population (no fake density).
  useEffect(() => {
    void runSearch({ q: "", evidence: [], availability: "", page: 1 }, false)
    // Saved state for “Saved ✓” marks — one listing call, not per-result probes.
    listConnections()
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
    evidence?: EvidenceFilter[]
    availability?: AvailabilityFilter | ""
  }) => {
    void runSearch(
      {
        q: input,
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
          Search every candidate with a published Verified Work Passport. Matches are
          explained with real evidence — never scores.
        </p>
      </div>

      <nav style={{ display: "flex", gap: 8 }} aria-label="Recruiter sections">
        <a
          data-testid="search-nav-workspace"
          href="/recruiters/workspace"
          style={{
            padding: "7px 14px",
            borderRadius: 999,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
            color: TOKEN.muted,
            fontSize: 12.5,
            fontWeight: 600,
            textDecoration: "none",
          }}
        >
          Saved candidates
        </a>
        <span
          aria-current="page"
          style={{
            padding: "7px 14px",
            borderRadius: 999,
            background: TOKEN.indigo,
            color: "#fff",
            fontSize: 12.5,
            fontWeight: 700,
          }}
        >
          Search
        </span>
      </nav>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
        style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
      >
        <input
          data-testid="search-input"
          type="search"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Search by skill, technology, project, name…"
          maxLength={200}
          style={{
            flex: "1 1 260px",
            padding: "11px 14px",
            borderRadius: 10,
            border: `1px solid ${TOKEN.line}`,
            fontSize: 13.5,
            color: TOKEN.ink,
            background: "#fff",
            outline: "none",
          }}
        />
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
      ) : results.length === 0 ? (
        <div data-testid="search-empty">
          <EmptyState
            icon="🔍"
            title={hasActiveRefinement ? "No candidates match this search" : "No discoverable candidates yet"}
            description={
              hasActiveRefinement
                ? "Try fewer terms or clear the filters — search only covers candidates who have published a public Work Passport."
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
          <p data-testid="search-result-count" style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
            {response?.total ?? results.length}{" "}
            {(response?.total ?? results.length) === 1 ? "candidate" : "candidates"}
            {activeQuery ? (
              <>
                {" "}matching <strong style={{ color: TOKEN.ink }}>“{activeQuery}”</strong>
              </>
            ) : (
              " with a published Work Passport"
            )}
          </p>
          {results.map((candidate) => (
            <ResultCard
              key={candidate.public_slug}
              candidate={candidate}
              query={activeQuery}
              initiallySaved={savedSlugs.has(candidate.public_slug)}
            />
          ))}
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
        Passport. Evidence is described qualitatively — VeriBridge never reduces a person
        to a number or ranking.
      </p>
    </div>
  )
}
