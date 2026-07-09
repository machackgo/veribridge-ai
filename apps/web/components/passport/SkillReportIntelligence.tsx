"use client"

/**
 * Skill Report Intelligence — the presentation layer that turns one skill's
 * proof data into a recruiter-readable evidence ARGUMENT:
 *
 *   Skill claim → evidence thesis → projects → exact proof → explanation →
 *   limitations → inspect proof.
 *
 * It reuses the Work Passport's four-tier proof↔passport vocabulary
 * (see ProofRelationshipGuide):
 *
 *   1. "Direct skill evidence"       — proof mapped to THIS skill, connected
 *      through a project chain. The only tier that counts for the claim.
 *   2. "Project-level proof"         — attached to the same project but NOT
 *      mapped to this skill. Context only, never counted.
 *   3. "Attached, not skill-mapped"  — real analyzed proof attached to one of
 *      this skill's projects that no skill claim consumed yet. Not counted.
 *   4. "Vault-only / suggested"      — saved in the Proof Vault or suggested,
 *      not attached to any project. Not counted.
 *
 * Everything here is presentation over fields the payloads already carry —
 * no new proof semantics, nothing inferred, no counts changed. Tiers 2–4 need
 * the owner's private passport payload; when it is unavailable (public surface,
 * fetch failure, legacy payload) the affected sections FAIL CLOSED and render
 * nothing rather than guessing.
 */

import type { ReactNode } from "react"
import Link from "next/link"

import type {
  PrivateWorkPassport,
  ProofAttachmentEntry,
  RealUnmappedProofContext,
  SkillReport,
  SkillReportProjectChain,
  SkillReportStandaloneEvidence,
} from "@/lib/vbr-api"
import { normalizeProofTypeLabel, SKILL_PROOF_TYPE_ORDER } from "@/app/student/vbr/passport/passport-graph"
import { Badge, TOKEN, type BadgeTone } from "./shared"
import { EvidenceRelationshipBadge, EvidenceTierSection } from "./ProofRelationshipGuide"

// ── Private passport context (tiers 2–4) ──────────────────────────────────────

/**
 * The skill-scoped slice of the private Work Passport the Skill Report needs to
 * separate project-level / unmapped / suggested proof from direct evidence.
 * Built ONLY from fields the passport payload already separates — never from
 * raw evidence. `null` (no passport available) fails closed: the report renders
 * without the context tiers.
 */
export type SkillReportIntelligenceContext = {
  /** project_id → ALL canonical proof sources attached to that project. */
  projectSources: Record<string, string[]>
  /** project_id → real analyzed proof attached but not mapped to ANY skill. */
  unmappedByProject: Record<string, RealUnmappedProofContext[]>
  /** Vault suggestions that name THIS skill — never counted until attached. */
  suggestedForSkill: ProofAttachmentEntry[]
}

/** Canonical proof-type set from raw labels (unknown labels drop). */
function canonicalTypeSet(labels: Array<string | null | undefined>): Set<string> {
  const set = new Set<string>()
  for (const label of labels) {
    const canonical = label ? normalizeProofTypeLabel(label) : null
    if (canonical) set.add(canonical)
  }
  return set
}

/** Canonical-order proof labels from a raw source list (unknown labels drop). */
function canonicalSources(sources: string[] | undefined | null): string[] {
  const present = new Set<string>()
  for (const src of sources ?? []) {
    const canonical = normalizeProofTypeLabel(src)
    if (canonical) present.add(canonical)
  }
  return SKILL_PROOF_TYPE_ORDER.filter((label) => present.has(label))
}

/**
 * Derive the intelligence context for one skill report from the private
 * passport. Pure and fail-closed: a missing passport, missing sections, or a
 * legacy payload yield `null` / empty maps — never a guessed relationship.
 */
export function buildSkillReportIntelligenceContext(
  passport: PrivateWorkPassport | null | undefined,
  report: SkillReport | null | undefined,
): SkillReportIntelligenceContext | null {
  if (!passport || !report) return null

  const projectSources: Record<string, string[]> = {}
  for (const project of passport.projects ?? []) {
    if (!project.project_id) continue
    projectSources[project.project_id] = canonicalSources(project.evidence_sources)
  }

  const unmappedByProject: Record<string, RealUnmappedProofContext[]> = {}
  for (const entry of passport.real_unmapped_proof_context ?? []) {
    if (!entry.project_id) continue
    ;(unmappedByProject[entry.project_id] ??= []).push(entry)
  }

  const skillNames = new Set(
    [report.skill, report.requested_skill].filter(Boolean).map((s) => s.trim().toLowerCase()),
  )
  const suggestedForSkill = (passport.attachment_overview?.suggested ?? []).filter((entry) =>
    entry.skill_names?.some((name) => skillNames.has(name.trim().toLowerCase())),
  )

  return { projectSources, unmappedByProject, suggestedForSkill }
}

