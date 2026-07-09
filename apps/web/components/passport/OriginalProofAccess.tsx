"use client"

/**
 * Original Proof Access — the trust layer that answers, for every proof in a
 * Skill Report: can the recruiter independently inspect the ORIGINAL evidence
 * source, how, and — when they cannot — why not.
 *
 * Every state here is DERIVED from fields the payloads already carry; nothing
 * is inferred and nothing is ever faked:
 *
 *   • GitHub    — the repository / exact code lines are the original source
 *                 (links live on the evidence rows themselves).
 *   • Website   — a safe public live URL is directly verifiable; a local or
 *                 private runtime is honest "recorded evidence": VeriBridge
 *                 never retains the raw workflow video, so the owner can view
 *                 the captured evidence FRAMES (streamed through the
 *                 visibility-gated thumbnail proxy — no storage paths or signed
 *                 URLs ever reach the DOM).
 *   • Document  — VeriBridge does not retain the original file after analysis;
 *                 verified excerpts and locators are the honest access level
 *                 (a download appears ONLY when the backend gated it open).
 *   • Defense   — the candidate's own explanation: transcript excerpts and the
 *                 authorized recording player render on the inspection cards;
 *                 the owner can additionally open the full session transcript.
 *   • Video     — timestamped cited moments; playable only where an authorized
 *                 recording handle already exists (never fabricated here).
 *
 * Owner-only affordances (frames gallery, full transcript) render ONLY when
 * `ownerSurface` is true — public projections fail closed to labels.
 */

import { useEffect, useRef, useState } from "react"

import {
  fetchFrameThumbnailObjectUrl,
  getVBRSessionTranscript,
  isSafePublicUrl,
  listWebsiteProofFrames,
  type SafeVisualFrameDescriptor,
  type SkillReport,
  type SkillReportProjectChain,
  type VBRTranscriptSegment,
} from "@/lib/vbr-api"
import { Badge, Mono, TOKEN, type BadgeTone } from "./shared"

// ── Access states (closed vocabulary) ─────────────────────────────────────────

/** How much of the ORIGINAL proof a recruiter can reach. Closed set. */
export type OriginalAccessState =
  | "original_available" // the original source itself can be opened (repo, live URL, shared file)
  | "recorded_evidence" // VeriBridge-captured evidence (frames / recording) — not the original runtime
  | "transcript_available" // the candidate's own explanation is inspectable as a transcript
  | "excerpts_only" // verified excerpts + locators only (original not retained)
  | "no_original_access" // summary only — no original artifact is available

const ACCESS_SPEC: Record<OriginalAccessState, { label: string; tone: BadgeTone }> = {
  original_available: { label: "Original available", tone: "emerald" },
  recorded_evidence: { label: "Recorded evidence", tone: "sky" },
  transcript_available: { label: "Transcript available", tone: "sky" },
  excerpts_only: { label: "Verified excerpts only", tone: "slate" },
  no_original_access: { label: "No original access", tone: "slate" },
}

/** The calm chip for one access state. */
export function OriginalAccessBadge({ state }: { state: OriginalAccessState }) {
  const spec = ACCESS_SPEC[state]
  return (
    <span data-testid="original-access-badge" data-state={state}>
      <Badge tone={spec.tone}>{spec.label}</Badge>
    </span>
  )
}

// ── Section chrome ─────────────────────────────────────────────────────────────

/**
 * The compact "Original proof access" block: heading, state chip, one honest
 * caption, and optional inline actions (children). Never renders fake actions —
 * callers pass children only when a real artifact affordance exists.
 */
export function OriginalProofAccess({
  state,
  caption,
  children,
  testid = "original-proof-access",
}: {
  state: OriginalAccessState
  caption: string
  children?: React.ReactNode
  testid?: string
}) {
  return (
    <div
      data-testid={testid}
      data-state={state}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: "8px 10px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: TOKEN.bg,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Mono style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.14em" }}>
          Original proof access
        </Mono>
        <OriginalAccessBadge state={state} />
      </div>
      <p style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{caption}</p>
      {children}
    </div>
  )
}

// ── Website — owner frames gallery ─────────────────────────────────────────────

const MAX_GALLERY_FRAMES = 8

type GalleryFrame = SafeVisualFrameDescriptor & { objectUrl: string }

/**
 * Owner-only gallery of the evidence frames VeriBridge captured during a
 * Website Proof session. Loaded lazily on request; every image is streamed
 * through the authorized thumbnail proxy into a local object URL, so no signed
 * URL or storage path ever appears in the DOM. Fails soft to an honest note.
 */
