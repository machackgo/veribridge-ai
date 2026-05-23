"use client"

import { createPortal } from "react-dom"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { CSSProperties } from "react"
import {
  createGithubRecruiterProofReport,
  createGithubSemanticVerificationResult,
  createSkillEvidence,
  createWebsiteSemanticVerificationResult,
  createWebsiteVerificationGuide,
  executeWebsiteBrowserVerificationRun,
  executeWebsiteVerificationRun,
  generateEvidenceAccessLinks,
  generateWebsiteVerificationPlan,
  listSkillEvidence,
  updateSkillEvidence,
  type SkillEvidenceResponse,
} from "@/lib/api"
import {
  formatProofDisplayLabel,
  reconcileProofVerificationDisplayState,
  type ProofVerificationReconciliation,
} from "./proof-verification-status"
import { GitHubPortfolioScanPanel } from "./github-portfolio-scan-panel"
import { SkillProofCenter } from "./skill-proof-center"
import { WebsiteAIAnalyzerPanel } from "./website-ai-analyzer-panel"
import {
  MultiSourceProofForm,
  SourceTypeSelector,
} from "./multi-source-proof-form"
import { ProofProcessingProgressPanel } from "./proof-processing-progress-panel"
import {
  createManualGitHubSaveSteps,
  createWebsiteSaveSteps,
  createAgentLinkSaveSteps,
  completeStep,
  failStep,
  initialProgress,
  startStep,
  type ProofProcessingProgress,
} from "@/lib/proof-processing"
import {
  type EvidenceSourceType,
  sourceTypeToEvidenceType,
  sourceTypeToBadgeLabel,
  parseTimestampToSeconds,
  formatSecondsAsTimestamp,
  buildYouTubeTimestampUrl,
} from "@/lib/evidence-sources"

type SubmissionTab = "github" | "website"
type ProofModalMode = "select" | "manual" | "ai_agent"
type ManualFlowStep = "source_select" | "form"

type SubmissionSummary = {
  title: string
  message: string
  notes: string[]
}

type GitHubFormState = {
  skillName: string
  projectTitle: string
  claim: string
  repositoryUrl: string
  filePath: string
  startLine: string
  endLine: string
  branchRef: string
  notes: string
}

type WebsiteFormState = {
  skillName: string
  projectTitle: string
  websiteUrl: string
  featureToVerify: string
  expectedOutput: string
  verificationSteps: string
  notes: string
}

const initialGitHubForm = (): GitHubFormState => ({
  skillName: "",
  projectTitle: "",
  claim: "",
  repositoryUrl: "",
  filePath: "",
  startLine: "",
  endLine: "",
  branchRef: "",
  notes: "",
})

const initialWebsiteForm = (): WebsiteFormState => ({
  skillName: "",
  projectTitle: "",
  websiteUrl: "",
  featureToVerify: "",
  expectedOutput: "",
  verificationSteps: "Open the deployed site\nFollow the primary user flow\nConfirm the expected output appears",
  notes: "",
})

function countWords(text: string): number {
  return (text || "").trim().match(/[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?/g)?.length ?? 0
}

function isPublicHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.hostname)
  } catch {
    return false
  }
}

function normalizeLineNumber(value: string): number | null {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : null
}


function buildEvidenceMetadataUpdate(
  existingMetadata: Record<string, unknown> | undefined,
  reconciliation: ProofVerificationReconciliation,
  extra: Record<string, unknown>
): Record<string, unknown> {
  return {
    ...(existingMetadata ?? {}),
    ...extra,
    verification_display_status: reconciliation.displayStatus,
    verification_display_label: reconciliation.shortDisplayLabel,
    verification_review_recommended: reconciliation.reviewRecommended,
    verification_confidence_band: reconciliation.confidenceBand,
    verification_display_message: reconciliation.studentFacingMessage,
    recruiter_verification_message: reconciliation.recruiterFacingMessage,
    proof_verification_reconciliation: reconciliation,
  }
}

function buildGitHubProofReconciliation(params: {
  baseStatus: string
  semanticStatus?: string | null
  reportStatus?: string | null
  report?: { missing_capabilities?: Array<Record<string, unknown>>; confirmed_capabilities?: Array<Record<string, unknown>> } | null
  semanticSegments?: Array<Record<string, unknown>> | null
}): ProofVerificationReconciliation {
  const missingCriticalRequirements = Boolean(
    (params.report?.missing_capabilities ?? []).some((item) => String(item["importance"] ?? "") === "critical")
  )
  const capabilityMatchStatus = missingCriticalRequirements
    ? "partial_capability_match"
    : params.semanticStatus === "verified" || params.reportStatus === "verified"
      ? "strong_capability_match"
      : "partial_capability_match"
  const blocksFullVerification = Boolean(
    params.reportStatus === "not_verified" ||
      params.semanticStatus === "not_verified" ||
      missingCriticalRequirements ||
      ((params.report?.missing_capabilities?.length ?? 0) > 0 && params.semanticStatus !== "verified" && params.reportStatus !== "verified")
  )
  return reconcileProofVerificationDisplayState({
    available: true,
    baseEvidenceStatus: params.baseStatus,
    semanticStatus: params.semanticStatus,
    reportStatus: params.reportStatus,
    capabilityMatchStatus,
    missingCriticalRequirements,
    blocksFullVerification,
    supportingEvidence: Boolean((params.semanticSegments?.length ?? 0) > 0 || (params.report?.confirmed_capabilities?.length ?? 0) > 0),
  })
}

function buildWebsiteProofReconciliation(params: {
  baseStatus: string
  semanticStatus?: string | null
  browserStatus?: string | null
  staticStatus?: string | null
  expectedOutputMatchStatus?: string | null
  expectedOutputBlocksVerification?: boolean
  semanticSourceSnapshot?: Record<string, unknown> | null
}): ProofVerificationReconciliation {
  return reconcileProofVerificationDisplayState({
    available: true,
    baseEvidenceStatus: params.baseStatus,
    semanticStatus: params.semanticStatus,
    browserStatus: params.browserStatus,
    staticStatus: params.staticStatus,
    expectedOutputMatchStatus: params.expectedOutputMatchStatus,
    expectedOutputBlocksVerification: params.expectedOutputBlocksVerification,
    supportingEvidence: Boolean(params.semanticSourceSnapshot?.semantic_similarity || params.semanticSourceSnapshot?.expected_output_match),
  })
}

