"use client"

/**
 * Hiring Briefs list — one brief per hiring need.
 *
 * A brief holds the role's requirements and its ROLE-SCOPED candidate pool:
 * a candidate can be Shortlisted for one brief while merely Saved for
 * another. Creating a brief parses the role description with the same
 * deterministic grammar as recruiter search — no scores, no LLM.
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
  type BadgeTone,
} from "../../../../components/passport/shared"
import {
  createBrief,
  deleteBrief,
  listBriefs,
  type HiringBriefListItem,
} from "@/lib/recruiter-briefs-api"

export const BRIEF_STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  active: "Active",
  paused: "Paused",
  closed: "Closed",
}

export const BRIEF_STATUS_TONE: Record<string, BadgeTone> = {
  draft: "slate",
  active: "emerald",
  paused: "amber",
  closed: "slate",
}

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

function BriefCard({
  brief,
  onDelete,
  deleting,
}: {
  brief: HiringBriefListItem
  onDelete: (id: string) => void
  deleting: boolean
}) {
  return (
    <Card style={{ padding: 18, height: "100%", display: "flex", flexDirection: "column" }}>
      <div
        data-testid="brief-card"
        style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1 }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h3
              data-testid="brief-card-title"
              style={{ fontSize: 15.5, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}
            >
              {brief.title}
            </h3>
            {brief.role && (
              <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5 }}>
                {brief.role}
              </p>
            )}
          </div>
          <Badge tone={BRIEF_STATUS_TONE[brief.status] ?? "slate"}>
            {BRIEF_STATUS_LABEL[brief.status] ?? brief.status}
          </Badge>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <Badge tone="indigo">
            {brief.candidate_count} {brief.candidate_count === 1 ? "candidate" : "candidates"}
          </Badge>
          {brief.shortlisted_count > 0 && (
            <Badge tone="emerald">{brief.shortlisted_count} shortlisted</Badge>
          )}
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
            {updatedLabel(brief.updated_at) ? `Updated ${updatedLabel(brief.updated_at)}` : ""}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              data-testid="brief-card-delete"
              onClick={() => onDelete(brief.id)}
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
              data-testid="brief-card-open"
              href={`/recruiters/briefs/${encodeURIComponent(brief.id)}`}
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
              Open role →
            </a>
          </div>
        </div>
      </div>
    </Card>
  )
}

export function BriefsListView() {
  const router = useRouter()
  const [briefs, setBriefs] = useState<HiringBriefListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const [title, setTitle] = useState("")
  const [roleText, setRoleText] = useState("")
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    listBriefs()
      .then(setBriefs)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load hiring briefs."),
      )
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const create = async () => {
    if (!roleText.trim() && !title.trim()) {
      setCreateError("Describe the role or give it a title first.")
      return
    }
    setCreating(true)
    setCreateError(null)
    try {
      const brief = await createBrief({
        title: title.trim() || null,
        role_text: roleText.trim() || null,
      })
      router.push(`/recruiters/briefs/${encodeURIComponent(brief.id)}`)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create the hiring brief.")
      setCreating(false)
    }
  }

  const remove = async (briefId: string) => {
    setDeletingId(briefId)
    try {
      await deleteBrief(briefId)
      setBriefs((current) => current.filter((b) => b.id !== briefId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete the hiring brief.")
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div
      data-testid="recruiter-briefs"
      style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <div style={{ minWidth: 0 }}>
        <p style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
          Recruiter Workspace
        </p>
        <h1 style={{ fontSize: 26, color: TOKEN.ink, margin: "4px 0 0", letterSpacing: "-0.5px" }}>
          Hiring Briefs
        </h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "6px 0 0", lineHeight: 1.5 }}>
          Define each role once — requirements, candidate pool, comparison and
          shortlist stay scoped to that role.
        </p>
      </div>

      <nav style={{ display: "flex", gap: 8, flexWrap: "wrap" }} aria-label="Recruiter sections">
        <a
          data-testid="briefs-nav-workspace"
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
        <a
          data-testid="briefs-nav-search"
          href="/recruiters/search"
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
          Search
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
          Hiring Briefs
        </span>
      </nav>

      <Card style={{ padding: 18 }}>
        <form
          data-testid="brief-create-form"
          onSubmit={(event) => {
            event.preventDefault()
            void create()
          }}
          style={{ display: "flex", flexDirection: "column", gap: 10 }}
        >
          <h2 style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
            New Hiring Brief
          </h2>
          <input
            data-testid="brief-create-title"
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Title (optional) — e.g. AI Engineer Intern, Fall 2026"
            maxLength={120}
            style={{
              padding: "10px 12px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              fontSize: 13.5,
              color: TOKEN.ink,
            }}
          />
          <textarea
            data-testid="brief-create-role-text"
            value={roleText}
            onChange={(event) => setRoleText(event.target.value)}
            placeholder="Describe the role in plain language — e.g. “Entry-level AI Engineer. Python, FastAPI and Machine Learning are required. NLP and live deployment are preferred.”"
            maxLength={600}
            rows={3}
            style={{
              padding: "10px 12px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              fontSize: 13.5,
              color: TOKEN.ink,
              resize: "vertical",
              lineHeight: 1.5,
            }}
          />
          {createError && (
            <p data-testid="brief-create-error" style={{ fontSize: 12.5, color: "#b91c1c", margin: 0 }}>
              {createError}
            </p>
          )}
          <div>
            <button
              type="submit"
              data-testid="brief-create-submit"
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
              {creating ? "Creating…" : "Create brief"}
            </button>
          </div>
        </form>
      </Card>

      {loading ? (
        <LoadingState label="Loading hiring briefs…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : briefs.length === 0 ? (
        <div data-testid="briefs-empty">
          <EmptyState
            icon="📋"
            title="No hiring briefs yet"
            description="Create a brief for each role you're hiring for. The same brief then drives search, evidence comparison and a role-scoped shortlist."
          />
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 340px), 1fr))",
            gap: 14,
            alignItems: "stretch",
          }}
        >
          {briefs.map((brief) => (
            <BriefCard
              key={brief.id}
              brief={brief}
              onDelete={(id) => void remove(id)}
              deleting={deletingId === brief.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
