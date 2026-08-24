"use client"

/**
 * One Talent Pool — the recruiter's evidence workspace for a set of people.
 *
 * Three things live on this page, and the design keeps them visibly apart:
 *
 *   1. VeriBridge EVIDENCE (live, consented, fail-closed). A candidate who
 *      unpublishes keeps their consented identity while the evidence context
 *      and passport link go dark.
 *   2. RECRUITER JUDGEMENT — workflow status, private note, tags. Never
 *      evidence, never candidate-visible, never leaves this recruiter.
 *   3. FILTERING over (1), run by the SAME deterministic engine as global
 *      recruiter search, so every candidate shown after a filter can be
 *      traced back to the published evidence that matched.
 *
 * Filter and selection state live in the URL, so a reload, a shared link and
 * browser back/forward all reproduce exactly what the recruiter was looking
 * at — and Compare deep-links into the matrix rather than trapping state in
 * a modal.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
  type BadgeTone,
} from "../../../../../components/passport/shared"
import { AddToBriefButton } from "../../../../../components/recruiter/AddToListButtons"
import { RecruiterNav } from "../../../../../components/recruiter/RecruiterNav"
import {
  deletePool,
  EVIDENCE_FILTER_KEYS,
  EVIDENCE_FILTER_LABEL,
  filterPoolCandidates,
  POOL_CANDIDATE_STATUSES,
  POOL_STATUS_LABEL,
  removePoolCandidate,
  updatePool,
  updatePoolCandidate,
  type EvidenceFilterKey,
  type FilteredPoolCandidate,
  type PoolFilterInterpretation,
  type PoolCandidateSource,
  type PoolCandidateStatus,
  type RecruiterTag,
  type TalentPool,
} from "@/lib/recruiter-pools-api"

const MIN_COMPARE = 2
const MAX_COMPARE = 5

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

/** Neutral, non-evaluative tones: a workflow stage is the recruiter's
 * process, so nothing here reads as a verdict on the person. */
const STATUS_TONE: Record<PoolCandidateStatus, BadgeTone> = {
  review: "slate",
  shortlisted: "indigo",
  interview: "purple",
  hold: "amber",
  pass: "slate",
}

