"use client"

/**
 * Talent Pool evidence comparison.
 *
 * This page answers "what have these people actually demonstrated?" — never
 * "who is best". It renders the shared deterministic matrix: closed cell
 * states, the candidate's own qualitative verification wording, transparent
 * counts, and a walkable trail from each proven cell to the project and the
 * underlying proof. There is no score, no ranking and no recommendation.
 *
 * A pool owns no requirement plan, so the axis comes from one of two honest
 * places, stated on the page:
 *   • a query — the recruiter's own words, parsed by the same engine that
 *     runs pool filtering and global search;
 *   • no query — the union of skills the SELECTED candidates have themselves
 *     published evidence for.
 *
 * Recruiter judgement (workflow status, private note, tags) appears in the
 * column header, visually and structurally apart from the evidence cells.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"

import {
  Badge,
  Card,
  ErrorState,
  LoadingState,
  TOKEN,
  type BadgeTone,
} from "../../../../../../components/passport/shared"
import { ComparisonMatrixView } from "../../../../../../components/recruiter/ComparisonMatrix"
import { RecruiterNav } from "../../../../../../components/recruiter/RecruiterNav"
import {
  comparePoolCandidates,
  POOL_CANDIDATE_STATUSES,
  POOL_STATUS_LABEL,
  updatePoolCandidate,
  type PoolCandidateStatus,
  type PoolComparisonResult,
} from "@/lib/recruiter-pools-api"

const STATUS_TONE: Record<PoolCandidateStatus, BadgeTone> = {
  review: "slate",
  shortlisted: "indigo",
  interview: "purple",
  hold: "amber",
  pass: "slate",
}

export function PoolComparisonView({ poolId }: { poolId: string }) {
  const router = useRouter()
  const params = useSearchParams()
  const ids = useMemo(
    () => (params.get("ids") ?? "").split(",").filter(Boolean),
    [params],
  )
  const query = params.get("q") ?? ""

  const [result, setResult] = useState<PoolComparisonResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [queryDraft, setQueryDraft] = useState(query)
  // Re-sync the draft when the URL changes underneath us (back/forward,
  // a cleared filter). Adjusted during render rather than in an effect so
  // there is no extra commit — the React-recommended shape for this.
  const [lastUrlQuery, setLastUrlQuery] = useState(query)
  if (query !== lastUrlQuery) {
    setLastUrlQuery(query)
    setQueryDraft(query)
  }
  const [savingFor, setSavingFor] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (ids.length < 2) {
      setLoading(false)
      setError(null)
      setResult(null)
      return
    }
    setLoading(true)
    setError(null)
    comparePoolCandidates(poolId, { student_user_ids: ids, q: query || null })
      .then(setResult)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to build the comparison."),
      )
      .finally(() => setLoading(false))
  }, [poolId, ids, query])

  useEffect(() => {
    load()
  }, [load])


  const applyQuery = (next: string) => {
    const search = new URLSearchParams({ ids: ids.join(",") })
    if (next.trim()) search.set("q", next.trim())
    router.push(
      `/recruiters/pools/${encodeURIComponent(poolId)}/compare?${search.toString()}`,
    )
  }

  const backHref = `/recruiters/pools/${encodeURIComponent(poolId)}${
    ids.length ? `?selected=${encodeURIComponent(ids.join(","))}${query ? `&q=${encodeURIComponent(query)}` : ""}` : ""
  }`

  const setStatus = async (studentUserId: string, status: PoolCandidateStatus) => {
    setSavingFor(studentUserId)
    setSaveError(null)
    try {
      await updatePoolCandidate(poolId, studentUserId, { status })
      setResult((current) =>
        current
          ? {
              ...current,
              matrix: {
                ...current.matrix,
                columns: current.matrix.columns.map((column) =>
                  column.user_id === studentUserId
                    ? { ...column, pool_status: status }
                    : column,
                ),
              },
            }
          : current,
      )
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to update the status.")
    } finally {
      setSavingFor(null)
    }
  }

  return (
    <div
      data-testid="recruiter-pool-comparison"
      style={{ maxWidth: 1280, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <p style={{ fontSize: 12.5, margin: 0 }}>
        <Link data-testid="comparison-back" href={backHref} style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}>
          ← Back to the Talent Pool
        </Link>
      </p>

      <RecruiterNav active="pools" testidPrefix="poolcompare" />

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 data-testid="comparison-title" style={{ fontSize: 24, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px" }}>
          Compare evidence
        </h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.55, maxWidth: 720 }}>
          {result?.pool.name ? `${result.pool.name} — ` : ""}
          this compares what each candidate has published evidence for. It is not a
          ranking and produces no score; every cell links back to the proof behind it.
        </p>
      </div>

      {ids.length < 2 ? (
        <Card style={{ padding: 20 }}>
          <p data-testid="comparison-too-few" style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}>
            Select between 2 and 5 candidates in the Talent Pool to compare their
            evidence.{" "}
            <Link href={backHref} style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}>
              Back to the pool →
            </Link>
          </p>
        </Card>
      ) : (
        <>
          <Card style={{ padding: 14 }}>
            <form
              onSubmit={(event) => {
                event.preventDefault()
                applyQuery(queryDraft)
              }}
              style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}
            >
              <input
                data-testid="comparison-query-input"
                type="search"
                value={queryDraft}
                maxLength={320}
                onChange={(event) => setQueryDraft(event.target.value)}
                aria-label="Compare against specific requirements"
                placeholder="Compare against requirements — “FastAPI and deployed website evidence”"
                style={{ flex: "1 1 320px", minWidth: 0, padding: "9px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 13, color: TOKEN.ink }}
              />
              <button type="submit" data-testid="comparison-query-submit" style={{ padding: "9px 16px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, border: "none", cursor: "pointer" }}>
                Apply
              </button>
              {query && (
                <button type="button" data-testid="comparison-query-clear" onClick={() => { setQueryDraft(""); applyQuery("") }} style={{ padding: "9px 14px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
                  Clear
                </button>
              )}
              <span style={{ fontSize: 11.5, color: TOKEN.muted, flexBasis: "100%", lineHeight: 1.5 }}>
                Leave this empty to compare the skills these candidates have
                themselves published evidence for.
              </span>
            </form>
          </Card>

          {loading ? (
            <LoadingState label="Building the evidence matrix…" />
          ) : error ? (
            <div data-testid="comparison-error">
              <ErrorState message={error} onRetry={load} />
            </div>
          ) : result ? (
            <>
              {saveError && (
                <p role="alert" style={{ fontSize: 12.5, color: "#b91c1c", margin: 0 }}>
                  {saveError}
                </p>
              )}
              <ComparisonMatrixView
                matrix={result.matrix}
                columnAccessory={(column) => (
                  <span style={{ display: "inline-flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
                    {/* RECRUITER judgement — deliberately outside the evidence
                        cells, so a workflow stage can never read as a finding. */}
                    {column.pool_status && (
                      <span data-testid="comparison-column-status">
                        <Badge tone={STATUS_TONE[column.pool_status as PoolCandidateStatus] ?? "slate"}>
                          {POOL_STATUS_LABEL[column.pool_status as PoolCandidateStatus] ?? column.pool_status}
                        </Badge>
                      </span>
                    )}
                    {column.tags.map((tag) => (
                      <Badge key={tag} tone="purple">
                        {tag}
                      </Badge>
                    ))}
                  </span>
                )}
              />

              {/* Act without leaving the comparison. */}
              <Card style={{ padding: 14 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <span style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 700, letterSpacing: "0.3px", textTransform: "uppercase" }}>
                    Your workflow — private to you
                  </span>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
                    {result.matrix.columns.map((column) => (
                      <div key={column.user_id} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12.5, color: TOKEN.ink, fontWeight: 600 }}>
                          {column.display_name ?? "Verified candidate"}
                        </span>
                        <select
                          data-testid="comparison-status-select"
                          value={(column.pool_status as PoolCandidateStatus) ?? "review"}
                          disabled={savingFor === column.user_id}
                          aria-label={`Workflow status for ${column.display_name ?? "this candidate"}`}
                          onChange={(event) =>
                            void setStatus(column.user_id, event.target.value as PoolCandidateStatus)
                          }
                          style={{ padding: "4px 8px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 12, color: TOKEN.inkSoft, background: "#fff", cursor: "pointer" }}
                        >
                          {POOL_CANDIDATE_STATUSES.map((status) => (
                            <option key={status} value={status}>
                              {POOL_STATUS_LABEL[status]}
                            </option>
                          ))}
                        </select>
                        {column.pool_note && (
                          <span data-testid="comparison-column-note" style={{ fontSize: 12, color: TOKEN.muted, maxWidth: 260, overflowWrap: "anywhere" }}>
                            “{column.pool_note}”
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            </>
          ) : null}
        </>
      )}
    </div>
  )
}
