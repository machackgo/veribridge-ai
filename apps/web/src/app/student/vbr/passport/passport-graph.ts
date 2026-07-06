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
}

export type PassportGraph = {
  skills: PassportSkillNode[]
  /** project_id → connected skill keys. */
  projectSkills: Map<string, string[]>
  /** skill key → connected project ids. */
  skillProjects: Map<string, string[]>
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
      d = { name: name.trim(), slug: "", status: "", sources: new Set(), projectIds: new Set(), payloadProjectCount: 0 }
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
  }
  const perSkillProjectMeta = new Map<string, Map<string, ProjEvidenceMeta>>()
  const recordProjectMeta = (
    skillKey: string,
    projectId: string | null,
    sources: string[] | undefined,
    status: string | undefined,
    isPublic: boolean | undefined,
    publicPath: string | null | undefined,
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
    bySkill.set(projectId, meta)
  }

  // 1 — passport skill aggregates (own the qualitative status when present).
  for (const s of passport.skills) {
    const d = draft(s.skill)
    const skillKey = s.skill.trim().toLowerCase()
    if (!d.status) d.status = s.status
    d.payloadProjectCount = Math.max(d.payloadProjectCount, s.project_count)
    for (const source of s.evidence_sources) d.sources.add(source)
    for (const ref of s.projects) {
      addProject(d, ref.project_id, ref.project_title)
      recordProjectMeta(
        skillKey,
        resolveProjectId(ref.project_id, ref.project_title),
        ref.evidence_sources,
        ref.skill_status,
        ref.report_is_public,
        ref.public_report_path,
      )
    }
    if (s.strongest_project) {
      addProject(d, s.strongest_project.project_id, s.strongest_project.project_title)
      recordProjectMeta(
        skillKey,
        resolveProjectId(s.strongest_project.project_id, s.strongest_project.project_title),
        s.strongest_project.evidence_sources,
        s.strongest_project.skill_status,
        s.strongest_project.report_is_public,
        s.strongest_project.public_report_path,
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

  return { skills, projectSkills, skillProjects }
}
