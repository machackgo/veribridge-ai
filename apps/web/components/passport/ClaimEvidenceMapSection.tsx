"use client"

import { useState } from "react"

import { fetchAPI } from "@/lib/api"
import type {
  CanonicalAccessDescriptor,
  CanonicalContradiction,
  CanonicalCorroborationGroup,
  CanonicalEvidenceCitation,
  CanonicalEvidenceGap,
  CanonicalSkillClaim,
  CanonicalSourceCounts,
  ClaimEvidenceMap,
} from "@/lib/vbr-api"

import { useAuthorizedMediaUrl } from "./AuthorizedReplayVideo"
import { ATTRIBUTION_STATE_TONE, CandidateAttributionBanner } from "./CandidateAttributionBanner"
import { Badge, TOKEN, type BadgeTone } from "./shared"

/**
 * Canonical claim→evidence map renderer — shared verbatim by the Skill Report
 * and the Project Report. It renders EXACTLY what the backend synthesized:
 * every relationship (implementation tier, website↔project identity,
 * corroboration, pending/mismatch states) comes from the payload. This
 * component never infers a relationship, invents a locator, or counts
 * evidence the backend flagged as not counted.
 */

const STATUS_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  Corroborated: "emerald",
  "Partially demonstrated": "sky",
  "Context only": "slate",
  "Analysis pending": "amber",
  "Mismatch detected": "rose",
  "Insufficient evidence": "slate",
  "Not assessed": "slate",
}

const PROOF_ORDER = ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense", "Video Evidence"]

function locatorLine(c: CanonicalEvidenceCitation): string | null {
  if (c.file_path) {
    const lines = c.start_line ? ` · L${c.start_line}${c.end_line ? `–L${c.end_line}` : ""}` : ""
    const symbol = c.symbol_name ? ` · ${c.symbol_name}()` : ""
    const commit = c.commit_sha ? ` · ${c.commit_sha.slice(0, 10)}` : ""
    return `${c.file_path}${lines}${symbol}${commit}`
  }
  if (c.page_number || c.section_title) {
    const page = c.page_number ? `Page ${c.page_number}` : null
    return [page, c.section_title, c.figure_or_table].filter(Boolean).join(" · ")
  }
  if (c.timestamp_start_label) {
    return `${c.timestamp_start_label}${c.timestamp_end_label ? `–${c.timestamp_end_label}` : ""}`
  }
  return c.route_or_page ?? c.source_locator ?? null
}

/** Honest per-bucket source counts — distinct proof types, never row counts.
 *  Rendered verbatim from the backend synthesis; zero buckets are omitted. */
function SourceCountsRow({ counts }: { counts?: CanonicalSourceCounts }) {
  if (!counts) return null
  const rows: { key: string; label: string; value: number; sources: string[]; tone: BadgeTone }[] = [
    { key: "direct", label: "Direct evidence sources", value: counts.direct, sources: counts.direct_sources, tone: "emerald" },
    { key: "corroborating", label: "Corroborating sources", value: counts.corroborating, sources: counts.corroborating_sources, tone: "sky" },
    { key: "context", label: "Context-only sources", value: counts.context_only, sources: counts.context_only_sources, tone: "slate" },
    { key: "pending", label: "Pending sources", value: counts.pending, sources: counts.pending_sources, tone: "amber" },
    { key: "vault", label: "Vault-only sources", value: counts.vault_only, sources: counts.vault_only_sources, tone: "slate" },
    { key: "unsupported", label: "Unsupported sources", value: counts.unsupported, sources: counts.unsupported_sources, tone: "rose" },
  ]
  const present = rows.filter((r) => r.value > 0)
  if (present.length === 0) return null
  return (
    <div data-testid="cem-source-counts" style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      {present.map((r) => (
        <span key={r.key} data-testid={`cem-count-${r.key}`} data-count={r.value} title={r.sources.join(", ")} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          <Badge tone={r.tone}>{r.label}: {r.value}</Badge>
          <span style={{ fontSize: 10, color: TOKEN.muted }}>{r.sources.join(" · ")}</span>
        </span>
      ))}
    </div>
  )
}

