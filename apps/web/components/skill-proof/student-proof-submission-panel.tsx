"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
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
  type SkillEvidenceResponse,
} from "@/lib/api"

type SubmissionTab = "github" | "website"

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

function formatVerificationStatus(status: string): string {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function getEvidenceTitle(evidence: SkillEvidenceResponse): string {
  const metadata = evidence.metadata as Record<string, unknown> | undefined
  const title = typeof metadata?.evidence_title === "string" ? metadata.evidence_title.trim() : ""
  return title || evidence.skill_name
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

  try {
    const semanticResult = await createGithubSemanticVerificationResult(createdEvidence.id)
    notes.push(`Created GitHub semantic result (${semanticResult.semantic_status}).`)
    try {
      const report = await createGithubRecruiterProofReport(createdEvidence.id, semanticResult.id)
      notes.push(`Created GitHub recruiter report (${report.report_status}).`)
    } catch (error) {
      notes.push(`Recruiter report could not be generated yet: ${error instanceof Error ? error.message : "unknown error"}`)
    }
  } catch (error) {
    notes.push(`GitHub semantic verification could not run yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  try {
    const links = await generateEvidenceAccessLinks(createdEvidence.id)
    notes.push(`Generated ${links.length} direct evidence access link${links.length === 1 ? "" : "s"}.`)
  } catch (error) {
    notes.push(`Direct evidence links could not be generated yet: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  await refreshEvidence()

  return {
    title: "GitHub proof submitted successfully.",
    message: `${form.skillName.trim()} proof is now recorded in VeriBridge.`,
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
    notes.push(`Static verification run completed (${staticRun.execution_status}).`)
  } catch (error) {
    notes.push(`Static verification run could not complete: ${error instanceof Error ? error.message : "unknown error"}`)
  }

  let browserRunId: string | null = null
  try {
    const browserRun = await executeWebsiteBrowserVerificationRun(createdEvidence.id, planId)
    browserRunId = browserRun.id
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
    notes.push(`Created website semantic result (${semantic.semantic_status}).`)
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
    message: `${form.skillName.trim()} proof is now recorded in VeriBridge.`,
    notes,
  }
}

export function StudentProofSubmissionPanel({
  notify,
}: {
  notify?: (message: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<SubmissionTab>("github")
  const [loadingEvidence, setLoadingEvidence] = useState(true)
  const [evidence, setEvidence] = useState<SkillEvidenceResponse[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [submissionSummary, setSubmissionSummary] = useState<SubmissionSummary | null>(null)
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [githubForm, setGitHubForm] = useState<GitHubFormState>(initialGitHubForm)
  const [websiteForm, setWebsiteForm] = useState<WebsiteFormState>(initialWebsiteForm)

  const evidenceCountLabel = useMemo(() => {
    if (loadingEvidence) return "Proof evidence"
    return evidence.length === 0
      ? "Proof evidence · none added yet"
      : `Proof evidence · ${evidence.length} item${evidence.length === 1 ? "" : "s"}`
  }, [evidence.length, loadingEvidence])

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

  function closeModal() {
    setOpen(false)
    setActiveTab("github")
    setSubmissionSummary(null)
    setSubmissionError(null)
    setGitHubForm(initialGitHubForm())
    setWebsiteForm(initialWebsiteForm())
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
    try {
      const summary =
        activeTab === "github"
          ? await runGitHubSubmission(githubForm, refreshEvidence)
          : await runWebsiteSubmission(websiteForm, refreshEvidence)
      setSubmissionSummary(summary)
      notify?.(summary.title)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Submission failed."
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
          Add GitHub code proof or a live website proof. Website proof is optional.
        </p>
        <button
          type="button"
          data-testid="open-proof-submission-modal"
          className="vb-btn-lift"
          style={{
            border: "1px solid var(--line-2)",
            borderRadius: 11,
            padding: "10px 14px",
            background: "var(--ink)",
            color: "#fff",
            width: "fit-content",
            fontWeight: 700,
            cursor: "pointer",
          }}
          onClick={() => setOpen(true)}
        >
          Add proof evidence
        </button>
      </div>

      <div style={{ display: "grid", gap: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>{evidenceCountLabel}</div>
        {loadingEvidence ? (
          <div style={{ color: "var(--muted)", fontSize: 13 }}>Loading proof evidence…</div>
        ) : evidence.length === 0 ? (
          <div style={{ border: "1px dashed var(--line-2)", borderRadius: 14, background: "var(--bg)", padding: 14, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
            No proof evidence has been attached yet. Add GitHub, live demo, certificates, reports, or dashboards.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {evidence.map((entry) => {
              const title = getEvidenceTitle(entry)
              return (
                <article
                  key={entry.id}
                  data-testid={`student-proof-evidence-${entry.id}`}
                  style={{
                    border: "1px solid var(--line)",
                    borderRadius: 12,
                    background: "#fff",
                    padding: 12,
                    display: "grid",
                    gap: 8,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                    <div style={{ display: "grid", gap: 3 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>{title}</div>
                      <div style={{ fontSize: 12, color: "var(--muted)" }}>
                        {entry.skill_name} · {entry.evidence_type}
                      </div>
                    </div>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 800,
                        letterSpacing: "0.12em",
                        textTransform: "uppercase",
                        color: "var(--ink-2)",
                        background: "var(--bg-2)",
                        border: "1px solid var(--line)",
                        borderRadius: 999,
                        padding: "5px 8px",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {formatVerificationStatus(entry.verification_status)}
                    </span>
                  </div>
                  {entry.evidence_description ? (
                    <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.55 }}>{entry.evidence_description}</div>
                  ) : null}
                  {entry.verification_summary ? (
                    <div style={{ fontSize: 12, color: "var(--ink-2)", lineHeight: 1.55 }}>{entry.verification_summary}</div>
                  ) : null}
                </article>
              )
            })}
          </div>
        )}
      </div>

      {open && (
        <div
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) closeModal()
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.52)",
            zIndex: 50,
            display: "grid",
            placeItems: "center",
            padding: 20,
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="proof-submit-title"
            data-testid="proof-submission-modal"
            style={{
              width: "min(900px, 100%)",
              maxHeight: "min(90vh, 920px)",
              overflow: "auto",
              borderRadius: 18,
              background: "#fff",
              border: "1px solid var(--line)",
              boxShadow: "0 30px 80px rgba(15,23,42,.25)",
              padding: 20,
              display: "grid",
              gap: 18,
            }}
          >
            {submissionSummary ? (
              <div style={{ display: "grid", gap: 16 }}>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted)" }}>
                    Completed
                  </div>
                  <h2 id="proof-submit-title" style={{ margin: "4px 0 0", fontSize: 24, color: "var(--ink)" }}>
                    {submissionSummary.title}
                  </h2>
                  <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: 14, lineHeight: 1.6 }}>
                    {submissionSummary.message}
                  </p>
                </div>
                {submissionSummary.notes.length > 0 ? (
                  <div style={{ display: "grid", gap: 8 }}>
                    {submissionSummary.notes.map((note, index) => (
                      <div
                        key={`${note}-${index}`}
                        style={{
                          border: "1px solid var(--line)",
                          borderRadius: 12,
                          background: "var(--bg-2)",
                          padding: "10px 12px",
                          color: "var(--ink-2)",
                          fontSize: 13,
                          lineHeight: 1.5,
                        }}
                      >
                        {note}
                      </div>
                    ))}
                  </div>
                ) : null}
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    onClick={closeModal}
                    style={{
                      border: "1px solid var(--line)",
                      background: "var(--ink)",
                      color: "#fff",
                      borderRadius: 10,
                      padding: "10px 14px",
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted)" }}>
                      Add proof evidence
                    </div>
                    <h2 id="proof-submit-title" style={{ margin: "4px 0 0", fontSize: 24, color: "var(--ink)" }}>
                      Submit GitHub or website proof
                    </h2>
                    <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: 14, lineHeight: 1.6 }}>
                      Website proof is optional. Use the GitHub tab for code evidence and the live website tab for deployed demo proof.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={closeModal}
                    aria-label="Close proof submission modal"
                    style={{
                      border: "1px solid var(--line)",
                      background: "#fff",
                      color: "var(--ink-2)",
                      borderRadius: 10,
                      width: 38,
                      height: 38,
                      fontSize: 18,
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    ×
                  </button>
                </div>

                <div role="tablist" aria-label="Proof evidence type" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
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
                  <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                    GitHub proof can be submitted on its own. Website proof is optional and only required when the project has a live deployed demo.
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      data-testid="proof-submit-cancel"
                      onClick={closeModal}
                      style={{
                        border: "1px solid var(--line)",
                        background: "#fff",
                        color: "var(--ink)",
                        borderRadius: 10,
                        padding: "10px 14px",
                        fontWeight: 700,
                        cursor: "pointer",
                      }}
                    >
                      Cancel
                    </button>
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
          </div>
        </div>
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
