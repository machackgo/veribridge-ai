/**
 * Client-side Projects ↔ Skills graph derivation for the private Work Passport.
 *
 * Everything here is derived from fields the passport payload already carries
 * (project top_skills, skill project refs, vault skill summaries) — no new
 * backend fields, no scores, and owner-only routes stay owner-only.
 */

import {
  fallbackSkillSlug,
  type PrivateWorkPassport,
} from "@/lib/vbr-api"
import type { StrongestProjectRef } from "../../../../../components/passport/VaultProofs"

/** Canonical render order for proof-type chips on a skill card. */
export const SKILL_PROOF_TYPE_ORDER = [
  "GitHub Proof",
  "Website Proof",
  "Document Proof",
  "Project Defense",
  "Video Evidence",
] as const

type CanonicalProofType = (typeof SKILL_PROOF_TYPE_ORDER)[number]

/**
 * Common proof-type spellings → their canonical SKILL_PROOF_TYPE_ORDER label.
 * The payload normally uses the canonical labels, but different producers (the
 * overview `evidence_source_counts`, project `evidence_sources`, vault summaries)
 * can carry variants — snake_case, a bare noun, or a different case. Keys here
 * are pre-normalized (see `normalizeProofTypeLabel`) so "website_proof",
 * "website" and "Website" all resolve to "Website Proof".
 */
const PROOF_TYPE_ALIASES: Record<string, CanonicalProofType> = {
  "github proof": "GitHub Proof",
  github: "GitHub Proof",
  "website proof": "Website Proof",
  website: "Website Proof",
  "document proof": "Document Proof",
  document: "Document Proof",
  "project defense": "Project Defense",
  defense: "Project Defense",
  "video evidence": "Video Evidence",
  video: "Video Evidence",
}

/**
 * Canonicalize a proof-type label to one of SKILL_PROOF_TYPE_ORDER, or null when
 * it maps to no known proof type. Collapses case and `_`/`-`/whitespace so any of
 * "Website Proof" / "website_proof" / "website" / "Website" reads as "Website
 * Proof" — keeps the proof-type filter's options consistent no matter which part
 * of the payload the label came from.
 */
export function normalizeProofTypeLabel(label: string): CanonicalProofType | null {
  const key = label.trim().toLowerCase().replace(/[_\-\s]+/g, " ").trim()
  if (!key) return null
  return PROOF_TYPE_ALIASES[key] ?? null
}

/**
 * One attached project→skill evidence relationship for a skill card: which
 * project demonstrates this skill, with which proof sources, and where to open
 * the skill's evidence inside that project's report.
 *
 * Every row here is ATTACHED — its `projectId` resolves to a known project on
 * this passport, so its `reportPath` is a real owner-only route. Unattached /
 * vault-only evidence never produces a row (a skill with none renders the
 * vault-only state instead), so a project-report CTA never fronts loose vault
 * evidence.
 */
export type SkillProjectEvidence = {
  projectId: string
  projectTitle: string
  /** This project's qualitative status FOR THIS SKILL (never a score). */
  skillStatus: string
  /** Proof-type labels THIS project contributes for THIS skill, canonical order. */
  evidenceSources: string[]
  /** Website Proof is among this project's sources for this skill. */
  hasWebsiteProof: boolean
  /** Safe, closed-vocabulary sentence for what Website Proof demonstrably showed
   *  for THIS skill in THIS project. Present only when `hasWebsiteProof`; the UI
   *  falls back to a generic runtime-behaviour note when absent. Never raw
   *  DOM/OCR/visual/provider text. */
  websiteEvidenceSummary?: string
  /** The project carries attached proof at the project level (any source),
   *  even when none of it is mapped to THIS skill. Lets the UI distinguish
   *  "project-level proof exists, but is not mapped to this skill yet" from a
   *  project with no attached proof at all. */
  projectHasProjectLevelProof: boolean
  /** Owner-only project-report route (always present — projectId is known). */
  reportPath: string
  publicReportPath: string | null
  reportIsPublic: boolean
}