function CountFlag({ c }: { c: CanonicalEvidenceCitation }) {
  if (c.duplicate_of_evidence_id) {
    return <Badge tone="slate">Citation into the same defense recording — not a separate source</Badge>
  }
  if (c.project_relationship?.state === "mismatched_project") {
    return <Badge tone="rose">Mismatched project — not counted</Badge>
  }
  if (c.project_relationship?.state === "suggested_match") {
    return <Badge tone="amber">Suggested match — not counted</Badge>
  }
  if (c.project_relationship?.state === "vault_only") {
    return <Badge tone="slate">Vault-only — not counted</Badge>
  }
  if (c.project_relationship?.state === "legacy_unresolved") {
    return <Badge tone="slate">Legacy unresolved — not counted</Badge>
  }
  if (c.identity_state === "mismatched") {
    return <Badge tone="rose">Mismatch — not counted</Badge>
  }
  if (c.analysis_pending) {
    return <Badge tone="amber">Analysis pending — not counted</Badge>
  }
  if (c.counted_as_direct_evidence) {
    return <Badge tone="emerald">Counted as direct evidence</Badge>
  }
  if (c.identity_state === "possible_match_review") {
    return <Badge tone="amber">Needs review — not counted</Badge>
  }
  return <Badge tone="slate">Context only — not counted</Badge>
}

function VideoBlock({ c }: { c: CanonicalEvidenceCitation }) {
  const v = c.video
  // Owner-gated API replay routes are streamed with the caller's session and
  // played from a local object URL; public absolute URLs pass through as-is.
  const playbackUrl = useAuthorizedMediaUrl(
    v?.access?.available && v?.access?.url ? v.access.url : null,
  )
  if (!v) return null
  return (
    <div
      data-testid="cem-video"
      data-availability={v.availability}
      style={{ display: "flex", flexDirection: "column", gap: 5, padding: 8, borderRadius: 8, background: TOKEN.bg, border: `1px solid ${TOKEN.line}` }}
    >
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone={v.recording_available ? "emerald" : "slate"}>
          {v.recording_available ? "Recording retained" : v.availability === "pending" ? "Recording pending" : "Recording not retained"}
        </Badge>
        {v.duration_label && <span style={{ fontSize: 11, color: TOKEN.muted }}>{v.duration_label}</span>}
        {v.transcript_available && <Badge tone="sky">Transcript available</Badge>}
      </div>
      {v.access?.available && v.access?.url && v.recording_available && (
        // Bounded, backend-authorized playback URL — never a raw storage path.
        // The src fills in once the owner-gated stream resolves.
        <video data-testid="cem-video-player" controls preload="none" src={playbackUrl ?? undefined} style={{ width: "100%", maxHeight: 260, borderRadius: 6, background: "#000" }} />
      )}
      {v.cited_segments.length > 0 && (
        <ul data-testid="cem-video-segments" style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: TOKEN.inkSoft, display: "flex", flexDirection: "column", gap: 2 }}>
          {v.cited_segments.map((s, i) => (
            <li key={i}>
              <strong>{[s.start_label, s.end_label].filter(Boolean).join("–")}</strong> — {s.description}
            </li>
          ))}
        </ul>
      )}
      {v.timeline_events.length > 0 && (
        <ul data-testid="cem-video-timeline" style={{ margin: 0, paddingLeft: 16, fontSize: 11, color: TOKEN.muted, display: "flex", flexDirection: "column", gap: 2 }}>
          {v.timeline_events.map((e, i) => (
            <li key={i}>{e.timestamp_label ? `${e.timestamp_label} — ` : ""}{e.description}</li>
          ))}
        </ul>
      )}
      {v.limitations.map((lim, i) => (
        <p key={i} style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>{lim}</p>
      ))}
    </div>
  )
}

