"use client"

/**
 * Add-to-list actions — explicit recruiter actions that place a candidate
 * into a Talent Pool or a Hiring Brief from wherever their card appears
 * (global search results, saved-search results, pool detail).
 *
 * Both pickers lazy-load their list only when opened. Adds are idempotent
 * server-side; a repeat add simply reports "Added ✓". Nothing here is ever
 * automatic — a candidate joins a pool or brief only on a click.
 */

import { useState } from "react"

import {
  addBriefCandidates,
  listBriefs,
  type HiringBriefListItem,
} from "@/lib/recruiter-briefs-api"
import {
  addPoolCandidates,
  createPool,
  listPools,
  type PoolCandidateSource,
  type TalentPool,
} from "@/lib/recruiter-pools-api"
import { TOKEN } from "../passport/shared"

const triggerStyle: React.CSSProperties = {
  padding: "6px 10px",
  borderRadius: 8,
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.muted,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
}

const optionStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  textAlign: "left",
  padding: "7px 10px",
  borderRadius: 8,
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.ink,
  fontSize: 12.5,
  fontWeight: 600,
  cursor: "pointer",
  overflowWrap: "anywhere",
}

const panelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "10px 12px",
  borderRadius: 10,
  border: `1px solid ${TOKEN.line}`,
  background: TOKEN.bg,
  width: "100%",
}

function AddedMark() {
  return (
    <span style={{ marginLeft: "auto", color: TOKEN.emerald, fontSize: 12, fontWeight: 700, whiteSpace: "nowrap" }}>
      Added ✓
    </span>
  )
}

export function AddToPoolButton({
  candidateSlug,
  source = "search",
}: {
  candidateSlug: string
  source?: PoolCandidateSource
}) {
  const [open, setOpen] = useState(false)
  const [pools, setPools] = useState<TalentPool[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [addedPoolIds, setAddedPoolIds] = useState<Set<string>>(new Set())
  const [busyPoolId, setBusyPoolId] = useState<string | null>(null)
  const [newName, setNewName] = useState("")
  const [creating, setCreating] = useState(false)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (next && pools === null && !loading) {
      setLoading(true)
      setError(null)
      try {
        setPools(await listPools())
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load Talent Pools.")
      } finally {
        setLoading(false)
      }
    }
  }

  const addTo = async (poolId: string) => {
    setBusyPoolId(poolId)
    setError(null)
    try {
      // Idempotent server-side: success and already_in_pool both mean the
      // candidate is in the pool now.
      await addPoolCandidates(poolId, { candidate_slugs: [candidateSlug], source })
      setAddedPoolIds((current) => new Set(current).add(poolId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add to the Talent Pool.")
    } finally {
      setBusyPoolId(null)
    }
  }

  const createAndAdd = async () => {
    const name = newName.trim()
    if (!name) {
      setError("Give the new Talent Pool a name first.")
      return
    }
    setCreating(true)
    setError(null)
    try {
      const pool = await createPool({ name })
      setPools((current) => [pool, ...(current ?? [])])
      await addPoolCandidates(pool.id, { candidate_slugs: [candidateSlug], source })
      setAddedPoolIds((current) => new Set(current).add(pool.id))
      setNewName("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create the Talent Pool.")
    } finally {
      setCreating(false)
    }
  }

  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      <button
        type="button"
        data-testid="add-to-pool"
        aria-expanded={open}
        onClick={() => void toggle()}
        style={triggerStyle}
      >
        Add to pool
      </button>
      {open && (
        <div style={panelStyle}>
          {loading && (
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>Loading Talent Pools…</p>
          )}
          {pools !== null && pools.length === 0 && (
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No Talent Pools yet — create one below.
            </p>
          )}
          {(pools ?? []).map((pool) => {
            const added = addedPoolIds.has(pool.id)
            return (
              <button
                key={pool.id}
                type="button"
                data-testid="add-to-pool-option"
                onClick={() => void addTo(pool.id)}
                disabled={added || busyPoolId === pool.id}
                style={{ ...optionStyle, cursor: added ? "default" : "pointer" }}
              >
                <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>{pool.name}</span>
                {added ? (
                  <AddedMark />
                ) : busyPoolId === pool.id ? (
                  <span style={{ marginLeft: "auto", color: TOKEN.muted, fontSize: 12 }}>Adding…</span>
                ) : null}
              </button>
            )
          })}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <input
              type="text"
              data-testid="add-to-pool-new-name"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="New pool…"
              maxLength={120}
              aria-label="New Talent Pool name"
              style={{
                flex: "1 1 140px",
                minWidth: 0,
                padding: "7px 10px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                fontSize: 12.5,
                color: TOKEN.ink,
                background: "#fff",
              }}
            />
            <button
              type="button"
              data-testid="add-to-pool-create"
              onClick={() => void createAndAdd()}
              disabled={creating}
              style={{
                padding: "7px 12px",
                borderRadius: 8,
                border: "none",
                background: TOKEN.indigo,
                color: "#fff",
                fontSize: 12,
                fontWeight: 600,
                cursor: creating ? "wait" : "pointer",
              }}
            >
              {creating ? "Creating…" : "Create + add"}
            </button>
          </div>
          {error && (
            <p role="alert" style={{ fontSize: 11.5, color: TOKEN.rose, margin: 0 }}>
              {error}
            </p>
          )}
        </div>
      )}
    </span>
  )
}

export function AddToBriefButton({ candidateSlug }: { candidateSlug: string }) {
  const [open, setOpen] = useState(false)
  const [briefs, setBriefs] = useState<HiringBriefListItem[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [addedBriefIds, setAddedBriefIds] = useState<Set<string>>(new Set())
  const [busyBriefId, setBusyBriefId] = useState<string | null>(null)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (next && briefs === null && !loading) {
      setLoading(true)
      setError(null)
      try {
        setBriefs(await listBriefs())
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load Hiring Briefs.")
      } finally {
        setLoading(false)
      }
    }
  }

  const addTo = async (briefId: string) => {
    setBusyBriefId(briefId)
    setError(null)
    try {
      await addBriefCandidates(briefId, { candidate_slugs: [candidateSlug] })
      setAddedBriefIds((current) => new Set(current).add(briefId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add to the Hiring Brief.")
    } finally {
      setBusyBriefId(null)
    }
  }

  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      <button
        type="button"
        data-testid="add-to-brief"
        aria-expanded={open}
        onClick={() => void toggle()}
        style={triggerStyle}
      >
        Add to brief
      </button>
      {open && (
        <div style={panelStyle}>
          {loading && (
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>Loading Hiring Briefs…</p>
          )}
          {briefs !== null && briefs.length === 0 && (
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No Hiring Briefs yet — create one on the Hiring Briefs page.
            </p>
          )}
          {(briefs ?? []).map((brief) => {
            const added = addedBriefIds.has(brief.id)
            return (
              <button
                key={brief.id}
                type="button"
                data-testid="add-to-brief-option"
                onClick={() => void addTo(brief.id)}
                disabled={added || busyBriefId === brief.id}
                style={{ ...optionStyle, cursor: added ? "default" : "pointer" }}
              >
                <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>{brief.title}</span>
                {added ? (
                  <AddedMark />
                ) : busyBriefId === brief.id ? (
                  <span style={{ marginLeft: "auto", color: TOKEN.muted, fontSize: 12 }}>Adding…</span>
                ) : null}
              </button>
            )
          })}
          {error && (
            <p role="alert" style={{ fontSize: 11.5, color: TOKEN.rose, margin: 0 }}>
              {error}
            </p>
          )}
        </div>
      )}
    </span>
  )
}
