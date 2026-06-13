"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import {
  createProjectDefense,
  generateDefenseQuestions,
  submitDefenseAnswers,
  syncProjectDefenseToSkillGraph,
  type DefenseAnalysisResponse,
  type ProjectDefenseCreateResponse,
  type SubmitDefenseAnswersResponse,
  type VBRSessionQuestionResponse,
} from "@/lib/vbr-api"
import {
  listDocumentProofs,
  listGitHubProofs,
  type DocumentProofResponse,
  type GitHubProofResponse,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  ErrorState,
  LoadingState,
  Mono,
  ProgressBar,
  TOKEN,
} from "./shared"

type AnswerMode = "combined" | "per_question"

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  border: `1px solid ${TOKEN.line}`,
  borderRadius: 8,
  fontSize: 13,
  background: TOKEN.paper,
  boxSizing: "border-box",
}

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: TOKEN.inkSoft,
  display: "block",
  marginBottom: 4,
}

function QuestionCard({ question }: { question: VBRSessionQuestionResponse }) {
  const kind = String(question.target_ref?.kind || "")
  const skill = question.target_ref?.skill ? String(question.target_ref.skill) : null
  return (
    <div style={{ padding: "10px 12px", border: `1px solid ${TOKEN.line}`, borderRadius: 8, background: TOKEN.bg }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
        {kind && <Badge tone="slate">{kind.replace(/_/g, " ")}</Badge>}
        {skill && <Badge tone="indigo">{skill}</Badge>}
      </div>
      <p style={{ fontSize: 13, color: TOKEN.ink, margin: 0, lineHeight: 1.5 }}>{question.question_text}</p>
    </div>
  )
}

function ScoreStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
          {label}
        </Mono>
        <Mono style={{ fontSize: 11, color: TOKEN.inkSoft, fontWeight: 700 }}>{value}/100</Mono>
      </div>
      <ProgressBar value={value} />
    </div>
  )
}

function AnalysisResults({
  analysis,
  syncStatus,
  syncSkills,
  onSync,
}: {
  analysis: DefenseAnalysisResponse
  syncStatus: "idle" | "syncing" | "saved" | "error"
  syncSkills: string[]
  onSync: () => void
}) {
  return (
    <Card style={{ border: `1px solid ${TOKEN.indigo}40`, background: TOKEN.indigoSoft }}>
      <CardHeader title="Project Defense Analysis" eyebrow="Step E · Deterministic analysis" icon="📊" />

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <ScoreStat label="Overall Defense Score" value={analysis.overall_defense_score} />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <ScoreStat label="Ownership signal" value={analysis.ownership_signal_score} />
          <ScoreStat label="Technical depth" value={analysis.technical_depth_score} />
          <ScoreStat label="Explanation clarity" value={analysis.explanation_clarity_score} />
          <ScoreStat label="Consistency with evidence" value={analysis.consistency_with_evidence_score} />
        </div>

        {analysis.recruiter_summary && (
          <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            {analysis.recruiter_summary}
          </p>
        )}

        {analysis.skills_mentioned.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Skills Mentioned
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {analysis.skills_mentioned.map((s) => (
                <Badge key={s} tone={analysis.skills_explained_well.includes(s) ? "emerald" : "slate"}>
                  {s}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {analysis.skills_missing_from_explanation.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Claimed Skills Not Yet Explained
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {analysis.skills_missing_from_explanation.map((s) => (
                <Badge key={s} tone="amber">{s}</Badge>
              ))}
            </div>
          </div>
        )}

        {analysis.recommended_improvements.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Suggested Improvements
            </Mono>
            <ul style={{ margin: "4px 0 0", padding: "0 0 0 14px" }}>
              {analysis.recommended_improvements.map((s, i) => (
                <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft, marginBottom: 2 }}>{s}</li>
              ))}
            </ul>
          </div>
        )}

        {analysis.risk_flags.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.rose, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Risk Flags
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {analysis.risk_flags.map((s, i) => (
                <Badge key={i} tone="rose">{s}</Badge>
              ))}
            </div>
          </div>
        )}

        <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
          Privacy scan: {analysis.privacy_scan_status}
        </Mono>

        <div style={{ borderTop: `1px solid ${TOKEN.line}`, paddingTop: 12 }}>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 8px" }}>
            This explanation can be saved as supporting project defense evidence on your Skill Graph. It
            stays separate from your GitHub, website, and document proof — it never overwrites or
            downgrades stronger evidence you already have.
          </p>
          {syncStatus !== "saved" && (
            <Btn variant="primary" onClick={onSync} disabled={syncStatus === "syncing"}>
              {syncStatus === "syncing" ? "Saving…" : "Save explanation evidence to Skill Graph"}
            </Btn>
          )}
          {syncStatus === "saved" && (
            <Mono style={{ fontSize: 12, color: TOKEN.emerald }}>
              ✓ Saved as supporting evidence for {syncSkills.join(", ") || "your claimed skills"}
            </Mono>
          )}
          {syncStatus === "error" && (
            <Mono style={{ fontSize: 11, color: TOKEN.rose, display: "block", marginTop: 6 }}>
              Couldn&apos;t save to Skill Graph. Try again.
            </Mono>
          )}
        </div>
      </div>
    </Card>
  )
}

