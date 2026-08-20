"use client"

/**
 * Saved Searches list — persisted recruiter searches that keep watching
 * published evidence. Each row restates the structured requirements the
 * search actually tracks, shows honest "new / updated evidence" counts
 * since the last review, and says plainly when a search has no hard
 * requirements and therefore tracks nothing.
 */

import { useCallback, useEffect, useState } from "react"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../components/passport/shared"
import { RecruiterNav } from "../../../../components/recruiter/RecruiterNav"
import type { RequirementsView } from "@/lib/recruiter-briefs-api"
import {
  deleteSavedSearch,
  listSavedSearches,
  updateSavedSearch,
  type SavedSearchListItem,
} from "@/lib/recruiter-saved-searches-api"

export function checkedAgoLabel(iso: string | null): string {
  if (!iso) return "Not checked yet"
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return "Not checked yet"
  const seconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000))
  if (seconds < 60) return "Checked just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `Checked ${minutes} ${minutes === 1 ? "minute" : "minutes"} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `Checked ${hours} ${hours === 1 ? "hour" : "hours"} ago`
  const days = Math.floor(hours / 24)
  return `Checked ${days} ${days === 1 ? "day" : "days"} ago`
}

export function RequirementChips({ view }: { view: RequirementsView }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {view.required.map((chip) => (
        <Badge key={`req-${chip.display}`} tone="indigo">
          {chip.display}
        </Badge>
      ))}
      {view.evidence.map((chip) => (
        <Badge key={`ev-${chip.key}`} tone="emerald">
          {chip.display}
        </Badge>
      ))}
      {view.preferred.map((chip) => (
        <Badge key={`pref-${chip.display}`} tone="slate">
          Preferred: {chip.display}
        </Badge>
      ))}
      {view.preferred_evidence.map((chip) => (
        <Badge key={`prefev-${chip.key}`} tone="slate">
          Preferred: {chip.display}
        </Badge>
      ))}
      {view.excluded.map((chip) => (
        <Badge key={`not-${chip.display}`} tone="rose">
          Not: {chip.display}
        </Badge>
      ))}
    </div>
  )
}

function SavedSearchCard({
  item,
  busy,
  onToggleStatus,
  onDelete,
  confirmingDelete,
}: {
  item: SavedSearchListItem
  busy: boolean
  onToggleStatus: (item: SavedSearchListItem) => void
  onDelete: (id: string) => void
  confirmingDelete: boolean
}) {
  const paused = item.status === "paused"
  return (
    <Card style={{ padding: 18 }}>
      <div data-testid="savedsearch-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0, flex: "1 1 220px" }}>
            <h3
              data-testid="savedsearch-card-name"
              style={{ fontSize: 15.5, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}
            >
              {item.name}
            </h3>
            {item.query_text && (
              <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: "2px 0 0", lineHeight: 1.5, overflowWrap: "anywhere" }}>
                “{item.query_text}”
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            {paused && <Badge tone="amber">Paused</Badge>}
            {!paused && (item.new_count ?? 0) > 0 && (
              <span data-testid="savedsearch-new-count">
                <Badge tone="emerald">
                  {item.new_count} new
                </Badge>
              </span>
            )}
            {!paused && (item.updated_count ?? 0) > 0 && (
              <span data-testid="savedsearch-updated-count">
                <Badge tone="indigo">
                  {item.updated_count} updated evidence
                </Badge>
              </span>
            )}
          </div>
        </div>

        <RequirementChips view={item.requirements} />

        {!item.tracking && (
          <p data-testid="savedsearch-untracked" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
            Add a required skill or evidence type to track new candidates.
          </p>
        )}

        {confirmingDelete && (
          <p data-testid="savedsearch-delete-confirm" role="alert" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            Deleting this saved search never removes candidates, Talent Pools,
            or Hiring Briefs. Press Delete again to confirm.
          </p>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, borderTop: `1px solid ${TOKEN.line}`, paddingTop: 10 }}>
          <span style={{ fontSize: 11.5, color: TOKEN.muted }}>
            {paused ? "Paused — not tracking" : checkedAgoLabel(item.last_evaluated_at)}
            {!paused && item.match_count !== null && (
              <>
                {" "}· {item.match_count} {item.match_count === 1 ? "match" : "matches"}
              </>
            )}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              data-testid={paused ? "savedsearch-resume" : "savedsearch-pause"}
              onClick={() => onToggleStatus(item)}
              disabled={busy}
              style={{
                padding: "7px 12px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.muted,
                fontSize: 12.5,
                fontWeight: 600,
                cursor: busy ? "wait" : "pointer",
              }}
            >
              {paused ? "Resume" : "Pause"}
            </button>
            <button
              type="button"
              data-testid="savedsearch-delete"
              onClick={() => onDelete(item.id)}
              disabled={busy}
              style={{
                padding: "7px 12px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.muted,
                fontSize: 12.5,
                fontWeight: 600,
                cursor: busy ? "wait" : "pointer",
              }}
            >
              Delete
            </button>
            <a
              data-testid="savedsearch-open"
              href={`/recruiters/saved-searches/${encodeURIComponent(item.id)}`}
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
              Open →
            </a>
          </div>
        </div>
      </div>
    </Card>
  )
}

export function SavedSearchesListView() {
  const [items, setItems] = useState<SavedSearchListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    listSavedSearches()
      .then(setItems)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load saved searches."),
      )
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const toggleStatus = async (item: SavedSearchListItem) => {
    setBusyId(item.id)
    setError(null)
    try {
      const updated = await updateSavedSearch(item.id, {
        status: item.status === "paused" ? "active" : "paused",
      })
      setItems((current) => current.map((s) => (s.id === updated.id ? updated : s)))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update the saved search.")
    } finally {
      setBusyId(null)
    }
  }

  const remove = async (id: string) => {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id)
      return
    }
    setConfirmDeleteId(null)
    setBusyId(id)
    try {
      await deleteSavedSearch(id)
      setItems((current) => current.filter((s) => s.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete the saved search.")
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div
      data-testid="recruiter-saved-searches"
      style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <div style={{ minWidth: 0 }}>
        <p style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
          Recruiter Workspace
        </p>
        <h1 style={{ fontSize: 26, color: TOKEN.ink, margin: "4px 0 0", letterSpacing: "-0.5px" }}>
          Saved Searches
        </h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "6px 0 0", lineHeight: 1.5 }}>
          Each saved search keeps watching published evidence — new candidates
          and updated proof are flagged when you come back, never scored.
        </p>
      </div>

      <RecruiterNav active="savedsearches" testidPrefix="savedsearches" />

      {loading ? (
        <LoadingState label="Loading saved searches…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items.length === 0 ? (
        <div data-testid="savedsearches-empty">
          <EmptyState
            icon="🔔"
            title="No saved searches yet"
            description="Save a recruiter search to be notified when new published evidence satisfies your requirements."
          />
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {items.map((item) => (
            <SavedSearchCard
              key={item.id}
              item={item}
              busy={busyId === item.id}
              onToggleStatus={(target) => void toggleStatus(target)}
              onDelete={(id) => void remove(id)}
              confirmingDelete={confirmDeleteId === item.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