export function WebsiteFramesGallery({ sessionId }: { sessionId: string }) {
  const [phase, setPhase] = useState<"idle" | "loading" | "loaded" | "empty" | "error">("idle")
  const [frames, setFrames] = useState<GalleryFrame[]>([])
  const urlsRef = useRef<string[]>([])

  // Revoke every minted object URL on unmount.
  useEffect(() => {
    const urls = urlsRef.current
    return () => {
      for (const url of urls) URL.revokeObjectURL(url)
    }
  }, [])

  const load = async () => {
    setPhase("loading")
    try {
      const listing = await listWebsiteProofFrames(sessionId)
      const viewable = (listing.frames ?? []).filter((f) => f.has_thumbnail).slice(0, MAX_GALLERY_FRAMES)
      const resolved: GalleryFrame[] = []
      for (const frame of viewable) {
        const objectUrl = await fetchFrameThumbnailObjectUrl(frame.frame_id)
        if (objectUrl) {
          urlsRef.current.push(objectUrl)
          resolved.push({ ...frame, objectUrl })
        }
      }
      if (resolved.length === 0) {
        setPhase("empty")
        return
      }
      setFrames(resolved)
      setPhase("loaded")
    } catch {
      setPhase("error")
    }
  }

  if (phase === "idle") {
    return (
      <button
        type="button"
        data-testid="website-frames-view-button"
        onClick={load}
        style={{
          alignSelf: "flex-start",
          fontSize: 12,
          fontWeight: 600,
          color: TOKEN.indigo,
          background: TOKEN.indigoSoft,
          border: "none",
          borderRadius: 6,
          padding: "6px 12px",
          cursor: "pointer",
        }}
      >
        View captured frames
      </button>
    )
  }
  if (phase === "loading") {
    return (
      <span data-testid="website-frames-loading" style={{ fontSize: 11, color: TOKEN.muted }}>
        Loading captured frames…
      </span>
    )
  }
  if (phase === "error" || phase === "empty") {
    return (
      <span data-testid="website-frames-unavailable" style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}>
        {phase === "error"
          ? "Captured frames could not be loaded right now."
          : "No viewable frames were stored for this session."}
      </span>
    )
  }
  return (
    <div data-testid="website-frames-gallery" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {frames.map((frame) => (
        <figure
          key={frame.frame_id}
          data-testid="website-frame"
          style={{ margin: 0, display: "flex", flexDirection: "column", gap: 2, alignItems: "center" }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- authorized blob object URL, not a remote asset */}
          <img
            src={frame.objectUrl}
            alt={`Captured evidence frame${frame.timestamp_label ? ` at ${frame.timestamp_label}` : ""}`}
            style={{ width: 148, borderRadius: 6, border: `1px solid ${TOKEN.line}`, display: "block" }}
          />
          {frame.timestamp_label && (
            <figcaption>
              <Mono style={{ fontSize: 10, color: TOKEN.muted }}>⏱ {frame.timestamp_label}</Mono>
            </figcaption>
          )}
        </figure>
      ))}
    </div>
  )
}

// ── Defense — owner full-transcript viewer ─────────────────────────────────────

/** Parse an "mm:ss" / "h:mm:ss" label to seconds; null when unparseable. */
function parseTimestampLabel(label?: string | null): number | null {
  if (!label) return null
  const parts = label
    .replace(/[^\d:]/g, "")
    .split(":")
    .filter(Boolean)
    .map(Number)
  if (parts.length === 0 || parts.some((n) => Number.isNaN(n))) return null
  return parts.reduce((total, part) => total * 60 + part, 0)
}

/**
 * Owner-only viewer for the full defense session transcript (the candidate's
 * own spoken explanation). Loaded lazily on request from the owner transcript
 * endpoint; segments whose time range covers a cited moment are highlighted so
 * the recruiter-relevant explanation is easy to find. Fails soft to an honest
 * note — never a fake transcript.
 */
