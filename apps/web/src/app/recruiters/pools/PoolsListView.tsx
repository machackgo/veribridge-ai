"use client"

/**
 * Talent Pools list — recruiter-owned, role-independent candidate
 * collections ("AI / ML Early Talent"). A pool is an organizing label:
 * membership is a reference to the candidate's stable identity, never a
 * copy of their data. Archived pools stay listed in their own group and
 * are restorable.
 */

import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../components/passport/shared"
import { RecruiterNav } from "../../../../components/recruiter/RecruiterNav"
import {
  createPool,
  deletePool,
  listPools,
  type TalentPool,
} from "@/lib/recruiter-pools-api"

function updatedLabel(iso: string | null): string {
  if (!iso) return ""
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ""
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

function PoolCard({
  pool,
  onDelete,
  deleting,
}: {
  pool: TalentPool
  onDelete: (id: string) => void
  deleting: boolean
}) {
  return (
    <Card style={{ padding: 18, height: "100%", display: "flex", flexDirection: "column" }}>
      <div
        data-testid="pool-card"
        style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1 }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h3
              data-testid="pool-card-name"
              style={{ fontSize: 15.5, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}
            >
              {pool.name}
            </h3>
            {pool.description && (
              <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5, overflowWrap: "anywhere" }}>
                {pool.description}
              </p>
            )}
          </div>
          {pool.status === "archived" && (
            <span data-testid="pool-card-archived">
              <Badge tone="amber">Archived</Badge>
            </span>
          )}
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <Badge tone="indigo">
            {pool.candidate_count} {pool.candidate_count === 1 ? "candidate" : "candidates"}
          </Badge>
        </div>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 10,
            borderTop: `1px solid ${TOKEN.line}`,
            paddingTop: 10,
            marginTop: "auto",
          }}
        >
          <span style={{ fontSize: 11.5, color: TOKEN.muted }}>
            {updatedLabel(pool.updated_at) ? `Updated ${updatedLabel(pool.updated_at)}` : ""}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              data-testid="pool-card-delete"
              onClick={() => onDelete(pool.id)}
              disabled={deleting}
              style={{
                padding: "7px 12px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.muted,
                fontSize: 12.5,
                fontWeight: 600,
                cursor: deleting ? "wait" : "pointer",
              }}
            >
              {deleting ? "Deleting…" : "Delete"}
            </button>
            <a
              data-testid="pool-card-open"
              href={`/recruiters/pools/${encodeURIComponent(pool.id)}`}
              style={{
                padding: "7px 14px",
                borderRadius: 8,
                background: TOKEN.indigo,
                color: "#fff",
                fontSize: 12.5,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              Open pool →
            </a>
          </div>
        </div>
      </div>
    </Card>
  )
}

export function PoolsListView() {
  const router = useRouter()
  const [pools, setPools] = useState<TalentPool[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    listPools()
      .then(setPools)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load Talent Pools."),
      )
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const create = async () => {
    if (!name.trim()) {
      setCreateError("Give the Talent Pool a name first.")
      return
    }
    setCreating(true)
    setCreateError(null)
    try {
      const pool = await createPool({
        name: name.trim(),
        description: description.trim() || null,
      })
      router.push(`/recruiters/pools/${encodeURIComponent(pool.id)}`)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create the Talent Pool.")
      setCreating(false)
    }
  }

  const remove = async (poolId: string) => {
    if (confirmDeleteId !== poolId) {
      setConfirmDeleteId(poolId)
      return
    }
    setConfirmDeleteId(null)
    setDeletingId(poolId)
    try {
      await deletePool(poolId)
      setPools((current) => current.filter((p) => p.id !== poolId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete the Talent Pool.")
    } finally {
      setDeletingId(null)
    }
  }

  const active = pools.filter((p) => p.status !== "archived")
  const archived = pools.filter((p) => p.status === "archived")

  const grid = (items: TalentPool[]) => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 340px), 1fr))",
        gap: 14,
        alignItems: "stretch",
      }}
    >
      {items.map((pool) => (
        <PoolCard
          key={pool.id}
          pool={pool}
          onDelete={(id) => void remove(id)}
          deleting={deletingId === pool.id}
        />
      ))}
    </div>
  )

  return (
    <div
      data-testid="recruiter-pools"
      style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <div style={{ minWidth: 0 }}>
        <p style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
          Recruiter Workspace
        </p>
        <h1 style={{ fontSize: 26, color: TOKEN.ink, margin: "4px 0 0", letterSpacing: "-0.5px" }}>
          Talent Pools
        </h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "6px 0 0", lineHeight: 1.5 }}>
          Reusable candidate collections that live across roles — one candidate
          can belong to many pools, and their evidence always stays live.
        </p>
      </div>

      <RecruiterNav active="pools" testidPrefix="pools" />

      <Card style={{ padding: 18 }}>
        <form
          data-testid="pools-create-form"
          onSubmit={(event) => {
            event.preventDefault()
            void create()
          }}
          style={{ display: "flex", flexDirection: "column", gap: 10 }}
        >
          <h2 style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
            New Talent Pool
          </h2>
          <input
            data-testid="pools-create-name"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Name — e.g. AI / ML Early Talent"
            maxLength={120}
            style={{
              padding: "10px 12px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              fontSize: 13.5,
              color: TOKEN.ink,
            }}
          />
          <input
            data-testid="pools-create-description"
            type="text"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Description (optional) — e.g. Prospects from the Fall 2026 career fair"
            maxLength={600}
            style={{
              padding: "10px 12px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              fontSize: 13.5,
              color: TOKEN.ink,
            }}
          />
          {createError && (
            <p data-testid="pools-create-error" style={{ fontSize: 12.5, color: "#b91c1c", margin: 0 }}>
              {createError}
            </p>
          )}
          <div>
            <button
              type="submit"
              data-testid="pools-create-submit"
              disabled={creating}
              style={{
                padding: "9px 18px",
                borderRadius: 8,
                background: TOKEN.indigo,
                color: "#fff",
                fontSize: 13,
                fontWeight: 700,
                border: "none",
                cursor: creating ? "wait" : "pointer",
              }}
            >
              {creating ? "Creating…" : "Create pool"}
            </button>
          </div>
        </form>
      </Card>

      {confirmDeleteId && (
        <p data-testid="pool-delete-confirm" role="alert" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          Delete this Talent Pool? Deleting a pool never removes candidates,
          saved connections, or Hiring Briefs — press Delete again to confirm.
        </p>
      )}

      {loading ? (
        <LoadingState label="Loading Talent Pools…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : pools.length === 0 ? (
        <div data-testid="pools-empty">
          <EmptyState
            icon="🗂"
            title="No Talent Pools yet"
            description="Create a Talent Pool to organize candidates across roles."
          />
        </div>
      ) : (
        <>
          {grid(active)}
          {archived.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <p data-testid="pools-archived-heading" style={{ fontSize: 13, color: TOKEN.muted, margin: "6px 0 0", fontWeight: 700 }}>
                Archived ({archived.length})
              </p>
              {grid(archived)}
            </div>
          )}
        </>
      )}
    </div>
  )
}
