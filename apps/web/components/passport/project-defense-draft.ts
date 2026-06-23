/**
 * Project Defense draft persistence.
 *
 * The Project Defense form lives at /student/proofs/project-defense. To attach a
 * Document Proof or Website Proof the student leaves this page entirely (a real
 * route change to /student/proofs/documents or /student/proofs/website), which
 * unmounts the panel and would otherwise discard everything they typed. We keep
 * a small draft in sessionStorage so the form is restored when they return.
 *
 * Only safe form-field values and selected proof IDs are stored — never raw
 * proof data, document text, screenshots, tokens, or storage paths. The draft is
 * scoped to the tab session (sessionStorage), survives client-side and full-page
 * navigations within that tab, and is cleared once the defense is created.
 */

const DRAFT_KEY = "veribridge.projectDefenseDraft.v1"

export type ProjectDefenseDraft = {
  projectTitle: string
  description: string
  claimedSkills: string
  roleContribution: string
  repositoryUrl: string
  selectedGithubProofId: string
  selectedDocumentIds: string[]
  selectedWebsiteProofIds: string[]
}

export function emptyProjectDefenseDraft(): ProjectDefenseDraft {
  return {
    projectTitle: "",
    description: "",
    claimedSkills: "",
    roleContribution: "",
    repositoryUrl: "",
    selectedGithubProofId: "",
    selectedDocumentIds: [],
    selectedWebsiteProofIds: [],
  }
}

/** A draft with no field set is not worth persisting (and must not stick around). */
export function isProjectDefenseDraftEmpty(draft: ProjectDefenseDraft): boolean {
  return (
    !draft.projectTitle.trim() &&
    !draft.description.trim() &&
    !draft.claimedSkills.trim() &&
    !draft.roleContribution.trim() &&
    !draft.repositoryUrl.trim() &&
    !draft.selectedGithubProofId &&
    draft.selectedDocumentIds.length === 0 &&
    draft.selectedWebsiteProofIds.length === 0
  )
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []
}

/** Read and validate the saved draft. Browser-only; never throws. */
export function readProjectDefenseDraft(): ProjectDefenseDraft | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.sessionStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Record<string, unknown>
    if (!parsed || typeof parsed !== "object") return null
    const draft: ProjectDefenseDraft = {
      projectTitle: asString(parsed.projectTitle),
      description: asString(parsed.description),
      claimedSkills: asString(parsed.claimedSkills),
      roleContribution: asString(parsed.roleContribution),
      repositoryUrl: asString(parsed.repositoryUrl),
      selectedGithubProofId: asString(parsed.selectedGithubProofId),
      selectedDocumentIds: asStringArray(parsed.selectedDocumentIds),
      selectedWebsiteProofIds: asStringArray(parsed.selectedWebsiteProofIds),
    }
    return isProjectDefenseDraftEmpty(draft) ? null : draft
  } catch {
    return null
  }
}

/** Persist the draft (only safe form values + selected IDs). Browser-only. */
export function saveProjectDefenseDraft(draft: ProjectDefenseDraft): void {
  if (typeof window === "undefined") return
  try {
    if (isProjectDefenseDraftEmpty(draft)) {
      window.sessionStorage.removeItem(DRAFT_KEY)
      return
    }
    window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
  } catch {
    // Storage may be unavailable (private mode, quota) — drafting is best-effort.
  }
}

/** Drop the saved draft (after successful creation or an explicit "Clear draft"). */
export function clearProjectDefenseDraft(): void {
  if (typeof window === "undefined") return
  try {
    window.sessionStorage.removeItem(DRAFT_KEY)
  } catch {
    // Best-effort.
  }
}
