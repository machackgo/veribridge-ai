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
  /** Proof types attached to this project that are NOT mapped to THIS skill —
   *  the project's canonical attached sources minus `evidenceSources`. Pure
   *  presentation split over fields the payload already separates: these render
   *  as the secondary "project-level proof" tier of the row and are never
   *  counted as skill evidence. Canonical order. */
  projectLevelSources: string[]
  /** Owner-only project-report route (always present — projectId is known). */
  reportPath: string
  publicReportPath: string | null
  reportIsPublic: boolean
}

/**
 * Canonical skill→evidence relationship, strongest first. Shared vocabulary
 * between the Skills Evidence Map and the Skill Report so the two never disagree:
 *  • `direct`     — a proof directly supports THIS skill in a project (report
 *                   skill_evidence / project top_skill). Counted as skill evidence.
 *  • `attached`   — the skill's proof is attached to a real project but that
 *                   project never skill-mapped it ("attached, not skill-mapped").
 *                   A project-level relationship — distinguished from direct.
 *  • `vault`      — retained proof exists only in the Proof Vault, attached to no
 *                   project on this passport (vault-only / standalone).
 *  • `suggested`  — no retained proof at all (a derived Skill-Graph/AI signal).
 *                   Never "evidence"; hidden from the default map.
 */