export function DefenseTranscriptViewer({
  sessionId,
  citedTimestampLabels = [],
}: {
  sessionId: string
  citedTimestampLabels?: Array<string | null | undefined>
}) {
  const [phase, setPhase] = useState<"idle" | "loading" | "loaded" | "empty" | "error">("idle")
  const [segments, setSegments] = useState<VBRTranscriptSegment[]>([])

  const citedSeconds = citedTimestampLabels
    .map((label) => parseTimestampLabel(label))
    .filter((s): s is number => s !== null)

  const load = async () => {
    setPhase("loading")
    try {
      const transcript = await getVBRSessionTranscript(sessionId)
      const rows = (transcript.segments ?? []).filter((s) => (s.text ?? "").trim())
      if (rows.length === 0) {
        setPhase("empty")
        return
      }
      setSegments(rows)
      setPhase("loaded")
    } catch {
      setPhase("error")
    }
  }

  if (phase === "idle") {
    return (
      <button
        type="button"
        data-testid="defense-transcript-view-button"
        onClick={load}
        style={{
          alignSelf: "flex-start",
          fontSize: 12,
          fontWeight: 600,
          color: TOKEN.indigo,
          background: TOKEN.indigoSoft,
          border: "none",
          borderRadius: 6,
          padding: "6px 12px",
          cursor: "pointer",
        }}
      >
        View defense transcript
      </button>
    )
  }
  if (phase === "loading") {
    return (
      <span data-testid="defense-transcript-loading" style={{ fontSize: 11, color: TOKEN.muted }}>
        Loading transcript…
      </span>
    )
  }
  if (phase === "error" || phase === "empty") {
    return (
      <span
        data-testid="defense-transcript-unavailable"
        style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
      >
        {phase === "error"
          ? "The defense transcript could not be loaded right now."
          : "No transcript text is stored for this defense session."}
      </span>
    )
  }

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`
  return (
    <div
      data-testid="defense-transcript-viewer"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        maxHeight: 260,
        overflowY: "auto",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        padding: "8px 10px",
        background: "#fff",
      }}
    >
      {segments.map((seg, i) => {
        const cited = citedSeconds.some((s) => s >= seg.start_s && s <= seg.end_s)
        return (
          <div
            key={`${seg.start_s}-${i}`}
            data-testid="defense-transcript-segment"
            data-cited={cited ? "true" : "false"}
            style={{
              display: "flex",
              gap: 8,
              alignItems: "baseline",
              background: cited ? TOKEN.indigoSoft : "transparent",
              borderRadius: 4,
              padding: cited ? "2px 4px" : 0,
            }}
          >
            <Mono style={{ fontSize: 10, color: cited ? TOKEN.indigo : TOKEN.muted, whiteSpace: "nowrap" }}>
              {fmt(seg.start_s)}
            </Mono>
            <span style={{ fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.5 }}>{seg.text}</span>
            {cited && (
              <span data-testid="defense-transcript-cited-chip">
                <Badge tone="indigo">Cited</Badge>
              </span>
            )}
          </div>
        )
      })}
      <p style={{ fontSize: 10, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        Transcript shows the candidate&rsquo;s own explanation, captured by VeriBridge during the
        Project Defense.
      </p>
    </div>
  )
}

// ── Per-chain access derivation (pure, fail-closed) ───────────────────────────

export type ChainAccessRow = {
  source: string
  state: OriginalAccessState
  note: string
}

function itemsHaveSafeUrl(items: Array<{ public_url?: string | null }> | undefined): boolean {
  return (items ?? []).some((it) => isSafePublicUrl(it.public_url ?? null))
}

/**
 * Derive one honest access row per proof source present in a chain — built ONLY
 * from availability fields the payload already carries. A source absent from
 * the chain yields no row; nothing is guessed.
 */
export function deriveChainAccessRows(chain: SkillReportProjectChain): ChainAccessRow[] {
  const rows: ChainAccessRow[] = []

  // GitHub — links render on the evidence rows; this row states the access level.
  const ghRows = [
    ...(chain.github_evidence ?? []),
    ...(chain.github_groups ?? []).flatMap((g) => g.rows ?? []),
  ]
  if (ghRows.length > 0) {
    const hasLine = ghRows.some((r) => Boolean((r as { github_line_url?: string | null }).github_line_url))
    const hasRepo =
      hasLine ||
      itemsHaveSafeUrl(ghRows as Array<{ public_url?: string | null }>) ||
      (chain.github_groups ?? []).some((g) => Boolean(g.repo_url)) ||
      (chain.github_evidence ?? []).some((r) => Boolean(r.repo_url))
    rows.push(
      hasRepo
        ? {
            source: "GitHub Proof",
            state: "original_available",
            note: hasLine
              ? "Recruiter can open the repository and the exact code lines cited above."
              : "Recruiter can open the repository cited above.",
          }
        : {
            source: "GitHub Proof",
            state: "no_original_access",
            note: "No public repository link is available for this code evidence.",
          },
    )
  }

  // Website — live URL vs recorded frames vs summary only.
  const webItems = chain.website_evidence ?? []
  if (webItems.length > 0) {
    const cards = webItems.map((it) => it.website_evidence_card).filter(Boolean)
    const hasLive =
      cards.some((c) => c!.is_public_live_url || isSafePublicUrl(c!.open_website_url ?? c!.target_url_safe ?? null)) ||
      itemsHaveSafeUrl(webItems)
    const hasFrames = cards.some((c) => c!.screenshot_available)
    if (hasLive) {
      rows.push({
        source: "Website Proof",
        state: "original_available",
        note: "Public live URL — recruiter can open the current deployment and verify runtime behaviour themselves.",
      })
    } else if (hasFrames) {
      rows.push({
        source: "Website Proof",
        state: "recorded_evidence",
        note:
          "This was captured from a local/private runtime, so the original URL cannot be opened. " +
          "Recruiter can review the workflow frames VeriBridge captured during inspection.",
      })
    } else {
      rows.push({
        source: "Website Proof",
        state: "no_original_access",
        note: "Local/private runtime and no captured frames were stored — only the recorded summary above is available.",
      })
    }
  }

  // Document — the original file is not retained after analysis (privacy
  // feature); a download exists only when the backend explicitly gated it open.
  const docs = chain.document_correlations ?? []
  if (docs.length > 0) {
    const downloadable = docs.some(
      (d) =>
        d.inspection_card?.can_download_document &&
        isSafePublicUrl(d.inspection_card.document_download_url ?? d.inspection_card.document_open_url ?? null),
    )
    rows.push(
      downloadable
        ? {
            source: "Document Proof",
            state: "original_available",
            note: "The candidate shared the original document for recruiter review — see the document card above.",
          }
        : {
            source: "Document Proof",
            state: "excerpts_only",
            note:
              "Original document was not retained after analysis; VeriBridge stores verified excerpts and locators.",
          },
    )
  }

  // Defense / video — the candidate's own explanation. Recording playback and
  // transcript excerpts render on the inspection cards when authorized.
  const inspection = chain.project_defense_inspection ?? []
  const hasDefense =
    (chain.defense_group?.grouped_count ?? 0) > 0 ||
    (chain.defense_evidence?.length ?? 0) > 0 ||
    inspection.length > 0
  if (hasDefense) {
    const hasRecording = inspection.some((c) => c.video_available)
    const hasTranscript =
      inspection.some((c) => c.transcript_excerpt_available) ||
      (chain.defense_group?.moments?.length ?? 0) > 0 ||
      (chain.defense_evidence ?? []).some((it) => it.answer_excerpt)
    if (hasRecording) {
      rows.push({
        source: "Project Defense",
        state: "recorded_evidence",
        note: "Defense recording and transcript excerpts are available — the candidate's own explanation is inspectable.",
      })
    } else if (hasTranscript) {
      rows.push({
        source: "Project Defense",
        state: "transcript_available",
        note: "Transcript shows the candidate's explanation for this skill; no recording playback from this view.",
      })
    } else {
      rows.push({
        source: "Project Defense",
        state: "no_original_access",
        note: "Only the summarized defense observations above are available.",
      })
    }
  }

  // Video evidence — timestamped cited moments into the same defense recording.
  const videoItems = chain.video_evidence ?? []
  if (videoItems.length > 0 && !hasDefense) {
    const hasTimestamps = videoItems.some((it) => it.timestamp_label)
    rows.push(
      hasTimestamps
        ? {
            source: "Video Evidence",
            state: "recorded_evidence",
            note: "Timestamped video moments are cited above, captured by VeriBridge during the recorded session.",
          }
        : {
            source: "Video Evidence",
            state: "no_original_access",
            note: "Only summarized video observations are available — no timestamped segments were stored.",
          },
    )
  }

  return rows
}

/** First defense-session id a chain's payload names (for the owner transcript). */
export function chainDefenseSessionId(chain: SkillReportProjectChain): string | null {
  const fromGroup = chain.defense_group?.source_ids?.[0] ?? chain.defense_group?.moments?.[0]?.source_id
  if (fromGroup) return fromGroup
  const fromEvidence = (chain.defense_evidence ?? [])[0]?.source_id ?? (chain.video_evidence ?? [])[0]?.source_id
  return fromEvidence || null
}

/** First website-proof session id (source_id) in a chain without a live URL. */
function chainRecordedWebsiteSessionId(chain: SkillReportProjectChain): string | null {
  for (const item of chain.website_evidence ?? []) {
    const card = item.website_evidence_card
    const live =
      (card && (card.is_public_live_url || isSafePublicUrl(card.open_website_url ?? card.target_url_safe ?? null))) ||
      isSafePublicUrl(item.public_url ?? null)
    const hasFrames = card ? card.screenshot_available : false
    if (!live && hasFrames && item.source_id) return item.source_id
  }
  return null
}

/**
 * The per-chain "Original proof access" strip: one honest row per proof source
 * in the chain, plus the owner-only artifacts that make the access real — the
 * captured-frames gallery for a recorded-only website proof and the full
 * defense transcript viewer. Renders nothing when the chain names no source.
 */
export function ChainOriginalProofAccess({
  chain,
  ownerSurface = false,
}: {
  chain: SkillReportProjectChain
  ownerSurface?: boolean
}) {
  const rows = deriveChainAccessRows(chain)
  if (rows.length === 0) return null

  const recordedWebsiteSessionId = ownerSurface ? chainRecordedWebsiteSessionId(chain) : null
  const defenseSessionId = ownerSurface ? chainDefenseSessionId(chain) : null
  const citedLabels = [
    ...(chain.defense_group?.moments ?? []).map((m) => m.timestamp_label),
    ...(chain.defense_evidence ?? []).map((it) => it.timestamp_label),
    ...(chain.video_evidence ?? []).map((it) => it.timestamp_label),
  ]

  return (
    <div data-testid="chain-original-proof-access" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Mono style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.14em" }}>
          Original proof access
        </Mono>
      </div>
      {rows.map((row) => (
        <div
          key={row.source}
          data-testid="original-access-row"
          data-source={row.source}
          data-state={row.state}
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <Badge tone="slate">{row.source.replace(" Proof", "").replace(" Evidence", "")}</Badge>
            <OriginalAccessBadge state={row.state} />
          </div>
          <p style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{row.note}</p>
          {row.source === "Website Proof" && row.state === "recorded_evidence" && recordedWebsiteSessionId && (
            <WebsiteFramesGallery sessionId={recordedWebsiteSessionId} />
          )}
          {row.source === "Project Defense" &&
            (row.state === "transcript_available" || row.state === "recorded_evidence") &&
            defenseSessionId && (
              <DefenseTranscriptViewer sessionId={defenseSessionId} citedTimestampLabels={citedLabels} />
            )}
        </div>
      ))}
    </div>
  )
}

// ── Report-level recruiter verification access summary ────────────────────────

export type VerificationAccessRow = {
  source: string
  state: OriginalAccessState
  note: string
}

/**
 * Derive the report-level "Recruiter verification access" rows: for each proof
 * source that actually appears in the report (direct chains or vault), the best
 * honest access level a recruiter gets. Pure and fail-closed — a source with no
 * evidence yields no row, and nothing upgrades beyond what the payload carries.
 */
export function deriveVerificationAccessRows(report: SkillReport): VerificationAccessRow[] {
  const chains = report.proof_chains ?? report.projects ?? []
  const std = report.standalone_evidence

  const chainRowsBySource = new Map<string, ChainAccessRow[]>()
  for (const chain of chains) {
    for (const row of deriveChainAccessRows(chain)) {
      const list = chainRowsBySource.get(row.source) ?? []
      list.push(row)
      chainRowsBySource.set(row.source, list)
    }
  }

  // Rank: the report-level row shows the BEST access any chain provides.
  const rank: Record<OriginalAccessState, number> = {
    original_available: 4,
    recorded_evidence: 3,
    transcript_available: 3,
    excerpts_only: 2,
    no_original_access: 1,
  }
  const best = (source: string): ChainAccessRow | null => {
    const list = chainRowsBySource.get(source) ?? []
    if (list.length === 0) return null
    return list.reduce((a, b) => (rank[b.state] > rank[a.state] ? b : a))
  }

  const rows: VerificationAccessRow[] = []

  const gh = best("GitHub Proof")
  const stdGh = (std?.github?.length ?? 0) > 0 || (std?.github_groups?.length ?? 0) > 0
  if (gh) rows.push(gh)
  else if (stdGh) {
    const stdRows = [...(std?.github ?? []), ...((std?.github_groups ?? []).flatMap((g) => g.rows ?? []))]
    const hasLink =
      stdRows.some((r) => Boolean((r as { github_line_url?: string | null }).github_line_url)) ||
      itemsHaveSafeUrl(stdRows as Array<{ public_url?: string | null }>) ||
      (std?.github_groups ?? []).some((g) => Boolean(g.repo_url))
    rows.push({
      source: "GitHub Proof",
      state: hasLink ? "original_available" : "no_original_access",
      note: hasLink
        ? "Repository / exact code lines can be opened on GitHub."
        : "No public repository link is available.",
    })
  }

  const web = best("Website Proof")
  const stdWeb = std?.website ?? []
  if (web) rows.push(web)
  else if (stdWeb.length > 0) {
    const hasLive =
      stdWeb.some((it) => {
        const card = it.website_evidence_card
        return (
          (card && (card.is_public_live_url || isSafePublicUrl(card.open_website_url ?? card.target_url_safe ?? null))) ||
          isSafePublicUrl(it.public_url ?? null)
        )
      })
    const hasFrames = stdWeb.some((it) => it.website_evidence_card?.screenshot_available)
    rows.push(
      hasLive
        ? {
            source: "Website Proof",
            state: "original_available",
            note: "Public live URL — the current deployment can be opened and inspected.",
          }
        : hasFrames
          ? {
              source: "Website Proof",
              state: "recorded_evidence",
              note: "Local/private runtime — VeriBridge-captured workflow frames are available.",
            }
          : {
              source: "Website Proof",
              state: "no_original_access",
              note: "Recorded summary only — no original URL or captured frames.",
            },
    )
  }

  const doc = best("Document Proof")
  const stdDocs = std?.documents ?? []
  if (doc) rows.push(doc)
  else if (stdDocs.length > 0) {
    const downloadable = stdDocs.some(
      (d) =>
        d.inspection_card?.can_download_document &&
        isSafePublicUrl(d.inspection_card.document_download_url ?? d.inspection_card.document_open_url ?? null),
    )
    rows.push(
      downloadable
        ? {
            source: "Document Proof",
            state: "original_available",
            note: "The candidate shared the original document for recruiter review.",
          }
        : {
            source: "Document Proof",
            state: "excerpts_only",
            note: "Original file not retained after analysis — verified excerpts and locators are shown.",
          },
    )
  }

  const defense = best("Project Defense")
  const stdDefense = std?.defense ?? []
  if (defense) rows.push(defense)
  else if (stdDefense.length > 0) {
    rows.push({
      source: "Project Defense",
      state: stdDefense.some((it) => it.answer_excerpt) ? "transcript_available" : "no_original_access",
      note: stdDefense.some((it) => it.answer_excerpt)
        ? "Transcript excerpts of the candidate's explanation are available."
        : "Only summarized defense observations are available.",
    })
  }

  const video = best("Video Evidence")
  const stdVideo = std?.video ?? []
  if (video) rows.push(video)
  else if (stdVideo.length > 0) {
    const hasTimestamps = stdVideo.some((it) => it.timestamp_label)
    rows.push({
      source: "Video Evidence",
      state: hasTimestamps ? "recorded_evidence" : "no_original_access",
      note: hasTimestamps
        ? "Timestamped video moments are cited in the evidence."
        : "Only summarized video observations are available.",
    })
  }

  return rows
}

/**
 * The report-level "Recruiter verification access" panel rendered near the
 * Evidence Thesis: one honest line per proof source stating whether — and how —
 * the recruiter can reach the original evidence. Generated ONLY from actual
 * availability; renders nothing when the report names no proof source.
 */
export function RecruiterVerificationAccessSummary({ report }: { report: SkillReport }) {
  const rows = deriveVerificationAccessRows(report)
  if (rows.length === 0) return null
  return (
    <div
      data-testid="recruiter-verification-access"
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      <h3
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: TOKEN.muted,
          margin: 0,
          textTransform: "uppercase",
          letterSpacing: 0.5,
        }}
      >
        Recruiter verification access
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.map((row) => (
          <div
            key={row.source}
            data-testid="verification-access-row"
            data-source={row.source}
            data-state={row.state}
            style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}
          >
            <span style={{ fontSize: 12, fontWeight: 600, color: TOKEN.ink, minWidth: 74 }}>
              {row.source.replace(" Proof", "").replace(" Evidence", "")}
            </span>
            <OriginalAccessBadge state={row.state} />
            <span style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>{row.note}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
