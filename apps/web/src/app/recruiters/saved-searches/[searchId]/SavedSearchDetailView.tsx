"use client"

/**
 * One Saved Search — live results with honest discovery annotations.
 *
 * Results are recomputed by the real search engine on every open (fail-
 * closed, published evidence only). The ONLY persisted state is which
 * candidates already satisfied the search at the last review: candidates
 * whose published evidence newly satisfies every requirement get a "New"
 * badge; candidates whose satisfying evidence changed get "Updated
 * evidence: …" naming the exact requirements. Never a score.
 */

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../../components/passport/shared"
import {
  AddToBriefButton,
  AddToPoolButton,
} from "../../../../../components/recruiter/AddToListButtons"
import { RequirementRow } from "../../../../../components/recruiter/EvidenceProofDrawer"
import { RecruiterNav } from "../../../../../components/recruiter/RecruiterNav"
import { saveCandidate } from "@/lib/recruiter-connections-api"
import {
  getSavedSearchResults,
  markSavedSearchReviewed,
  updateSavedSearch,
  type SavedSearchAnnotation,
  type SavedSearchResults,
} from "@/lib/recruiter-saved-searches-api"
import type { SearchResultCandidate } from "@/lib/recruiter-search-api"
import { checkedAgoLabel, RequirementChips } from "../SavedSearchesListView"

function SaveCandidateAction({ slug, query }: { slug: string; query: string }) {
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle")
  const [message, setMessage] = useState<string | null>(null)

  const save = async () => {
    setState("saving")
    setMessage(null)
    try {
      // Same idempotent connection model as the search page.
      await saveCandidate(slug, "search", { passport_slug: slug, ...(query ? { query } : {}) })
      setState("saved")
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to save candidate.")
      setState("error")
    }
  }

  if (state === "saved") {
    return (
      <span
        data-testid="savedsearch-result-saved"
        style={{ padding: "7px 12px", borderRadius: 8, background: TOKEN.emeraldSoft, color: TOKEN.emerald, fontSize: 12, fontWeight: 600 }}
      >
        Saved ✓
      </span>
    )
  }
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 4 }}>
      <button
        type="button"
        data-testid="savedsearch-result-save"
        onClick={() => void save()}
        disabled={state === "saving"}
        style={{
          padding: "7px 12px",
          borderRadius: 8,
          border: "none",
          background: state === "saving" ? TOKEN.indigoSoft : TOKEN.indigo,
          color: state === "saving" ? TOKEN.indigo : "#fff",
          fontSize: 12,
          fontWeight: 600,
          cursor: state === "saving" ? "wait" : "pointer",
        }}
      >
        {state === "saving" ? "Saving…" : "Save candidate"}
      </button>
      {state === "error" && (
        <span role="alert" style={{ fontSize: 11.5, color: TOKEN.rose }}>
          {message ?? "Failed to save."}
        </span>
      )}
    </span>
  )
}

