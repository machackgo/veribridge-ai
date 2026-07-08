"use client"

/**
 * Proof Relationship UX — the shared vocabulary that explains HOW a proof source
 * relates to the Work Passport. Four honest relationship tiers, in trust order:
 *
 *   1. "Direct skill evidence"        — supports one specific skill in one
 *      specific project. The ONLY tier the Skills Evidence Map and its proof
 *      filters count.
 *   2. "Project-level proof"          — attached to a project overall, not one
 *      skill. Shown near the project, clearly labelled, never counted as skill
 *      evidence.
 *   3. "Attached, not skill-mapped"   — real analyzed proof attached to a
 *      project that no exact skill claim consumed yet. Own secondary section.
 *   4. "Vault-only / suggested"       — saved in the Proof Vault or suggested,
 *      not attached to any project. Never appears as evidence until attached.
 *
 * Everything here is presentation over fields the payload already carries —
 * no new proof semantics, no inferred relationships, no counts changed. When a
 * relationship cannot be derived safely (e.g. a legacy payload without the
 * skill-specific proof breakdown), the affected line fails closed and renders
 * nothing rather than guessing.
 */

import type { CSSProperties, ReactNode } from "react"
import Link from "next/link"
import type { PassportProjectSummary } from "@/lib/vbr-api"
import { Badge, TOKEN, type BadgeTone } from "./shared"
import { normalizeProofTypeLabel, SKILL_PROOF_TYPE_ORDER } from "@/app/student/vbr/passport/passport-graph"

/** The four proof↔passport relationship tiers (closed set). */
export type ProofRelationshipKind = "skill" | "project" | "unmapped" | "vault"

type RelationshipSpec = {
  kind: ProofRelationshipKind
  label: string
  tone: BadgeTone
  /** One-sentence recruiter-facing definition (shown in the guide). */
  description: string
}

export const PROOF_RELATIONSHIPS: RelationshipSpec[] = [
  {
    kind: "skill",
    label: "Direct skill evidence",
    tone: "indigo",
    description:
      "Directly supports one specific skill in one specific project. This is the only proof counted in the map and proof filters.",
  },
  {
    kind: "project",
    label: "Project-level proof",
    tone: "sky",
    description:
      "Attached to a project overall rather than one skill. Shown on the project card, never counted as skill evidence.",
  },
  {
    kind: "unmapped",
    label: "Attached, not skill-mapped",
    tone: "amber",
    description:
      "Real analyzed proof attached to a project, but not tied to a skill claim yet. Listed in its own section below the map.",
  },
  {
    kind: "vault",
    label: "Vault-only / suggested",
    tone: "slate",
    description:
      "Saved in your Proof Vault or suggested, not attached to a project. It never appears as evidence until you attach it.",
  },
]

const RELATIONSHIP_BY_KIND: Record<ProofRelationshipKind, RelationshipSpec> = Object.fromEntries(
  PROOF_RELATIONSHIPS.map((r) => [r.kind, r]),
) as Record<ProofRelationshipKind, RelationshipSpec>

const RELATIONSHIP_DOT: Record<ProofRelationshipKind, string> = {
  skill: TOKEN.indigo,
  project: TOKEN.sky,
  unmapped: TOKEN.amber,
  vault: "#94a3b8",
}

/**
 * The ONE visual grammar for evidence tiers, used by every skill card and
 * project row so the hierarchy reads identically across all skills:
 *
 *   • skill    (primary)   — solid indigo left rule: counted evidence.
 *   • project  (secondary) — dashed sky left rule: real, project-level,
 *     not counted for the skill.
 *   • unmapped (secondary) — dashed amber left rule: attached, awaiting a
 *     skill mapping.
 *   • vault    (tertiary)  — dashed slate left rule: saved/suggested only.
 */
const TIER_RULE: Record<ProofRelationshipKind, { color: string; line: "solid" | "dashed" }> = {
  skill: { color: TOKEN.indigo, line: "solid" },
  project: { color: TOKEN.sky, line: "dashed" },
  unmapped: { color: TOKEN.amber, line: "dashed" },
  vault: { color: "#94a3b8", line: "dashed" },
}

/**
 * A compact tier container: a colored left rule + `data-tier` attribute, no
 * copy of its own. Every place that groups proof chips by relationship renders
 * through this, so "direct vs project-level vs vault-only" always LOOKS the
 * same, card to card. Presentation only — it never counts or filters anything.
 */
export function EvidenceTierSection({
  kind,
  testid,
  projectId,
  children,
}: {
  kind: ProofRelationshipKind
  testid?: string
  projectId?: string
  children: ReactNode
}) {
  const rule = TIER_RULE[kind]
  return (
    <div
      data-testid={testid}
      data-tier={kind}
      data-project-id={projectId}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        paddingLeft: 8,
        borderLeft: `2px ${rule.line} ${rule.color}`,
      }}
    >
      {children}
    </div>
  )
}

/**
 * Small pill naming a section's relationship tier ("Direct skill evidence",
 * "Attached, not skill-mapped", …) so chips underneath never need long labels.
 */
export function EvidenceRelationshipBadge({ kind }: { kind: ProofRelationshipKind }) {
  const spec = RELATIONSHIP_BY_KIND[kind]
  return (
    <span data-testid="evidence-relationship-badge" data-kind={kind}>
      <Badge tone={spec.tone}>{spec.label}</Badge>
    </span>
  )
}