export function ProjectDefensePanel() {
  const router = useRouter()

  // Step A/B — project identity + attached proofs
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [claimedSkills, setClaimedSkills] = useState("")
  const [studentRole, setStudentRole] = useState("")
  const [repoUrl, setRepoUrl] = useState("")
  const [selectedGithubProofId, setSelectedGithubProofId] = useState("")
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])

  const [githubProofs, setGithubProofs] = useState<GitHubProofResponse[] | null>(null)
  const [documentProofs, setDocumentProofs] = useState<DocumentProofResponse[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [created, setCreated] = useState<ProjectDefenseCreateResponse | null>(null)

  // Step C — generated questions
  const [questions, setQuestions] = useState<VBRSessionQuestionResponse[] | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)

  // Step D — answers
  const [answerMode, setAnswerMode] = useState<AnswerMode>("combined")
  const [combinedText, setCombinedText] = useState("")
  const [perQuestionAnswers, setPerQuestionAnswers] = useState<Record<string, string>>({})

  // Step E — analysis
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<SubmitDefenseAnswersResponse | null>(null)

  // Step F — sync
  const [syncStatus, setSyncStatus] = useState<"idle" | "syncing" | "saved" | "error">("idle")
  const [syncSkills, setSyncSkills] = useState<string[]>([])

  useEffect(() => {
    Promise.all([listGitHubProofs(), listDocumentProofs()])
      .then(([gh, docs]) => {
        setGithubProofs(gh.filter((p) => p.status === "analyzed"))
        setDocumentProofs(docs.filter((d) => d.status === "analyzed"))
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  const claimedSkillsList = () => claimedSkills.split(",").map((s) => s.trim()).filter(Boolean)

  const toggleDocument = (id: string) => {
    setSelectedDocumentIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  const handleCreate = async () => {
    setCreating(true)
    setCreateError(null)
    try {
      if (!title.trim()) {
        setCreateError("Give your project a title.")
        return
      }
      const response = await createProjectDefense({
        title: title.trim(),
        description: description.trim(),
        claimed_skills: claimedSkillsList(),
        student_role: studentRole.trim(),
        repo_url: repoUrl.trim() || null,
        attached_proofs: {
          github_proof_id: selectedGithubProofId || null,
          document_evidence_ids: selectedDocumentIds,
        },
      })
      setCreated(response)
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : "Failed to create project defense.")
    } finally {
      setCreating(false)
    }
  }

  const handleGenerateQuestions = async () => {
    if (!created) return
    setGenerating(true)
    setGenerateError(null)
    try {
      const response = await generateDefenseQuestions(created.project.id)
      setQuestions(response.questions)
      setSessionId(response.session_id)
    } catch (e: unknown) {
      setGenerateError(e instanceof Error ? e.message : "Failed to generate defense questions.")
    } finally {
      setGenerating(false)
    }
  }

  const handleSubmitAnswers = async () => {
    if (!sessionId) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const body =
        answerMode === "combined"
          ? { combined_text: combinedText.trim() || null }
          : {
              answers: Object.entries(perQuestionAnswers)
                .filter(([, text]) => text.trim())
                .map(([questionId, text]) => ({ question_id: questionId, answer_text: text.trim() })),
            }
      const response = await submitDefenseAnswers(sessionId, body)
      setResult(response)
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Failed to submit defense answers.")
    } finally {
      setSubmitting(false)
    }
  }

  const handleSync = async () => {
    if (!sessionId) return
    setSyncStatus("syncing")
    try {
      const response = await syncProjectDefenseToSkillGraph(sessionId)
      if (response.ok && response.errors.length === 0) {
        setSyncSkills(response.skills_synced)
        setSyncStatus("saved")
      } else {
        setSyncStatus("error")
      }
    } catch {
      setSyncStatus("error")
    }
  }

  const attachedSummary = created?.metadata.attached_proofs ?? {}
  const githubAttached = attachedSummary["github_proof"] as { repo_url?: string; detected_skills?: string[] } | undefined
  const documentsAttached = attachedSummary["documents"] as Array<{ title?: string }> | undefined

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Project Defense</h2>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
          Explain your individual contribution to a project in your own words. VeriBridge generates
          deterministic defense questions from your attached proof, and the answers become supporting
          project defense evidence on your Skill Graph.
        </p>
      </div>

      {loadError && <ErrorState message={loadError} />}

      {/* Step A/B — Project identity + attached proofs */}
      {!created && (
        <Card>
          <CardHeader title="Project identity" eyebrow="Step A · Tell us about your project" icon="🧩" />
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={labelStyle}>Project title *</label>
              <input
                type="text"
                placeholder="e.g. Skill Evidence Tracker"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                style={inputStyle}
              />
            </div>

            <div>
              <label style={labelStyle}>Description (optional)</label>
              <textarea
                placeholder="What does this project do?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>

            <div>
              <label style={labelStyle}>Claimed skills (comma-separated)</label>
              <input
                type="text"
                placeholder="Python, React, PostgreSQL"
                value={claimedSkills}
                onChange={(e) => setClaimedSkills(e.target.value)}
                style={inputStyle}
              />
            </div>

            <div>
              <label style={labelStyle}>Your role / contribution (optional)</label>
              <textarea
                placeholder="What part of this project did you build?"
                value={studentRole}
                onChange={(e) => setStudentRole(e.target.value)}
                rows={2}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>

            <div>
              <label style={labelStyle}>
                Repository URL {selectedGithubProofId ? "(optional — using selected GitHub proof)" : "*"}
              </label>
              <input
                type="text"
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                style={inputStyle}
              />
            </div>

            {githubProofs !== null && githubProofs.length > 0 && (
              <div>
                <label style={labelStyle}>Attach a GitHub proof (optional)</label>
                <select
                  value={selectedGithubProofId}
                  onChange={(e) => setSelectedGithubProofId(e.target.value)}
                  style={inputStyle}
                >
                  <option value="">— None —</option>
                  {githubProofs.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.repo_owner ? `${p.repo_owner}/${p.repo_name}` : p.repo_url}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {documentProofs !== null && documentProofs.length > 0 && (
              <div>
                <label style={labelStyle}>Attach document proof (optional)</label>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {documentProofs.map((d) => (
                    <label key={d.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: TOKEN.inkSoft }}>
                      <input
                        type="checkbox"
                        checked={selectedDocumentIds.includes(d.id)}
                        onChange={() => toggleDocument(d.id)}
                      />
                      {d.title || d.filename || "Untitled document"}
                    </label>
                  ))}
                </div>
              </div>
            )}

            {createError && (
              <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6 }}>
                {createError}
              </p>
            )}

            <div>
              <Btn variant="primary" onClick={handleCreate} disabled={creating}>
                {creating ? "Creating…" : "Create project defense"}
              </Btn>
            </div>
          </div>
        </Card>
      )}

      {/* Created project summary */}
      {created && (
        <Card>
          <CardHeader title={created.project.title} eyebrow="Project identity" icon="🧩" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {created.project.repo_full_name && (
              <Mono style={{ fontSize: 12, color: TOKEN.muted }}>{created.project.repo_full_name}</Mono>
            )}
            {created.metadata.claimed_skills.length > 0 && (
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {created.metadata.claimed_skills.map((s) => (
                  <Badge key={s} tone="indigo">{s}</Badge>
                ))}
              </div>
            )}
            {githubAttached?.repo_url && (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                GitHub proof attached: {githubAttached.repo_url}
              </Mono>
            )}
            {documentsAttached && documentsAttached.length > 0 && (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                {documentsAttached.length} document proof{documentsAttached.length === 1 ? "" : "s"} attached
              </Mono>
            )}
          </div>
        </Card>
      )}

      {/* Step C — Generate questions */}
      {created && !questions && (
        <Card>
          <CardHeader title="Generate defense questions" eyebrow="Step B · Deterministic questions" icon="❓" />
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "0 0 12px" }}>
            VeriBridge will generate a short set of questions about your project&apos;s architecture, your
            individual contribution, your claimed skills, and any attached proof.
          </p>
          {generateError && (
            <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6, marginBottom: 8 }}>
              {generateError}
            </p>
          )}
          <Btn variant="primary" onClick={handleGenerateQuestions} disabled={generating}>
            {generating ? "Generating…" : "Generate questions"}
          </Btn>
        </Card>
      )}

      {/* Step C results + Step D — answers */}
      {questions && !result && (
        <Card>
          <CardHeader title="Defense questions" eyebrow="Step C · Answer in your own words" icon="❓" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
            {questions.map((q) => (
              <QuestionCard key={q.id} question={q} />
            ))}
          </div>

          <div style={{ marginBottom: 16 }}>
            <Btn
              variant="secondary"
              onClick={() => sessionId && router.push(`/student/proofs/project-defense/record/${sessionId}`)}
            >
              Record defense
            </Btn>
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: "6px 0 0" }}>
              Optionally record yourself answering these questions, or paste your explanation below.
            </p>
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <Btn size="sm" variant={answerMode === "combined" ? "primary" : "secondary"} onClick={() => setAnswerMode("combined")}>
              Paste one explanation
            </Btn>
            <Btn size="sm" variant={answerMode === "per_question" ? "primary" : "secondary"} onClick={() => setAnswerMode("per_question")}>
              Answer each question
            </Btn>
          </div>

          {answerMode === "combined" ? (
            <div>
              <label style={labelStyle}>Your explanation</label>
              <textarea
                placeholder="Explain your project, your role, the architecture, and any challenges or improvements in your own words…"
                value={combinedText}
                onChange={(e) => setCombinedText(e.target.value)}
                rows={8}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {questions.map((q) => (
                <div key={q.id}>
                  <label style={labelStyle}>{q.question_text}</label>
                  <textarea
                    value={perQuestionAnswers[q.id] || ""}
                    onChange={(e) => setPerQuestionAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                    rows={3}
                    style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
                  />
                </div>
              ))}
            </div>
          )}

          {submitError && (
            <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6, marginTop: 12 }}>
              {submitError}
            </p>
          )}

          <div style={{ marginTop: 12 }}>
            <Btn variant="primary" onClick={handleSubmitAnswers} disabled={submitting}>
              {submitting ? "Analyzing…" : "Analyze my answers"}
            </Btn>
          </div>
        </Card>
      )}

      {/* Step E/F — analysis + save to Skill Graph */}
      {result && (
        <AnalysisResults
          analysis={result.analysis}
          syncStatus={syncStatus}
          syncSkills={syncSkills}
          onSync={handleSync}
        />
      )}

      {!created && githubProofs === null && documentProofs === null && !loadError && (
        <LoadingState label="Loading your proof sources…" />
      )}

      <p style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", marginTop: 4 }}>
        Project Defense is supporting explanation evidence — it never counts as fully verified proof on its
        own and does not change your existing GitHub, website, or document evidence.
      </p>
    </div>
  )
}