async function runGitHubSubmission(
  form: GitHubFormState,
  refreshEvidence: () => Promise<void>
): Promise<SubmissionSummary> {
  const createdEvidence = await createSkillEvidence({
    skill_name: form.skillName.trim(),
    evidence_type: "github repository",
    repository_url: form.repositoryUrl.trim(),
    file_path: form.filePath.trim(),
    line_start: normalizeLineNumber(form.startLine) ?? undefined,
    line_end: normalizeLineNumber(form.endLine) ?? undefined,
    evidence_description: form.claim.trim(),
    metadata: {
      proof_kind: "github_code",
      evidence_title: form.projectTitle.trim(),
      submission_source: "student_profile_proof_modal",
      branch_ref: form.branchRef.trim() || undefined,
      notes: form.notes.trim() || undefined,
    },
  })

  const notes: string[] = [`Created GitHub evidence row ${createdEvidence.id}.`]
  let semanticResult: Awaited<ReturnType<typeof createGithubSemanticVerificationResult>> | null = null
  let report: Awaited<ReturnType<typeof createGithubRecruiterProofReport>> | null = null

  try {
    semanticResult = await createGithubSemanticVerificationResult(createdEvidence.id)
    try {
      report = await createGithubRecruiterProofReport(createdEvidence.id, semanticResult.id)
    } catch (error) {
      report = null
      notes.push(`Recruiter report could not be generated yet: ${error instanceof Error ? error.message : "unknown error"}`)
    }
  } catch (error) {
    semanticResult = null
    notes.push(`GitHub semantic verification could not run yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  try {
    const links = await generateEvidenceAccessLinks(createdEvidence.id)
    notes.push(`Generated ${links.length} direct evidence access link${links.length === 1 ? "" : "s"}.`)
  } catch (error) {
    notes.push(`Direct evidence links could not be generated yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  const reconciliation = buildGitHubProofReconciliation({
    baseStatus: createdEvidence.verification_status,
    semanticStatus: semanticResult?.semantic_status,
    reportStatus: report?.report_status,
    report,
    semanticSegments: semanticResult?.matched_segments ?? null,
  })

  try {
    await updateSkillEvidence(createdEvidence.id, {
      metadata: buildEvidenceMetadataUpdate(createdEvidence.metadata as Record<string, unknown> | undefined, reconciliation, {
        latest_semantic_status: semanticResult?.semantic_status ?? null,
        latest_report_status: report?.report_status ?? null,
      }),
    })
  } catch (error) {
    notes.push(`Proof status labels could not be reconciled yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  notes.unshift(`Claim verification: ${formatProofDisplayLabel(reconciliation.displayStatus, "student")}.`)

  await refreshEvidence()

  return {
    title: "GitHub proof submitted successfully.",
    message: reconciliation.studentFacingMessage,
    notes,
  }
}

function splitVerificationSteps(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((step) => step.trim())
    .filter(Boolean)
}

async function runWebsiteSubmission(
  form: WebsiteFormState,
  refreshEvidence: () => Promise<void>
): Promise<SubmissionSummary> {
  const createdEvidence = await createSkillEvidence({
    skill_name: form.skillName.trim(),
    evidence_type: "deployed website",
    evidence_url: form.websiteUrl.trim(),
    evidence_description: form.featureToVerify.trim(),
    metadata: {
      proof_kind: "website_live_demo",
      evidence_title: form.projectTitle.trim(),
      submission_source: "student_profile_proof_modal",
      notes: form.notes.trim() || undefined,
    },
  })

  const notes: string[] = [`Created website evidence row ${createdEvidence.id}.`]
  let websiteReconciliation: ProofVerificationReconciliation | null = null
  let staticRunStatus: string | null = null
  let browserRunStatus: string | null = null
  const guidePayload = {
    project_overview: form.projectTitle.trim() || null,
    feature_to_verify: form.featureToVerify.trim(),
    verification_steps: splitVerificationSteps(form.verificationSteps),
    expected_output: form.expectedOutput.trim(),
    login_required: false,
    access_notes: form.notes.trim() || null,
  }

  const guide = await createWebsiteVerificationGuide(createdEvidence.id, guidePayload)
  notes.push(`Saved website verification guide (${guide.id}).`)

  let planId: string | null = null
  try {
    const plan = await generateWebsiteVerificationPlan(createdEvidence.id)
    planId = plan.id
    notes.push(`Generated website verification plan (${plan.plan_status}).`)
  } catch (error) {
    notes.push(`Website verification plan could not be generated yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  let staticRunId: string | null = null
  try {
    const staticRun = await executeWebsiteVerificationRun(createdEvidence.id, planId)
    staticRunId = staticRun.id
    staticRunStatus = staticRun.execution_status
    notes.push(`Static verification run completed (${staticRun.execution_status}).`)
  } catch (error) {
    notes.push(`Static verification run could not complete: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  let browserRunId: string | null = null
  try {
    const browserRun = await executeWebsiteBrowserVerificationRun(createdEvidence.id, planId)
    browserRunId = browserRun.id
    browserRunStatus = browserRun.browser_execution_status
    notes.push(`Browser verification run completed (${browserRun.browser_execution_status}).`)
  } catch (error) {
    notes.push(`Browser verification run could not complete: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  try {
    const semantic = await createWebsiteSemanticVerificationResult(createdEvidence.id, {
      plan_id: planId,
      static_run_id: staticRunId,
      browser_run_id: browserRunId,
    })
    const snapshot = (semantic.source_snapshot || {}) as Record<string, unknown>
    const expectedOutputMatch = (snapshot.expected_output_match as Record<string, unknown> | undefined) ?? {}
    websiteReconciliation = buildWebsiteProofReconciliation({
      baseStatus: createdEvidence.verification_status,
      semanticStatus: semantic.semantic_status,
      browserStatus: browserRunStatus,
      staticStatus: staticRunStatus,
      expectedOutputMatchStatus: typeof expectedOutputMatch.label === "string" ? expectedOutputMatch.label : null,
      expectedOutputBlocksVerification: Boolean(expectedOutputMatch.blocks_full_verification),
      semanticSourceSnapshot: snapshot,
    })
    notes.push(`Claim verification: ${formatProofDisplayLabel(websiteReconciliation.displayStatus, "student")}.`)

    try {
      await updateSkillEvidence(createdEvidence.id, {
        metadata: buildEvidenceMetadataUpdate(createdEvidence.metadata as Record<string, unknown> | undefined, websiteReconciliation, {
          latest_semantic_status: semantic.semantic_status,
          latest_static_run_status: staticRunId ? "available" : null,
          latest_browser_run_status: browserRunId ? "available" : null,
        }),
      })
    } catch (error) {
      notes.push(`Proof status labels could not be reconciled yet: ${error instanceof Error ? error.message : "unknown error"}`)
    }
  } catch (error) {
    notes.push(`Website semantic result could not be created yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  try {
    const links = await generateEvidenceAccessLinks(createdEvidence.id)
    notes.push(`Generated ${links.length} direct evidence access link${links.length === 1 ? "" : "s"}.`)
  } catch (error) {
    notes.push(`Direct evidence links could not be generated yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  await refreshEvidence()

  return {
    title: "Website proof submitted successfully.",
    message: websiteReconciliation?.studentFacingMessage ?? "VeriBridge created the website proof record and generated the verification workflow.",
    notes,
  }
}

export function StudentProofSubmissionPanel({
  notify,
}: {
  notify?: (message: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [scanOpen, setScanOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<SubmissionTab>("github")
  const [loadingEvidence, setLoadingEvidence] = useState(true)
  const [evidence, setEvidence] = useState<SkillEvidenceResponse[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [submissionSummary, setSubmissionSummary] = useState<SubmissionSummary | null>(null)
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [submissionProgress, setSubmissionProgress] = useState<ProofProcessingProgress | null>(null)
  const [githubForm, setGitHubForm] = useState<GitHubFormState>(initialGitHubForm)
  const [websiteForm, setWebsiteForm] = useState<WebsiteFormState>(initialWebsiteForm)
  // Mode selection state (J4B)
  const [proofMode, setProofMode] = useState<ProofModalMode>("select")
  const [manualStep, setManualStep] = useState<ManualFlowStep>("source_select")
  const [selectedSourceType, setSelectedSourceType] = useState<EvidenceSourceType | null>(null)
  // Website AI Analyzer (J4D) — shown inline in AI Agent mode
  const [showWebsiteAnalyzer, setShowWebsiteAnalyzer] = useState(false)
  // AI Agent simple resource form state (J4B fix)
  const [agentSourceType, setAgentSourceType] = useState<EvidenceSourceType | null>(null)
  const [agentUrl, setAgentUrl] = useState("")
  const [agentSkillFocus, setAgentSkillFocus] = useState("")
  const [agentTimestampStart, setAgentTimestampStart] = useState("")
  const [agentTimestampEnd, setAgentTimestampEnd] = useState("")
  const [agentTranscript, setAgentTranscript] = useState("")
  // Website analyzer owns its form fields in the parent so they survive panel remounts
  const [agentGithubRepoUrl, setAgentGithubRepoUrl] = useState("")
  const [agentFunctionalTestPlan, setAgentFunctionalTestPlan] = useState<{
    whatToTest: string; testInput: string; expectedOutput: string
    frontendUrl: string; browserWorkflowInstructions: string
    runApiVerification: boolean; runBrowserVerification: boolean
  }>({ whatToTest: "", testInput: "", expectedOutput: "", frontendUrl: "", browserWorkflowInstructions: "", runApiVerification: true, runBrowserVerification: true })
  // Pre-fills the scan panel when opened from AI Agent mode
  const [pendingScanUrl, setPendingScanUrl] = useState("")

  // Modal content ref — used to scroll to top on open
  const modalContentRef = useRef<HTMLDivElement>(null)

  const refreshEvidence = useCallback(async () => {
    setLoadingEvidence(true)
    try {
      const results = await listSkillEvidence()
      setEvidence(results)
    } catch {
      setEvidence([])
    } finally {
      setLoadingEvidence(false)
    }
  }, [])

  useEffect(() => {
    void refreshEvidence()
  }, [refreshEvidence])

  useEffect(() => {
    if (!open) {
      setSubmissionSummary(null)
      setSubmissionError(null)
      setSubmitting(false)
    }
  }, [open])

  // Lock body scroll while modal is open; scroll modal content to top on each open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden"
      modalContentRef.current?.scrollTo({ top: 0 })
    } else {
      document.body.style.overflow = ""
    }
    return () => { document.body.style.overflow = "" }
  }, [open])

  function closeModal() {
    setOpen(false)
    setActiveTab("github")
    setSubmissionSummary(null)
    setSubmissionError(null)
    setGitHubForm(initialGitHubForm())
    setWebsiteForm(initialWebsiteForm())
    setProofMode("select")
    setManualStep("source_select")
    setSelectedSourceType(null)
    setSubmissionProgress(null)
    setShowWebsiteAnalyzer(false)
    resetAgentForm()
  }

  function resetAgentForm() {
    setAgentSourceType(null)
    setAgentUrl("")
    setAgentSkillFocus("")
    setAgentGithubRepoUrl("")
    setAgentFunctionalTestPlan({ whatToTest: "", testInput: "", expectedOutput: "", frontendUrl: "", browserWorkflowInstructions: "", runApiVerification: true, runBrowserVerification: true })
    setAgentTimestampStart("")
    setAgentTimestampEnd("")
    setAgentTranscript("")
    setShowWebsiteAnalyzer(false)
    setSubmissionError(null)
  }

  async function handleAgentSubmit() {
    if (!agentSourceType) return
    setSubmissionError(null)

    // GitHub: close modal and open the scan panel pre-filled with the URL
    if (agentSourceType === "github_repository") {
      setPendingScanUrl(agentUrl.trim())
      closeModal()
      setTimeout(() => setScanOpen(true), 50)
      return
    }

    // All other sources: save as lightweight link evidence
    const skill = agentSkillFocus.trim()
    if (!skill) {
      setSubmissionError("Enter the skill this evidence relates to.")
      return
    }
    const url = agentUrl.trim()

    const meta: Record<string, unknown> = {
      evidence_title: `${skill} — ${sourceTypeToBadgeLabel(agentSourceType)} link`,
      submission_source: "student_ai_agent_mode",
      proof_kind: agentSourceType,
      extraction_status: "queued",
    }

    if (agentSourceType === "youtube_demo") {
      const startSec = parseTimestampToSeconds(agentTimestampStart)
      const endSec = parseTimestampToSeconds(agentTimestampEnd)
      if (startSec !== null) {
        meta.timestamp_start_seconds = startSec
        meta.timestamp_start_formatted = formatSecondsAsTimestamp(startSec)
      }
      if (endSec !== null) {
        meta.timestamp_end_seconds = endSec
        meta.timestamp_end_formatted = formatSecondsAsTimestamp(endSec)
      }
      if (agentTranscript.trim()) meta.transcript_snippet = agentTranscript.trim()
    }

    const evidenceUrl = agentSourceType === "youtube_demo" && url
      ? (() => {
          const startSec = parseTimestampToSeconds(agentTimestampStart)
          return startSec !== null ? buildYouTubeTimestampUrl(url, startSec) : url
        })()
      : url || null

    const payload: import("@/lib/api").SkillEvidencePayload = {
      skill_name: skill,
      evidence_type: sourceTypeToEvidenceType(agentSourceType),
      evidence_url: evidenceUrl,
      evidence_description: `AI Agent: ${sourceTypeToBadgeLabel(agentSourceType)} evidence saved for future extraction. Skill: ${skill}.`,
      proof_visibility: "public",
      metadata: meta,
    }

    await handleGenericSubmit(payload)
    resetAgentForm()
  }

  function handleSourceSelect(sourceType: EvidenceSourceType) {
    setSelectedSourceType(sourceType)
    if (sourceType === "github_repository") {
      setActiveTab("github")
    } else if (sourceType === "deployed_website") {
      setActiveTab("website")
    }
    setManualStep("form")
    setSubmissionError(null)
  }

  async function handleGenericSubmit(payload: import("@/lib/api").SkillEvidencePayload) {
    setSubmitting(true)
    setSubmissionError(null)

    const steps = createAgentLinkSaveSteps()
    let prog = initialProgress(completeStep(steps, "read"))
    prog = { ...prog, steps: startStep(prog.steps, "save") }
    setSubmissionProgress(prog)

    try {
      const ev = await createSkillEvidence(payload)

      prog = { ...prog, steps: completeStep(prog.steps, "save") }
      prog = { ...prog, steps: completeStep(prog.steps, "queue") }
      setSubmissionProgress(prog)

      try {
        await generateEvidenceAccessLinks(ev.id)
      } catch { /* best-effort */ }

      await refreshEvidence()

      prog = { ...prog, steps: completeStep(prog.steps, "links") }
      prog = { ...prog, steps: completeStep(prog.steps, "refresh") }

      const sourceName = typeof payload.metadata === "object" && payload.metadata !== null
        ? String((payload.metadata as Record<string, unknown>).proof_kind ?? payload.evidence_type)
        : payload.evidence_type

      prog = {
        ...prog,
        steps: completeStep(prog.steps, "complete", {
          description: `${sourceName} link saved for "${payload.skill_name}".`,
        }),
        overallStatus: "completed",
        savedCount: 1,
      }
      setSubmissionProgress(prog)

      setSubmissionSummary({
        title: "Proof evidence saved.",
        message: `Your ${sourceName} proof for "${payload.skill_name}" has been added to your Skill Proof Center.`,
        notes: ["AI verification or extraction will run in upcoming phases for this source type."],
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Submission failed."
      prog = { ...prog, steps: failStep(prog.steps, "save", msg), overallStatus: "failed", failedCount: 1, errorMessages: [msg] }
      setSubmissionProgress(prog)
      setSubmissionError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSubmit() {
    setSubmissionError(null)
    setSubmissionSummary(null)

    if (activeTab === "github") {
      if (!githubForm.skillName.trim()) {
        setSubmissionError("Choose a skill to prove.")
        return
      }
      if (!githubForm.repositoryUrl.trim() || !isPublicHttpUrl(githubForm.repositoryUrl.trim())) {
        setSubmissionError("Enter a valid public GitHub repository URL.")
        return
      }
      if (!githubForm.filePath.trim()) {
        setSubmissionError("Enter the file path inside the repository.")
        return
      }
      const start = normalizeLineNumber(githubForm.startLine)
      const end = normalizeLineNumber(githubForm.endLine)
      if (!start || start < 1) {
        setSubmissionError("Start line must be 1 or greater.")
        return
      }
      if (!end || end < start) {
        setSubmissionError("End line must be the same as or greater than the start line.")
        return
      }
      if (!githubForm.claim.trim()) {
        setSubmissionError("Describe what this code proves.")
        return
      }
    } else {
      if (!websiteForm.skillName.trim()) {
        setSubmissionError("Choose a skill to prove.")
        return
      }
      if (!websiteForm.websiteUrl.trim() || !isPublicHttpUrl(websiteForm.websiteUrl.trim())) {
        setSubmissionError("Enter a valid public website URL.")
        return
      }
      if (countWords(websiteForm.featureToVerify) < 20) {
        setSubmissionError("Feature description must contain at least 20 words.")
        return
      }
      if (countWords(websiteForm.expectedOutput) < 8) {
        setSubmissionError("Expected output must contain at least 8 words.")
        return
      }
      if (splitVerificationSteps(websiteForm.verificationSteps).length === 0) {
        setSubmissionError("Add at least one verification step.")
        return
      }
    }

    setSubmitting(true)
    const isGitHub = activeTab === "github"
    const steps = isGitHub ? createManualGitHubSaveSteps() : createWebsiteSaveSteps()

    // Step 1: validate already passed above
    let prog = initialProgress(completeStep(steps, "validate"))
    setSubmissionProgress(prog)

    // Step 2: save + verify (single async call wraps both)
    prog = { ...prog, steps: startStep(prog.steps, "save") }
    setSubmissionProgress(prog)

    try {
      const summary = isGitHub
        ? await runGitHubSubmission(githubForm, refreshEvidence)
        : await runWebsiteSubmission(websiteForm, refreshEvidence)

      prog = { ...prog, steps: completeStep(prog.steps, "save") }
      prog = { ...prog, steps: completeStep(prog.steps, "verify") }
      prog = { ...prog, steps: completeStep(prog.steps, "links") }
      prog = { ...prog, steps: completeStep(prog.steps, "refresh") }
      prog = { ...prog, steps: completeStep(prog.steps, "complete", { description: summary.title }), overallStatus: "completed", savedCount: 1 }
      setSubmissionProgress(prog)
      setSubmissionSummary(summary)
      notify?.(summary.title)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Submission failed."
      prog = { ...prog, steps: failStep(prog.steps, "save", message), overallStatus: "failed", failedCount: 1, errorMessages: [message] }
      setSubmissionProgress(prog)
      setSubmissionError(message)
      notify?.(message)
    } finally {
      setSubmitting(false)
    }
  }

  const websiteFeatureWordCount = countWords(websiteForm.featureToVerify)
  const websiteExpectedWordCount = countWords(websiteForm.expectedOutput)

  return (
    <section
      data-testid="student-proof-submission-panel"
      style={{
        display: "grid",
        gap: 14,
        border: "1px solid var(--line)",
        borderRadius: 14,
        background: "var(--paper)",
        padding: 20,
      }}
    >
      <div style={{ display: "grid", gap: 12 }}>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
          Add proof manually or let the AI agent scan your evidence sources — GitHub, LinkedIn, YouTube, documents, certificates, and more.
        </p>
        <div>
          <button
            type="button"
            data-testid="open-proof-submission-modal"
            className="vb-btn-lift"
            style={{
              border: "1px solid var(--line-2)",
              borderRadius: 11,
              padding: "10px 18px",
              background: "var(--ink)",
              color: "#fff",
              fontWeight: 700,
              cursor: "pointer",
            }}
            onClick={() => setOpen(true)}
          >
            Add proof evidence
          </button>
        </div>
      </div>

      {scanOpen && (
        <GitHubPortfolioScanPanel
          onImportSuccess={() => void refreshEvidence()}
          onClose={() => { setScanOpen(false); setPendingScanUrl("") }}
          initialProfileUrl={pendingScanUrl}
        />
      )}

      {/* Skill Proof Center — grouped hierarchical view of all saved evidence */}
      <SkillProofCenter evidence={evidence} loading={loadingEvidence} />

      {open && createPortal(
        <div
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) closeModal()
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.52)",
            zIndex: 200,
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            overflowY: "auto",
            padding: "24px 20px",
          }}
        >
          <div
            ref={modalContentRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="proof-submit-title"
            data-testid="proof-submission-modal"
            style={{
              position: "relative",
              width: "min(900px, 100%)",
              maxHeight: "calc(100vh - 48px)",
              overflow: "auto",
              borderRadius: 18,
              background: "#fff",
              border: "1px solid var(--line)",
              boxShadow: "0 30px 80px rgba(15,23,42,.25)",
              padding: 20,
              display: "grid",
              gap: 18,
              margin: "0 auto",
            }}
          >
            {submissionProgress && (submissionSummary || submissionProgress.overallStatus === "failed") ? (
              <ProofProcessingProgressPanel
                title={activeTab === "github" ? "Saving GitHub proof" : selectedSourceType === "deployed_website" ? "Saving website proof" : "Saving proof evidence"}
                progress={submissionProgress}
                onClose={closeModal}
                canClose
              />
            ) : submitting && submissionProgress ? (
              <ProofProcessingProgressPanel
                title={activeTab === "github" ? "Saving GitHub proof" : "Saving proof evidence"}
                progress={submissionProgress}
                canClose={false}
              />
            ) : (
              <>
                {/* ── Dynamic header ── */}
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted)" }}>
                      Add proof evidence
                    </div>
                    <h2 id="proof-submit-title" style={{ margin: "4px 0 0", fontSize: 24, color: "var(--ink)" }}>
                      {proofMode === "select" ? "How do you want to add proof?"
                        : proofMode === "ai_agent" ? "AI Agent — Multi-Source Proof"
                        : manualStep === "source_select" ? "Select evidence source"
                        : selectedSourceType === "github_repository" ? "GitHub Code Proof"
                        : selectedSourceType === "deployed_website" ? "Live Website Proof"
                        : "Add Proof Evidence"}
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={closeModal}
                    aria-label="Close proof submission modal"
                    style={{ border: "1px solid var(--line)", background: "#fff", color: "var(--ink-2)", borderRadius: 10, width: 38, height: 38, fontSize: 18, fontWeight: 700, cursor: "pointer" }}
                  >
                    ×
                  </button>
                </div>

                {/* ── Mode: select ── */}
                {proofMode === "select" && (
                  <div style={{ display: "grid", gap: 16 }}>
                    <p style={{ margin: 0, fontSize: 13, color: "var(--muted)", lineHeight: 1.6 }}>
                      Choose how you want to add evidence. Only add proof you own or have permission to share.
                    </p>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      {([
                        ["manual", "✍ Add Manually", "Pick an evidence type and fill in the details yourself — GitHub, LinkedIn, YouTube, PDF, certificate, or free text."],
                        ["ai_agent", "✦ Use AI Agent", "Paste resource links. GitHub scanning is active now. Other AI extraction (LinkedIn, YouTube, docs) coming in upcoming phases."],
                      ] as const).map(([mode, title, desc]) => (
                        <button
                          key={`mode-${mode}`}
                          type="button"
                          onClick={() => { setProofMode(mode); setSubmissionError(null); }}
                          style={{
                            border: "1px solid var(--line)",
                            borderRadius: 14,
                            padding: "20px 18px",
                            background: "#fff",
                            cursor: "pointer",
                            textAlign: "left",
                            display: "flex",
                            flexDirection: "column",
                            gap: 8,
                            transition: "border-color 0.1s",
                          }}
                        >
                          <span style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>{title}</span>
                          <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>{desc}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* ── Mode: manual — source type selector ── */}
                {proofMode === "manual" && manualStep === "source_select" && (
                  <div style={{ display: "grid", gap: 12 }}>
                    <SourceTypeSelector onSelect={handleSourceSelect} />
                    <div>
                      <button
                        type="button"
                        onClick={() => { setProofMode("select"); setSubmissionError(null); }}
                        style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "8px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
                      >
                        ← Back
                      </button>
                    </div>
                  </div>
                )}

                {/* ── Mode: manual — multi-source form (new source types) ── */}
                {proofMode === "manual" && manualStep === "form" && selectedSourceType &&
                  selectedSourceType !== "github_repository" && selectedSourceType !== "deployed_website" && (
                  <MultiSourceProofForm
                    sourceType={selectedSourceType}
                    submitting={submitting}
                    error={submissionError}
                    onBack={() => { setManualStep("source_select"); setSubmissionError(null); }}
                    onSubmit={handleGenericSubmit}
                  />
                )}

                {/* ── Mode: AI Agent — card grid ── */}
                {proofMode === "ai_agent" && !agentSourceType && (
                  <div style={{ display: "grid", gap: 14 }}>
                    <p style={{ margin: 0, fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
                      Give VeriBridge your resource links. GitHub scanning is active now.
                      LinkedIn, YouTube, documents, and certificate AI extraction will be added in upcoming phases — you can save links now.
                    </p>

                    <div style={{ display: "grid", gap: 8 }}>
                      {([
                        {
                          icon: "⌨", title: "GitHub Profile / Repo Scan",
                          desc: "AI scans your public repositories and extracts skill evidence automatically.",
                          status: "active" as const, sourceType: "github_repository" as EvidenceSourceType,
                        },
                        {
                          icon: "🌐", title: "Website / Portfolio Scan",
                          desc: "Submit a live deployed URL. AI checks your site for skill demonstration.",
                          status: "active" as const, sourceType: "deployed_website" as EvidenceSourceType,
                        },
                        {
                          icon: "💼", title: "LinkedIn Profile / Post Analysis",
                          desc: "AI will read your public LinkedIn posts and connect proof to skills.",
                          status: "soon" as const, sourceType: "linkedin_post" as EvidenceSourceType,
                        },
                        {
                          icon: "▶", title: "YouTube / Demo Video Analysis",
                          desc: "AI will analyze transcripts and timestamps to identify skill demonstrations.",
                          status: "soon" as const, sourceType: "youtube_demo" as EvidenceSourceType,
                        },
                        {
                          icon: "📄", title: "Google Drive / Document Analysis",
                          desc: "AI will read shared docs, slides, and reports for skill evidence.",
                          status: "soon" as const, sourceType: "google_drive_document" as EvidenceSourceType,
                        },
                        {
                          icon: "🏅", title: "Certificate / Report Analysis",
                          desc: "AI will verify certificates and extract skills from reports and papers.",
                          status: "soon" as const, sourceType: "certificate" as EvidenceSourceType,
                        },
                      ] as const).map((card) => (
                        <div
                          key={`ai-card-${card.sourceType}`}
                          style={{ border: "1px solid var(--line)", borderRadius: 12, padding: "14px 16px", display: "flex", alignItems: "flex-start", gap: 14 }}
                        >
                          <span style={{ fontSize: 22, flexShrink: 0, marginTop: 2 }}>{card.icon}</span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>{card.title}</span>
                              <span style={{
                                fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", padding: "2px 7px", borderRadius: 999,
                                ...(card.status === "active"
                                  ? { color: "#166534", background: "#dcfce7", border: "1px solid #bbf7d0" }
                                  : { color: "#854d0e", background: "#fef9c3", border: "1px solid #fef08a" }),
                              }}>
                                {card.status === "active" ? "Active" : "Coming soon"}
                              </span>
                            </div>
                            <p style={{ margin: "0 0 10px", fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>{card.desc}</p>
                            <button
                              type="button"
                              onClick={() => { setAgentSourceType(card.sourceType); setSubmissionError(null); }}
                              style={{
                                border: card.status === "active" ? "1px solid var(--ink)" : "1px solid var(--line-2)",
                                background: card.status === "active" ? "var(--ink)" : "transparent",
                                color: card.status === "active" ? "#fff" : "var(--ink-2)",
                                borderRadius: 9, padding: "7px 12px", fontWeight: 600, fontSize: 12, cursor: "pointer",
                              }}
                            >
                              {card.status === "active" ? "Get started" : "Save link now"}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>

                    <button
                      type="button"
                      onClick={() => { setProofMode("select"); setSubmissionError(null); }}
                      style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "8px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer", alignSelf: "flex-start" }}
                    >
                      ← Back
                    </button>
                  </div>
                )}

                {/* ── Mode: AI Agent — website analyzer (J4D) ── */}
                {proofMode === "ai_agent" && agentSourceType === "deployed_website" && (
                  <WebsiteAIAnalyzerPanel
                    url={agentUrl}
                    onUrlChange={setAgentUrl}
                    skillFocus={agentSkillFocus}
                    onSkillFocusChange={setAgentSkillFocus}
                    githubRepoUrl={agentGithubRepoUrl}
                    onGithubRepoUrlChange={setAgentGithubRepoUrl}
                    functionalTestPlan={agentFunctionalTestPlan}
                    onFunctionalTestPlanChange={setAgentFunctionalTestPlan}
                    onSaveComplete={() => void refreshEvidence()}
                    onBack={resetAgentForm}
                  />
                )}

                {/* ── Mode: AI Agent — simple resource link form (non-website sources) ── */}
                {proofMode === "ai_agent" && agentSourceType && agentSourceType !== "deployed_website" && (
                  <div style={{ display: "grid", gap: 14 }}>
                    {/* Source header */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>
                          {agentSourceType === "github_repository" ? "GitHub Profile / Repo Scan"
                            : agentSourceType === "linkedin_post" ? "LinkedIn Profile / Post"
                            : agentSourceType === "youtube_demo" ? "YouTube / Demo Video"
                            : agentSourceType === "google_drive_document" ? "Google Drive / Document"
                            : "Certificate / Report"}
                        </div>
                        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                          {agentSourceType === "github_repository"
                            ? "Enter your GitHub profile URL. We'll scan your public repos automatically."
                            : "Enter the link. AI extraction will be added in an upcoming phase — your link will be saved now."}
                        </div>
                      </div>
                    </div>

                    {submissionError && (
                      <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 10, padding: "8px 12px", fontSize: 12 }}>
                        {submissionError}
                      </div>
                    )}

                    {/* URL field — always shown */}
                    <div style={{ display: "grid", gap: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
                        {agentSourceType === "github_repository" ? "GitHub profile or repo URL *"
                          : agentSourceType === "linkedin_post" ? "LinkedIn post or profile URL *"
                          : agentSourceType === "youtube_demo" ? "YouTube video URL *"
                          : agentSourceType === "google_drive_document" ? "Google Drive shareable link *"
                          : "Certificate or document URL *"}
                      </span>
                      <input
                        value={agentUrl}
                        onChange={(e) => setAgentUrl(e.target.value)}
                        placeholder={
                          agentSourceType === "github_repository" ? "https://github.com/yourusername"
                          : agentSourceType === "youtube_demo" ? "https://youtube.com/watch?v=..."
                          : agentSourceType === "linkedin_post" ? "https://linkedin.com/in/... or linkedin.com/posts/..."
                          : "https://..."
                        }
                        style={inputStyle}
                      />
                      <span style={{ fontSize: 11, color: "var(--muted)" }}>
                        Only add links you own or have permission to share.
                      </span>
                    </div>

                    {/* Skill focus — for non-GitHub sources */}
                    {agentSourceType !== "github_repository" && (
                      <div style={{ display: "grid", gap: 4 }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>Skill focus *</span>
                        <input
                          value={agentSkillFocus}
                          onChange={(e) => setAgentSkillFocus(e.target.value)}
                          placeholder="e.g. Machine Learning, FastAPI, Docker"
                          style={inputStyle}
                        />
                        <span style={{ fontSize: 11, color: "var(--muted)" }}>Which skill does this evidence demonstrate?</span>
                      </div>
                    )}

                    {/* YouTube: timestamp + transcript */}
                    {agentSourceType === "youtube_demo" && (
                      <>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                          <div style={{ display: "grid", gap: 4 }}>
                            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>Start timestamp</span>
                            <input value={agentTimestampStart} onChange={(e) => setAgentTimestampStart(e.target.value)} placeholder="05:12" style={inputStyle} />
                          </div>
                          <div style={{ display: "grid", gap: 4 }}>
                            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>End timestamp</span>
                            <input value={agentTimestampEnd} onChange={(e) => setAgentTimestampEnd(e.target.value)} placeholder="06:40" style={inputStyle} />
                          </div>
                        </div>
                        <div style={{ display: "grid", gap: 4 }}>
                          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>Transcript snippet <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span></span>
                          <textarea
                            value={agentTranscript}
                            onChange={(e) => setAgentTranscript(e.target.value)}
                            placeholder="e.g. Here I explain RandomForest model training with scikit-learn..."
                            style={{ ...inputStyle, minHeight: 64, resize: "vertical", fontFamily: "inherit", lineHeight: 1.5 }}
                          />
                        </div>
                      </>
                    )}

                    {/* Footer */}
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                      <button
                        type="button"
                        onClick={resetAgentForm}
                        style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
                      >
                        ← Back to sources
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleAgentSubmit()}
                        disabled={submitting}
                        style={{
                          border: "1px solid transparent",
                          background: submitting ? "var(--bg-2)" : "var(--ink)",
                          color: submitting ? "var(--muted)" : "#fff",
                          borderRadius: 10, padding: "10px 18px", fontWeight: 700, fontSize: 14, cursor: submitting ? "not-allowed" : "pointer",
                        }}
                      >
                        {submitting ? "Saving…"
                          : agentSourceType === "github_repository" ? "Scan GitHub with AI"
                          : "Save link for AI extraction"}
                      </button>
                    </div>
                  </div>
                )}

                {/* ── Mode: manual — GitHub / Website forms (existing logic) ── */}
                {proofMode === "manual" && manualStep === "form" &&
                  (selectedSourceType === "github_repository" || selectedSourceType === "deployed_website") && (
                  <><div role="tablist" aria-label="Proof evidence type" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {(
                    [
                      ["github", "GitHub Code"],
                      ["website", "Live Website"],
                    ] as const
                  ).map(([tabKey, label]) => {
                    const active = activeTab === tabKey
                    return (
                      <button
                        key={tabKey}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        data-testid={`proof-tab-${tabKey}`}
                        onClick={() => setActiveTab(tabKey)}
                        style={{
                          border: `1px solid ${active ? "var(--ink)" : "var(--line)"}`,
                          background: active ? "var(--ink)" : "#fff",
                          color: active ? "#fff" : "var(--ink)",
                          borderRadius: 999,
                          padding: "9px 14px",
                          fontWeight: 700,
                          cursor: "pointer",
                        }}
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>

                {submissionError ? (
                  <div
                    role="alert"
                    style={{
                      border: "1px solid #fecaca",
                      background: "#fef2f2",
                      color: "#991b1b",
                      borderRadius: 12,
                      padding: "10px 12px",
                      fontSize: 13,
                      lineHeight: 1.5,
                    }}
                  >
                    {submissionError}
                  </div>
                ) : null}

                <div style={{ display: "grid", gap: 14 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Skill you want to prove</span>
                      <input
                        value={activeTab === "github" ? githubForm.skillName : websiteForm.skillName}
                        onChange={(event) => {
                          const value = event.target.value
                          if (activeTab === "github") {
                            setGitHubForm((prev) => ({ ...prev, skillName: value }))
                          } else {
                            setWebsiteForm((prev) => ({ ...prev, skillName: value }))
                          }
                        }}
                        placeholder="Example: Machine Learning"
                        style={inputStyle}
                      />
                    </label>

                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Project or evidence title</span>
                      <input
                        value={activeTab === "github" ? githubForm.projectTitle : websiteForm.projectTitle}
                        onChange={(event) => {
                          const value = event.target.value
                          if (activeTab === "github") {
                            setGitHubForm((prev) => ({ ...prev, projectTitle: value }))
                          } else {
                            setWebsiteForm((prev) => ({ ...prev, projectTitle: value }))
                          }
                        }}
                        placeholder="Example: Boston Accident Risk Rerouting"
                        style={inputStyle}
                      />
                    </label>
                  </div>

                  {activeTab === "github" ? (
                    <div style={{ display: "grid", gap: 12 }}>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>What does this code prove?</span>
                        <textarea
                          value={githubForm.claim}
                          onChange={(event) => setGitHubForm((prev) => ({ ...prev, claim: event.target.value }))}
                          placeholder="Describe the capability this selected code demonstrates."
                          rows={4}
                          style={{ ...inputStyle, minHeight: 100, resize: "vertical" }}
                        />
                      </label>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>GitHub repository URL</span>
                          <input
                            value={githubForm.repositoryUrl}
                            onChange={(event) => setGitHubForm((prev) => ({ ...prev, repositoryUrl: event.target.value }))}
                            placeholder="https://github.com/user/repo"
                            style={inputStyle}
                          />
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Optional branch or ref</span>
                          <input
                            value={githubForm.branchRef}
                            onChange={(event) => setGitHubForm((prev) => ({ ...prev, branchRef: event.target.value }))}
                            placeholder="main"
                            style={inputStyle}
                          />
                        </label>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 12 }}>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>File path inside the repo</span>
                          <input
                            value={githubForm.filePath}
                            onChange={(event) => setGitHubForm((prev) => ({ ...prev, filePath: event.target.value }))}
                            placeholder="app/model.py"
                            style={inputStyle}
                          />
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Start line</span>
                          <input
                            type="number"
                            min={1}
                            value={githubForm.startLine}
                            onChange={(event) => setGitHubForm((prev) => ({ ...prev, startLine: event.target.value }))}
                            placeholder="20"
                            style={inputStyle}
                          />
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>End line</span>
                          <input
                            type="number"
                            min={1}
                            value={githubForm.endLine}
                            onChange={(event) => setGitHubForm((prev) => ({ ...prev, endLine: event.target.value }))}
                            placeholder="32"
                            style={inputStyle}
                          />
                        </label>
                      </div>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Notes</span>
                        <textarea
                          value={githubForm.notes}
                          onChange={(event) => setGitHubForm((prev) => ({ ...prev, notes: event.target.value }))}
                          placeholder="Optional context for recruiters or future verification."
                          rows={3}
                          style={{ ...inputStyle, minHeight: 82, resize: "vertical" }}
                        />
                      </label>
                    </div>
                  ) : (
                    <div style={{ display: "grid", gap: 12 }}>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Live website URL</span>
                        <input
                          value={websiteForm.websiteUrl}
                          onChange={(event) => setWebsiteForm((prev) => ({ ...prev, websiteUrl: event.target.value }))}
                          placeholder="https://student-app.example.com"
                          style={inputStyle}
                        />
                      </label>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                          Feature to verify
                          <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, color: "var(--muted)" }}>
                            {websiteFeatureWordCount} / 20 words
                          </span>
                        </span>
                        <textarea
                          aria-label="Feature to verify"
                          value={websiteForm.featureToVerify}
                          onChange={(event) => setWebsiteForm((prev) => ({ ...prev, featureToVerify: event.target.value }))}
                          placeholder="After the user enters a source and destination, the website analyzes route risk and displays a safer rerouting recommendation."
                          rows={4}
                          style={{ ...inputStyle, minHeight: 110, resize: "vertical" }}
                        />
                        <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
                          Use at least 20 words. Mention what the user enters or clicks, what the website does, and what result should appear.
                        </span>
                      </label>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                          Expected output
                          <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, color: "var(--muted)" }}>
                            {websiteExpectedWordCount} / 8 words
                          </span>
                        </span>
                        <textarea
                          aria-label="Expected output"
                          value={websiteForm.expectedOutput}
                          onChange={(event) => setWebsiteForm((prev) => ({ ...prev, expectedOutput: event.target.value }))}
                          placeholder="A risk score card and safer route recommendation appear on the results section."
                          rows={3}
                          style={{ ...inputStyle, minHeight: 90, resize: "vertical" }}
                        />
                        <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
                          Use at least 8 words. Describe the visible result VeriBridge should look for.
                        </span>
                      </label>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Verification steps</span>
                        <textarea
                          value={websiteForm.verificationSteps}
                          onChange={(event) => setWebsiteForm((prev) => ({ ...prev, verificationSteps: event.target.value }))}
                          placeholder="One step per line."
                          rows={4}
                          style={{ ...inputStyle, minHeight: 104, resize: "vertical" }}
                        />
                        <span style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
                          One step per line. Include the exact clicks or inputs VeriBridge should verify.
                        </span>
                      </label>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Notes</span>
                        <textarea
                          value={websiteForm.notes}
                          onChange={(event) => setWebsiteForm((prev) => ({ ...prev, notes: event.target.value }))}
                          placeholder="Optional notes about login, demo data, or limitations."
                          rows={3}
                          style={{ ...inputStyle, minHeight: 82, resize: "vertical" }}
                        />
                      </label>
                    </div>
                  )}
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => { setManualStep("source_select"); setSubmissionError(null); }}
                    style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
                  >
                    ← Back to sources
                  </button>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      data-testid="proof-submit-action"
                      onClick={() => void handleSubmit()}
                      disabled={submitting}
                      style={{
                        border: "1px solid var(--line)",
                        background: submitting ? "var(--bg-2)" : "var(--ink)",
                        color: submitting ? "var(--muted)" : "#fff",
                        borderRadius: 10,
                        padding: "10px 14px",
                        fontWeight: 700,
                        cursor: submitting ? "not-allowed" : "pointer",
                        minWidth: 154,
                      }}
                    >
                      {submitting ? "Submitting…" : activeTab === "github" ? "Submit GitHub proof" : "Submit website proof"}
                    </button>
                  </div>
                </div>
                </>
                )}
              </>
            )}
          </div>
        </div>,
        document.body
      )}
    </section>
  )
}

const inputStyle: CSSProperties = {
  width: "100%",
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "#fff",
  color: "var(--ink)",
  padding: "10px 12px",
  fontSize: 14,
  outline: "none",
  boxSizing: "border-box",
}