function addedLabel(iso: string | null): string {
  if (!iso) return ""
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ""
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

function chipButton(active: boolean): React.CSSProperties {
  return {
    padding: "5px 11px",
    borderRadius: 999,
    border: `1px solid ${active ? TOKEN.indigo : TOKEN.line}`,
    background: active ? TOKEN.indigoSoft : "#fff",
    color: active ? "#3730a3" : TOKEN.muted,
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
  }
}

/** Why this candidate survived an evidence filter — reconstructed from the
 * deterministic evaluation, never a score and never generated prose. */
function MatchExplanation({ entry }: { entry: FilteredPoolCandidate }) {
  const match = entry.match
  if (!match) return null
  const met = (match.requirements ?? []).filter((r) => r.satisfied === true)
  const missing = match.missing_requirements ?? []
  const slug = entry.candidate.public_slug

  return (
    <div
      data-testid="pool-candidate-match"
      style={{ display: "flex", flexDirection: "column", gap: 5, background: TOKEN.bg, borderRadius: 8, padding: "8px 10px" }}
    >
      <span style={{ fontSize: 10.5, color: TOKEN.muted, fontWeight: 700, letterSpacing: "0.4px", textTransform: "uppercase" }}>
        {match.match_type === "close" ? "Close match — some evidence missing" : "Matched on published evidence"}
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
        {met.map((requirement, index) => {
          const display = String(requirement.display ?? requirement.requirement ?? "")
          const concept = String(requirement.requirement ?? "")
          if (!display) return null
          // Deep link straight to the skill report that satisfied it: the
          // recruiter can always open the evidence behind the match.
          return slug && concept ? (
            <a
              key={`${display}-${index}`}
              data-testid="pool-match-proof-link"
              href={`/p/${encodeURIComponent(slug)}/skills/${encodeURIComponent(concept)}`}
              style={{ textDecoration: "none" }}
            >
              <Badge tone="emerald">{display} →</Badge>
            </a>
          ) : (
            <Badge key={`${display}-${index}`} tone="emerald">{display}</Badge>
          )
        })}
        {missing.map((display) => (
          <Badge key={display} tone="slate">
            {display}: not demonstrated
          </Badge>
        ))}
      </div>
    </div>
  )
}

function PoolCandidateCard({
  poolId,
  entry,
  selected,
  selectable,
  onToggleSelect,
  onChanged,
  onRemoved,
  tagVocabulary,
}: {
  poolId: string
  entry: FilteredPoolCandidate
  selected: boolean
  selectable: boolean
  onToggleSelect: (studentUserId: string) => void
  onChanged: (candidate: FilteredPoolCandidate) => void
  onRemoved: (studentUserId: string) => void
  tagVocabulary: RecruiterTag[]
}) {
  const [busy, setBusy] = useState(false)
  const [noteDraft, setNoteDraft] = useState(entry.note ?? "")
  const [noteOpen, setNoteOpen] = useState(false)
  const [tagDraft, setTagDraft] = useState("")
  const [tagsOpen, setTagsOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const name = entry.candidate.display_name ?? "Verified candidate"
  const noLongerPublished = entry.evidence === null && !entry.candidate.is_published

  const patch = async (
    params: Parameters<typeof updatePoolCandidate>[2],
    onDone?: () => void,
  ) => {
    setBusy(true)
    setError(null)
    try {
      const updated = await updatePoolCandidate(poolId, entry.student_user_id, params)
      onChanged({ ...updated, match: entry.match })
      onDone?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save.")
    } finally {
      setBusy(false)
    }
  }

  const saveNote = () => {
    const trimmed = noteDraft.trim()
    return patch(trimmed ? { note: trimmed } : { clear_note: true }, () => setNoteOpen(false))
  }

  const addTag = (raw: string) => {
    const tag = raw.trim()
    if (!tag) return
    if (entry.tags.some((t) => t.toLowerCase() === tag.toLowerCase())) {
      setTagDraft("")
      return
    }
    void patch({ tags: [...entry.tags, tag] }, () => setTagDraft(""))
  }

  const removeTag = (tag: string) =>
    void patch({ tags: entry.tags.filter((t) => t !== tag) })

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

  const suggestions = tagVocabulary
    .map((t) => t.tag)
    .filter((t) => !entry.tags.some((existing) => existing.toLowerCase() === t.toLowerCase()))
    .slice(0, 6)

  return (
    <Card
      style={{
        padding: 16,
        height: "100%",
        display: "flex",
        flexDirection: "column",
        ...(selected ? { boxShadow: `0 0 0 2px ${TOKEN.indigo}` } : {}),
        ...(noLongerPublished ? { opacity: 0.75 } : {}),
      }}
    >
      <div data-testid="pool-candidate-card" style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <label
            style={{ display: "flex", alignItems: "center", gap: 6, cursor: selectable || selected ? "pointer" : "not-allowed" }}
          >
            <input
              type="checkbox"
              data-testid="pool-candidate-select"
              checked={selected}
              disabled={!selected && !selectable}
              onChange={() => onToggleSelect(entry.student_user_id)}
              aria-label={`Select ${name} for comparison`}
              style={{ width: 16, height: 16, accentColor: TOKEN.indigo, cursor: "inherit" }}
            />
          </label>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h3 data-testid="pool-candidate-name" style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700, overflowWrap: "anywhere" }}>
              {name}
            </h3>
            {entry.candidate.headline && (
              <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.45, overflowWrap: "anywhere" }}>
                {entry.candidate.headline}
              </p>
            )}
            {entry.candidate.role_areas.length > 0 && (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "2px 0 0", overflowWrap: "anywhere" }}>
                {entry.candidate.role_areas.join(" · ")}
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

        {/* ── Recruiter workflow stage: this recruiter's process, not a
            judgement recorded against the candidate. ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span data-testid="pool-candidate-status">
            <Badge tone={STATUS_TONE[entry.status]}>{POOL_STATUS_LABEL[entry.status]}</Badge>
          </span>
          <select
            data-testid="pool-candidate-status-select"
            value={entry.status}
            disabled={busy}
            aria-label={`Workflow status for ${name}`}
            onChange={(event) =>
              void patch({ status: event.target.value as PoolCandidateStatus })
            }
            style={{
              padding: "4px 8px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              fontSize: 12,
              color: TOKEN.inkSoft,
              background: "#fff",
              cursor: "pointer",
            }}
          >
            {POOL_CANDIDATE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {POOL_STATUS_LABEL[status]}
              </option>
            ))}
          </select>
        </div>

        {entry.evidence ? (
          <div data-testid="pool-candidate-evidence" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, fontWeight: 600 }}>
              {entry.evidence.skill_count} {entry.evidence.skill_count === 1 ? "skill" : "skills"} ·{" "}
              {entry.evidence.project_count} {entry.evidence.project_count === 1 ? "project" : "projects"}
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
            No longer published — evidence goes dark until the candidate re-publishes
            their Work Passport.
          </p>
        )}

        <MatchExplanation entry={entry} />

        {/* ── Recruiter-private tags ── */}
        {(entry.tags.length > 0 || tagsOpen) && (
          <div data-testid="pool-candidate-tags" style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
            {entry.tags.map((tag) => (
              <span key={tag} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <Badge tone="purple">{tag}</Badge>
                {tagsOpen && (
                  <button
                    type="button"
                    data-testid="pool-candidate-tag-remove"
                    onClick={() => removeTag(tag)}
                    disabled={busy}
                    aria-label={`Remove tag ${tag}`}
                    style={{ background: "none", border: "none", color: TOKEN.muted, cursor: "pointer", fontSize: 13, padding: 0, lineHeight: 1 }}
                  >
                    ×
                  </button>
                )}
              </span>
            ))}
          </div>
        )}
        {tagsOpen && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <input
                data-testid="pool-candidate-tag-input"
                type="text"
                value={tagDraft}
                maxLength={40}
                placeholder="Add a tag — Backend, Career Fair…"
                aria-label={`Add a tag for ${name}`}
                onChange={(event) => setTagDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault()
                    addTag(tagDraft)
                  }
                }}
                style={{ flex: "1 1 160px", minWidth: 0, padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 12.5, color: TOKEN.ink }}
              />
              <button
                type="button"
                data-testid="pool-candidate-tag-add"
                onClick={() => addTag(tagDraft)}
                disabled={busy}
                style={{ padding: "6px 12px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer" }}
              >
                Add tag
              </button>
            </div>
            {suggestions.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {suggestions.map((tag) => (
                  <button key={tag} type="button" onClick={() => addTag(tag)} style={chipButton(false)}>
                    + {tag}
                  </button>
                ))}
              </div>
            )}
            <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
              Tags are yours alone — the candidate never sees them and they are
              never treated as evidence.
            </p>
          </div>
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
              aria-label={`Private note for ${name}`}
              placeholder="Private note for this pool — the candidate never sees it."
              style={{ padding: "8px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 12.5, color: TOKEN.ink, resize: "vertical", lineHeight: 1.5 }}
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
          <button
            type="button"
            data-testid="pool-candidate-tags-toggle"
            onClick={() => setTagsOpen((v) => !v)}
            style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
          >
            {tagsOpen ? "Done" : entry.tags.length ? "Edit tags" : "Add tags"}
          </button>
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
  const params = useSearchParams()

  // Filter + selection state is URL-derived so reload, deep links and
  // back/forward all reproduce the same view.
  const urlQuery = params.get("q") ?? ""
  const urlEvidence = useMemo(
    () => (params.get("evidence") ?? "").split(",").filter(Boolean) as EvidenceFilterKey[],
    [params],
  )
  const urlStatus = (params.get("status") ?? "") as PoolCandidateStatus | ""
  const urlTags = useMemo(
    () => (params.get("tags") ?? "").split(",").filter(Boolean),
    [params],
  )
  const urlSelected = useMemo(
    () => (params.get("selected") ?? "").split(",").filter(Boolean),
    [params],
  )

  const [pool, setPool] = useState<TalentPool | null>(null)
  const [candidates, setCandidates] = useState<FilteredPoolCandidate[]>([])
  const [poolTotal, setPoolTotal] = useState(0)
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({})
  const [tagVocabulary, setTagVocabulary] = useState<RecruiterTag[]>([])
  const [unavailableExcluded, setUnavailableExcluded] = useState(0)
  const [interpretation, setInterpretation] =
    useState<PoolFilterInterpretation | null>(null)
  const [closeCandidates, setCloseCandidates] = useState<FilteredPoolCandidate[]>([])
  const [closeOpen, setCloseOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [queryDraft, setQueryDraft] = useState(urlQuery)
  // Re-sync the draft when the URL changes underneath us (back/forward,
  // a cleared filter). Adjusted during render rather than in an effect so
  // there is no extra commit — the React-recommended shape for this.
  const [lastUrlUrlQuery, setLastUrlUrlQuery] = useState(urlQuery)
  if (urlQuery !== lastUrlUrlQuery) {
    setLastUrlUrlQuery(urlQuery)
    setQueryDraft(urlQuery)
  }
  const [renameOpen, setRenameOpen] = useState(false)
  const [nameDraft, setNameDraft] = useState("")
  const [descriptionOpen, setDescriptionOpen] = useState(false)
  const [descriptionDraft, setDescriptionDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const filtering = Boolean(urlQuery || urlEvidence.length || urlStatus || urlTags.length)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    filterPoolCandidates(poolId, {
      q: urlQuery,
      evidence: urlEvidence,
      status: urlStatus || null,
      tags: urlTags,
    })
      .then((result) => {
        setPool(result.pool)
        setCandidates(result.candidates)
        setCloseCandidates(result.close_candidates ?? [])
        setPoolTotal(result.pool_total)
        setStatusCounts(result.status_counts)
        setTagVocabulary(result.tag_vocabulary)
        setUnavailableExcluded(result.unavailable_excluded)
        setInterpretation(result.interpretation)
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load the Talent Pool."),
      )
      .finally(() => setLoading(false))
  }, [poolId, urlQuery, urlEvidence, urlStatus, urlTags])

  useEffect(() => {
    load()
  }, [load])


  const pushState = useCallback(
    (next: {
      q?: string
      evidence?: string[]
      status?: string
      tags?: string[]
      selected?: string[]
    }) => {
      const search = new URLSearchParams()
      const q = next.q ?? urlQuery
      const evidence = next.evidence ?? urlEvidence
      const status = next.status ?? urlStatus
      const tags = next.tags ?? urlTags
      const selected = next.selected ?? urlSelected
      if (q.trim()) search.set("q", q.trim())
      if (evidence.length) search.set("evidence", evidence.join(","))
      if (status) search.set("status", status)
      if (tags.length) search.set("tags", tags.join(","))
      if (selected.length) search.set("selected", selected.join(","))
      const qs = search.toString()
      router.push(`/recruiters/pools/${encodeURIComponent(poolId)}${qs ? `?${qs}` : ""}`)
    },
    [poolId, router, urlQuery, urlEvidence, urlStatus, urlTags, urlSelected],
  )

  // Selection only ever refers to candidates currently on screen.
  const visibleIds = useMemo(
    () =>
      new Set(
        [...candidates, ...closeCandidates].map((c) => c.student_user_id),
      ),
    [candidates, closeCandidates],
  )
  const selected = useMemo(
    () => urlSelected.filter((id) => visibleIds.has(id)),
    [urlSelected, visibleIds],
  )
  const canSelectMore = selected.length < MAX_COMPARE

  const toggleSelect = (studentUserId: string) => {
    const next = selected.includes(studentUserId)
      ? selected.filter((id) => id !== studentUserId)
      : selected.length >= MAX_COMPARE
        ? selected
        : [...selected, studentUserId]
    pushState({ selected: next })
  }

  const compare = () => {
    const search = new URLSearchParams({ ids: selected.join(",") })
    if (urlQuery.trim()) search.set("q", urlQuery.trim())
    router.push(
      `/recruiters/pools/${encodeURIComponent(poolId)}/compare?${search.toString()}`,
    )
  }

  const patch = async (params2: Parameters<typeof updatePool>[1]) => {
    setBusy(true)
    setActionError(null)
    try {
      const updated = await updatePool(poolId, params2)
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
    const ok = trimmed ? await patch({ description: trimmed }) : await patch({ clear_description: true })
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

  const unrecognized = interpretation?.unrecognized_terms ?? []
  // Every requirement the engine actually executed, listed separately.
  // Shown because an evidence requirement is CANDIDATE-level: "machine
  // learning with GitHub proof" asks for someone with published ML evidence
  // AND published GitHub evidence — it does not assert that the GitHub proof
  // is what backs the ML. Saying so beats letting the recruiter assume it.
  const understoodAs: { label: string; kind: "concept" | "evidence" }[] = [
    ...(interpretation?.required ?? []).map((r) => ({
      label: r.display,
      kind: "concept" as const,
    })),
    ...(interpretation?.evidence ?? []).map((e) => ({
      label: e.display,
      kind: "evidence" as const,
    })),
  ]

  return (
    <div
      data-testid="recruiter-pool-detail"
      style={{ maxWidth: 1180, margin: "0 auto", padding: "40px 24px", display: "flex", flexDirection: "column", gap: 18 }}
    >
      <p style={{ fontSize: 12.5, margin: 0 }}>
        <Link data-testid="pool-back" href="/recruiters/pools" style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}>
          ← Talent Pools
        </Link>
      </p>

      <RecruiterNav active="pools" testidPrefix="pooldetail" />

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !pool && loading ? (
        <LoadingState label="Loading the Talent Pool…" />
      ) : !pool ? null : (
        <>
          {/* ── Pool header ── */}
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
                  style={{ flex: "1 1 240px", minWidth: 0, padding: "9px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 15, fontWeight: 700, color: TOKEN.ink }}
                />
                <button type="button" data-testid="pool-rename-save" onClick={() => void rename()} disabled={busy} style={{ padding: "8px 14px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, border: "none", cursor: "pointer" }}>
                  Save
                </button>
                <button type="button" onClick={() => setRenameOpen(false)} style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
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
                <button type="button" data-testid="pool-rename" onClick={() => { setNameDraft(pool.name); setRenameOpen(true) }} style={{ padding: "5px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
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
                  style={{ flex: "1 1 280px", minWidth: 0, padding: "8px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 13, color: TOKEN.ink }}
                />
                <button type="button" data-testid="pool-description-save" onClick={() => void saveDescription()} disabled={busy} style={{ padding: "8px 14px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, border: "none", cursor: "pointer" }}>
                  Save
                </button>
                <button type="button" onClick={() => setDescriptionOpen(false)} style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
                  Cancel
                </button>
              </div>
            ) : (
              <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.5, overflowWrap: "anywhere" }}>
                {pool.description ?? "No description yet."}{" "}
                <button type="button" data-testid="pool-description-edit" onClick={() => { setDescriptionDraft(pool.description ?? ""); setDescriptionOpen(true) }} style={{ background: "none", border: "none", color: TOKEN.indigo, fontWeight: 600, cursor: "pointer", fontSize: 12.5, padding: 0 }}>
                  Edit
                </button>
              </p>
            )}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Badge tone="indigo">
                {poolTotal} {poolTotal === 1 ? "candidate" : "candidates"}
              </Badge>
              {POOL_CANDIDATE_STATUSES.filter((s) => (statusCounts[s] ?? 0) > 0 && s !== "review").map((s) => (
                <span key={s} data-testid="pool-status-count">
                  <Badge tone={STATUS_TONE[s]}>
                    {statusCounts[s]} {POOL_STATUS_LABEL[s].toLowerCase()}
                  </Badge>
                </span>
              ))}
              {pool.status === "archived" ? (
                <button type="button" data-testid="pool-restore" onClick={() => void patch({ status: "active" })} disabled={busy} style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.indigo, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                  Restore
                </button>
              ) : (
                <button type="button" data-testid="pool-archive" onClick={() => void patch({ status: "archived" })} disabled={busy} style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                  Archive
                </button>
              )}
              <button type="button" data-testid="pool-delete" onClick={() => void removeWholePool()} disabled={busy} style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid #fecdd3`, background: TOKEN.roseSoft, color: TOKEN.rose, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                {confirmDelete ? "Confirm delete" : "Delete pool"}
              </button>
            </div>
            {confirmDelete && (
              <p data-testid="pool-delete-confirm" role="alert" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
                Deleting this pool never removes candidates, saved connections, or
                Hiring Briefs — press again to confirm.
              </p>
            )}
            {actionError && (
              <p role="alert" style={{ fontSize: 12.5, color: "#b91c1c", margin: 0 }}>
                {actionError}
              </p>
            )}
          </div>

          {/* ── Filter bar ── */}
          <Card style={{ padding: 14 }}>
            <div data-testid="pool-filter" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  pushState({ q: queryDraft, selected: [] })
                }}
                style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
              >
                <input
                  data-testid="pool-filter-input"
                  type="search"
                  value={queryDraft}
                  onChange={(event) => setQueryDraft(event.target.value)}
                  maxLength={320}
                  aria-label="Filter this pool by evidence"
                  placeholder="Filter by evidence — “FastAPI with deployed website evidence”"
                  style={{ flex: "1 1 320px", minWidth: 0, padding: "9px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 13, color: TOKEN.ink }}
                />
                <button type="submit" data-testid="pool-filter-submit" style={{ padding: "9px 16px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, border: "none", cursor: "pointer" }}>
                  Filter
                </button>
                {filtering && (
                  <button
                    type="button"
                    data-testid="pool-filter-clear"
                    onClick={() => {
                      setQueryDraft("")
                      pushState({ q: "", evidence: [], status: "", tags: [], selected: [] })
                    }}
                    style={{ padding: "9px 14px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}
                  >
                    Clear
                  </button>
                )}
              </form>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 700, letterSpacing: "0.3px", textTransform: "uppercase" }}>
                  Proof source
                </span>
                {EVIDENCE_FILTER_KEYS.map((key) => {
                  const active = urlEvidence.includes(key)
                  return (
                    <button
                      key={key}
                      type="button"
                      data-testid="pool-filter-evidence"
                      aria-pressed={active}
                      onClick={() =>
                        pushState({
                          evidence: active ? urlEvidence.filter((e) => e !== key) : [...urlEvidence, key],
                          selected: [],
                        })
                      }
                      style={chipButton(active)}
                    >
                      {EVIDENCE_FILTER_LABEL[key]}
                    </button>
                  )
                })}
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 700, letterSpacing: "0.3px", textTransform: "uppercase" }}>
                  Your workflow
                </span>
                {POOL_CANDIDATE_STATUSES.map((s) => {
                  const active = urlStatus === s
                  return (
                    <button
                      key={s}
                      type="button"
                      data-testid="pool-filter-status"
                      aria-pressed={active}
                      onClick={() => pushState({ status: active ? "" : s, selected: [] })}
                      style={chipButton(active)}
                    >
                      {POOL_STATUS_LABEL[s]}
                    </button>
                  )
                })}
                {tagVocabulary.slice(0, 10).map((tag) => {
                  const active = urlTags.some((t) => t.toLowerCase() === tag.tag.toLowerCase())
                  return (
                    <button
                      key={tag.tag_key}
                      type="button"
                      data-testid="pool-filter-tag"
                      aria-pressed={active}
                      onClick={() =>
                        pushState({
                          tags: active
                            ? urlTags.filter((t) => t.toLowerCase() !== tag.tag.toLowerCase())
                            : [...urlTags, tag.tag],
                          selected: [],
                        })
                      }
                      style={chipButton(active)}
                    >
                      #{tag.tag}
                    </button>
                  )
                })}
              </div>

              {filtering && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {understoodAs.length > 0 && (
                    <div
                      data-testid="pool-filter-understood"
                      style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}
                    >
                      <span style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 700, letterSpacing: "0.3px", textTransform: "uppercase" }}>
                        Understood as
                      </span>
                      {understoodAs.map((chip) => (
                        <Badge key={`${chip.kind}-${chip.label}`} tone={chip.kind === "evidence" ? "sky" : "indigo"}>
                          {chip.label}
                        </Badge>
                      ))}
                      <span style={{ flexBasis: "100%", fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
                        Each is checked separately against published evidence —
                        a proof-source requirement means the candidate has
                        published that kind of proof, not that it is what backs
                        the skill above.
                      </span>
                    </div>
                  )}
                  <p data-testid="pool-filter-summary" style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0 }}>
                    Showing {candidates.length} of {poolTotal}{" "}
                    {poolTotal === 1 ? "candidate" : "candidates"} in this pool.
                  </p>
                  {unrecognized.length > 0 && (
                    <p data-testid="pool-filter-unrecognized" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
                      Not understood as a requirement, so not used to match:{" "}
                      {unrecognized.join(", ")}.
                    </p>
                  )}
                  {unavailableExcluded > 0 && (
                    <p data-testid="pool-filter-unavailable" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
                      {unavailableExcluded}{" "}
                      {unavailableExcluded === 1 ? "candidate is" : "candidates are"} not
                      shown because their evidence is no longer published — that is not a
                      judgement about them.
                    </p>
                  )}
                </div>
              )}
            </div>
          </Card>

          {/* ── Compare bar ── */}
          <div
            data-testid="pool-compare-bar"
            style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", minHeight: 34 }}
          >
            <span style={{ fontSize: 12.5, color: TOKEN.muted }}>
              {selected.length === 0
                ? `Select ${MIN_COMPARE}–${MAX_COMPARE} candidates to compare their evidence.`
                : `${selected.length} selected${selected.length >= MAX_COMPARE ? " (maximum)" : ""}.`}
            </span>
            <button
              type="button"
              data-testid="pool-compare"
              disabled={selected.length < MIN_COMPARE}
              onClick={compare}
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                background: selected.length < MIN_COMPARE ? TOKEN.bg : TOKEN.indigo,
                color: selected.length < MIN_COMPARE ? TOKEN.muted : "#fff",
                border: selected.length < MIN_COMPARE ? `1px solid ${TOKEN.line}` : "none",
                fontSize: 12.5,
                fontWeight: 600,
                cursor: selected.length < MIN_COMPARE ? "not-allowed" : "pointer",
              }}
            >
              Compare evidence
            </button>
            {selected.length > 0 && (
              <button type="button" data-testid="pool-compare-clear" onClick={() => pushState({ selected: [] })} style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.muted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
                Clear selection
              </button>
            )}
          </div>

          {loading ? (
            <LoadingState label="Loading candidates…" />
          ) : candidates.length === 0 ? (
            <div data-testid={filtering ? "pool-filter-empty" : "pool-candidates-empty"}>
              <EmptyState
                icon={filtering ? "🔍" : "🗂"}
                title={
                  filtering
                    ? "No candidates in this pool match that evidence"
                    : "No candidates in this Talent Pool yet"
                }
                description={
                  filtering
                    ? closeCandidates.length > 0
                      ? "No member of this pool satisfies every part of that filter. Nothing here is a judgement about anyone — some candidates match it partially and are listed below."
                      : "Nothing here is a judgement about anyone — it only means no member of this pool has published evidence satisfying that filter."
                    : "Add candidates from Search or your Saved Candidates — membership is a reference to the person, never a copy of their evidence."
                }
                action={
                  filtering ? (
                    <button
                      type="button"
                      data-testid="pool-filter-empty-clear"
                      onClick={() => {
                        setQueryDraft("")
                        pushState({ q: "", evidence: [], status: "", tags: [], selected: [] })
                      }}
                      style={{ padding: "9px 16px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, border: "none", cursor: "pointer" }}
                    >
                      Clear filters
                    </button>
                  ) : (
                    <div style={{ display: "inline-flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                      <Link data-testid="pool-empty-saved" href="/recruiters/workspace" style={{ padding: "9px 16px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 12.5, fontWeight: 600, textDecoration: "none" }}>
                        Add saved candidates
                      </Link>
                      <Link data-testid="pool-empty-search" href="/recruiters/search" style={{ padding: "9px 16px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.inkSoft, fontSize: 12.5, fontWeight: 600, textDecoration: "none" }}>
                        Search candidates
                      </Link>
                    </div>
                  )
                }
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
                  selected={selected.includes(entry.student_user_id)}
                  selectable={canSelectMore}
                  onToggleSelect={toggleSelect}
                  tagVocabulary={tagVocabulary}
                  onChanged={(updated) =>
                    setCandidates((current) =>
                      current.map((c) =>
                        c.student_user_id === updated.student_user_id ? updated : c,
                      ),
                    )
                  }
                  onRemoved={(studentUserId) => {
                    setCandidates((current) =>
                      current.filter((c) => c.student_user_id !== studentUserId),
                    )
                    setPoolTotal((n) => Math.max(0, n - 1))
                  }}
                />
              ))}
            </div>
          )}

          {/* Close matches are NOT results — a filter means what it says.
              They are offered separately, with the gap already named, so the
              recruiter widens deliberately instead of being handed a padded
              list. */}
          {closeCandidates.length > 0 && (
            <div data-testid="pool-close-section" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <button
                type="button"
                data-testid="pool-close-toggle"
                aria-expanded={closeOpen}
                onClick={() => setCloseOpen((v) => !v)}
                style={{
                  alignSelf: "flex-start",
                  padding: "8px 14px",
                  borderRadius: 8,
                  border: `1px solid ${TOKEN.line}`,
                  background: "#fff",
                  color: TOKEN.inkSoft,
                  fontSize: 12.5,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {closeOpen ? "Hide" : "Show"} {closeCandidates.length}{" "}
                {closeCandidates.length === 1 ? "candidate" : "candidates"} missing
                some of this evidence
              </button>
              {closeOpen && (
                <>
                  <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
                    These candidates did not satisfy every requirement, so they are
                    not results. What each is missing is named on their card —
                    missing VeriBridge evidence is not evidence of missing ability.
                  </p>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 340px), 1fr))",
                      gap: 14,
                      alignItems: "stretch",
                    }}
                  >
                    {closeCandidates.map((entry) => (
                      <PoolCandidateCard
                        key={entry.student_user_id}
                        poolId={poolId}
                        entry={entry}
                        selected={selected.includes(entry.student_user_id)}
                        selectable={canSelectMore}
                        onToggleSelect={toggleSelect}
                        tagVocabulary={tagVocabulary}
                        onChanged={(updated) =>
                          setCloseCandidates((current) =>
                            current.map((c) =>
                              c.student_user_id === updated.student_user_id ? updated : c,
                            ),
                          )
                        }
                        onRemoved={(studentUserId) => {
                          setCloseCandidates((current) =>
                            current.filter((c) => c.student_user_id !== studentUserId),
                          )
                          setPoolTotal((n) => Math.max(0, n - 1))
                        }}
                      />
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
