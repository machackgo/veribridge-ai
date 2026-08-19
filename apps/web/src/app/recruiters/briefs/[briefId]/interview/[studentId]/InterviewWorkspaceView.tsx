"use client"

/**
 * Interview workspace — evidence-grounded interview prep for one
 * (brief, candidate) pair.
 *
 * The deterministic core is the verification checklist: the brief's
 * requirement axis evaluated LIVE against the candidate's PUBLISHED
 * evidence (fail-closed — unpublishing is honored on every load). Around
 * it: evidence-grounded interview questions (AI advisory only, always with
 * a deterministic fallback and honest provenance), recruiter-private
 * prep/interview/decision notes with debounced autosave, per-requirement
 * interview marks, the role-stage decision strip and a compact activity
 * trail.
 *
 * PRIVACY: notes, marks, questions and activity are recruiter hiring
 * context ONLY — never candidate-visible, never public evidence. Language
 * invariant: absence of evidence is NEVER framed as absence of skill
 * ("No published X evidence", never "doesn't know X"). No scores, no
 * percentages — transparent counts only.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../../../../components/passport/shared"
import { EvidenceProofDrawer } from "../../../../../../../components/recruiter/EvidenceProofDrawer"
import {
  CANDIDATE_STAGE_ORDER,
  generateInterviewQuestions,
  getInterviewWorkspace,
  setChecklistMark,
  updateBriefCandidate,
  updateInterview,
  type BriefCandidateStatus,
  type InterviewActivityEvent,
  type InterviewMarkState,
  type InterviewPatch,
  type InterviewQuestion,
  type InterviewQuestions,
  type InterviewWorkspace,
  type MatrixCell,
  type MatrixRequirement,
} from "@/lib/recruiter-briefs-api"
import {
  CANDIDATE_STATUS_LABEL,
  CANDIDATE_STATUS_TONE,
} from "../../BriefDetailView"

const MARK_OPTIONS: { state: InterviewMarkState; label: string }[] = [
  { state: "discussed", label: "Discussed" },
  { state: "verified", label: "Verified in interview" },
  { state: "follow_up", label: "Follow up" },
]

/** Explicit outcome shortcuts (forward-relevant stages only). */
const DECISION_ACTIONS: { status: BriefCandidateStatus; label: string }[] = [
  { status: "interview", label: "Move to Interview" },
  { status: "decision", label: "Move to Decision" },
  { status: "hired", label: "Hired" },
  { status: "passed", label: "Passed" },
  { status: "archived", label: "Archived" },
]