/** Every project id a chain represents (its own + grouped/collapsed attempts). */
function chainProjectIds(chain: SkillReportProjectChain): string[] {
  const ids = new Set<string>()
  if (chain.project_id) ids.add(chain.project_id)
  for (const id of chain.grouped_project_ids ?? []) ids.add(id)
  for (const id of chain.collapsed_project_ids ?? []) ids.add(id)
  return [...ids]
}

/** All attached sources for a chain's project(s), from the passport context. */
function chainAttachedSources(chain: SkillReportProjectChain, context: SkillReportIntelligenceContext): string[] {
  const union = new Set<string>()
  for (const id of chainProjectIds(chain)) {
    for (const src of context.projectSources[id] ?? []) union.add(src)
  }
  return SKILL_PROOF_TYPE_ORDER.filter((label) => union.has(label))
}

/** Unmapped-proof entries for a chain's project(s), from the passport context. */
function chainUnmappedEntries(
  chain: SkillReportProjectChain,
  context: SkillReportIntelligenceContext,
): RealUnmappedProofContext[] {
  return chainProjectIds(chain).flatMap((id) => context.unmappedByProject[id] ?? [])
}

// ── Shared section chrome ─────────────────────────────────────────────────────

/** The uppercase section heading used across the Skill Report. */
export function SectionHeading({ children }: { children: ReactNode }) {
  return (
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
      {children}
    </h3>
  )
}

/** The small amber "Not counted yet" marker used by every non-counted tier. */
function NotCountedBadge() {
  return (
    <span data-testid="not-counted-badge">
      <Badge tone="amber">Not counted yet</Badge>
    </span>
  )
}

// ── B — Evidence thesis ───────────────────────────────────────────────────────

/**
 * One short, derived paragraph stating what actually backs the claim: how many
 * connected projects, which proof sources, and the standing honesty rule that
 * only direct, skill-mapped evidence counts. Derived ONLY from real payload
 * counts — never invented, never a score.
 */
export function SkillEvidenceThesis({
  report,
  directChains,
}: {
  report: SkillReport
  directChains: SkillReportProjectChain[]
}) {
  const directSources = canonicalSources(directChains.flatMap((c) => c.sources))
  const projectCount = directChains.length
  const hasAnyProof = Object.values(report.source_counts ?? {}).some((n) => n > 0)
  if (projectCount === 0 && !hasAnyProof) return null

  const thesis =
    projectCount > 0
      ? `This skill claim is supported by ${projectCount} connected project${projectCount === 1 ? "" : "s"}` +
        (directSources.length > 0
          ? ` and ${directSources.length} proof source${directSources.length === 1 ? "" : "s"}: ${directSources.join(", ")}.`
          : ".")
      : "No project-connected evidence backs this skill claim yet. Proof exists in the vault below, but it is not counted until it is attached to a project and mapped to this skill."

  return (
    <div data-testid="skill-report-thesis" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <p style={{ fontSize: 12, color: TOKEN.ink, margin: 0, lineHeight: 1.6, fontWeight: 600 }}>{thesis}</p>
      <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        Only direct, skill-mapped evidence counts toward this claim. Project-level proof,
        attached-but-unmapped proof, and vault-only / suggested proof are shown separately below and
        are not counted.
      </p>
    </div>
  )
}

// ── D — Project context evidence (attached, mapped to the project not the skill) ─

/**
 * For each direct-evidence project: the proof sources attached to that project
 * that do NOT support this skill. Shown as honest context chips — never full
 * evidence cards (their detail belongs to the project report), never counted.
 * Sources that the passport reports as attached-but-unmapped are excluded here
 * (they get their own richer section E). Fails closed without context.
 */
