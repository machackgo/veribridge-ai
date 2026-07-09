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
  fetchProofArtifactObjectUrl,
  getVBRSessionTranscript,
  getVideoProofTranscript,
  isSafePublicUrl,
  listVideoProofFrames,
  listWebsiteProofFrames,
  type SafeVisualFrameDescriptor,
  type SkillReport,
  type SkillReportProjectChain,
  type SkillReportVideoProofCard,
  type VBRTranscriptSegment,
  type VideoProofFrameDescriptor,
  type VideoProofTranscriptSegment,
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

// ── Document — retained-original viewer ────────────────────────────────────────

const _ACTION_BUTTON_STYLE: React.CSSProperties = {
  alignSelf: "flex-start",
  fontSize: 12,
  fontWeight: 600,
  color: TOKEN.indigo,
  background: TOKEN.indigoSoft,
  border: "none",
  borderRadius: 6,
  padding: "6px 12px",
  cursor: "pointer",
}

/**
 * Opens a RETAINED original document through the access-gated artifact route.
 * The bytes stream into a local object URL that opens in a new tab — no storage
 * path or signed URL ever reaches the DOM, and the backend re-checks access per
 * request (an owner-only artifact 404s for anyone else). Fails soft to an
 * honest note — never a broken link.
 */
export function DocumentOriginalViewer({ artifactId }: { artifactId: string }) {
  const [phase, setPhase] = useState<"idle" | "loading" | "opened" | "error">("idle")
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [])

  const open = async () => {
    setPhase("loading")
    const objectUrl = await fetchProofArtifactObjectUrl(artifactId)
    if (!objectUrl) {
      setPhase("error")
      return
    }
    urlRef.current = objectUrl
    window.open(objectUrl, "_blank", "noopener")
    setPhase("opened")
  }

  if (phase === "error") {
    return (
      <span
        data-testid="document-original-unavailable"
        style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
      >
        The original document could not be loaded right now.
      </span>
    )
  }
  return (
    <button
      type="button"
      data-testid="document-original-view-button"
      onClick={open}
      disabled={phase === "loading"}
      style={{ ..._ACTION_BUTTON_STYLE, opacity: phase === "loading" ? 0.6 : 1 }}
    >
      {phase === "loading" ? "Opening document…" : "View original document"}
    </button>
  )
}

// ── Video Proof — replay / transcript / frames access block ───────────────────

