"use client"

import type { CandidateAttribution } from "@/lib/vbr-api"

import { Badge, TOKEN, type BadgeTone } from "./shared"

/**
 * Candidate ↔ project relationship — rendered verbatim from the backend's
 * closed-template attribution block. The recruiter must never have to infer
 * ownership from technical evidence: this banner states it explicitly.
 *
 * PROJECT EVIDENCE != CANDIDATE OWNERSHIP: the surrounding report argues what
 * the project's artifacts show; this block states what the evidence supports
 * about the CANDIDATE (verified/claimed contribution, understanding only,
 * explicit non-authorship, or an unresolved conflict).
 */

export const ATTRIBUTION_STATE_TONE: Record<string, BadgeTone> = {
  verified_author: "emerald",
  verified_contributor: "emerald",
  claimed_contributor: "sky",
  unknown: "slate",
  // An explicit denial is honest delimitation — neutral-informative, never an
  // error state.
  denied_by_candidate: "indigo",
  conflicted: "amber",
}

export function CandidateAttributionBanner({
  attribution,
  heading = "Candidate relationship to this project",
}: {
  attribution: CandidateAttribution | null | undefined
  heading?: string
}) {
  if (!attribution || !attribution.label) return null
  return (
    <section
      data-testid="candidate-attribution"
      data-attribution-state={attribution.state}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: 12,
        borderRadius: 10,
        border: `1px solid ${TOKEN.line}`,
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>{heading}</h3>
        <span data-testid="candidate-attribution-label">
          <Badge tone={ATTRIBUTION_STATE_TONE[attribution.state] ?? "slate"}>{attribution.label}</Badge>
        </span>
      </div>
      <p data-testid="candidate-attribution-text" style={{ margin: 0, fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.55 }}>
        {attribution.candidate_claim_text}
      </p>
      {attribution.basis.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11, color: TOKEN.muted, display: "flex", flexDirection: "column", gap: 2 }}>
          {attribution.basis.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      )}
      {attribution.limitations.map((lim, i) => (
        <p key={i} style={{ margin: 0, fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
          {lim}
        </p>
      ))}
    </section>
  )
}
