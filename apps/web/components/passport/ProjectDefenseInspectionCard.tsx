"use client"

import type { ProjectDefenseInspectionCard as ProjectDefenseInspectionCardData } from "@/lib/vbr-api"
import { Badge, Mono, TOKEN } from "./shared"

/**
 * Project Defense recruiter *inspection* card — the defense parallel to GitHub /
 * Website / Document inspection. It answers, for one defended question: what was
 * asked, what the student explained, which skill/project claim it supports, what
 * safe clip locator exists, what corroborates it, what it demonstrates, and —
 * conservatively — what it does NOT prove by itself.
 *
 * Framing rule: Project Defense is explanation / corroboration evidence. This
 * card never renders raw transcript, transcript segments, storage paths, signed
 * URLs, internal ids, or numeric confidence — it only shows the safe, derived
 * fields the backend already vetted. When a card is not public-safe the backend
 * sends a withheld placeholder (no answer text, no clip); this component renders
 * that neutral state instead of any answer content.
 */

const DEFAULT_LIMITATION =
  "Project Defense is explanation evidence. It should be read with GitHub Proof for implementation, " +
  "Website Proof for runtime behavior, and Document Proof for written project evidence."

/** Qualitative statuses that read as a genuine, targeted explanation. */
const EXPLAINED_STATUSES = new Set(["Explained with evidence", "Partially explained"])

/**
 * A URL is playable in a `<video>` element only when it is an ordinary http(s)
 * URL. This blocks `javascript:` / `blob:` / `data:` and bare storage keys — we
 * never inject a non-http string as a media source. The backend already returns
 * an authorized owner URL (or null); this is a defensive front-end gate.
 */
function isPlayableUrl(url: string | null | undefined): url is string {
  if (typeof url !== "string") return false
  const trimmed = url.trim()
  return /^https?:\/\//i.test(trimmed)
}

function badgeLabel(card: ProjectDefenseInspectionCardData): { label: string; tone: "indigo" | "amber" | "slate" } {
  const corroborates = card.corroborates_github || card.corroborates_website || card.corroborates_document
  if (corroborates) return { label: "Corroborating defense", tone: "indigo" }
  return { label: "Explanation evidence", tone: "amber" }
}