export function ProjectContextEvidenceList({
  chains,
  context,
  skill,
}: {
  chains: SkillReportProjectChain[]
  context?: SkillReportIntelligenceContext | null
  skill: string
}) {
  if (!context) return null
  const rows = chains
    .map((chain) => {
      const direct = new Set(canonicalSources(chain.sources))
      const unmappedTypes = canonicalTypeSet(chainUnmappedEntries(chain, context).map((e) => e.proof_type))
      const contextSources = chainAttachedSources(chain, context).filter(
        (src) => !direct.has(src) && !unmappedTypes.has(src),
      )
      return { chain, contextSources }
    })
    .filter((row) => row.contextSources.length > 0)
  if (rows.length === 0) return null

  return (
    <div data-testid="skill-report-project-context" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <SectionHeading>Project proof (context only)</SectionHeading>
        <EvidenceRelationshipBadge kind="project" />
        <NotCountedBadge />
      </div>
      <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        Attached to the same project(s) — this proof helps explain the project, but it is not mapped
        to {skill} and is not counted as direct skill evidence.
      </p>
      <EvidenceTierSection kind="project">
        {rows.map(({ chain, contextSources }) => (
          <div
            key={chain.project_id ?? chain.project_title}
            data-testid="project-context-row"
            data-project={chain.project_id ?? ""}
            style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", padding: "4px 0" }}
          >
            <span style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft }}>{chain.project_title}:</span>
            {contextSources.map((src) => (
              <span key={src} data-testid="project-context-chip" data-source={src}>
                <Badge tone="sky">{src}</Badge>
              </span>
            ))}
          </div>
        ))}
      </EvidenceTierSection>
    </div>
  )
}

// ── E — Attached, not skill-mapped ────────────────────────────────────────────

/**
 * Real, analyzed proof attached to one of this skill's projects that no skill
 * claim consumed yet. Shown separately with the passport's honest vocabulary —
 * never as skill evidence, never counted. Fails closed without context.
 */
export function UnmappedProofNotice({
  chains,
  context,
}: {
  chains: SkillReportProjectChain[]
  context?: SkillReportIntelligenceContext | null
}) {
  if (!context) return null
  const seen = new Set<string>()
  const entries = chains
    .flatMap((chain) => chainUnmappedEntries(chain, context))
    .filter((e) => {
      const key = `${e.project_id}|${e.proof_type}|${e.evidence_label ?? ""}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  if (entries.length === 0) return null

  return (
    <div data-testid="skill-report-unmapped" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <SectionHeading>Attached proof not yet skill-mapped</SectionHeading>
        <EvidenceRelationshipBadge kind="unmapped" />
        <NotCountedBadge />
      </div>
      <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        Real analyzed proof attached to these project(s) that is not tied to a skill claim yet — shown
        so it is never confused with direct skill evidence.
      </p>
      <EvidenceTierSection kind="unmapped">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {entries.map((entry, i) => (
            <div
              key={`${entry.project_id}-${entry.proof_type}-${i}`}
              data-testid="skill-report-unmapped-entry"
              data-proof-type={entry.proof_type}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                padding: "8px 10px",
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
                background: "#fff",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <Badge tone="amber">{entry.proof_type}</Badge>
                <span style={{ fontSize: 12, fontWeight: 600, color: TOKEN.ink }}>{entry.project_title}</span>
              </div>
              {entry.safe_summary && (
                <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{entry.safe_summary}</p>
              )}
              {entry.reason && (
                <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>{entry.reason}</p>
              )}
              {entry.report_url && (
                <Link
                  href={entry.inspection_anchor ? `${entry.report_url}#${entry.inspection_anchor}` : entry.report_url}
                  data-testid="unmapped-inspect-link"
                  style={{ fontSize: 11, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
                >
                  Inspect in project report →
                </Link>
              )}
            </div>
          ))}
        </div>
      </EvidenceTierSection>
    </div>
  )
}

// ── F — Vault suggestions (not attached, naming this skill) ───────────────────

/**
 * Vault suggestions that name this skill: compact rows only (title, source,
 * why), each explicitly "not counted until attached". Nothing here ever renders
 * as evidence; nothing is attached automatically. Fails closed without context.
 */
export function VaultSuggestedEvidenceList({
  entries,
}: {
  entries?: ProofAttachmentEntry[] | null
}) {
  if (!entries || entries.length === 0) return null
  return (
    <div data-testid="skill-report-suggested" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted }}>
        Suggested from your Proof Vault — review before attaching; not counted until attached.
      </span>
      {entries.map((entry) => (
        <div
          key={entry.entry_id_safe}
          data-testid="skill-report-suggested-entry"
          data-proof-type={entry.proof_type}
          style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}
        >
          <Badge tone="slate">{entry.proof_type}</Badge>
          <span style={{ fontSize: 12, color: TOKEN.inkSoft }}>{entry.display_title}</span>
          {entry.reason_label && <span style={{ fontSize: 11, color: TOKEN.muted }}>— {entry.reason_label}</span>}
          <NotCountedBadge />
        </div>
      ))}
    </div>
  )
}

