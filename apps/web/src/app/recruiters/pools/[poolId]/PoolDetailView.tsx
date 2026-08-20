"use client"

/**
 * One Talent Pool — header (inline rename, description, archive/restore,
 * delete) plus the live candidate grid. Every card shows the candidate's
 * consented public identity and a light LIVE evidence context (counts,
 * top skills, evidence types — never a score). A candidate who unpublished
 * keeps their consented identity but the evidence context and passport
 * link go dark (fail-closed).
 */

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../../components/passport/shared"
import { AddToBriefButton } from "../../../../../components/recruiter/AddToListButtons"
import { RecruiterNav } from "../../../../../components/recruiter/RecruiterNav"
import {
  deletePool,
  getPool,
  removePoolCandidate,
  updatePool,
  updatePoolCandidate,
  type PoolCandidate,
  type PoolCandidateSource,
  type TalentPool,
} from "@/lib/recruiter-pools-api"

const SOURCE_LABEL: Record<PoolCandidateSource, string> = {
  qr_scan: "QR scan",
  shared_link: "Shared link",
  search: "Search",
  role_match: "Role match",
  direct: "Direct",
  saved_search: "Saved search",
}

const EVIDENCE_FLAG_LABEL: Record<string, string> = {
  github: "GitHub code",
  live_site: "Live site",
  documents: "Documents",
  project_defense: "Project defense",
  video: "Video",
}

function addedLabel(iso: string | null): string {
  if (!iso) return ""
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ""
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

function PoolCandidateCard({
  poolId,
  entry,
  onChanged,
  onRemoved,
}: {
  poolId: string
  entry: PoolCandidate
  onChanged: (candidate: PoolCandidate) => void
  onRemoved: (studentUserId: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [noteDraft, setNoteDraft] = useState(entry.note ?? "")
  const [noteOpen, setNoteOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const name = entry.candidate.display_name ?? "Verified candidate"
  const noLongerPublished = entry.evidence === null && !entry.candidate.is_published

  const saveNote = async () => {
    setBusy(true)
    setError(null)
    try {
      const trimmed = noteDraft.trim()
      const updated = trimmed
        ? await updatePoolCandidate(poolId, entry.student_user_id, { note: trimmed })
        : await updatePoolCandidate(poolId, entry.student_user_id, { clear_note: true })
      onChanged(updated)
      setNoteOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save note.")
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await removePoolCandidate(poolId, entry.student_user_id)
      onRemoved(entry.student_user_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove candidate.")
      setBusy(false)
    }
  }

  return (
    <Card style={{ padding: 16, height: "100%", display: "flex", flexDirection: "column", ...(noLongerPublished ? { opacity: 0.75 } : {}) }}>
      <div data-testid="pool-candidate-card" style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h3 data-testid="pool-candidate-name" style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}>
              {name}
            </h3>
            {entry.candidate.headline && (
              <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.45, overflowWrap: "anywhere" }}>
                {entry.candidate.headline}
              </p>
            )}
            {entry.candidate.location && (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "2px 0 0", overflowWrap: "anywhere" }}>
                {entry.candidate.location}
              </p>
            )}
          </div>
          <span data-testid="pool-candidate-source">
            <Badge tone="slate">{SOURCE_LABEL[entry.source] ?? "Direct"}</Badge>
          </span>
        </div>

        {entry.evidence ? (
          <div data-testid="pool-candidate-evidence" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, fontWeight: 600 }}>
              {entry.evidence.skill_count}{" "}
              {entry.evidence.skill_count === 1 ? "skill" : "skills"} ·{" "}
              {entry.evidence.project_count}{" "}
              {entry.evidence.project_count === 1 ? "project" : "projects"}
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {entry.evidence.top_skills.map((skill) => (
                <Badge key={skill} tone="emerald" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                  {skill}
                </Badge>
              ))}
              {Object.entries(entry.evidence.evidence_flags)
                .filter(([, present]) => present)
                .map(([key]) => (
                  <Badge key={key} tone="sky">
                    {EVIDENCE_FLAG_LABEL[key] ?? key}
                  </Badge>
                ))}
            </div>
          </div>
        ) : (
          <p data-testid="pool-candidate-unpublished" style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
            No longer published — evidence goes dark until the candidate
            re-publishes their Work Passport.
          </p>
        )}

        {entry.note && !noteOpen && (
          <p data-testid="pool-candidate-note" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5, background: TOKEN.bg, borderRadius: 8, padding: "8px 10px", overflowWrap: "anywhere" }}>
            {entry.note}
          </p>
        )}
        {noteOpen && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <textarea
              data-testid="pool-candidate-note-input"
              value={noteDraft}
              onChange={(event) => setNoteDraft(event.target.value)}
              maxLength={4000}
              rows={3}
              placeholder="Private note for this pool — the candidate never sees it."
              style={{
                padding: "8px 10px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                fontSize: 12.5,
                color: TOKEN.ink,
                resize: "vertical",
                lineHeight: 1.5,
              }}
            />
            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                data-testid="pool-candidate-note-save"
                onClick={() => void saveNote()}
                disabled={busy}
                style={{ padding: "6px 12px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer" }}
              >
                Save note
              </button>
              <button
                type="button"
                onClick={() => {
                  setNoteOpen(false)
                  setNoteDraft(entry.note ?? "")
                }}
                style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {error && (
          <p role="alert" style={{ fontSize: 12, color: "#b91c1c", margin: 0 }}>
            {error}
          </p>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, borderTop: `1px solid ${TOKEN.line}`, paddingTop: 10, marginTop: "auto" }}>
          {!noteOpen && (
            <button
              type="button"
              data-testid="pool-candidate-note-toggle"
              onClick={() => setNoteOpen(true)}
              style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
            >
              {entry.note ? "Edit note" : "Add note"}
            </button>
          )}
          {entry.candidate.public_slug && (
            <AddToBriefButton candidateSlug={entry.candidate.public_slug} />
          )}
          <button
            type="button"
            data-testid="pool-candidate-remove"
            onClick={() => void remove()}
            disabled={busy}
            style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: busy ? "wait" : "pointer" }}
          >
            Remove
          </button>
          <span style={{ marginLeft: "auto", fontSize: 11.5, color: TOKEN.muted }}>
            {addedLabel(entry.added_at) ? `Added ${addedLabel(entry.added_at)}` : ""}
          </span>
          {entry.candidate.public_slug ? (
            <a
              data-testid="pool-candidate-open"
              href={`/p/${encodeURIComponent(entry.candidate.public_slug)}`}
              style={{ padding: "6px 12px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12, fontWeight: 600, textDecoration: "none" }}
            >
              Open Passport →
            </a>
          ) : (
            <Badge tone="amber">Passport currently private</Badge>
          )}
        </div>
      </div>
    </Card>
  )
}