export function ProjectDefenseInspectionCard({
  card,
}: {
  card: ProjectDefenseInspectionCardData
}) {
  if (!card) return null

  const withheld = card.public_safe === false && Boolean(card.withheld_reason)
  const { label: badge, tone } = badgeLabel(card)
  const chips = (card.evidence_basis_chips || []).filter((c) => typeof c === "string" && c.trim())
  const corroborations: string[] = []
  if (card.corroborates_github) corroborations.push("GitHub")
  if (card.corroborates_website) corroborations.push("Website")
  if (card.corroborates_document) corroborations.push("Document")
  const explained = EXPLAINED_STATUSES.has(String(card.qualitative_status || ""))

  // Prefer a bounded clip URL (same signed source + #t media fragment); fall
  // back to the full recording. Only ever an http(s) URL reaches the element.
  const playbackUrl = isPlayableUrl(card.clip_playback_url)
    ? card.clip_playback_url
    : isPlayableUrl(card.video_playback_url)
      ? card.video_playback_url
      : null
  const recordingNote = card.recording_access_note
  const transcriptExcerpt =
    card.transcript_excerpt_available && card.safe_transcript_excerpt
      ? card.safe_transcript_excerpt
      : null
  const transcriptRange = [card.transcript_excerpt_start_label, card.transcript_excerpt_end_label]
    .filter((l) => typeof l === "string" && l.trim())
    .join(" – ")

  return (
    <div
      data-testid="project-defense-inspection-card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "12px 14px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 10,
        background: TOKEN.paper,
      }}
    >
      {/* Header + badge */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Project Defense inspection</h4>
        <Badge tone={tone}>{badge}</Badge>
        {card.mapped_skill && (
          <span data-testid="pdi-skill">
            <Badge tone="slate">{card.mapped_skill}</Badge>
          </span>
        )}
      </div>

      {withheld ? (
        <p data-testid="pdi-withheld" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          {card.withheld_reason}
        </p>
      ) : (
        <>
          {/* Defense question */}
          {card.question_text && (
            <div data-testid="pdi-question">
              <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: 0.4 }}>
                Defense question
              </span>
              <p style={{ fontSize: 13, color: TOKEN.ink, margin: "2px 0 0", lineHeight: 1.5 }}>{card.question_text}</p>
            </div>
          )}

          {/* Student answer summary */}
          {card.safe_answer_summary && (
            <div data-testid="pdi-answer-summary">
              <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: 0.4 }}>
                Student explained
              </span>
              <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5 }}>{card.safe_answer_summary}</p>
            </div>
          )}

          {/* Skill / project connection */}
          {(card.project_title || card.qualitative_status) && (
            <div data-testid="pdi-connection" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {card.qualitative_status && (
                <Badge tone={explained ? "emerald" : "slate"}>{card.qualitative_status}</Badge>
              )}
              {card.project_title && <span style={{ fontSize: 11, color: TOKEN.muted }}>Project: {card.project_title}</span>}
            </div>
          )}

          {/* Evidence basis chips */}
          {chips.length > 0 && (
            <div data-testid="pdi-basis-chips" style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {chips.map((chip, i) => (
                <Badge key={`${chip}-${i}`} tone="slate">
                  {chip}
                </Badge>
              ))}
            </div>
          )}

          {/* Timestamp / clip locator (safe locator only) */}
          {card.clip_available && card.timestamp_label && (
            <div data-testid="pdi-timestamp" style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <Mono style={{ fontSize: 11, color: TOKEN.indigo }}>⏱ {card.timestamp_label}</Mono>
              <span style={{ fontSize: 11, color: TOKEN.muted }}>defense clip locator</span>
            </div>
          )}

          {/* Recording / clip — a real player only with a safe owner URL */}
          <div data-testid="pdi-recording">
            <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: 0.4 }}>
              Recording / clip
            </span>
            {playbackUrl ? (
              <video
                data-testid="pdi-video"
                controls
                preload="metadata"
                src={playbackUrl}
                style={{ width: "100%", marginTop: 4, borderRadius: 8, background: "#000", maxHeight: 320 }}
              />
            ) : (
              recordingNote && (
                <p data-testid="pdi-recording-note" style={{ fontSize: 12, color: TOKEN.muted, margin: "2px 0 0", lineHeight: 1.5 }}>
                  {recordingNote}
                </p>
              )
            )}
          </div>

          {/* Transcript excerpt — bounded, sanitized snippet (never full dump) */}
          <div data-testid="pdi-transcript">
            <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: 0.4 }}>
              Transcript excerpt
              {transcriptRange && <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}> · {transcriptRange}</span>}
            </span>
            {transcriptExcerpt ? (
              <p
                data-testid="pdi-transcript-excerpt"
                style={{
                  fontSize: 12,
                  color: TOKEN.inkSoft,
                  margin: "2px 0 0",
                  lineHeight: 1.5,
                  borderLeft: `2px solid ${TOKEN.line}`,
                  paddingLeft: 8,
                  fontStyle: "italic",
                }}
              >
                “{transcriptExcerpt}”
              </p>
            ) : (
              card.transcript_access_note && (
                <p data-testid="pdi-transcript-note" style={{ fontSize: 12, color: TOKEN.muted, margin: "2px 0 0", lineHeight: 1.5 }}>
                  {card.transcript_access_note}
                </p>
              )
            )}
          </div>

          {/* Corroborates */}
          {corroborations.length > 0 && (
            <div data-testid="pdi-corroborates" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted }}>Corroborates:</span>
              {corroborations.map((c) => (
                <Badge key={c} tone="indigo">
                  {c}
                </Badge>
              ))}
            </div>
          )}
          {card.corroboration_summary && (
            <p style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{card.corroboration_summary}</p>
          )}

          {/* What this demonstrates */}
          {card.what_this_demonstrates && (
            <div data-testid="pdi-demonstrates">
              <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: 0.4 }}>
                What this demonstrates
              </span>
              <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: "2px 0 0", lineHeight: 1.5 }}>{card.what_this_demonstrates}</p>
            </div>
          )}
        </>
      )}

      {/* Limitation — always shown so the honest framing is never dropped */}
      <p data-testid="pdi-limitation" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        <strong style={{ color: TOKEN.inkSoft }}>Limitation: </strong>
        {card.limitation || DEFAULT_LIMITATION}
      </p>
    </div>
  )
}

/** A titled list of Project Defense inspection cards, or null when empty. */
export function ProjectDefenseInspectionSection({
  cards,
  testId = "project-defense-inspection",
}: {
  cards?: ProjectDefenseInspectionCardData[] | null
  testId?: string
}) {
  const list = (cards || []).filter(Boolean)
  if (list.length === 0) return null
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Project Defense inspection</h4>
      {list.map((card, i) => (
        <ProjectDefenseInspectionCard key={card.evidence_id_safe || `pdi-${i}`} card={card} />
      ))}
    </div>
  )
}