/**
 * Compact legend near the Skills Evidence Map: the four relationship tiers,
 * one line each. Pure static copy — it never counts, filters, or fetches, so
 * it can never change what evidence the map shows.
 */
export function ProofRelationshipGuide() {
  return (
    <div
      data-testid="proof-relationship-guide"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "10px 14px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 12,
        background: TOKEN.bg,
      }}
    >
      <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Proof relationship guide
      </span>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: "6px 16px" }}>
        {PROOF_RELATIONSHIPS.map((r) => (
          <div
            key={r.kind}
            data-testid="proof-relationship-guide-item"
            data-kind={r.kind}
            style={{ display: "flex", gap: 7, alignItems: "flex-start" }}
          >
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: RELATIONSHIP_DOT[r.kind],
                marginTop: 4,
                flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.45 }}>
              <strong style={{ color: TOKEN.inkSoft, fontWeight: 700 }}>{r.label}:</strong> {r.description}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Canonical-order proof labels from a raw source list (unknown labels drop). */
function canonicalProofTypes(sources: string[] | undefined): string[] {
  const present = new Set<string>()
  for (const src of sources ?? []) {
    const canonical = normalizeProofTypeLabel(src)
    if (canonical) present.add(canonical)
  }
  return SKILL_PROOF_TYPE_ORDER.filter((label) => present.has(label))
}

/**
 * The per-project "evidence relationship map": which of this project's attached
 * proof sources back a specific skill claim, which are project-level only, and
 * how many vault suggestions target it. Derived ONLY from fields the payload
 * already separates:
 *
 *   • skill evidence      = union of `top_skills[].supporting_proof_types`
 *   • project-level proof = attached `evidence_sources` NOT in that union
 *   • vault suggestions   = `suggested_attachments` count (never shown as proof)
 *
 * FAIL-CLOSED: on a legacy payload whose skill rows carry no
 * `supporting_proof_types` breakdown, the skill-vs-project split cannot be
 * derived safely, so the split lines render nothing (the proof-chain row above
 * still shows what is attached). A project with skill rows but an empty
 * breakdown keeps the honest "project-level" classification, because the
 * backend recorded that nothing mapped to those skills.
 */
export function ProjectProofRelationshipSummary({ project }: { project: PassportProjectSummary }) {
  const topSkills = project.top_skills ?? []
  const hasBreakdown = topSkills.some((t) => t.supporting_proof_types !== undefined)
  const attached = canonicalProofTypes(project.evidence_sources)

  // Legacy payload with skill rows but no skill-specific breakdown: the split is
  // unknowable — render nothing instead of guessing.
  if (topSkills.length > 0 && !hasBreakdown) return null
  if (attached.length === 0 && (project.suggested_attachments?.length ?? 0) === 0) return null

  const skillMapped = new Set(canonicalProofTypes(topSkills.flatMap((t) => t.supporting_proof_types ?? [])))
  const skillEvidence = attached.filter((label) => skillMapped.has(label))
  const projectLevelOnly = attached.filter((label) => !skillMapped.has(label))
  const suggestionCount = project.suggested_attachments?.length ?? 0

  if (skillEvidence.length === 0 && projectLevelOnly.length === 0 && suggestionCount === 0) return null

  const lineStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }
  const lineLabel: CSSProperties = { fontSize: 11, fontWeight: 700, color: TOKEN.muted }

  return (
    <div
      data-testid="project-proof-relationships"
      data-project-id={project.project_id}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 5,
        padding: "8px 10px",
        border: `1px dashed ${TOKEN.line}`,
        borderRadius: 8,
        background: TOKEN.bg,
      }}
    >
      <span style={{ fontSize: 10, fontWeight: 700, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>
        How this project&apos;s proof relates
      </span>
      {skillEvidence.length > 0 && (
        <EvidenceTierSection kind="skill">
          <div data-testid="project-relationship-skill-evidence" style={lineStyle}>
            <span style={lineLabel}>Direct skill evidence:</span>
            {skillEvidence.map((label) => (
              <span key={label} data-testid="project-relationship-skill-chip" data-source={label}>
                <Badge tone="indigo">{label}</Badge>
              </span>
            ))}
          </div>
        </EvidenceTierSection>
      )}
      {projectLevelOnly.length > 0 && (
        <EvidenceTierSection kind="project">
          <div data-testid="project-relationship-project-level" style={lineStyle}>
            <span style={lineLabel}>Project-level proof (not skill-specific):</span>
            {projectLevelOnly.map((label) => (
              <span key={label} data-testid="project-relationship-project-chip" data-source={label}>
                <Badge tone="sky">{label}</Badge>
              </span>
            ))}
          </div>
        </EvidenceTierSection>
      )}
      {suggestionCount > 0 && (
        <EvidenceTierSection kind="vault">
          <div data-testid="project-relationship-vault-suggestions" style={lineStyle}>
            <span style={lineLabel}>Vault suggestions:</span>
            <span style={{ fontSize: 11, color: TOKEN.muted }}>
              {suggestionCount} available — not counted until attached.
            </span>
            <Link
              href="/student/vbr/passport/vault"
              data-testid="project-relationship-open-vault"
              style={{ fontSize: 11, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
            >
              Review in Proof Vault →
            </Link>
          </div>
        </EvidenceTierSection>
      )}
    </div>
  )
}