/** One skill node in the Projects ↔ Skills explorer — labels and links only. */
export type PassportSkillNode = {
  /** Stable lowercased identity key. */
  key: string
  name: string
  slug: string
  /** Qualitative evidence state ("Demonstrated", … , "Not assessed"). */
  status: string
  /** Present proof-type labels, in canonical order. */
  proofTypes: string[]
  /** Connected projects that exist on this passport (render targets). */
  projectIds: string[]
  /** Connected-project count (payload count when it knows more than the ids). */
  projectCount: number
  /** The project where this skill is most strongly evidenced, when known. */
  strongest: StrongestProjectRef | null
  /** Per-attached-project evidence rows for contextual "proof → project → skill"
   *  navigation. Empty when the skill has only vault-only evidence. Strongest
   *  project first. */
  projectEvidence: SkillProjectEvidence[]
  /** Proof-type sources for this skill that live in the Proof Vault but are NOT
   *  attached to any project (standalone / vault-only evidence). Rendered as a
   *  separate, clearly-labelled section so it is never counted as project proof.
   *  Canonical order; empty when there is no unattached vault evidence. */
  vaultOnlySources: string[]
}

export type PassportGraph = {
  skills: PassportSkillNode[]
  /** project_id → connected skill keys. */
  projectSkills: Map<string, string[]>
  /** skill key → connected project ids. */
  skillProjects: Map<string, string[]>
  /**
   * Proof-type labels (canonical order) that exist ANYWHERE in this passport's
   * evidence — the overview `evidence_source_counts`, any project's attached
   * sources, any skill's sources/vault-only sources, and the skill→project
   * evidence map. This is the recruiter-facing Proof Type dropdown's option set:
   * a proof type stays selectable because the candidate has it, not because the
   * currently-visible skill block happens to map it. Selecting one still filters
   * skill→project rows to that exact skill-project relationship (fail-closed), so
   * an option here can legitimately resolve to the "no matching rows" empty state.
   */
  proofTypeOptions: string[]
}

/**
 * Skill (lowercased) → strongest related project, from the passport aggregate,
 * including the owner-only project report route for "View project evidence".
 */
export function strongestProjectBySkill(
  passport: PrivateWorkPassport,
): Record<string, StrongestProjectRef> {
  const strongestBySkill: Record<string, StrongestProjectRef> = {}
  for (const s of passport.skills) {
    if (s.strongest_project_title) {
      const link = s.strongest_project
      strongestBySkill[s.skill.toLowerCase()] = {
        title: s.strongest_project_title,
        status: s.strongest_project_status ?? "",
        reportPath:
          link?.project_report_path ??
          (link?.project_id ? `/student/vbr/projects/${link.project_id}/report` : null),
        publicPath: link?.public_report_path ?? null,
        reportIsPublic: link?.report_is_public ?? false,
      }
    }
  }
  return strongestBySkill
}

type SkillDraft = {
  name: string
  slug: string
  status: string
  sources: Set<string>
  projectIds: Set<string>
  payloadProjectCount: number
  /** Vault-only proof-type sources for this skill (unattached to any project). */
  vaultOnlySources: Set<string>
}

/**
 * Build the Projects ↔ Skills adjacency from the evidence-backed project↔skill
 * relationships the payload already expresses: skill project refs, vault summary
 * project ids, and project top_skills. Every edge here is evidence-backed —
 * evidence-less claimed skills are deliberately NOT linked, so a project↔skill
 * highlight always means "this skill is proven by this project", never a bare
 * claim. Ambiguous, title-only matches fail closed for the same reason.
 */