export function PoolDetailView({ poolId }: { poolId: string }) {
  const router = useRouter()
  const [pool, setPool] = useState<TalentPool | null>(null)
  const [candidates, setCandidates] = useState<PoolCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [renameOpen, setRenameOpen] = useState(false)
  const [nameDraft, setNameDraft] = useState("")
  const [descriptionOpen, setDescriptionOpen] = useState(false)
  const [descriptionDraft, setDescriptionDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getPool(poolId)
      .then((detail) => {
        setPool(detail.pool)
        setCandidates(detail.candidates)
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load the Talent Pool."),
      )
      .finally(() => setLoading(false))
  }, [poolId])

  useEffect(() => {
    load()
  }, [load])

  const patch = async (params: Parameters<typeof updatePool>[1]) => {
    setBusy(true)
    setActionError(null)
    try {
      const updated = await updatePool(poolId, params)
      setPool(updated)
      return true
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to update the Talent Pool.")
      return false
    } finally {
      setBusy(false)
    }
  }

  const rename = async () => {
    if (!nameDraft.trim()) {
      setActionError("Give the Talent Pool a name.")
      return
    }
    if (await patch({ name: nameDraft.trim() })) setRenameOpen(false)
  }

  const saveDescription = async () => {
    const trimmed = descriptionDraft.trim()
    const ok = trimmed
      ? await patch({ description: trimmed })
      : await patch({ clear_description: true })
    if (ok) setDescriptionOpen(false)
  }

  const removeWholePool = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      await deletePool(poolId)
      router.push("/recruiters/pools")
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to delete the Talent Pool.")
      setBusy(false)
    }
  }

  return (
    <div
      data-testid="recruiter-pool-detail"
      style={{ maxWidth: 1080, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <p style={{ fontSize: 12.5, margin: 0 }}>
        <Link
          data-testid="pool-back"
          href="/recruiters/pools"
          style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
        >
          ← Talent Pools
        </Link>
      </p>

      <RecruiterNav active="pools" testidPrefix="pooldetail" />

      {loading ? (
        <LoadingState label="Loading the Talent Pool…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !pool ? null : (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
            {renameOpen ? (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  data-testid="pool-rename-input"
                  type="text"
                  value={nameDraft}
                  onChange={(event) => setNameDraft(event.target.value)}
                  maxLength={120}
                  aria-label="Pool name"
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
                  data-testid="pool-rename-save"
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
                <h1 data-testid="pool-title" style={{ fontSize: 24, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px", overflowWrap: "anywhere" }}>
                  {pool.name}
                </h1>
                {pool.status === "archived" && (
                  <span data-testid="pool-archived-badge">
                    <Badge tone="amber">Archived</Badge>
                  </span>
                )}
                <button
                  type="button"
                  data-testid="pool-rename"
                  onClick={() => {
                    setNameDraft(pool.name)
                    setRenameOpen(true)
                  }}
                  style={{ padding: "5px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                >
                  Rename
                </button>
              </div>
            )}

            {descriptionOpen ? (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  data-testid="pool-description-input"
                  type="text"
                  value={descriptionDraft}
                  onChange={(event) => setDescriptionDraft(event.target.value)}
                  maxLength={600}
                  aria-label="Pool description"
                  placeholder="Describe what this pool is for…"
                  style={{
                    flex: "1 1 280px",
                    minWidth: 0,
                    padding: "8px 12px",
                    borderRadius: 8,
                    border: `1px solid ${TOKEN.line}`,
                    fontSize: 13,
                    color: TOKEN.ink,
                  }}
                />
                <button
                  type="button"
                  data-testid="pool-description-save"
                  onClick={() => void saveDescription()}
                  disabled={busy}
                  style={{ padding: "8px 14px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, border: "none", cursor: "pointer" }}
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => setDescriptionOpen(false)}
                  style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.5, overflowWrap: "anywhere" }}>
                {pool.description ?? "No description yet."}{" "}
                <button
                  type="button"
                  data-testid="pool-description-edit"
                  onClick={() => {
                    setDescriptionDraft(pool.description ?? "")
                    setDescriptionOpen(true)
                  }}
                  style={{ background: "none", border: "none", color: TOKEN.indigo, fontWeight: 600, cursor: "pointer", fontSize: 12.5, padding: 0 }}
                >
                  Edit
                </button>
              </p>
            )}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Badge tone="indigo">
                {candidates.length} {candidates.length === 1 ? "candidate" : "candidates"}
              </Badge>
              {pool.status === "archived" ? (
                <button
                  type="button"
                  data-testid="pool-restore"
                  onClick={() => void patch({ status: "active" })}
                  disabled={busy}
                  style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.indigo, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                >
                  Restore
                </button>
              ) : (
                <button
                  type="button"
                  data-testid="pool-archive"
                  onClick={() => void patch({ status: "archived" })}
                  disabled={busy}
                  style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                >
                  Archive
                </button>
              )}
              <button
                type="button"
                data-testid="pool-delete"
                onClick={() => void removeWholePool()}
                disabled={busy}
                style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid #fecdd3`, background: TOKEN.roseSoft, color: TOKEN.rose, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
              >
                {confirmDelete ? "Confirm delete" : "Delete pool"}
              </button>
            </div>
            {confirmDelete && (
              <p data-testid="pool-delete-confirm" role="alert" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
                Deleting this pool never removes candidates, saved connections,
                or Hiring Briefs — press again to confirm.
              </p>
            )}
            {actionError && (
              <p role="alert" style={{ fontSize: 12.5, color: "#b91c1c", margin: 0 }}>
                {actionError}
              </p>
            )}
          </div>

          {candidates.length === 0 ? (
            <div data-testid="pool-candidates-empty">
              <EmptyState
                icon="🗂"
                title="No candidates in this pool yet"
                description="Add candidates from Search or a Saved Search — membership is a reference, never a copy."
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
              {candidates.map((entry) => (
                <PoolCandidateCard
                  key={entry.student_user_id}
                  poolId={poolId}
                  entry={entry}
                  onChanged={(updated) =>
                    setCandidates((current) =>
                      current.map((c) =>
                        c.student_user_id === updated.student_user_id ? updated : c,
                      ),
                    )
                  }
                  onRemoved={(studentUserId) =>
                    setCandidates((current) =>
                      current.filter((c) => c.student_user_id !== studentUserId),
                    )
                  }
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
