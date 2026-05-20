import type { EvidenceAccessLink, SkillEvidenceResponse } from "@/lib/api"

export type RecruiterProjectEvidenceBundle = {
  id: string
  projectTitle: string
  note?: string | null
  evidenceItems: SkillEvidenceResponse[]
  githubAccessLinks: EvidenceAccessLink[]
  websiteAccessLinks: EvidenceAccessLink[]
  combinedAccessLinks: EvidenceAccessLink[]
  latestVerificationStatus?: string | null
  summary?: string | null
}

export type RecruiterProofArtifact = {
  icon: string
  label: string
  meta: string
  evidence: {
    backendEvidenceId?: string
    skill: string
    sourceType: string
    evidenceAccessMethod: "public_link" | "upload_file"
    evidenceTitle?: string
    evidenceUrl?: string
    repositoryUrl?: string
    filePath?: string
    startLine?: string
    endLine?: string
    description?: string
    verificationStatus: "Verified" | "Pending review" | "Pending verification" | "Skill usage not found" | "Needs review" | string
    verificationSummary?: string | null
    accessLinks?: EvidenceAccessLink[]
    isRecruiterVisible?: boolean
    requiresApproval?: boolean
    visibilityNote?: string
    uploadedFileName?: string
    uploadedFileType?: string
    uploadedFileSize?: string
    uploadedFileUrl?: string
    linkedInPostUrl?: string
    relatedProjectUrl?: string
    certificateIssuer?: string
    completionDate?: string
    diagramUrl?: string
  }
}

const REAL_PROOF_SUBMISSION_SOURCE = "student_profile_proof_modal"

function readMetadata(evidence: SkillEvidenceResponse): Record<string, unknown> {
  return (evidence.metadata as Record<string, unknown> | null | undefined) ?? {}
}

export function getRecruiterProjectTitle(evidence: SkillEvidenceResponse): string {
  const metadata = readMetadata(evidence)
  const title = typeof metadata.evidence_title === "string" ? metadata.evidence_title.trim() : ""
  return title || evidence.skill_name?.trim() || "Project Evidence"
}

export function isRealSubmittedProofEvidence(evidence: SkillEvidenceResponse): boolean {
  const metadata = readMetadata(evidence)
  const submissionSource = typeof metadata.submission_source === "string" ? metadata.submission_source.trim() : ""
  return submissionSource === REAL_PROOF_SUBMISSION_SOURCE
}

function normalizeTitle(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ")
}

function slugify(value: string): string {
  return normalizeTitle(value)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "project-evidence"
}