// ── G — Proof matrix ──────────────────────────────────────────────────────────

type MatrixCellState = "direct" | "context" | "unmapped" | "vault" | "absent"

const MATRIX_CELL: Record<MatrixCellState, { label: string; tone: BadgeTone | null }> = {
  direct: { label: "Direct", tone: "indigo" },
  context: { label: "Context", tone: "sky" },
  unmapped: { label: "Not mapped", tone: "amber" },
  vault: { label: "Vault-only", tone: "slate" },
  absent: { label: "—", tone: null },
}

const MATRIX_LEGEND: Array<{ state: MatrixCellState; text: string }> = [
  { state: "direct", text: "Direct — mapped to this skill; counted." },
  { state: "context", text: "Context — attached to the project, not this skill; not counted." },
  { state: "unmapped", text: "Not mapped — attached, awaiting a skill mapping; not counted." },
  { state: "vault", text: "Vault-only — saved or suggested, not attached; not counted." },
]

function standaloneHasSource(std: SkillReportStandaloneEvidence | null | undefined, source: string): boolean {
  if (!std) return false
  switch (source) {
    case "GitHub Proof":
      return (std.github?.length ?? 0) > 0 || (std.github_groups?.length ?? 0) > 0
    case "Website Proof":
      return (std.website?.length ?? 0) > 0
    case "Document Proof":
      return (std.documents?.length ?? 0) > 0
    case "Project Defense":
      return (std.defense?.length ?? 0) > 0
    case "Video Evidence":
      return (std.video?.length ?? 0) > 0
    default:
      return false
  }
}

/**
 * Proof coverage at a glance: one row per direct-evidence project (plus one
 * vault row), one column per attachable proof source. Each cell is the tier the
 * proof holds for THIS skill — Direct / Context / Not mapped / Vault-only — or
 * absent. Context and Not-mapped cells need the passport context; without it
 * those cells fail closed to absent rather than guessing.
 */