export type SkillRelationship = "direct" | "attached" | "vault" | "suggested"

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
  /** Honest connected-project count: distinct projects with a real, resolvable
   *  evidence relationship to this skill ON THIS PASSPORT. Never inflated by the
   *  Proof Vault summary's raw `project_count` (which counts duplicate-attempt
   *  `vbr_projects` rows and would let an unattached skill read "24 projects"
   *  while showing zero project rows). Vault-only proof does not count here. */
  projectCount: number
  /** Number of distinct proof-source TYPES supporting this skill (attached
   *  project proof + vault-only), so a skill row can honestly state how much
   *  proof backs it — a vault-only skill still shows "N proof sources" instead of
   *  looking empty, and a suggestion with no retained proof shows 0. */
  proofSourceCount: number
  /** Canonical relationship of this skill to its strongest evidence. Drives the
   *  relationship badge, the Relationship-type filter, and whether the skill is a
   *  bare suggestion hidden from the default map. */
  relationship: SkillRelationship
  /** Grouped, on-passport projects the skill's proof is ATTACHED to but which
   *  never skill-mapped it (the "attached, not skill-mapped" tier). Empty for a
   *  direct skill (its projects are in `projectEvidence`) and for vault-only /
   *  suggested skills. Each id resolves to a real project card + owner route. */
  attachedProjects: { projectId: string; projectTitle: string }[]
  /** Non-counting proof→project suggestions for this skill. They are visible in
   *  filters and review UI but never enter `projectIds`, `projectCount`, status,
   *  corroboration, or direct project evidence. */
  suggestedProjects: {
    projectId: string
    projectTitle: string
    proofType: string
    reason: string
    confidenceLabel: string
  }[]
  /** A retained, inspectable proof source backs this skill (not only an AI/Skill-
   *  Graph signal). False → a bare suggestion that must never read as "evidence". */
  hasRetainedProof: boolean
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
  /** Canonical proof-type labels the Proof Vault summary recorded for this skill
   *  (any of its proofs, regardless of attachment). Used ONLY to reveal the real
   *  proof source of a skill whose evidence lives solely in the vault — a skill
   *  with no resolvable project edge — so its GitHub / Document / Website / Defense
   *  proof is never invisible. Never applied to a skill that already has an
   *  attached project edge (that proof is shown on its project row, not as
   *  vault-only). */
  vaultSummaryProofTypes: Set<string>
  /** Grouped, on-passport project id → title the vault summary attaches this skill
   *  to (raw duplicate-attempt rows already resolved by the backend). Used to build
   *  the "attached, not skill-mapped" tier for a skill with no direct edge. */
  vaultConnectedProjects: Map<string, string>
  /** The backend flagged a retained, inspectable proof source for this skill. */
  hasRetainedProof: boolean
  /** This skill carried a vault summary at all (vs. only report/project edges). */
  fromVault: boolean
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
  const projectById = new Map(passport.projects.map((p) => [p.project_id, p]))
  const suggestedBySkill = new Map<string, PassportSkillNode["suggestedProjects"]>()
  for (const suggestion of passport.unattached_proof_summary?.suggestions ?? []) {
    const match = (suggestion.likely_project_ref_safe ?? "").match(/\/student\/vbr\/projects\/([^/]+)\/report/)
    const projectId = match?.[1]
    const proofType = normalizeProofTypeLabel(suggestion.proof_type)
    if (!projectId || !proofType || !knownProjectIds.has(projectId)) continue
    for (const skill of suggestion.likely_skill_names ?? []) {
      const key = skill.trim().toLowerCase()
      if (!key) continue
      const rows = suggestedBySkill.get(key) ?? []
      if (!rows.some((row) => row.projectId === projectId && row.proofType === proofType)) {
        rows.push({
          projectId,
          projectTitle: suggestion.likely_project_title || projectById.get(projectId)?.project_title || "Project",
          proofType,
          reason: suggestion.suggestion_reason,
          confidenceLabel: suggestion.confidence_label,
        })
      }
      suggestedBySkill.set(key, rows)
    }
  }
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
      d = { name: name.trim(), slug: "", status: "", sources: new Set(), projectIds: new Set(), payloadProjectCount: 0, vaultOnlySources: new Set(), vaultSummaryProofTypes: new Set(), vaultConnectedProjects: new Map(), hasRetainedProof: false, fromVault: false }
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

  // 2 — vault skill summaries (slug + status + connected-project COUNT only).
  //
  // FAIL-CLOSED (wider-vault isolation): the vault summary spans a skill's WHOLE
  // proof vault — attached AND unattached proofs, across every project. It must
  // NEVER contribute to the skill's ATTACHED proof-type set (`d.sources`, which
  // feeds `node.proofTypes` + the proof-type chips/filter) nor to its attached
  // project edges (`d.projectIds`). Doing so let a Website Proof living in the
  // wider vault (attached to a *different* project, or standalone) advertise
  // "Website Proof" on a skill / add a spurious project row here — even though the
  // project the row links to never had it attached. Attached proof types and
  // project edges come exclusively from the project-honest surfaces (the skill
  // aggregate refs in step 1 and project `top_skills` in step 3); vault-only proof
  // types are surfaced separately via `vaultOnlySources` (step 1) and the vault
  // section. We take only the skill's slug/status and its connected-project COUNT
  // (a display number, not an attached edge) from the vault summary.
  for (const v of passport.vault_skill_summaries ?? []) {
    const d = draft(v.skill)
    d.fromVault = true
    if (v.has_retained_proof) d.hasRetainedProof = true
    if (!d.slug && v.skill_slug) d.slug = v.skill_slug
    if (!d.status) d.status = v.status
    // Grouped, on-passport projects the backend resolved this skill's vault proof
    // to (duplicate-attempt rows already collapsed). Only ids that are real
    // projects on THIS passport are kept, so a stale id never fronts a dead link.
    const connectedIds = v.connected_project_ids ?? []
    const connectedTitles = v.connected_project_titles ?? []
    connectedIds.forEach((pid, i) => {
      if (knownProjectIds.has(pid)) {
        d.vaultConnectedProjects.set(pid, connectedTitles[i] ?? projectById.get(pid)?.project_title ?? "Project")
      }
    })
    // Record the vault's real proof-source types for this skill. These reveal
    // WHERE a purely-vault skill's evidence came from (GitHub / Document / …) so
    // it is never rendered as an empty "vault-only" row — but they are applied
    // (below) ONLY to skills with no resolvable project edge, so attached proof is
    // never mislabelled vault-only. Non-proof pipeline signals (e.g. "Skill
    // Graph") canonicalize to null and are dropped.
    for (const label of Object.keys(v.proof_source_counts ?? {})) {
      const canonical = normalizeProofTypeLabel(label)
      if (canonical) d.vaultSummaryProofTypes.add(canonical)
    }
    // IMPORTANT (project-count honesty): the vault summary's `project_count`
    // counts distinct raw `vbr_projects` rows a proof is attached to — inflated by
    // duplicate Project Defense attempts of the same real project (e.g. 24 rows
    // for 2 real projects) and non-zero even when NOTHING is attached to a project
    // the map can render. It must never drive the connected-project count, so it
    // is deliberately NOT merged into `payloadProjectCount` here. Connected
    // projects come only from real, resolvable edges (steps 1 & 3) plus the report
    // aggregate's already-grouped `project_count`.
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
        // The project's attached proof that did NOT map to this skill — the
        // honest secondary tier of the row. Canonicalized so variant labels in
        // `evidence_sources` never dodge the subtraction.
        const attachedToProject = new Set<CanonicalProofType>()
        for (const src of proj.evidence_sources ?? []) {
          const canonical = normalizeProofTypeLabel(src)
          if (canonical) attachedToProject.add(canonical)
        }
        const projectLevelSources = SKILL_PROOF_TYPE_ORDER.filter(
          (label) => attachedToProject.has(label) && !sources.includes(label),
        )
        return {
          projectId: pid,
          projectTitle: proj.project_title,
          skillStatus: meta?.status ?? "",
          evidenceSources: sources,
          hasWebsiteProof: sources.includes("Website Proof"),
          websiteEvidenceSummary: sources.includes("Website Proof") ? meta?.websiteSummary : undefined,
          projectHasProjectLevelProof: (proj.evidence_sources?.length ?? 0) > 0,
          projectLevelSources,
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
    const proofTypes = SKILL_PROOF_TYPE_ORDER.filter((label) => d.sources.has(label))
    // Vault-only proof-type chips. When the backend already computed the skill's
    // unattached vault sources (report skills carry `vault_only_sources`), those
    // win. Otherwise, for a skill with NO resolvable project edge, fall back to
    // the vault summary's own proof types so a purely-vault skill still shows its
    // real proof source (GitHub / Document / …) instead of an empty row. A skill
    // that DOES have a project edge never synthesizes vault chips from the summary
    // — its proof belongs on the project row, not the vault-only tier.
    const vaultOnlySources =
      d.vaultOnlySources.size > 0
        ? SKILL_PROOF_TYPE_ORDER.filter((label) => d.vaultOnlySources.has(label))
        : d.projectIds.size === 0
          ? SKILL_PROOF_TYPE_ORDER.filter((label) => d.vaultSummaryProofTypes.has(label))
          : []
    // Distinct proof-source types backing the skill: attached project proof plus
    // any vault-only proof, deduped. Zero only when the skill truly has no
    // retained proof source (a bare suggestion), which the UI can label honestly.
    const proofSourceCount = new Set([...proofTypes, ...vaultOnlySources]).size
    const hasDirect = d.projectIds.size > 0
    // "Attached, not skill-mapped": the skill's vault proof resolves to a real
    // project on this passport, but that project never surfaced it as a top skill
    // (so no direct edge exists). Exclude any project already a direct edge.
    const attachedProjects = hasDirect
      ? []
      : [...d.vaultConnectedProjects.entries()]
          .filter(([pid]) => !d.projectIds.has(pid))
          .map(([projectId, projectTitle]) => ({ projectId, projectTitle }))
    // Does any retained (inspectable) proof source back this skill? True whenever
    // a direct project edge, the skill's own proof-type set, a vault-only chip, or
    // the backend's retained-proof flag says so. False → a bare AI/Skill-Graph
    // suggestion (no GitHub/Document/Website/Defense/Video proof anywhere).
    const hasRetainedProof =
      hasDirect || proofTypes.length > 0 || vaultOnlySources.length > 0 || d.hasRetainedProof
    const relationship: SkillRelationship = hasDirect
      ? "direct"
      : attachedProjects.length > 0
        ? "attached"
        : hasRetainedProof
          ? "vault"
          : "suggested"
    // Honest connected-project count: distinct grouped projects with a real
    // relationship to this skill — direct edges plus attached (not-skill-mapped)
    // projects. Never the inflated raw vault `project_count`. A vault-only or
    // suggested skill has zero.
    const connectedProjectIds = new Set<string>([...d.projectIds, ...attachedProjects.map((a) => a.projectId)])
    return {
      key,
      name: d.name,
      slug: d.slug || fallbackSkillSlug(d.name),
      status: d.status || "Not assessed",
      proofTypes,
      projectIds: [...d.projectIds],
      projectCount: connectedProjectIds.size,
      proofSourceCount,
      relationship,
      attachedProjects,
      suggestedProjects: suggestedBySkill.get(key) ?? [],
      hasRetainedProof,
      strongest: hasDirect ? strongest[key] ?? null : null,
      projectEvidence,
      vaultOnlySources,
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