function formatStatus(status: string): string {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function getHostname(value?: string | null): string {
  if (!value) return ""
  try {
    return new URL(value).hostname
  } catch {
    return value
  }
}

function buildEvidenceAccessMethod(evidence: SkillEvidenceResponse): "public_link" | "upload_file" {
  return evidence.evidence_type === "github repository" || evidence.evidence_type === "deployed website"
    ? "public_link"
    : "upload_file"
}

function buildEvidenceArtifactIcon(evidence: SkillEvidenceResponse): string {
  if (evidence.evidence_type === "github repository") return "⌥"
  if (evidence.evidence_type === "deployed website") return "▤"
  return "◐"
}

function buildEvidenceArtifactLabel(evidence: SkillEvidenceResponse): string {
  if (evidence.evidence_type === "github repository") return "GitHub code file"
  if (evidence.evidence_type === "deployed website") return "Live website"
  return evidence.evidence_type || "Proof evidence"
}

function buildEvidenceArtifactMeta(evidence: SkillEvidenceResponse): string {
  if (evidence.evidence_type === "github repository") {
    const repo = getHostname(evidence.repository_url ?? evidence.evidence_url ?? "")
    const path = evidence.file_path?.trim() || "code"
    return `${repo || "GitHub"} · ${path}`
  }

  if (evidence.evidence_type === "deployed website") {
    const host = getHostname(evidence.evidence_url ?? "")
    return `${host || "Website"} · public deployed proof`
  }

  return evidence.skill_name
}

function dedupeAccessLinks(links: EvidenceAccessLink[]): EvidenceAccessLink[] {
  const seen = new Set<string>()
  const deduped: EvidenceAccessLink[] = []
  for (const link of links) {
    const key = `${link.access_type}:${normalizeTitle(link.url)}:${link.line_start ?? ""}:${link.line_end ?? ""}`
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(link)
  }
  return deduped
}

export function groupRecruiterProjectEvidenceBundles(
  evidenceRows: SkillEvidenceResponse[],
  accessLinksByEvidenceId: Map<string, EvidenceAccessLink[]>
): RecruiterProjectEvidenceBundle[] {
  const grouped = new Map<
    string,
    {
      projectTitle: string
      evidenceItems: SkillEvidenceResponse[]
      links: EvidenceAccessLink[]
    }
  >()

  for (const evidence of evidenceRows) {
    if (!isRealSubmittedProofEvidence(evidence)) continue

    const projectTitle = getRecruiterProjectTitle(evidence)
    const key = normalizeTitle(projectTitle)
    const links = accessLinksByEvidenceId.get(evidence.id) ?? []
    const existing = grouped.get(key)
    if (existing) {
      existing.evidenceItems.push(evidence)
      existing.links.push(...links)
    } else {
      grouped.set(key, {
        projectTitle,
        evidenceItems: [evidence],
        links: [...links],
      })
    }
  }

  return Array.from(grouped.entries())
    .map(([key, entry]) => {
      const evidenceItems = [...entry.evidenceItems].sort((left, right) => {
        return new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
      })
      const combinedAccessLinks = dedupeAccessLinks(entry.links).filter((link) => link.availability_status === "available")
      const githubAccessLinks = combinedAccessLinks.filter((link) => link.access_type === "github_exact_lines")
      const websiteAccessLinks = combinedAccessLinks.filter((link) => link.access_type === "live_website")
      const latestEvidence = evidenceItems[0] ?? null

      return {
        id: key,
        projectTitle: entry.projectTitle,
        note: latestEvidence?.verification_summary || (latestEvidence ? `Latest status: ${formatStatus(latestEvidence.verification_status)}` : null),
        evidenceItems,
        githubAccessLinks,
        websiteAccessLinks,
        combinedAccessLinks,
        latestVerificationStatus: latestEvidence?.verification_status ?? null,
        summary: latestEvidence?.verification_summary ?? null,
      }
    })
    .sort((left, right) => {
      const leftTime = left.evidenceItems[0] ? new Date(left.evidenceItems[0].created_at).getTime() : 0
      const rightTime = right.evidenceItems[0] ? new Date(right.evidenceItems[0].created_at).getTime() : 0
      return rightTime - leftTime
    })
}

export const buildRecruiterProjectEvidenceBundles = groupRecruiterProjectEvidenceBundles

function buildEvidenceArtifactFromRow(
  evidence: SkillEvidenceResponse,
  links: EvidenceAccessLink[]
): RecruiterProofArtifact | null {
  if (evidence.evidence_type !== "github repository" && evidence.evidence_type !== "deployed website") {
    return null
  }

  const evidenceAccessMethod = buildEvidenceAccessMethod(evidence)
  const verificationSummary = evidence.verification_summary || "Pending review"
  const verificationStatus = formatStatus(evidence.verification_status)
  const title = getRecruiterProjectTitle(evidence)

  return {
    icon: buildEvidenceArtifactIcon(evidence),
    label: buildEvidenceArtifactLabel(evidence),
    meta: buildEvidenceArtifactMeta(evidence),
    evidence: {
      backendEvidenceId: evidence.id,
      skill: evidence.skill_name,
      sourceType: evidence.evidence_type === "github repository" ? "GitHub code file" : "Deployed website",
      evidenceAccessMethod,
      evidenceTitle: title,
      evidenceUrl: evidence.evidence_url ?? evidence.repository_url ?? undefined,
      repositoryUrl: evidence.repository_url ?? undefined,
      filePath: evidence.file_path ?? undefined,
      startLine: typeof evidence.line_start === "number" ? String(evidence.line_start) : undefined,
      endLine: typeof evidence.line_end === "number" ? String(evidence.line_end) : undefined,
      description: evidence.evidence_description ?? undefined,
      verificationStatus,
      verificationSummary,
      accessLinks: links,
      isRecruiterVisible: true,
      requiresApproval: false,
      visibilityNote: "Loaded from backend proof submissions.",
    },
  }
}

export function buildRecruiterProofArtifacts(
  evidenceRows: SkillEvidenceResponse[],
  accessLinksByEvidenceId: Map<string, EvidenceAccessLink[]>
): RecruiterProofArtifact[] {
  return evidenceRows
    .filter(isRealSubmittedProofEvidence)
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime())
    .map((evidence) => buildEvidenceArtifactFromRow(evidence, accessLinksByEvidenceId.get(evidence.id) ?? []))
    .filter((item): item is RecruiterProofArtifact => Boolean(item))
}
