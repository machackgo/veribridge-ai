/**
 * Pure deterministic logic for the /student dashboard (consolidation Stage 2).
 * Kept outside the route file so it can be unit-tested and because Next.js
 * route files may only export route-recognized symbols.
 */

import type { VBRProjectResponse, WorkPassportStatus } from "@/lib/vbr-api"
import type {
  DocumentProofResponse,
  GitHubProofResponse,
  WebsiteProofSummaryResponse,
} from "@/lib/passport-api"
import type { SkillGapsOverviewResponse } from "@/lib/skill-gaps-api"

export function isDefenseProject(project: VBRProjectResponse): boolean {
  return project.metadata?.phase === "project_defense_mvp_v1"
}

export type ProofWorkflowState =
  | "Not started"
  | "In progress"
  | "Processing"
  | "Complete"
  | "Failed / retry available"

/** Closed-vocabulary rollup of raw backend status strings for one proof type. */
export function summarizeProofStatuses(statuses: string[]): ProofWorkflowState {
  if (statuses.length === 0) return "Not started"
  const lower = statuses.map((s) => (s ?? "").toLowerCase())
  if (lower.some((s) => s.includes("fail") || s.includes("error"))) return "Failed / retry available"
  if (lower.some((s) => s.includes("analyzing") || s.includes("processing") || s.includes("transcrib")))
    return "Processing"
  if (lower.some((s) => s.includes("pending") || s.includes("submitted") || s.includes("draft") || s.includes("created")))
    return "In progress"
  return "Complete"
}

export type NextAction = { label: string; description: string; href: string }

/**
 * One deterministic next action from real current state. First matching rule
 * wins; every rule reads only existing records — no LLM, no scores.
 */
export function deriveNextAction(input: {
  projects: VBRProjectResponse[] | null
  githubProofs: GitHubProofResponse[] | null
  websiteProofs: WebsiteProofSummaryResponse[] | null
  documentProofs: DocumentProofResponse[] | null
  gaps: SkillGapsOverviewResponse | null
  passport: WorkPassportStatus | null
  resumableSessionId: string | null
}): NextAction {
  const projects = input.projects ?? []
  const github = input.githubProofs ?? []
  const website = input.websiteProofs ?? []
  const documents = input.documentProofs ?? []

  const nothingYet =
    projects.length === 0 && github.length === 0 && website.length === 0 && documents.length === 0
  if (nothingYet) {
    return {
      label: "Add your first proof",
      description: "Start with a GitHub repository — VeriBridge will detect skills from your code.",
      href: "/student/proofs/github",
    }
  }

  if (github.some((p) => summarizeProofStatuses([p.status]) === "Failed / retry available")) {
    return {
      label: "Retry GitHub Proof",
      description: "A GitHub proof analysis failed — open it to retry.",
      href: "/student/proofs/github",
    }
  }

  if (input.resumableSessionId) {
    return {
      label: "Resume walkthrough recording",
      description: "You have an unfinished walkthrough session — pick up where you left off.",
      href: `/student/vbr/sessions/${input.resumableSessionId}`,
    }
  }

  const pendingDefense = projects.find(
    (p) => isDefenseProject(p) && p.metadata?.project_defense_status !== "analyzed"
  )
  if (pendingDefense) {
    return {
      label: "Complete Project Defense",
      description: `Finish defending “${pendingDefense.title}” to add explanation evidence.`,
      href: "/student/proofs/project-defense",
    }
  }

  if ((input.gaps?.total_gap_count ?? 0) > 0) {
    return {
      label: "Review Skill Gaps",
      description: "Some claimed skills still lack evidence — see exactly what's missing.",
      href: "/dashboard/skill-gaps",
    }
  }

  if (input.passport && !input.passport.is_published) {
    return {
      label: "Review & publish your Work Passport",
      description: "Your proof sources are in — review your passport and publish it for recruiters.",
      href: "/student/vbr/passport",
    }
  }

  if (input.passport?.is_published) {
    return {
      label: "View your published Work Passport",
      description: "Your passport is live — open it to share or keep adding evidence.",
      href: "/student/vbr/passport",
    }
  }

  return {
    label: "Open Work Passport",
    description: "See how your proof sources come together as verified skills.",
    href: "/student/vbr/passport",
  }
}