/** Format seconds as m:ss for transcript rows. */
function fmtSeconds(s: number): string {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`
}

/**
 * Owner (or shared) playback of the RETAINED demo video: streamed through the
 * gated artifact route into a local object URL for a <video> element — never a
 * storage path or signed URL in the DOM. Fails soft to an honest note.
 */
function VideoProofPlayer({ artifactId }: { artifactId: string }) {
  const [phase, setPhase] = useState<"idle" | "loading" | "playing" | "error">("idle")
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [])

  const load = async () => {
    setPhase("loading")
    const url = await fetchProofArtifactObjectUrl(artifactId)
    if (!url) {
      setPhase("error")
      return
    }
    urlRef.current = url
    setObjectUrl(url)
    setPhase("playing")
  }

  if (phase === "idle" || phase === "loading") {
    return (
      <button
        type="button"
        data-testid="video-proof-play-button"
        onClick={load}
        disabled={phase === "loading"}
        style={{ ..._ACTION_BUTTON_STYLE, opacity: phase === "loading" ? 0.6 : 1 }}
      >
        {phase === "loading" ? "Loading video…" : "Play video proof"}
      </button>
    )
  }
  if (phase === "error" || !objectUrl) {
    return (
      <span
        data-testid="video-proof-player-unavailable"
        style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
      >
        The video could not be loaded right now.
      </span>
    )
  }
  return (
    <video
      data-testid="video-proof-player"
      src={objectUrl}
      controls
      style={{ width: "100%", maxWidth: 420, borderRadius: 8, border: `1px solid ${TOKEN.line}` }}
    />
  )
}

/** Lazy timestamped narration transcript viewer for one Video Proof. */
function VideoProofTranscriptViewer({ proofId }: { proofId: string }) {
  const [phase, setPhase] = useState<"idle" | "loading" | "loaded" | "empty" | "error">("idle")
  const [segments, setSegments] = useState<VideoProofTranscriptSegment[]>([])

  const load = async () => {
    setPhase("loading")
    try {
      const transcript = await getVideoProofTranscript(proofId)
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
      <button type="button" data-testid="video-proof-transcript-button" onClick={load} style={_ACTION_BUTTON_STYLE}>
        View transcript
      </button>
    )
  }
  if (phase === "loading") {
    return (
      <span data-testid="video-proof-transcript-loading" style={{ fontSize: 11, color: TOKEN.muted }}>
        Loading transcript…
      </span>
    )
  }
  if (phase === "error" || phase === "empty") {
    return (
      <span
        data-testid="video-proof-transcript-unavailable"
        style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
      >
        {phase === "error"
          ? "The video transcript could not be loaded right now."
          : "No transcript text is stored for this video."}
      </span>
    )
  }
  return (
    <div
      data-testid="video-proof-transcript-viewer"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        maxHeight: 220,
        overflowY: "auto",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        padding: "8px 10px",
        background: "#fff",
      }}
    >
      {segments.map((seg, i) => (
        <div key={`${seg.seq}-${i}`} data-testid="video-proof-transcript-segment" style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
          <Mono style={{ fontSize: 10, color: TOKEN.muted, whiteSpace: "nowrap" }}>{fmtSeconds(seg.start_s)}</Mono>
          <span style={{ fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.5 }}>{seg.text}</span>
        </div>
      ))}
      <p style={{ fontSize: 10, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        Narration transcript extracted from the demo video&rsquo;s audio track.
      </p>
    </div>
  )
}

const MAX_VIDEO_PROOF_FRAMES = 8

type VideoProofGalleryFrame = VideoProofFrameDescriptor & { objectUrl: string }

/** Lazy gallery of the frames extracted from one Video Proof — streamed through
 * the gated artifact route into object URLs; no paths/signed URLs in the DOM. */
function VideoProofFramesGallery({ proofId }: { proofId: string }) {
  const [phase, setPhase] = useState<"idle" | "loading" | "loaded" | "empty" | "error">("idle")
  const [frames, setFrames] = useState<VideoProofGalleryFrame[]>([])
  const urlsRef = useRef<string[]>([])

  useEffect(() => {
    const urls = urlsRef.current
    return () => {
      for (const url of urls) URL.revokeObjectURL(url)
    }
  }, [])

  const load = async () => {
    setPhase("loading")
    try {
      const listing = await listVideoProofFrames(proofId)
      const viewable = (listing.frames ?? []).filter((f) => f.frame_artifact_id).slice(0, MAX_VIDEO_PROOF_FRAMES)
      const resolved: VideoProofGalleryFrame[] = []
      for (const frame of viewable) {
        const objectUrl = await fetchProofArtifactObjectUrl(frame.frame_artifact_id as string)
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
      <button type="button" data-testid="video-proof-frames-button" onClick={load} style={_ACTION_BUTTON_STYLE}>
        View captured frames
      </button>
    )
  }
  if (phase === "loading") {
    return (
      <span data-testid="video-proof-frames-loading" style={{ fontSize: 11, color: TOKEN.muted }}>
        Loading captured frames…
      </span>
    )
  }
  if (phase === "error" || phase === "empty") {
    return (
      <span
        data-testid="video-proof-frames-unavailable"
        style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
      >
        {phase === "error"
          ? "Captured frames could not be loaded right now."
          : "No viewable frames were stored for this video."}
      </span>
    )
  }
  return (
    <div data-testid="video-proof-frames-gallery" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {frames.map((frame) => (
        <figure
          key={frame.frame_id}
          data-testid="video-proof-frame"
          style={{ margin: 0, display: "flex", flexDirection: "column", gap: 2, alignItems: "center" }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- authorized blob object URL, not a remote asset */}
          <img
            src={frame.objectUrl}
            alt={`Video proof frame${frame.timestamp_label ? ` at ${frame.timestamp_label}` : ""}`}
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

/**
 * The full access block for ONE Video Proof: honest availability chips, the
 * deterministic demo summary + proof-strength wording, then ONLY the real
 * affordances — player when a replay is retained, transcript viewer when
 * narration was extracted, frames gallery when frames exist. Non-owner
 * surfaces render actions only when the owner shared the proof (public_safe);
 * the backend still re-checks access on every byte served.
 */
export function VideoProofAccessBlock({
  proof,
  ownerSurface = false,
}: {
  proof: SkillReportVideoProofCard
  ownerSurface?: boolean
}) {
  const actionsAllowed = ownerSurface || proof.public_safe
  return (
    <div
      data-testid="video-proof-access-block"
      data-proof-id={proof.proof_id}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "8px 10px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: TOKEN.bg,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: TOKEN.ink }}>{proof.title}</span>
        <Badge tone="slate">{proof.source_kind_label}</Badge>
        {proof.duration_label && <Mono style={{ fontSize: 10, color: TOKEN.muted }}>{proof.duration_label}</Mono>}
        {proof.replay_available && (
          <span data-testid="video-proof-availability-chip" data-kind="replay">
            <Badge tone="sky">Video replay available</Badge>
          </span>
        )}
        {proof.transcript_available && (
          <span data-testid="video-proof-availability-chip" data-kind="transcript">
            <Badge tone="sky">Transcript available</Badge>
          </span>
        )}
        {proof.frames_available && (
          <span data-testid="video-proof-availability-chip" data-kind="frames">
            <Badge tone="sky">Frames available</Badge>
          </span>
        )}
        {!proof.replay_available && !proof.transcript_available && !proof.frames_available && (
          <span data-testid="video-proof-availability-chip" data-kind="summary-only">
            <Badge tone="slate">Summary only</Badge>
          </span>
        )}
        {!proof.public_safe && !ownerSurface && (
          <span data-testid="video-proof-availability-chip" data-kind="not-public-safe">
            <Badge tone="slate">Not public-safe</Badge>
          </span>
        )}
        {proof.needs_review && <Badge tone="amber">Needs review</Badge>}
      </div>
      {proof.demo_summary && (
        <p style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{proof.demo_summary}</p>
      )}
      {proof.proof_strength_label && (
        <p style={{ fontSize: 10, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>{proof.proof_strength_label}</p>
      )}
      {actionsAllowed && proof.replay_available && proof.original_artifact_id && (
        <VideoProofPlayer artifactId={proof.original_artifact_id} />
      )}
      {actionsAllowed && proof.transcript_available && <VideoProofTranscriptViewer proofId={proof.proof_id} />}
      {actionsAllowed && proof.frames_available && <VideoProofFramesGallery proofId={proof.proof_id} />}
      {proof.limitations.length > 0 && (
        <p data-testid="video-proof-limitation" style={{ fontSize: 10, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          {proof.limitations[0]}
        </p>
      )}
    </div>
  )
}

// ── Per-chain access derivation (pure, fail-closed) ───────────────────────────

export type ChainAccessRow = {
  source: string
  state: OriginalAccessState
  note: string
}

/** Compact badge label for one access-row source. "Video Proof" stays
 * distinguishable from Project-Defense "Video Evidence" (both would
 * otherwise shorten to "Video"). */
function sourceBadgeLabel(source: string): string {
  if (source === "Video Proof") return "Demo Video"
  return source.replace(" Proof", "").replace(" Evidence", "")
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
        note:
          "Public live URL — recruiter can open the current deployment and verify runtime behaviour themselves. " +
          "Note: the live site may have changed since VeriBridge's recorded inspection.",
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

  // Document — three honest levels: retained & shared (original can be
  // opened via the gated document routes), retained privately (owner-only
  // original; recruiters keep excerpts), or not retained at all (legacy —
  // verified excerpts and locators are all that exists).
  const docs = chain.document_correlations ?? []
  if (docs.length > 0) {
    const downloadable = docs.some((d) => {
      const card = d.inspection_card
      if (!card?.can_download_document) return false
      return (
        (card.document_retained && Boolean(card.document_artifact_id)) ||
        isSafePublicUrl(card.document_download_url ?? card.document_open_url ?? null)
      )
    })
    const retained = docs.some((d) => d.document_retained || d.inspection_card?.document_retained)
    rows.push(
      downloadable
        ? {
            source: "Document Proof",
            state: "original_available",
            note:
              "The candidate shared the original document — it can be viewed or downloaded through " +
              "VeriBridge's access-gated document routes.",
          }
        : retained
          ? {
              source: "Document Proof",
              state: "excerpts_only",
              note:
                "The original document is retained privately (not shared for download); recruiters see " +
                "verified excerpts and locators.",
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

  // First-class Video Proofs (uploaded/recorded demo videos). Availability
  // flags come straight from the retained data — never inferred here.
  const videoProofRow = deriveVideoProofAccessRow(chain.video_proofs ?? [])
  if (videoProofRow) rows.push(videoProofRow)

  return rows
}

/**
 * The honest access row for a set of Video Proof cards — the best genuinely
 * available access level: replay > frames > transcript > summary only. The
 * note carries the finer recruiter-facing labels ("Video replay available",
 * "Frames only", "Transcript available"). Null when there are no cards.
 */
export function deriveVideoProofAccessRow(
  proofs: SkillReportVideoProofCard[],
): ChainAccessRow | null {
  if (proofs.length === 0) return null
  const hasReplay = proofs.some((v) => v.replay_available)
  const hasTranscript = proofs.some((v) => v.transcript_available)
  const hasFrames = proofs.some((v) => v.frames_available)
  if (hasReplay) {
    const extras = [
      hasTranscript ? "narration transcript" : null,
      hasFrames ? "captured frames" : null,
    ].filter(Boolean)
    return {
      source: "Video Proof",
      state: "recorded_evidence",
      note:
        "Video replay available — the retained demo video can be played through VeriBridge's gated access" +
        (extras.length > 0 ? `, with ${extras.join(" and ")}.` : ".") +
        " A demo video shows runtime behaviour and the candidate's explanation; it does not prove authorship.",
    }
  }
  if (hasFrames) {
    return {
      source: "Video Proof",
      state: "recorded_evidence",
      note:
        "Frames only — extracted visual frames from the demo video are available" +
        (hasTranscript ? ", with a narration transcript." : "; no replay is retained."),
    }
  }
  if (hasTranscript) {
    return {
      source: "Video Proof",
      state: "transcript_available",
      note: "Transcript available — the demo narration is inspectable; no replay or frames were retained.",
    }
  }
  return {
    source: "Video Proof",
    state: "no_original_access",
    note: "Summary only — no replay, transcript, or frames were retained for this demo video.",
  }
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
  // Retained-original document access: the owner can always open their own
  // retained original; a non-owner surface gets the viewer ONLY when the
  // candidate shared it (can_download). The artifact route re-checks access
  // on every request either way.
  const retainedDocArtifactId = (() => {
    for (const corr of chain.document_correlations ?? []) {
      const card = corr.inspection_card
      if (!card?.document_retained || !card.document_artifact_id) continue
      if (ownerSurface || card.can_download_document) return card.document_artifact_id
    }
    return null
  })()
  const videoProofs = chain.video_proofs ?? []

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
            <Badge tone="slate">{sourceBadgeLabel(row.source)}</Badge>
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
          {row.source === "Document Proof" && retainedDocArtifactId && (
            <DocumentOriginalViewer artifactId={retainedDocArtifactId} />
          )}
          {row.source === "Video Proof" &&
            videoProofs.map((proof) => (
              <VideoProofAccessBlock key={proof.proof_id} proof={proof} ownerSurface={ownerSurface} />
            ))}
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
    const downloadable = stdDocs.some((d) => {
      const card = d.inspection_card
      if (!card?.can_download_document) return false
      return (
        (card.document_retained && Boolean(card.document_artifact_id)) ||
        isSafePublicUrl(card.document_download_url ?? card.document_open_url ?? null)
      )
    })
    const retained = stdDocs.some((d) => d.document_retained || d.inspection_card?.document_retained)
    rows.push(
      downloadable
        ? {
            source: "Document Proof",
            state: "original_available",
            note: "The candidate shared the original document — it can be opened through gated document access.",
          }
        : retained
          ? {
              source: "Document Proof",
              state: "excerpts_only",
              note: "Original document retained privately (not shared) — verified excerpts and locators are shown.",
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

  // First-class Video Proofs — best chain row, else the standalone bucket.
  const videoProof = best("Video Proof")
  if (videoProof) rows.push(videoProof)
  else {
    const stdRow = deriveVideoProofAccessRow(std?.video_proofs ?? [])
    if (stdRow) rows.push(stdRow)
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
              {sourceBadgeLabel(row.source)}
            </span>
            <OriginalAccessBadge state={row.state} />
            <span style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>{row.note}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
