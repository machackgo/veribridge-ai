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
  const addProject = (d: SkillDraft, projectId?: string | null, projectTitle?: string | null) => {
    if (projectId && knownProjectIds.has(projectId)) {
      d.projectIds.add(projectId)
      return
    }
    // Fail closed on the title-only fallback: only resolve a title that maps to
    // exactly one known project. Ambiguous same-title matches create no edge.
    const key = projectTitle?.trim().toLowerCase()
    if (!key) return
    const ids = titleToIds.get(key)
    if (ids && ids.size === 1) d.projectIds.add([...ids][0])
  }

  // 1 — passport skill aggregates (own the qualitative status when present).
  for (const s of passport.skills) {
    const d = draft(s.skill)
    if (!d.status) d.status = s.status
    d.payloadProjectCount = Math.max(d.payloadProjectCount, s.project_count)
    for (const source of s.evidence_sources) d.sources.add(source)
    for (const ref of s.projects) addProject(d, ref.project_id, ref.project_title)
    if (s.strongest_project) addProject(d, s.strongest_project.project_id, s.strongest_project.project_title)
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

  const skills: PassportSkillNode[] = [...drafts.entries()].map(([key, d]) => ({
    key,
    name: d.name,
    slug: d.slug || fallbackSkillSlug(d.name),
    status: d.status || "Not assessed",
    proofTypes: SKILL_PROOF_TYPE_ORDER.filter((label) => d.sources.has(label)),
    projectIds: [...d.projectIds],
    projectCount: Math.max(d.projectIds.size, d.payloadProjectCount),
    strongest: strongest[key] ?? null,
  }))
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
