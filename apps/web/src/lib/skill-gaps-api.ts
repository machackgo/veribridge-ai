/**
 * Evidence-derived Skill Gaps API client.
 *
 * Backed by GET /api/v1/student/skill-gaps — a deterministic, owner-scoped
 * computation over stored evidence (claimed skills, canonical skill claims +
 * evidence links, completed website workflow analyses). No AI, no market
 * data, no fabricated readiness numbers.
 */

import { fetchAPI } from "./api"

export type SkillGapStatus =
  | "missing_evidence"
  | "partially_demonstrated"
  | "not_assessed"
  | "insufficient_evidence"

export type EvidenceBasisEntry = {
  kind: "claim_link" | "website_analysis" | "claimed_skill"
  reference_id: string
  proof_type: string | null
  proof_id: string | null
  citation_type: string | null
  link_status: string | null
  evidence_quality: string | null
  detail: string
  limitations: string[]
}

export type SkillGapItem = {
  skill_name: string
  skill_key: string
  status: SkillGapStatus
  status_label: string
  why: string
  evidence_basis: EvidenceBasisEntry[]
  recommended_action: string
  claim_id: string | null
}

export type ProjectSkillGapSummary = {
  total_claimed: number
  demonstrated: number
  partially_demonstrated: number
  insufficient_evidence: number
  missing_evidence: number
  not_assessed: number
}

export type ProjectSkillGapReport = {
  project_id: string
  project_title: string
  assessment_state: "assessed" | "insufficient_evidence"
  insufficient_evidence_note: string | null
  claimed_skills: string[]
  demonstrated_skills: string[]
  gap_items: SkillGapItem[]
  summary: ProjectSkillGapSummary
}

export type SkillGapsOverviewResponse = {
  projects: ProjectSkillGapReport[]
  total_gap_count: number
  generated_at: string
}

export async function getSkillGapsOverview(): Promise<SkillGapsOverviewResponse> {
  const res = await fetchAPI("/api/v1/student/skill-gaps")
  if (!res.ok) throw new Error(`Failed to load skill gaps (HTTP ${res.status}).`)
  return res.json()
}

/** Route to the evidence surface backing a basis entry, when one exists. */
export function evidenceBasisHref(entry: EvidenceBasisEntry): string | null {
  if (entry.kind === "website_analysis" && entry.proof_id) {
    return `/student/proofs/website?session=${encodeURIComponent(entry.proof_id)}`
  }
  if (entry.kind === "claim_link") {
    if (entry.proof_type === "document") return "/student/proofs/documents"
    if (entry.proof_type === "github") return "/student/proofs/github"
    if (entry.proof_type === "website" && entry.proof_id) {
      return `/student/proofs/website?session=${encodeURIComponent(entry.proof_id)}`
    }
  }
  return null
}
