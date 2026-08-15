"use client"

/**
 * Recruiter Workspace — the saved-candidates list.
 *
 * Every candidate here was saved by the signed-in recruiter from a public
 * Work Passport (QR scan or shared link). Cards surface only the candidate's
 * consented public identity; the "Open Passport" action reopens the live
 * public passport. A candidate who has since unpublished stays listed, but
 * their passport link goes dark until they re-publish.
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
import {
  deleteConnection,
  listConnections,
  type ConnectionSource,
  type RecruiterConnection,
} from "@/lib/recruiter-connections-api"

const SOURCE_LABEL: Record<ConnectionSource, string> = {
  qr_scan: "QR scan",
  shared_link: "Shared link",
  search: "Search",
  role_match: "Role match",
  direct: "Direct",
}

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

function savedDateLabel(iso: string | null): string {
  if (!iso) return ""
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ""
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

function CandidateCard({
  connection,
  onRemove,
  removing,
}: {
  connection: RecruiterConnection
  onRemove: (id: string) => void
  removing: boolean
}) {
  const { candidate } = connection
  const name = candidate.display_name ?? "Verified candidate"
  const savedOn = savedDateLabel(connection.created_at)

  return (
    <Card style={{ padding: 18 }}>
      <div
        data-testid="workspace-candidate-card"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
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
          <div style={{ minWidth: 0, flex: 1 }}>
            <h3
              data-testid="workspace-candidate-name"
              style={{ fontSize: 15.5, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}
            >
              {name}
            </h3>
            {candidate.headline && (
              <p
                data-testid="workspace-candidate-headline"
                style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5, overflowWrap: "anywhere" }}
              >
                {candidate.headline}
              </p>
            )}
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
          {!candidate.is_published && (
            <span data-testid="workspace-candidate-private">
              <Badge tone="amber">Passport currently private</Badge>
            </span>
          )}
        </div>

        {candidate.summary && (
          <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0, lineHeight: 1.55, overflowWrap: "anywhere" }}>
            {candidate.summary}
          </p>
        )}

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 10,
            borderTop: `1px solid ${TOKEN.line}`,
            paddingTop: 10,
          }}
        >
          <span data-testid="workspace-candidate-meta" style={{ fontSize: 11.5, color: TOKEN.muted }}>
            {savedOn ? `Saved ${savedOn}` : "Saved"} · {SOURCE_LABEL[connection.source] ?? "Shared link"}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              data-testid="workspace-candidate-remove"
              onClick={() => onRemove(connection.id)}
              disabled={removing}
              style={{
                padding: "7px 12px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
                color: TOKEN.muted,
                fontSize: 12.5,
                fontWeight: 600,
                cursor: removing ? "wait" : "pointer",
              }}
            >
              {removing ? "Removing…" : "Remove"}
            </button>
            {candidate.public_slug ? (
              <a
                data-testid="workspace-candidate-open"
                href={`/p/${encodeURIComponent(candidate.public_slug)}`}
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
                Open Passport →
              </a>
            ) : (
              <span
                style={{
                  padding: "7px 14px",
                  borderRadius: 8,
                  background: TOKEN.bg,
                  color: TOKEN.muted,
                  fontSize: 12.5,
                  fontWeight: 600,
                }}
              >
                Passport private
              </span>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}

export function RecruiterWorkspaceView() {
  const [connections, setConnections] = useState<RecruiterConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    listConnections()
      .then(setConnections)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load saved candidates."),
      )
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const remove = async (connectionId: string) => {
    setRemovingId(connectionId)
    try {
      await deleteConnection(connectionId)
      setConnections((current) => current.filter((c) => c.id !== connectionId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove saved candidate.")
    } finally {
      setRemovingId(null)
    }
  }

  return (
    <div
      data-testid="recruiter-workspace"
      style={{ maxWidth: 860, margin: "0 auto", padding: "40px 20px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <p style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
            Recruiter Workspace
          </p>
          <h1 style={{ fontSize: 24, color: TOKEN.ink, margin: "4px 0 0", letterSpacing: "-0.4px" }}>
            Saved candidates
          </h1>
        </div>
        {!loading && !error && connections.length > 0 && (
          <span data-testid="workspace-count" style={{ marginLeft: "auto", fontSize: 12.5, color: TOKEN.muted }}>
            {connections.length} {connections.length === 1 ? "candidate" : "candidates"}
          </span>
        )}
      </div>

      {loading ? (
        <LoadingState label="Loading saved candidates…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : connections.length === 0 ? (
        <div data-testid="workspace-empty">
          <EmptyState
            icon="🪪"
            title="No saved candidates yet"
            description="Scan a candidate's Passport QR code or open their shared passport link, then press “Save Candidate” — they'll appear here for review any time."
          />
          <p style={{ textAlign: "center", fontSize: 12.5, color: TOKEN.muted, marginTop: 8 }}>
            Have a report link instead?{" "}
            <a href="/recruiters/open" style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}>
              Open a Verified Build Report →
            </a>
          </p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {connections.map((connection) => (
            <CandidateCard
              key={connection.id}
              connection={connection}
              onRemove={(id) => void remove(id)}
              removing={removingId === connection.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