function DocumentBlock({ c }: { c: CanonicalEvidenceCitation }) {
  const block = c.document_block
  if (!block) return null
  const label = [
    "Document",
    block.page_number ? `page ${block.page_number}` : null,
    block.block_type.replaceAll("_", " "),
  ].filter(Boolean).join(" · ")
  return (
    <div
      data-testid="cem-document-block"
      data-block-type={block.block_type}
      style={{ display: "flex", flexDirection: "column", gap: 6, padding: 9, borderRadius: 8, background: TOKEN.bg, border: `1px solid ${TOKEN.line}` }}
    >
      <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.ink }}>[{label}]</span>
      {block.extracted_text && (
        <blockquote data-testid="cem-document-block-text" style={{ margin: 0, padding: "4px 9px", borderLeft: `2px solid ${TOKEN.line}`, fontSize: 12, color: TOKEN.inkSoft }}>
          {block.extracted_text}
        </blockquote>
      )}
      {block.table_cells.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table data-testid="cem-document-table" style={{ borderCollapse: "collapse", fontSize: 11, color: TOKEN.inkSoft, width: "100%" }}>
            <tbody>
              {block.table_cells.map((row, i) => (
                <tr key={i}>{row.map((cell, j) => <td key={j} style={{ border: `1px solid ${TOKEN.line}`, padding: "4px 6px" }}>{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {block.visual_description && <p style={{ margin: 0, fontSize: 12, color: TOKEN.inkSoft }}>{block.visual_description}</p>}
      {block.nearby_caption && <p style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>Context: {block.nearby_caption}</p>}
      <span style={{ fontSize: 10, color: TOKEN.muted }}>Extraction: {block.extraction_confidence.replaceAll("_", " ")}</span>
      {block.model_limitation && (
        <p data-testid="cem-document-block-limitation" style={{ margin: 0, fontSize: 11, color: "#92600a" }}>{block.model_limitation}</p>
      )}
    </div>
  )
}

/**
 * Owner-gated artifact action for a Bearer-gated `/api/…` access route
 * (document original open/download, cited-page open). A raw anchor can never
 * authorize against the API origin, so the bytes stream through `fetchAPI`
 * into a local object URL — the backend re-checks ownership per request, and
 * no gated route ever appears as an href in the DOM. Downloads save under the
 * document's ORIGINAL filename. Fails soft to an honest note — never a
 * broken link.
 */
function GatedArtifactAction({
  action,
  fileName,
}: {
  action: CanonicalAccessDescriptor
  fileName?: string | null
}) {
  const [phase, setPhase] = useState<"idle" | "loading" | "error">("idle")
  const isDownload = action.kind === "document_download"

  const run = async () => {
    setPhase("loading")
    try {
      const [path, hash] = (action.url ?? "").split("#")
      const res = await fetchAPI(path)
      if (!res.ok) throw new Error(String(res.status))
      const blob = await res.blob()
      if (!blob || blob.size === 0) throw new Error("empty")
      const objectUrl = URL.createObjectURL(blob)
      if (isDownload) {
        const anchor = document.createElement("a")
        anchor.href = objectUrl
        anchor.download = fileName || "document"
        document.body.appendChild(anchor)
        anchor.click()
        anchor.remove()
      } else {
        window.open(hash ? `${objectUrl}#${hash}` : objectUrl, "_blank", "noopener")
      }
      // Give the browser a beat to consume the blob before releasing it.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 2000)
      setPhase("idle")
    } catch {
      setPhase("error")
    }
  }

  if (phase === "error") {
    return (
      <span
        data-testid="cem-gated-action-unavailable"
        style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
      >
        {(action.action_label ?? action.label)} is not available right now.
      </span>
    )
  }
  return (
    <button
      type="button"
      data-testid="cem-gated-action"
      data-action-kind={action.kind}
      onClick={run}
      disabled={phase === "loading"}
      style={{
        fontSize: 12,
        fontWeight: 600,
        color: TOKEN.indigo,
        background: "none",
        border: "none",
        padding: 0,
        cursor: "pointer",
        opacity: phase === "loading" ? 0.6 : 1,
      }}
    >
      {action.action_label ?? action.label} {phase === "loading" ? "…" : "→"}
    </button>
  )
}

function CitationActions({ c }: { c: CanonicalEvidenceCitation }) {
  const candidates = [...(c.actions ?? []), ...(c.access ? [c.access] : [])]
  const seen = new Set<string>()
  const actions = candidates.filter((action) => {
    if (!action.available || !action.url) return false
    const key = `${action.kind}:${action.url}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  if (actions.length === 0) return null
  return (
    <div data-testid="cem-actions" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {actions.map((action) =>
        action.url!.startsWith("/api/") ? (
          // Bearer-gated artifact route: streamed via fetchAPI, never an href.
          <GatedArtifactAction
            key={`${action.kind}:${action.url}`}
            action={action}
            fileName={c.document_access?.original_filename}
          />
        ) : (
          <a
            key={`${action.kind}:${action.url}`}
            data-testid="cem-access-link"
            data-action-kind={action.kind}
            href={action.url!}
            target={action.url!.startsWith("http") ? "_blank" : undefined}
            rel={action.url!.startsWith("http") ? "noreferrer" : undefined}
            style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
          >
            {action.action_label ?? action.label} →
          </a>
        ),
      )}
    </div>
  )
}

function DocumentAccessBlock({ c }: { c: CanonicalEvidenceCitation }) {
  const d = c.document_access
  if (!d) return null
  return (
    <div data-testid="cem-doc-access" data-retained={d.retained} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {d.retained ? (
          <>
            <Badge tone="emerald">Original retained</Badge>
            {d.open_available && <Badge tone="sky">Open original available</Badge>}
            {d.download_available && <Badge tone="sky">Download available</Badge>}
          </>
        ) : (
          <Badge tone="slate">Excerpts only — original not retained</Badge>
        )}
      </div>
      {d.limitations.map((lim, i) => (
        <p key={i} style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>{lim}</p>
      ))}
    </div>
  )
}

function CitationCard({ c }: { c: CanonicalEvidenceCitation }) {
  const locator = locatorLine(c)
  const mismatch = c.identity_state === "mismatched"
  return (
    <div
      data-testid="cem-citation"
      data-proof-type={c.proof_type}
      data-counted={c.counted_as_direct_evidence}
      data-identity={c.identity_state ?? ""}
      style={{
        display: "flex", flexDirection: "column", gap: 6, padding: 10, borderRadius: 8,
        border: `1px solid ${mismatch ? "#e11d48" : TOKEN.line}`,
        background: mismatch ? "rgba(225,29,72,0.05)" : "transparent",
      }}
    >
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: TOKEN.ink }}>{c.source_title}</span>
        <Badge tone="slate">{c.strength}</Badge>
        <CountFlag c={c} />
      </div>
      {locator && (
        <code data-testid="cem-citation-locator" style={{ fontSize: 11, color: TOKEN.inkSoft }}>{locator}</code>
      )}
      {c.context_start_line != null && c.context_end_line != null &&
        (c.context_start_line !== c.start_line || c.context_end_line !== c.end_line) && (
        <span data-testid="cem-analyzed-context" style={{ fontSize: 11, color: TOKEN.muted }}>
          Analyzed context: L{c.context_start_line}–L{c.context_end_line}
          {c.symbol_name ? ` (${c.symbol_name})` : ""} — classification used the containing
          code block; the cited target lines above are unchanged.
        </span>
      )}
      {mismatch && (
        <div data-testid="cem-mismatch-warning" role="alert" style={{ display: "flex", flexDirection: "column", gap: 3, padding: 8, borderRadius: 6, border: "1px solid #e11d48", background: "rgba(225,29,72,0.08)" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#be123c" }}>
            Identity mismatch — this recording does not match this project
          </span>
          {c.identity_reasons.map((r, i) => (
            <p key={i} style={{ margin: 0, fontSize: 11, color: TOKEN.inkSoft }}>{r}</p>
          ))}
          <p style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>
            It is excluded from this claim and creates no corroboration. Review it in the Proof Vault to
            detach, reassign, or explicitly confirm it — it is never deleted automatically.
          </p>
        </div>
      )}
      {c.identity_state === "possible_match_review" && !mismatch && (
        <div data-testid="cem-identity-review" style={{ fontSize: 11, color: "#92600a" }}>
          {c.identity_reasons[0] ?? "Project association needs owner review before this counts."}
        </div>
      )}
      {c.project_relationship && (
        <div data-testid="cem-project-relationship" data-state={c.project_relationship.state} style={{ fontSize: 11, color: TOKEN.muted }}>
          Project relationship: <strong>{c.project_relationship.state.replaceAll("_", " ")}</strong>
          {c.project_relationship.reasons[0] ? ` — ${c.project_relationship.reasons[0]}` : ""}
        </div>
      )}
      {c.analysis_pending && (
        <p data-testid="cem-pending" style={{ margin: 0, fontSize: 11, color: "#92600a" }}>
          Defense captured, analysis pending — visible for transparency, not counted as skill evidence.
        </p>
      )}
      {c.question_text && (
        <p style={{ margin: 0, fontSize: 12, color: TOKEN.inkSoft }}>
          <strong>Q:</strong> {c.question_text}
        </p>
      )}
      {c.code_excerpt && (
        <pre data-testid="cem-code-excerpt" style={{ margin: 0, padding: 8, borderRadius: 6, fontSize: 11, lineHeight: 1.5, overflowX: "auto", background: "rgba(15,23,42,0.06)", color: TOKEN.ink }}>
          <code>{c.code_excerpt}</code>
        </pre>
      )}
      {c.transcript_excerpt && (
        <blockquote data-testid="cem-excerpt" style={{ margin: 0, padding: "4px 10px", borderLeft: `2px solid ${TOKEN.line}`, fontSize: 12, color: TOKEN.inkSoft }}>
          {c.transcript_excerpt}
        </blockquote>
      )}
      {(c.observed_action || c.observed_output) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 12, color: TOKEN.inkSoft }}>
          {c.observed_action && <span><strong>Observed action:</strong> {c.observed_action}</span>}
          {c.observed_output && <span><strong>Observed output:</strong> {c.observed_output}</span>}
        </div>
      )}
      {c.explanation && <p style={{ margin: 0, fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.5 }}>{c.explanation}</p>}
      {c.relevance && <p style={{ margin: 0, fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>{c.relevance}</p>}
      <VideoBlock c={c} />
      <DocumentBlock c={c} />
      <DocumentAccessBlock c={c} />
      <CitationActions c={c} />
      {c.limitations.map((lim, i) => (
        <p key={i} style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>{lim}</p>
      ))}
    </div>
  )
}

function CorroborationBlock({ group }: { group: CanonicalCorroborationGroup }) {
  return (
    <div data-testid="cem-corroboration" style={{ display: "flex", flexDirection: "column", gap: 4, padding: 10, borderRadius: 8, border: "1px solid rgba(5,150,105,0.4)", background: "rgba(5,150,105,0.05)" }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone="emerald">Cross-proof corroboration</Badge>
        <span style={{ fontSize: 11, color: TOKEN.muted }}>{group.sources.join(" + ")}</span>
      </div>
      <p style={{ margin: 0, fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.5 }}>{group.alignment_reason}</p>
      <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11, color: TOKEN.muted, display: "flex", flexDirection: "column", gap: 2 }}>
        {group.unique_contributions.map((u, i) => (
          <li key={i}>{u}</li>
        ))}
      </ul>
      {group.limitations.map((lim, i) => (
        <p key={i} style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>{lim}</p>
      ))}
    </div>
  )
}

function ClaimBlock({
  claim,
  citations,
  corroborations,
  gaps,
}: {
  claim: CanonicalSkillClaim
  citations: CanonicalEvidenceCitation[]
  corroborations: CanonicalCorroborationGroup[]
  gaps: CanonicalEvidenceGap[]
}) {
  const byType = new Map<string, CanonicalEvidenceCitation[]>()
  for (const c of citations) {
    byType.set(c.proof_type, [...(byType.get(c.proof_type) ?? []), c])
  }
  const orderedTypes = [
    ...PROOF_ORDER.filter((t) => byType.has(t)),
    ...[...byType.keys()].filter((t) => !PROOF_ORDER.includes(t)),
  ]
  return (
    <div data-testid="cem-claim" style={{ display: "flex", flexDirection: "column", gap: 8, padding: 12, borderRadius: 10, border: `1px solid ${TOKEN.line}` }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>{claim.claim_text}</span>
        <span data-testid="cem-claim-status">
          <Badge tone={STATUS_TONE[claim.qualitative_status] ?? "slate"}>{claim.qualitative_status}</Badge>
        </span>
        <span style={{ fontSize: 11, color: TOKEN.muted }}>Strongest evidence: {claim.strongest_evidence_tier}</span>
      </div>
      {claim.candidate_attribution && claim.candidate_attribution.label && (
        <div data-testid="cem-claim-attribution" style={{ display: "flex", gap: 6, alignItems: "flex-start", flexWrap: "wrap" }}>
          <Badge tone={ATTRIBUTION_STATE_TONE[claim.candidate_attribution.state] ?? "slate"}>
            {claim.candidate_attribution.label}
          </Badge>
          <span style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5, flex: "1 1 240px" }}>
            {claim.candidate_attribution.candidate_claim_text}
          </span>
        </div>
      )}
      <SourceCountsRow counts={claim.source_counts} />
      {claim.limitations.map((lim, i) => (
        <p key={i} style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>{lim}</p>
      ))}
      {orderedTypes.map((ptype) => (
        <div key={ptype} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3, color: TOKEN.muted }}>{ptype}</span>
          {(byType.get(ptype) ?? []).map((c) => (
            <CitationCard key={c.evidence_id} c={c} />
          ))}
        </div>
      ))}
      {corroborations.map((g) => (
        <CorroborationBlock key={g.group_id} group={g} />
      ))}
      {gaps.length > 0 && (
        <ul data-testid="cem-claim-gaps" style={{ margin: 0, paddingLeft: 16, fontSize: 11, color: TOKEN.muted, display: "flex", flexDirection: "column", gap: 2 }}>
          {gaps.map((g, i) => (
            <li key={i} data-testid="cem-gap">
              {g.description} <em>{g.recommended_action}</em>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ClaimEvidenceMapSection({ map }: { map: ClaimEvidenceMap | null | undefined }) {
  // Legacy payloads carry no canonical map — render nothing rather than guess.
  if (!map || map.claims.length === 0) return null
  const citationsByClaim = new Map<string, CanonicalEvidenceCitation[]>()
  for (const c of map.citations) {
    if (!c.claim_id) continue
    citationsByClaim.set(c.claim_id, [...(citationsByClaim.get(c.claim_id) ?? []), c])
  }
  // Weak/repo-level context the backend deduplicated to map level — shown ONCE
  // for the whole report instead of repeating under every claim.
  const groupedContext = map.citations.filter((c) => c.grouped_context)
  const contradictions: CanonicalContradiction[] = map.contradictions
  return (
    <section data-testid="claim-evidence-map" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: TOKEN.ink }}>Claim-to-evidence map</h3>
        <p style={{ margin: 0, fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
          Each claim below is argued from exact citations. Mismatched, pending, and context-only sources
          stay visible but are never counted; corroboration requires sources that independently pass their
          own relevance and identity checks — never mere same-project attachment.
        </p>
      </div>
      {map.project_relationship && (
        <CandidateAttributionBanner attribution={map.project_relationship} />
      )}
      {map.source_counts && (
        <div data-testid="cem-map-source-counts" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <h4 style={{ margin: 0, fontSize: 12, fontWeight: 700, color: TOKEN.ink }}>Proof sources across this report</h4>
          <SourceCountsRow counts={map.source_counts} />
        </div>
      )}
      {map.claims.map((claim) => (
        <ClaimBlock
          key={claim.id}
          claim={claim}
          citations={citationsByClaim.get(claim.id) ?? []}
          corroborations={map.corroborations.filter((g) => g.claim_id === claim.id)}
          gaps={map.gaps.filter((g) => g.claim_id === claim.id)}
        />
      ))}
      {groupedContext.length > 0 && (
        <div data-testid="cem-grouped-context" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h4 style={{ margin: 0, fontSize: 12, fontWeight: 700, color: TOKEN.ink }}>
            Grouped repository context — shown once, never counted
          </h4>
          <p style={{ margin: 0, fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
            README / dependency / configuration-level signals apply to the whole repository, so they are
            grouped here instead of repeating under every skill claim.
          </p>
          {groupedContext.map((c) => (
            <CitationCard key={c.evidence_id} c={c} />
          ))}
        </div>
      )}
      {contradictions.length > 0 && (
        <div data-testid="cem-contradictions" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h4 style={{ margin: 0, fontSize: 12, fontWeight: 700, color: "#be123c" }}>Mismatches & contradictions</h4>
          {contradictions.map((x) => (
            <div key={x.contradiction_id} data-testid="cem-contradiction" style={{ padding: 8, borderRadius: 8, border: "1px solid #e11d48", background: "rgba(225,29,72,0.05)", display: "flex", flexDirection: "column", gap: 3 }}>
              <p style={{ margin: 0, fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.5 }}>{x.description}</p>
              <p style={{ margin: 0, fontSize: 11, color: TOKEN.muted }}>{x.recommended_action}</p>
            </div>
          ))}
        </div>
      )}
      {map.recruiter_actions.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <h4 style={{ margin: 0, fontSize: 12, fontWeight: 700, color: TOKEN.ink }}>What a recruiter can inspect</h4>
          <ul data-testid="cem-recruiter-actions" style={{ margin: 0, paddingLeft: 16, fontSize: 11, color: TOKEN.inkSoft, display: "flex", flexDirection: "column", gap: 2 }}>
            {map.recruiter_actions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