export function buildPassportGraph(passport: PrivateWorkPassport): PassportGraph {
  const strongest = strongestProjectBySkill(passport)
  const knownProjectIds = new Set(passport.projects.map((p) => p.project_id))
  // Title → the project ids that share it. A title mapping to more than one id
  // is ambiguous, so title-only matching against it must fail closed.
  const titleToIds = new Map<string, Set<string>>()
  for (const p of passport.projects) {
    const key = p.project_title.trim().toLowerCase()
    if (!key) continue
    const ids = titleToIds.get(key) ?? new Set<string>()
    ids.add(p.project_id)
    titleToIds.set(key, ids)
  }

  const drafts = new Map<string, SkillDraft>()
  const draft = (name: string): SkillDraft => {
    const key = name.trim().toLowerCase()
    let d = drafts.get(key)
    if (!d) {
      d = { name: name.trim(), slug: "", status: "", sources: new Set(), projectIds: new Set(), payloadProjectCount: 0, vaultOnlySources: new Set() }
      drafts.set(key, d)
    }
    return d
  }
  // Resolve a project reference to a known project id, failing closed: a direct
  // id must be one of this passport's projects, and a title-only fallback only
  // resolves a title that maps to exactly ONE known project (ambiguous same-title
  // matches resolve to nothing, so they never create an edge or a routed CTA).
  const resolveProjectId = (projectId?: string | null, projectTitle?: string | null): string | null => {
    if (projectId && knownProjectIds.has(projectId)) return projectId
    const key = projectTitle?.trim().toLowerCase()
    if (!key) return null
    const ids = titleToIds.get(key)
    if (ids && ids.size === 1) return [...ids][0]
    return null
  }
  const addProject = (d: SkillDraft, projectId?: string | null, projectTitle?: string | null) => {
    const id = resolveProjectId(projectId, projectTitle)
    if (id) d.projectIds.add(id)
  }

  // skill key → (resolved project id → this project's proof sources + safe report
  // context FOR THIS SKILL). Only evidence-source-bearing refs (skill.projects and
  // the strongest-project link) feed this, so a row's `evidenceSources` reflects
  // what that project actually contributes for the skill — never a broad claim.
  type ProjEvidenceMeta = {
    sources: Set<string>
    status: string
    isPublic: boolean
    publicPath: string | null
    websiteSummary?: string
  }
  const perSkillProjectMeta = new Map<string, Map<string, ProjEvidenceMeta>>()
  const recordProjectMeta = (
    skillKey: string,
    projectId: string | null,
    sources: string[] | undefined,
    status: string | undefined,
    isPublic: boolean | undefined,
    publicPath: string | null | undefined,
    websiteSummary?: string | null,
  ) => {
    if (!projectId) return
    let bySkill = perSkillProjectMeta.get(skillKey)
    if (!bySkill) {
      bySkill = new Map()
      perSkillProjectMeta.set(skillKey, bySkill)
    }
    const meta = bySkill.get(projectId) ?? { sources: new Set<string>(), status: "", isPublic: false, publicPath: null }
    for (const src of sources ?? []) meta.sources.add(src)
    if (!meta.status && status) meta.status = status
    if (isPublic) meta.isPublic = true
    if (!meta.publicPath && publicPath) meta.publicPath = publicPath
    // Keep the first safe Website Proof behaviour sentence recorded for this
    // (skill, project) — the strongest_project link and the per-project refs both
    // feed this, and either may carry it.
    if (!meta.websiteSummary && websiteSummary) meta.websiteSummary = websiteSummary
    bySkill.set(projectId, meta)
  }

  // 1 — passport skill aggregates (own the qualitative status when present).
  for (const s of passport.skills) {
    const d = draft(s.skill)
    const skillKey = s.skill.trim().toLowerCase()
    if (!d.status) d.status = s.status
    d.payloadProjectCount = Math.max(d.payloadProjectCount, s.project_count)
    for (const source of s.evidence_sources) d.sources.add(source)
    // Vault-only (standalone) sources come pre-computed by the backend as the
    // proof types that exist for this skill but are attached to NO project.
    for (const source of s.vault_only_sources ?? []) d.vaultOnlySources.add(source)
    for (const ref of s.projects) {
      addProject(d, ref.project_id, ref.project_title)
      recordProjectMeta(
        skillKey,
        resolveProjectId(ref.project_id, ref.project_title),
        // Prefer the skill-specific breakdown; fall back to the project-wide
        // source union only for legacy payloads that predate the field. When the
        // new field is present (even as an empty list) it wins, so a row shows a
        // proof-type chip only where that proof actually supports THIS skill.
        ref.supporting_proof_types ?? ref.evidence_sources,
        ref.skill_status,
        ref.report_is_public,
        ref.public_report_path,
        ref.website_evidence_summary,
      )
    }
    if (s.strongest_project) {
      addProject(d, s.strongest_project.project_id, s.strongest_project.project_title)
      recordProjectMeta(
        skillKey,
        resolveProjectId(s.strongest_project.project_id, s.strongest_project.project_title),
        s.strongest_project.supporting_proof_types ?? s.strongest_project.evidence_sources,
        s.strongest_project.skill_status,
        s.strongest_project.report_is_public,
        s.strongest_project.public_report_path,
        s.strongest_project.website_evidence_summary,
      )
    }
  }

  // 2 — vault skill summaries (slug + proof-source coverage + project ids).
  for (const v of passport.vault_skill_summaries ?? []) {
    const d = draft(v.skill)
    if (!d.slug && v.skill_slug) d.slug = v.skill_slug
    if (!d.status) d.status = v.status
    d.payloadProjectCount = Math.max(d.payloadProjectCount, v.project_count)
    for (const [source, count] of Object.entries(v.proof_source_counts ?? {})) {
      if (count > 0) d.sources.add(source)
    }
    v.project_ids.forEach((id, i) => addProject(d, id, v.project_titles[i]))
  }

  // 3 — project top skills (evidence-backed Project → Skill edges). top_skills
  // are the skills a project *proves*; bare `claimed_skills` are intentionally
  // not linked here so no highlight ever implies unproven evidence.
  for (const p of passport.projects) {
    for (const t of p.top_skills ?? []) {
      const d = draft(t.skill)
      if (!d.status) d.status = t.status
      if (!d.slug && t.skill_slug) d.slug = t.skill_slug
      d.projectIds.add(p.project_id)
    }
  }

  const projectById = new Map(passport.projects.map((p) => [p.project_id, p]))
  const skills: PassportSkillNode[] = [...drafts.entries()].map(([key, d]) => {
    const strongestTitle = strongest[key]?.title?.trim().toLowerCase() ?? null
    const projectMeta = perSkillProjectMeta.get(key)
    // One evidence row per connected (attached) project. `projectIds` only ever
    // holds known ids, so every row resolves to a real project + owner route.
    const projectEvidence: SkillProjectEvidence[] = [...d.projectIds]
      .map((pid): SkillProjectEvidence | null => {
        const proj = projectById.get(pid)
        if (!proj) return null
        const meta = projectMeta?.get(pid)
        const sources = meta ? SKILL_PROOF_TYPE_ORDER.filter((label) => meta.sources.has(label)) : []
        return {
          projectId: pid,
          projectTitle: proj.project_title,
          skillStatus: meta?.status ?? "",
          evidenceSources: sources,
          hasWebsiteProof: sources.includes("Website Proof"),
          websiteEvidenceSummary: sources.includes("Website Proof") ? meta?.websiteSummary : undefined,
          projectHasProjectLevelProof: (proj.evidence_sources?.length ?? 0) > 0,
          reportPath: `/student/vbr/projects/${pid}/report`,
          publicReportPath: meta?.publicPath ?? proj.report.public_path ?? null,
          reportIsPublic: meta?.isPublic ?? proj.report.is_public ?? false,
        }
      })
      .filter((row): row is SkillProjectEvidence => row !== null)
    // Strongest-evidenced project first, then stable by title.
    projectEvidence.sort((a, b) => {
      const aStrong = strongestTitle && a.projectTitle.trim().toLowerCase() === strongestTitle ? 0 : 1
      const bStrong = strongestTitle && b.projectTitle.trim().toLowerCase() === strongestTitle ? 0 : 1
      return aStrong - bStrong || a.projectTitle.localeCompare(b.projectTitle)
    })
    return {
      key,
      name: d.name,
      slug: d.slug || fallbackSkillSlug(d.name),
      status: d.status || "Not assessed",
      proofTypes: SKILL_PROOF_TYPE_ORDER.filter((label) => d.sources.has(label)),
      projectIds: [...d.projectIds],
      projectCount: Math.max(d.projectIds.size, d.payloadProjectCount),
      strongest: strongest[key] ?? null,
      projectEvidence,
      vaultOnlySources: SKILL_PROOF_TYPE_ORDER.filter((label) => d.vaultOnlySources.has(label)),
    }
  })
  skills.sort((a, b) => b.projectIds.length - a.projectIds.length || a.name.localeCompare(b.name))

  const projectSkills = new Map<string, string[]>()
  const skillProjects = new Map<string, string[]>()
  for (const p of passport.projects) projectSkills.set(p.project_id, [])
  for (const node of skills) {
    skillProjects.set(node.key, node.projectIds)
    for (const id of node.projectIds) {
      const list = projectSkills.get(id)
      if (list) list.push(node.key)
    }
  }

  // Proof-type dropdown options: every proof type present ANYWHERE in the
  // passport, normalized to a canonical label. Sourced from the overview counts,
  // project-level attached sources, each skill's sources + vault-only sources,
  // and the skill→project evidence map — so Website Proof (and every other type
  // the candidate actually has) is offered even when the visible skill block does
  // not map it. Selecting one still fails closed to the skill→project rows.
  const presentProofTypes = new Set<CanonicalProofType>()
  const addPresent = (label: string) => {
    const canonical = normalizeProofTypeLabel(label)
    if (canonical) presentProofTypes.add(canonical)
  }
  for (const [label, count] of Object.entries(passport.evidence_source_counts ?? {})) {
    if (count > 0) addPresent(label)
  }
  for (const p of passport.projects) for (const src of p.evidence_sources ?? []) addPresent(src)
  for (const node of skills) {
    for (const src of node.proofTypes) addPresent(src)
    for (const src of node.vaultOnlySources) addPresent(src)
    for (const row of node.projectEvidence) for (const src of row.evidenceSources) addPresent(src)
  }
  const proofTypeOptions = SKILL_PROOF_TYPE_ORDER.filter((label) => presentProofTypes.has(label))

  return { skills, projectSkills, skillProjects, proofTypeOptions }
}