export function SkillProofMatrix({
  directChains,
  standalone,
  context,
  suggested,
}: {
  directChains: SkillReportProjectChain[]
  standalone?: SkillReportStandaloneEvidence | null
  context?: SkillReportIntelligenceContext | null
  suggested?: ProofAttachmentEntry[] | null
}) {
  const suggestedTypes = canonicalTypeSet((suggested ?? []).map((e) => e.proof_type))
  const vaultRowStates: Record<string, MatrixCellState> = {}
  for (const source of SKILL_PROOF_TYPE_ORDER) {
    vaultRowStates[source] =
      standaloneHasSource(standalone, source) || suggestedTypes.has(source) ? "vault" : "absent"
  }
  const hasVaultRow = Object.values(vaultRowStates).some((s) => s !== "absent")

  const projectRows = directChains.map((chain) => {
    const direct = new Set(canonicalSources(chain.sources))
    const attached = context ? new Set(chainAttachedSources(chain, context)) : null
    const unmappedTypes = context
      ? canonicalTypeSet(chainUnmappedEntries(chain, context).map((e) => e.proof_type))
      : null
    const states: Record<string, MatrixCellState> = {}
    for (const source of SKILL_PROOF_TYPE_ORDER) {
      if (direct.has(source)) states[source] = "direct"
      else if (unmappedTypes?.has(source)) states[source] = "unmapped"
      else if (attached?.has(source)) states[source] = "context"
      else states[source] = "absent"
    }
    return { key: chain.project_id ?? chain.project_title, title: chain.project_title, states }
  })

  if (projectRows.length === 0 && !hasVaultRow) return null

  const cellStyle = {
    padding: "6px 8px",
    borderBottom: `1px solid ${TOKEN.line}`,
    textAlign: "center" as const,
    whiteSpace: "nowrap" as const,
  }

  const renderCell = (source: string, state: MatrixCellState) => {
    const spec = MATRIX_CELL[state]
    return (
      <td key={source} data-testid="matrix-cell" data-source={source} data-state={state} style={cellStyle}>
        {spec.tone ? (
          <Badge tone={spec.tone}>{spec.label}</Badge>
        ) : (
          <span style={{ fontSize: 11, color: TOKEN.muted }}>{spec.label}</span>
        )}
      </td>
    )
  }

  return (
    <div data-testid="skill-proof-matrix" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <SectionHeading>Proof coverage matrix</SectionHeading>
      <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        How each proof source relates to this skill, per project. Only &ldquo;Direct&rdquo; cells count.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12, minWidth: 520 }}>
          <thead>
            <tr>
              <th
                scope="col"
                style={{ ...cellStyle, textAlign: "left", fontSize: 11, color: TOKEN.muted, fontWeight: 700 }}
              >
                Project
              </th>
              {SKILL_PROOF_TYPE_ORDER.map((source) => (
                <th
                  key={source}
                  scope="col"
                  style={{ ...cellStyle, fontSize: 11, color: TOKEN.muted, fontWeight: 700 }}
                >
                  {source.replace(" Proof", "").replace(" Evidence", "")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {projectRows.map((row) => (
              <tr key={row.key} data-testid="matrix-project-row" data-project={row.key}>
                <th
                  scope="row"
                  style={{ ...cellStyle, textAlign: "left", fontWeight: 600, color: TOKEN.ink, whiteSpace: "normal" }}
                >
                  {row.title}
                </th>
                {SKILL_PROOF_TYPE_ORDER.map((source) => renderCell(source, row.states[source]))}
              </tr>
            ))}
            {hasVaultRow && (
              <tr data-testid="matrix-vault-row">
                <th
                  scope="row"
                  style={{ ...cellStyle, textAlign: "left", fontWeight: 600, color: TOKEN.muted, whiteSpace: "normal" }}
                >
                  Vault-only / suggested
                </th>
                {SKILL_PROOF_TYPE_ORDER.map((source) => renderCell(source, vaultRowStates[source]))}
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {MATRIX_LEGEND.map(({ state, text }) => (
          <span key={state} style={{ fontSize: 10, color: TOKEN.muted, lineHeight: 1.5 }}>
            {text}
          </span>
        ))}
      </div>
    </div>
  )
}

// ── I — What this report does not claim ───────────────────────────────────────

/**
 * The standing honesty block. Static, closed copy — it never varies with the
 * evidence, so it can never overclaim or underclaim a specific proof.
 */
export function EvidenceLimitations({ skill }: { skill: string }) {
  return (
    <div data-testid="skill-report-disclaimers" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
        What this report does not claim
      </h4>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: TOKEN.muted, lineHeight: 1.6 }}>
        <li>It does not certify professional employment experience.</li>
        <li>It demonstrates the specific claims evidenced above — not every subtopic of {skill}.</li>
        <li>Project-level proof is separated from direct skill evidence and is not counted.</li>
        <li>Attached-but-unmapped and vault-only / suggested proof are not counted until skill-mapped.</li>
      </ul>
    </div>
  )
}

// ── J — Inspect proof actions ─────────────────────────────────────────────────

/**
 * One clean, deduplicated action row: each direct-evidence project's report
 * plus the Proof Vault. Per-proof inspect links (View code lines, Open live
 * site, …) live on the evidence cards themselves — never repeated here.
 * Owner-only routes, so the caller must not render this on a public surface.
 */
export function ProofInspectActions({ directChains }: { directChains: SkillReportProjectChain[] }) {
  const seen = new Set<string>()
  const projects = directChains.filter((chain) => {
    if (!chain.project_id || seen.has(chain.project_id)) return false
    seen.add(chain.project_id)
    return true
  })

  const linkStyle = {
    fontSize: 12,
    fontWeight: 600,
    color: TOKEN.indigo,
    background: TOKEN.indigoSoft,
    borderRadius: 6,
    padding: "6px 12px",
    textDecoration: "none",
  } as const

  return (
    <div data-testid="skill-report-actions" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <SectionHeading>Inspect evidence</SectionHeading>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {projects.map((chain) => {
          const href = `/student/vbr/projects/${encodeURIComponent(chain.project_id!)}/report`
          return (
            <Link
              key={`project-report-${chain.project_id}-${href}`}
              href={href}
              data-testid="skill-report-project-report-link"
              style={linkStyle}
            >
              Open project report — {chain.project_title} →
            </Link>
          )
        })}
        <Link href="/student/vbr/passport/vault" data-testid="skill-report-vault-link" style={linkStyle}>
          Review Proof Vault →
        </Link>
      </div>
    </div>
  )
}