/** ISO timestamp → value for an <input type="datetime-local"> (local time). */
function isoToLocalInput(iso: string | null): string {
  if (!iso) return ""
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** datetime-local value → ISO timestamp (or null when unparseable). */
function localInputToIso(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

function activityLabel(event: InterviewActivityEvent): string {
  switch (event.event_type) {
    case "added":
      return "Added to role"
    case "removed":
      return "Removed from role"
    case "stage_changed": {
      const to = typeof event.detail?.to === "string" ? event.detail.to : null
      const label =
        to && to in CANDIDATE_STATUS_LABEL
          ? CANDIDATE_STATUS_LABEL[to as BriefCandidateStatus]
          : to
      return label ? `Moved to ${label}` : "Stage changed"
    }
    case "note_updated":
      return "Private note updated"
    case "interview_updated":
      return "Interview details updated"
    case "checklist_marked":
      return "Checklist mark updated"
    case "questions_generated":
      return "Interview questions generated"
    default:
      return event.event_type.replace(/_/g, " ")
  }
}

type ChecklistGroup = "Required" | "Required evidence" | "Preferred"

function groupOf(req: MatrixRequirement): ChecklistGroup {
  if (!req.required) return "Preferred"
  return req.kind === "evidence" ? "Required evidence" : "Required"
}

function ChecklistRow({
  req,
  cell,
  mark,
  candidateSlug,
  onToggleMark,
}: {
  req: MatrixRequirement
  cell: MatrixCell | undefined
  mark: InterviewMarkState | null
  candidateSlug: string | null
  onToggleMark: (requirementKey: string, state: InterviewMarkState) => void
}) {
  const [proofOpen, setProofOpen] = useState(false)
  const state = cell?.state ?? "none"
  const proven = state === "proven"
  const canExpandProof = proven && req.kind === "concept" && Boolean(candidateSlug)
  const proofConcept = req.concepts[0] ?? req.display

  return (
    <div
      data-testid="interview-checklist-row"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 0",
        borderBottom: `1px solid ${TOKEN.line}`,
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 13, color: TOKEN.ink, fontWeight: 700, overflowWrap: "anywhere" }}>
          {req.display}
        </span>
        {proven ? (
          <span style={{ fontSize: 12.5, color: TOKEN.emerald, fontWeight: 600 }}>
            ✓ Published evidence
          </span>
        ) : state === "claimed" ? (
          <span style={{ fontSize: 12.5, color: TOKEN.amber, fontWeight: 600 }}>
            Claimed — not verified evidence
          </span>
        ) : state === "unavailable" ? (
          <span style={{ fontSize: 12.5, color: TOKEN.muted, fontWeight: 600 }}>
            Evidence currently unavailable
          </span>
        ) : (
          <span style={{ fontSize: 12.5, color: TOKEN.muted, fontWeight: 600 }}>
            ? No published evidence — verify during interview
          </span>
        )}
        {proven && cell?.matched_label && cell.matched_label !== req.display && (
          <span style={{ fontSize: 12, color: TOKEN.muted }}>via {cell.matched_label}</span>
        )}
        {proven && cell?.proof_path && (
          <a
            data-testid="interview-proof-link"
            href={cell.proof_path}
            style={{ fontSize: 12, color: TOKEN.indigo, fontWeight: 700, textDecoration: "none" }}
          >
            View proof →
          </a>
        )}
        {canExpandProof && (
          <button
            type="button"
            data-testid="requirement-view-proof"
            aria-expanded={proofOpen}
            onClick={() => setProofOpen((current) => !current)}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              color: TOKEN.indigo,
              fontSize: 12,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            {proofOpen ? "Hide evidence" : "Show evidence"}
          </button>
        )}
      </div>
      {proven && (cell?.evidence_sources.length || cell?.project_titles.length) ? (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          {[
            cell?.evidence_sources.slice(0, 3).join(" · "),
            cell?.project_titles.length ? `in ${cell.project_titles.slice(0, 2).join(", ")}` : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
      {canExpandProof && (
        <EvidenceProofDrawer
          open={proofOpen}
          skill={proofConcept}
          candidateSlug={candidateSlug ?? undefined}
        />
      )}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
        {MARK_OPTIONS.map((option) => {
          const active = mark === option.state
          return (
            <button
              key={option.state}
              type="button"
              data-testid={`interview-mark-${option.state}`}
              aria-pressed={active}
              onClick={() => onToggleMark(req.key, option.state)}
              style={{
                padding: "4px 10px",
                borderRadius: 999,
                border: `1px solid ${active ? TOKEN.indigo : TOKEN.line}`,
                background: active ? TOKEN.indigoSoft : "#fff",
                color: active ? TOKEN.indigo : TOKEN.muted,
                fontSize: 11.5,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function QuestionCard({ question }: { question: InterviewQuestion }) {
  const evidenceBacked = question.kind === "evidence"
  const grounding = question.grounding
  const groundingParts = [
    grounding.requirement_display,
    grounding.project_titles.slice(0, 2).join(", "),
    grounding.evidence_sources.slice(0, 3).join(", "),
  ].filter(Boolean)
  return (
    <div
      data-testid="interview-question-card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "12px 14px",
        borderRadius: 10,
        border: `1px solid ${TOKEN.line}`,
        background: evidenceBacked ? "#fafbff" : "#fffdf5",
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        <Badge tone={evidenceBacked ? "emerald" : "amber"}>
          {evidenceBacked ? "Evidence-backed" : "Gap to verify"}
        </Badge>
      </div>
      <p style={{ fontSize: 13.5, color: TOKEN.ink, margin: 0, lineHeight: 1.55, overflowWrap: "anywhere" }}>
        {question.question}
      </p>
      <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5, overflowWrap: "anywhere" }}>
        {groundingParts.join(" · ")}
        {grounding.proof_path && question.evidence_available && (
          <>
            {" "}
            <a
              data-testid="interview-question-proof"
              href={grounding.proof_path}
              style={{ color: TOKEN.indigo, fontWeight: 700, textDecoration: "none" }}
            >
              View proof →
            </a>
          </>
        )}
      </p>
      {/* Only an evidence-backed question can go stale — a gap question
          never cited published proof, and a claimed-grounded question
          already says "not verified". Stale = the cited requirement's
          evidence has since disappeared entirely. */}
      {question.kind === "evidence" &&
        (grounding.state === "none" || grounding.state === "unavailable") && (
        <p
          data-testid="interview-question-stale"
          style={{ fontSize: 12, color: TOKEN.amber, margin: 0, fontWeight: 600 }}
        >
          Previously referenced evidence is no longer published.
        </p>
      )}
    </div>
  )
}

export function InterviewWorkspaceView({
  briefId,
  studentUserId,
}: {
  briefId: string
  studentUserId: string
}) {
  const [workspace, setWorkspace] = useState<InterviewWorkspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [poolStatus, setPoolStatus] = useState<BriefCandidateStatus>("saved")
  const [stageError, setStageError] = useState<string | null>(null)

  const [markByKey, setMarkByKey] = useState<Record<string, InterviewMarkState>>({})
  const [markError, setMarkError] = useState<string | null>(null)

  const [questions, setQuestions] = useState<InterviewQuestions | null>(null)
  const [questionsBusy, setQuestionsBusy] = useState(false)
  const [questionsError, setQuestionsError] = useState<string | null>(null)

  const [activityOpen, setActivityOpen] = useState(false)

  // ── Notes autosave (debounced, stale-response-dropping, save-on-blur) ──
  const emptyForm = {
    scheduled_at: "",
    interviewer_name: "",
    prep_notes: "",
    notes: "",
    decision_notes: "",
  }
  const [form, setForm] = useState(emptyForm)
  const formRef = useRef(form)
  // Last successfully persisted snapshot — the diff base for patches.
  const savedRef = useRef(form)
  const saveSeq = useRef(0)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle")

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getInterviewWorkspace(briefId, studentUserId)
      .then((loaded) => {
        setWorkspace(loaded)
        setPoolStatus(loaded.pool_status)
        setQuestions(loaded.questions)
        setMarkByKey(
          Object.fromEntries(loaded.marks.map((mark) => [mark.requirement_key, mark.state])),
        )
        const initial = {
          scheduled_at: isoToLocalInput(loaded.interview?.scheduled_at ?? null),
          interviewer_name: loaded.interview?.interviewer_name ?? "",
          prep_notes: loaded.interview?.prep_notes ?? "",
          notes: loaded.interview?.notes ?? "",
          decision_notes: loaded.interview?.decision_notes ?? "",
        }
        setForm(initial)
        formRef.current = initial
        savedRef.current = initial
        setSaveState("idle")
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load the interview workspace."),
      )
      .finally(() => setLoading(false))
  }, [briefId, studentUserId])

  useEffect(() => {
    load()
  }, [load])

  /** Diff the current form against the last saved snapshot → API patch. */
  const buildPatch = useCallback((): InterviewPatch => {
    const current = formRef.current
    const saved = savedRef.current
    const patch: InterviewPatch = {}
    if (current.scheduled_at !== saved.scheduled_at) {
      const iso = localInputToIso(current.scheduled_at)
      if (iso) patch.scheduled_at = iso
      else patch.clear_scheduled_at = true
    }
    const textField = (
      key: "interviewer_name" | "prep_notes" | "notes" | "decision_notes",
      clearKey: "clear_interviewer_name" | "clear_prep_notes" | "clear_notes" | "clear_decision_notes",
    ) => {
      if (current[key] === saved[key]) return
      if (current[key].trim() === "") patch[clearKey] = true
      else patch[key] = current[key]
    }
    textField("interviewer_name", "clear_interviewer_name")
    textField("prep_notes", "clear_prep_notes")
    textField("notes", "clear_notes")
    textField("decision_notes", "clear_decision_notes")
    return patch
  }, [])

  const flushSave = useCallback(async () => {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    const patch = buildPatch()
    if (Object.keys(patch).length === 0) return
    const seq = ++saveSeq.current
    const snapshot = { ...formRef.current }
    setSaveState("saving")
    try {
      await updateInterview(briefId, studentUserId, patch)
      // Stale-drop: a newer edit's save is already in flight or done.
      if (seq !== saveSeq.current) return
      savedRef.current = snapshot
      setSaveState("saved")
    } catch {
      if (seq !== saveSeq.current) return
      setSaveState("error")
    }
  }, [briefId, buildPatch, studentUserId])

  const editField = (key: keyof typeof emptyForm, value: string) => {
    setForm((current) => {
      const next = { ...current, [key]: value }
      formRef.current = next
      return next
    })
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      void flushSave()
    }, 800)
  }

  // Warn before leaving with unsaved notes (autosave is fast, but honest).
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      const dirty =
        JSON.stringify(formRef.current) !== JSON.stringify(savedRef.current)
      if (!dirty) return
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", onBeforeUnload)
    return () => window.removeEventListener("beforeunload", onBeforeUnload)
  }, [])

  const toggleMark = (requirementKey: string, state: InterviewMarkState) => {
    const previous = markByKey[requirementKey] ?? null
    const next = previous === state ? null : state
    setMarkError(null)
    setMarkByKey((current) => {
      const updated = { ...current }
      if (next) updated[requirementKey] = next
      else delete updated[requirementKey]
      return updated
    })
    setChecklistMark(briefId, studentUserId, { requirement_key: requirementKey, state: next })
      .then((marks) =>
        setMarkByKey(
          Object.fromEntries(marks.map((mark) => [mark.requirement_key, mark.state])),
        ),
      )
      .catch((err: unknown) => {
        setMarkByKey((current) => {
          const reverted = { ...current }
          if (previous) reverted[requirementKey] = previous
          else delete reverted[requirementKey]
          return reverted
        })
        setMarkError(err instanceof Error ? err.message : "Failed to save the mark.")
      })
  }

  const generate = (regenerate: boolean) => {
    setQuestionsBusy(true)
    setQuestionsError(null)
    generateInterviewQuestions(
      briefId,
      studentUserId,
      regenerate ? { regenerate: true } : {},
    )
      .then(setQuestions)
      .catch((err: unknown) =>
        setQuestionsError(
          err instanceof Error ? err.message : "Failed to generate interview questions.",
        ),
      )
      .finally(() => setQuestionsBusy(false))
  }

  const setStage = (status: BriefCandidateStatus) => {
    if (status === poolStatus) return
    const previous = poolStatus
    setStageError(null)
    setPoolStatus(status)
    updateBriefCandidate(briefId, studentUserId, { status }).catch((err: unknown) => {
      setPoolStatus(previous)
      setStageError(err instanceof Error ? err.message : "Failed to update the stage.")
    })
  }

  if (loading) {
    return (
      <div style={{ width: "100%", maxWidth: 1140, margin: "0 auto", padding: "40px 24px" }}>
        <LoadingState label="Loading interview workspace…" />
      </div>
    )
  }
  if (error || !workspace) {
    return (
      <div style={{ width: "100%", maxWidth: 1140, margin: "0 auto", padding: "40px 24px" }}>
        <ErrorState
          message={error ?? "This interview workspace was not found."}
          onRetry={load}
        />
      </div>
    )
  }

  const { brief, candidate, checklist } = workspace
  const name = candidate.display_name ?? "Verified candidate"
  const candidateSlug = candidate.public_slug
  const groups: ChecklistGroup[] = ["Required", "Required evidence", "Preferred"]
  const grouped = groups
    .map((group) => ({
      group,
      requirements: checklist.requirements.filter((req) => groupOf(req) === group),
    }))
    .filter((entry) => entry.requirements.length > 0)

  const notesCaption = "Private to you — never visible to the candidate."

  return (
    <div
      data-testid="interview-workspace"
      style={{
        width: "100%",
        maxWidth: 1140,
        margin: "0 auto",
        padding: "40px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 18,
      }}
    >
      {/* ── Header ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <p style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: TOKEN.muted, margin: 0, fontWeight: 700 }}>
          <Link
            href={`/recruiters/briefs/${encodeURIComponent(briefId)}`}
            data-testid="interview-back"
            style={{ color: TOKEN.muted, textDecoration: "none" }}
          >
            ← {brief.title}
          </Link>
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
          <h1 style={{ fontSize: 24, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px", overflowWrap: "anywhere" }}>
            {name}
          </h1>
          <Badge tone={CANDIDATE_STATUS_TONE[poolStatus]}>
            {CANDIDATE_STATUS_LABEL[poolStatus]}
          </Badge>
          {candidateSlug ? (
            <a
              data-testid="interview-open-passport"
              href={`/p/${encodeURIComponent(candidateSlug)}`}
              style={{ fontSize: 12.5, color: TOKEN.indigo, fontWeight: 700, textDecoration: "none" }}
            >
              Open Passport →
            </a>
          ) : (
            <Badge tone="amber">Passport currently private</Badge>
          )}
        </div>
        {candidate.headline && (
          <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            {candidate.headline}
          </p>
        )}
        <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
          Interview prep for <strong style={{ color: TOKEN.inkSoft }}>{brief.title}</strong>
        </p>
        {checklist.summary && (
          <p
            data-testid="interview-summary"
            style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.55 }}
          >
            {checklist.summary}
          </p>
        )}
        {checklist.available && checklist.counts.required_total > 0 && (
          <p
            data-testid="interview-coverage"
            style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, fontWeight: 600 }}
          >
            Required evidence supported: {checklist.counts.required_proven} of{" "}
            {checklist.counts.required_total}
          </p>
        )}
      </div>

      {/* ── Two columns on desktop, stacked on narrow screens ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))",
          gap: 16,
          alignItems: "start",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          {/* ── Verification checklist ── */}
          <Card style={{ padding: 18 }}>
            <div data-testid="interview-checklist" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h2 style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                Verification checklist
              </h2>
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
                Re-checked against live published evidence on every load. Marks
                are recruiter-private — they never become public evidence.
              </p>
              {!checklist.available ? (
                <div
                  data-testid="interview-checklist-unavailable"
                  style={{
                    padding: "12px 14px",
                    borderRadius: 10,
                    background: TOKEN.amberSoft,
                    color: TOKEN.amber,
                    fontSize: 13,
                    fontWeight: 600,
                    lineHeight: 1.5,
                  }}
                >
                  This candidate&apos;s passport is currently unpublished or
                  restricted — evidence checks are unavailable.
                </div>
              ) : checklist.requirements.length === 0 ? (
                <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
                  This role has no requirements yet — edit the brief to build the checklist.
                </p>
              ) : (
                grouped.map(({ group, requirements }) => (
                  <div key={group} style={{ display: "flex", flexDirection: "column" }}>
                    <h3
                      style={{
                        fontSize: 11.5,
                        letterSpacing: "0.07em",
                        textTransform: "uppercase",
                        color: TOKEN.muted,
                        margin: "6px 0 0",
                        fontWeight: 700,
                      }}
                    >
                      {group}
                    </h3>
                    {requirements.map((req) => (
                      <ChecklistRow
                        key={req.key}
                        req={req}
                        cell={checklist.cells[req.key]}
                        mark={markByKey[req.key] ?? null}
                        candidateSlug={candidateSlug}
                        onToggleMark={toggleMark}
                      />
                    ))}
                  </div>
                ))
              )}
              {markError && (
                <p role="alert" style={{ fontSize: 12, color: "#b91c1c", margin: 0 }}>
                  {markError}
                </p>
              )}
              <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0 }}>
                Recruiter-private — never becomes public evidence.
              </p>
            </div>
          </Card>

          {/* ── Interview questions ── */}
          <Card style={{ padding: 18 }}>
            <div data-testid="interview-questions" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <h2 style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                  Interview questions
                </h2>
                {questions && (
                  <button
                    type="button"
                    data-testid="interview-regenerate-questions"
                    onClick={() => generate(true)}
                    disabled={questionsBusy}
                    style={{
                      marginLeft: "auto",
                      padding: "6px 12px",
                      borderRadius: 8,
                      border: `1px solid ${TOKEN.line}`,
                      background: "#fff",
                      color: TOKEN.muted,
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: questionsBusy ? "wait" : "pointer",
                    }}
                  >
                    {questionsBusy ? "Generating…" : "Regenerate"}
                  </button>
                )}
              </div>
              {questionsError && (
                <p role="alert" style={{ fontSize: 12, color: "#b91c1c", margin: 0 }}>
                  {questionsError}
                </p>
              )}
              {!questions ? (
                <EmptyState
                  icon="💬"
                  title="No questions generated yet"
                  description="Generate interview questions grounded in this candidate's published evidence and this role's requirements."
                  action={
                    <button
                      type="button"
                      data-testid="interview-generate-questions"
                      onClick={() => generate(false)}
                      disabled={questionsBusy}
                      style={{
                        padding: "8px 16px",
                        borderRadius: 8,
                        border: "none",
                        background: TOKEN.indigo,
                        color: "#fff",
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: questionsBusy ? "wait" : "pointer",
                      }}
                    >
                      {questionsBusy ? "Generating…" : "Generate questions"}
                    </button>
                  }
                />
              ) : (
                <>
                  <p
                    data-testid="interview-questions-provenance"
                    style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
                  >
                    {questions.source === "llm"
                      ? "AI-suggested from published evidence — advisory only."
                      : "Generated deterministically from published evidence — advisory only."}
                    {questions.fallback_reason ? ` ${questions.fallback_reason}` : ""}
                  </p>
                  {questions.items.length === 0 ? (
                    <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
                      No questions could be grounded in the current checklist.
                    </p>
                  ) : (
                    questions.items.map((question) => (
                      <QuestionCard key={question.id} question={question} />
                    ))
                  )}
                </>
              )}
            </div>
          </Card>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          {/* ── Notes (autosaved) ── */}
          <Card style={{ padding: 18 }}>
            <div data-testid="interview-notes" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                <h2 style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                  Notes
                </h2>
                <span
                  data-testid="interview-notes-status"
                  aria-live="polite"
                  style={{
                    marginLeft: "auto",
                    fontSize: 12,
                    fontWeight: 600,
                    color:
                      saveState === "error"
                        ? "#b91c1c"
                        : saveState === "saved"
                          ? TOKEN.emerald
                          : TOKEN.muted,
                  }}
                >
                  {saveState === "saving"
                    ? "Saving…"
                    : saveState === "saved"
                      ? "Saved ✓"
                      : saveState === "error"
                        ? "Couldn't save"
                        : ""}
                  {saveState === "error" && (
                    <>
                      {" "}
                      <button
                        type="button"
                        data-testid="interview-notes-retry"
                        onClick={() => void flushSave()}
                        style={{
                          background: "none",
                          border: "none",
                          padding: 0,
                          color: TOKEN.indigo,
                          fontSize: 12,
                          fontWeight: 700,
                          cursor: "pointer",
                        }}
                      >
                        Retry
                      </button>
                    </>
                  )}
                </span>
              </div>
              <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0 }}>{notesCaption}</p>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: TOKEN.muted, fontWeight: 600, flex: "1 1 180px" }}>
                  Scheduled
                  <input
                    type="datetime-local"
                    data-testid="interview-scheduled-at"
                    value={form.scheduled_at}
                    onChange={(event) => editField("scheduled_at", event.target.value)}
                    onBlur={() => void flushSave()}
                    style={{ padding: "7px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 12.5, color: TOKEN.ink, background: "#fff" }}
                  />
                </label>
                <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: TOKEN.muted, fontWeight: 600, flex: "1 1 180px" }}>
                  Interviewer
                  <input
                    type="text"
                    data-testid="interview-interviewer-name"
                    value={form.interviewer_name}
                    onChange={(event) => editField("interviewer_name", event.target.value)}
                    onBlur={() => void flushSave()}
                    maxLength={120}
                    placeholder="Who is interviewing?"
                    style={{ padding: "7px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 12.5, color: TOKEN.ink, background: "#fff" }}
                  />
                </label>
              </div>

              {(
                [
                  ["prep_notes", "Preparation notes", "interview-prep-notes", "What to probe, logistics, context…"],
                  ["notes", "Interview notes", "interview-notes-input", "Live notes during the interview…"],
                  ["decision_notes", "Decision notes", "interview-decision-notes", "Outcome rationale for this role…"],
                ] as const
              ).map(([key, label, testId, placeholder]) => (
                <label key={key} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: TOKEN.muted, fontWeight: 600 }}>
                  {label}
                  <textarea
                    data-testid={testId}
                    value={form[key]}
                    onChange={(event) => editField(key, event.target.value)}
                    onBlur={() => void flushSave()}
                    maxLength={4000}
                    rows={4}
                    placeholder={placeholder}
                    style={{
                      padding: "8px 10px",
                      borderRadius: 8,
                      border: `1px solid ${TOKEN.line}`,
                      fontSize: 12.5,
                      color: TOKEN.ink,
                      resize: "vertical",
                      lineHeight: 1.5,
                    }}
                  />
                </label>
              ))}
            </div>
          </Card>

          {/* ── Decision strip ── */}
          <Card style={{ padding: 18 }}>
            <div data-testid="interview-decision" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <h2 style={{ fontSize: 15, color: TOKEN.ink, margin: 0, fontWeight: 700 }}>
                  Role stage
                </h2>
                <Badge tone={CANDIDATE_STATUS_TONE[poolStatus]}>
                  {CANDIDATE_STATUS_LABEL[poolStatus]}
                </Badge>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {DECISION_ACTIONS.map((action) => (
                  <button
                    key={action.status}
                    type="button"
                    data-testid={`interview-stage-${action.status}`}
                    onClick={() => setStage(action.status)}
                    disabled={action.status === poolStatus}
                    style={{
                      padding: "6px 12px",
                      borderRadius: 8,
                      border: `1px solid ${action.status === poolStatus ? TOKEN.indigo : TOKEN.line}`,
                      background: action.status === poolStatus ? TOKEN.indigoSoft : "#fff",
                      color: action.status === poolStatus ? TOKEN.indigo : TOKEN.inkSoft,
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: action.status === poolStatus ? "default" : "pointer",
                    }}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: TOKEN.muted, fontWeight: 600 }}>
                Any stage
                <select
                  data-testid="interview-stage-select"
                  value={poolStatus}
                  onChange={(event) => setStage(event.target.value as BriefCandidateStatus)}
                  style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, fontSize: 12.5, color: TOKEN.ink, background: "#fff" }}
                >
                  {CANDIDATE_STAGE_ORDER.map((status) => (
                    <option key={status} value={status}>
                      {CANDIDATE_STATUS_LABEL[status]}
                    </option>
                  ))}
                </select>
              </label>
              {stageError && (
                <p role="alert" style={{ fontSize: 12, color: "#b91c1c", margin: 0 }}>
                  {stageError}
                </p>
              )}
              <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0 }}>
                Stage changes apply to this role only — never to other briefs.
              </p>
            </div>
          </Card>

          {/* ── Activity ── */}
          <Card style={{ padding: 18 }}>
            <div data-testid="interview-activity" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <button
                type="button"
                data-testid="interview-activity-toggle"
                aria-expanded={activityOpen}
                onClick={() => setActivityOpen((current) => !current)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  textAlign: "left",
                  fontSize: 15,
                  color: TOKEN.ink,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Activity {activityOpen ? "▾" : "▸"}
              </button>
              {activityOpen &&
                (workspace.activity.length === 0 ? (
                  <p style={{ fontSize: 12.5, color: TOKEN.muted, margin: 0 }}>
                    No activity recorded yet.
                  </p>
                ) : (
                  workspace.activity.map((event, index) => (
                    <p
                      key={`${event.event_type}-${event.created_at}-${index}`}
                      data-testid="interview-activity-event"
                      style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}
                    >
                      {activityLabel(event)}
                      {event.created_at && (
                        <span style={{ color: TOKEN.muted }}>
                          {" · "}
                          {new Date(event.created_at).toLocaleString()}
                        </span>
                      )}
                    </p>
                  ))
                ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