function ResultCard({
  candidate,
  annotation,
  query,
  close,
}: {
  candidate: SearchResultCandidate
  annotation: SavedSearchAnnotation | null
  query: string
  close: boolean
}) {
  const name = candidate.display_name ?? "Verified candidate"
  const requirements = candidate.requirements ?? []
  const satisfiedRequired = requirements.filter((r) => r.required && r.satisfied).length
  const requiredTotal = requirements.filter((r) => r.required).length

  return (
    <Card style={{ padding: 18, ...(close ? { opacity: 0.96 } : {}) }}>
      <div
        data-testid="savedsearch-result-card"
        data-match-type={candidate.match_type}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0, flex: "1 1 200px" }}>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              <h3 style={{ fontSize: 16, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}>
                {name}
              </h3>
              {!close && annotation?.is_new && (
                <span data-testid="savedsearch-badge-new">
                  <Badge tone="emerald">New</Badge>
                </span>
              )}
              {!close && annotation?.evidence_updated && (
                <span data-testid="savedsearch-badge-updated">
                  <Badge
                    tone="indigo"
                    style={{ whiteSpace: "normal", overflowWrap: "anywhere", textAlign: "left" }}
                  >
                    Updated evidence
                    {annotation.changed_requirements.length > 0
                      ? `: ${annotation.changed_requirements.join(", ")}`
                      : ""}
                  </Badge>
                </span>
              )}
            </div>
            {candidate.headline && (
              <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5, overflowWrap: "anywhere" }}>
                {candidate.headline}
              </p>
            )}
            {!close && requiredTotal > 0 && (
              <p data-testid="savedsearch-result-counts" style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>
                Satisfies all {requiredTotal} required{" "}
                {requiredTotal === 1 ? "requirement" : "requirements"}
              </p>
            )}
            {close && candidate.missing_requirements.length > 0 && (
              <p data-testid="savedsearch-result-missing" style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0", overflowWrap: "anywhere" }}>
                Missing: {candidate.missing_requirements.join(", ")}
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexWrap: "wrap" }}>
            <a
              data-testid="savedsearch-result-open"
              href={`/p/${encodeURIComponent(candidate.public_slug)}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: "7px 12px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.ink,
                fontSize: 12,
                fontWeight: 600,
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              Open Passport →
            </a>
            <SaveCandidateAction slug={candidate.public_slug} query={query} />
            <AddToPoolButton candidateSlug={candidate.public_slug} source="saved_search" />
            <AddToBriefButton candidateSlug={candidate.public_slug} />
          </div>
        </div>

        {requirements.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {requirements.map((req, index) => (
              <RequirementRow
                key={`${req.kind}-${req.requirement}-${index}`}
                req={req}
                candidateSlug={candidate.public_slug}
              />
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

export function SavedSearchDetailView({ searchId }: { searchId: string }) {
  const [data, setData] = useState<SavedSearchResults | null>(null)
  const [results, setResults] = useState<SearchResultCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [renameOpen, setRenameOpen] = useState(false)
  const [nameDraft, setNameDraft] = useState("")

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getSavedSearchResults(searchId)
      .then((body) => {
        setData(body)
        setResults(body.results)
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load the saved search."),
      )
      .finally(() => setLoading(false))
  }, [searchId])

  useEffect(() => {
    load()
  }, [load])

  const loadMore = async () => {
    if (!data?.has_more || loadingMore) return
    setLoadingMore(true)
    try {
      const body = await getSavedSearchResults(searchId, { page: data.page + 1 })
      setData(body)
      setResults((current) => [...current, ...body.results])
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to load more results.")
    } finally {
      setLoadingMore(false)
    }
  }

  const markReviewed = async () => {
    setBusy(true)
    setActionError(null)
    try {
      const updated = await markSavedSearchReviewed(searchId)
      setData((current) =>
        current
          ? { ...current, saved_search: updated, annotations: {} }
          : current,
      )
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to mark reviewed.")
    } finally {
      setBusy(false)
    }
  }

  const rename = async () => {
    if (!nameDraft.trim()) {
      setActionError("Give the saved search a name.")
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      const updated = await updateSavedSearch(searchId, { name: nameDraft.trim() })
      setData((current) => (current ? { ...current, saved_search: updated } : current))
      setRenameOpen(false)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to rename the saved search.")
    } finally {
      setBusy(false)
    }
  }

  const item = data?.saved_search ?? null
  const paused = item?.status === "paused"
  const query = item?.query_text ?? ""
  const annotations = data?.annotations ?? {}
  const exactResults = results.filter((r) => r.match_type === "exact")
  const otherResults = results.filter((r) => r.match_type !== "exact")
  const interpretation = data?.interpretation ?? null
  const hasNew = Object.values(annotations).some((a) => a.is_new || a.evidence_updated)

  return (
    <div
      data-testid="recruiter-saved-search-detail"
      style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <p style={{ fontSize: 12.5, margin: 0 }}>
        <Link
          data-testid="savedsearch-back"
          href="/recruiters/saved-searches"
          style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
        >
          ← Saved Searches
        </Link>
      </p>

      <RecruiterNav active="savedsearches" testidPrefix="savedsearchdetail" />

      {loading ? (
        <LoadingState label="Checking published evidence…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !item ? null : (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
            {renameOpen ? (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  data-testid="savedsearch-rename-input"
                  type="text"
                  value={nameDraft}
                  onChange={(event) => setNameDraft(event.target.value)}
                  maxLength={120}
                  aria-label="Saved search name"
                  style={{
                    flex: "1 1 240px",
                    minWidth: 0,
                    padding: "9px 12px",
                    borderRadius: 8,
                    border: `1px solid ${TOKEN.line}`,
                    fontSize: 15,
                    fontWeight: 700,
                    color: TOKEN.ink,
                  }}
                />
                <button
                  type="button"
                  data-testid="savedsearch-rename-save"
                  onClick={() => void rename()}
                  disabled={busy}
                  style={{ padding: "8px 14px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, border: "none", cursor: "pointer" }}
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => setRenameOpen(false)}
                  style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <h1 data-testid="savedsearch-title" style={{ fontSize: 24, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px", overflowWrap: "anywhere" }}>
                  {item.name}
                </h1>
                {paused && <Badge tone="amber">Paused</Badge>}
                <button
                  type="button"
                  data-testid="savedsearch-rename"
                  onClick={() => {
                    setNameDraft(item.name)
                    setRenameOpen(true)
                  }}
                  style={{ padding: "5px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                >
                  Rename
                </button>
              </div>
            )}

            {item.query_text && (
              <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.5, overflowWrap: "anywhere" }}>
                “{item.query_text}”
              </p>
            )}

            <RequirementChips view={item.requirements} />
            {interpretation && interpretation.residual_terms.length > 0 && (
              <p data-testid="savedsearch-residual-terms" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                Not understood (never silently used): {interpretation.residual_terms.join(", ")}
              </p>
            )}
            {!item.tracking && (
              <p data-testid="savedsearch-untracked" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                Add a required skill or evidence type to track new candidates.
              </p>
            )}
            {data?.truncated && (
              <p role="alert" style={{ fontSize: 12, color: TOKEN.amber, margin: 0 }}>
                This search matches more candidates than tracking covers —
                narrow the requirements for complete change tracking.
              </p>
            )}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ fontSize: 11.5, color: TOKEN.muted }}>
                {paused ? "Paused" : checkedAgoLabel(item.last_evaluated_at)}
              </span>
              {!paused && hasNew && (
                <button
                  type="button"
                  data-testid="savedsearch-mark-reviewed"
                  onClick={() => void markReviewed()}
                  disabled={busy}
                  style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.indigo, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                >
                  Mark reviewed
                </button>
              )}
            </div>

            {paused && (
              <p
                data-testid="savedsearch-paused-banner"
                style={{
                  fontSize: 12.5,
                  color: TOKEN.amber,
                  margin: 0,
                  lineHeight: 1.5,
                  padding: "10px 12px",
                  borderRadius: 10,
                  background: TOKEN.amberSoft,
                }}
              >
                Paused — not tracking new candidates. Live results below still
                reflect currently published evidence.
              </p>
            )}
            {actionError && (
              <p role="alert" style={{ fontSize: 12.5, color: "#b91c1c", margin: 0 }}>
                {actionError}
              </p>
            )}
          </div>

          {results.length === 0 ? (
            <div data-testid="savedsearch-results-empty">
              <EmptyState
                icon="🔔"
                title="No matches yet"
                description="No published evidence-backed candidates satisfy this search yet."
              />
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div data-testid="savedsearch-section-exact" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <p style={{ fontSize: 13, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                  Exact matches{" "}
                  <span style={{ color: TOKEN.muted, fontWeight: 600 }}>
                    ({data?.exact_total ?? exactResults.length})
                  </span>
                </p>
                <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
                  Every requirement is backed by published evidence.
                </p>
              </div>
              {exactResults.length === 0 && (
                <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
                  No published evidence-backed candidates satisfy this search yet.
                </p>
              )}
              {exactResults.map((candidate) => (
                <ResultCard
                  key={candidate.public_slug}
                  candidate={candidate}
                  annotation={annotations[candidate.public_slug] ?? null}
                  query={query}
                  close={false}
                />
              ))}

              {otherResults.length > 0 && (
                <>
                  <div data-testid="savedsearch-section-close" style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 4 }}>
                    <p style={{ fontSize: 13, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                      Close matches — missing requirements shown{" "}
                      <span style={{ color: TOKEN.muted, fontWeight: 600 }}>
                        ({data?.close_total ?? otherResults.length})
                      </span>
                    </p>
                  </div>
                  {otherResults.map((candidate) => (
                    <ResultCard
                      key={candidate.public_slug}
                      candidate={candidate}
                      annotation={null}
                      query={query}
                      close
                    />
                  ))}
                </>
              )}

              {data?.has_more && (
                <button
                  type="button"
                  data-testid="savedsearch-load-more"
                  onClick={() => void loadMore()}
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
            Results are recomputed from currently published Work Passports on
            every open. “New” and “Updated evidence” reflect changes since your
            last review — VeriBridge never reduces a person to a number or
            ranking.
          </p>
        </>
      )}
    </div>
  )
}
