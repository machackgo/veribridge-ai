"use client"

/**
 * /student — the canonical authenticated Student Dashboard (dashboard
 * consolidation Stage 2).
 *
 * This page is a read-only aggregation over the EXISTING canonical APIs and a
 * launcher for the EXISTING canonical workflows. Deliberate constraints:
 *  - No new endpoints, no dashboard-only proof state, no duplicated workflow
 *    logic: every button navigates to the current canonical route.
 *  - The "next action" is derived with narrow deterministic rules over real
 *    records (no LLM, no scores).
 *  - Defense projects (metadata.phase === "project_defense_mvp_v1") are never
 *    advertised as recordable walkthroughs — same contract the old Proof
 *    Studio enforced.
 *  - ?section=proofs (used by the legacy /student/vbr redirect) scrolls the
 *    Proofs section into view so old links land somewhere meaningful.
 */

import Link from "next/link"
import { Suspense, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { useSearchParams } from "next/navigation"
import {
  getVBRProjectQuestions,
  getVBRProjectReportPublishStatus,
  getWorkPassportStatus,
  listVBRProjects,
  type ProjectReportPublishStatus,
  type VBRProjectResponse,
  type WorkPassportStatus,
} from "@/lib/vbr-api"
import {
  listDocumentProofs,
  listGitHubProofs,
  listWebsiteProofs,
  type DocumentProofResponse,
  type GitHubProofResponse,
  type WebsiteProofSummaryResponse,
} from "@/lib/passport-api"
import { getSkillGapsOverview, type SkillGapsOverviewResponse } from "@/lib/skill-gaps-api"
import { RecorderExtensionCard } from "../../../components/student/recorder-extension-card"
import {
  deriveNextAction,
  isDefenseProject,
  summarizeProofStatuses,
  type ProofWorkflowState,
} from "../../../components/student/dashboard-logic"

/* ── Visual primitives (existing student-page idiom) ─────────────────────── */

const cardStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--paper)",
  padding: 18,
}

const chipStyle: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink-2)",
  fontSize: 12,
  fontFamily: "var(--font-mono)",
  whiteSpace: "nowrap",
}

const actionLinkStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "8px 14px",
  borderRadius: 10,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink)",
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
}

const primaryLinkStyle: CSSProperties = {
  ...actionLinkStyle,
  background: "var(--ink)",
  color: "#fff",
  border: "1px solid var(--ink)",
}

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", margin: "0 0 12px" }}>{children}</h2>
  )
}

function stateChipColor(state: ProofWorkflowState): CSSProperties {
  if (state === "Failed / retry available")
    return { background: "var(--rose-soft, #fff1f2)", borderColor: "var(--rose)", color: "var(--ink)" }
  if (state === "Complete") return { background: "#ecfdf5", borderColor: "#a7f3d0", color: "#065f46" }
  if (state === "Not started") return {}
  return { background: "#fffbeb", borderColor: "#fde68a", color: "#92400e" }
}

/* ── Page ────────────────────────────────────────────────────────────────── */

const RESUME_LOOKUP_CAP = 6
const REPORT_STATUS_CAP = 8
const ENRICHMENT_CONCURRENCY = 3

/**
 * Bounded-concurrency map for the per-project enrichment lookups: keeps the
 * dashboard's request burst small (the core lists already fire in parallel)
 * so accounts with many projects don't stampede the API.
 */
async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<R>
): Promise<R[]> {
  const out: R[] = new Array(items.length)
  let next = 0
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next
      next += 1
      out[i] = await fn(items[i])
    }
  })
  await Promise.all(workers)
  return out
}

type ResumeCheckpoint = { projectId: string; projectTitle: string; sessionId: string }

function StudentDashboardInner() {
  const searchParams = useSearchParams()
  const focusSection = searchParams.get("section")
  const proofsRef = useRef<HTMLElement | null>(null)

  const [projects, setProjects] = useState<VBRProjectResponse[] | null>(null)
  const [githubProofs, setGithubProofs] = useState<GitHubProofResponse[] | null>(null)
  const [websiteProofs, setWebsiteProofs] = useState<WebsiteProofSummaryResponse[] | null>(null)
  const [documentProofs, setDocumentProofs] = useState<DocumentProofResponse[] | null>(null)
  const [passport, setPassport] = useState<WorkPassportStatus | null>(null)
  const [passportFailed, setPassportFailed] = useState(false)
  const [gaps, setGaps] = useState<SkillGapsOverviewResponse | null>(null)
  const [gapsFailed, setGapsFailed] = useState(false)
  const [checkpoints, setCheckpoints] = useState<ResumeCheckpoint[] | null>(null)
  const [reportStatuses, setReportStatuses] = useState<Record<string, ProjectReportPublishStatus> | null>(null)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  // True when any of the three proof lists failed to load. Failed lists stay
  // null (never []) so an API outage can NEVER render as "Not started" —
  // that would tell a student their existing work doesn't exist.
  const [proofListsFailed, setProofListsFailed] = useState(false)
  const [reloadTick, setReloadTick] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function load() {
      // Independent loads: one failing surface never blanks the others.
      listGitHubProofs()
        .then((rows) => !cancelled && setGithubProofs(rows))
        .catch(() => !cancelled && setProofListsFailed(true))
      listWebsiteProofs()
        .then((rows) => !cancelled && setWebsiteProofs(rows))
        .catch(() => !cancelled && setProofListsFailed(true))
      listDocumentProofs()
        .then((rows) => !cancelled && setDocumentProofs(rows))
        .catch(() => !cancelled && setProofListsFailed(true))
      getWorkPassportStatus()
        .then((status) => !cancelled && setPassport(status))
        .catch(() => {
          if (!cancelled) setPassportFailed(true)
        })
      getSkillGapsOverview()
        .then((overview) => !cancelled && setGaps(overview))
        .catch(() => {
          if (!cancelled) setGapsFailed(true)
        })

      let projectRows: VBRProjectResponse[] = []
      try {
        projectRows = await listVBRProjects()
        if (cancelled) return
        setProjects(projectRows)
      } catch (err) {
        if (!cancelled) {
          setProjects([])
          setCheckpoints([])
          setReportStatuses({})
          setProjectsError(err instanceof Error ? err.message : "Failed to load your projects.")
        }
        return
      }

      // Resumable walkthrough checkpoints — recorder sessions only ever exist
      // for non-defense projects, so defense projects are never queried and
      // never advertised as recordable (same contract as the old Proof Studio).
      const walkthroughs = projectRows.filter((p) => !isDefenseProject(p)).slice(0, RESUME_LOOKUP_CAP)
      const found = await mapWithConcurrency(walkthroughs, ENRICHMENT_CONCURRENCY, async (project) => {
        try {
          const questions = await getVBRProjectQuestions(project.id)
          return questions.session_id
            ? { projectId: project.id, projectTitle: project.title, sessionId: questions.session_id }
            : null
        } catch {
          return null
        }
      })
      if (!cancelled) setCheckpoints(found.filter((c): c is ResumeCheckpoint => c !== null))

      // Report publish status per project (bounded; each failure renders as "—").
      const reportTargets = projectRows.slice(0, REPORT_STATUS_CAP)
      const statuses = await mapWithConcurrency(reportTargets, ENRICHMENT_CONCURRENCY, async (project) => {
        try {
          return await getVBRProjectReportPublishStatus(project.id)
        } catch {
          return null
        }
      })
      if (!cancelled) {
        const byProject: Record<string, ProjectReportPublishStatus> = {}
        statuses.forEach((status) => {
          if (status) byProject[status.project_id] = status
        })
        setReportStatuses(byProject)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [reloadTick])

  // Legacy /student/vbr links land on ?section=proofs — bring that section into view.
  useEffect(() => {
    if (focusSection === "proofs") {
      proofsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [focusSection])

  const coreLoaded =
    projects !== null && githubProofs !== null && websiteProofs !== null && documentProofs !== null

  const resumableSessionId = checkpoints?.[0]?.sessionId ?? null
  const nextAction = coreLoaded
    ? deriveNextAction({
        projects,
        githubProofs,
        websiteProofs,
        documentProofs,
        gaps,
        passport,
        resumableSessionId,
      })
    : null

  const githubState = summarizeProofStatuses((githubProofs ?? []).map((p) => p.status))
  // listWebsiteProofs() only returns completed sessions, so presence == complete.
  const websiteState: ProofWorkflowState = (websiteProofs?.length ?? 0) > 0 ? "Complete" : "Not started"
  const documentState = summarizeProofStatuses((documentProofs ?? []).map((p) => p.status))
  const defenseProjects = (projects ?? []).filter(isDefenseProject)
  const defenseState: ProofWorkflowState =
    defenseProjects.length === 0
      ? "Not started"
      : defenseProjects.every((p) => p.metadata?.project_defense_status === "analyzed")
        ? "Complete"
        : "In progress"

  const proofCards: Array<{
    key: string
    icon: string
    title: string
    state: ProofWorkflowState
    count: number | null
    href: string
    cta: string
  }> = [
    {
      key: "github",
      icon: "🐙",
      title: "GitHub Proof",
      state: githubState,
      count: githubProofs?.length ?? null,
      href: "/student/proofs/github",
      cta: githubProofs?.length ? "Open GitHub Proof" : "Add GitHub proof",
    },
    {
      key: "website",
      icon: "🌐",
      title: "Website / Live App Proof",
      state: websiteState,
      count: websiteProofs?.length ?? null,
      href: "/student/proofs/website",
      cta: websiteProofs?.length ? "Open Website Proof" : "Add website proof",
    },
    {
      key: "documents",
      icon: "📄",
      title: "Document Proof",
      state: documentState,
      count: documentProofs?.length ?? null,
      href: "/student/proofs/documents",
      cta: documentProofs?.length ? "Open Document Proof" : "Add document proof",
    },
    {
      key: "defense",
      icon: "🧩",
      title: "Project Defense",
      state: defenseState,
      count: projects ? defenseProjects.length : null,
      href: "/student/proofs/project-defense",
      cta: defenseProjects.length ? "Open Project Defense" : "Start project defense",
    },
  ]

  const gapSummary = gaps
    ? {
        assessedProjects: gaps.projects.filter((p) => p.assessment_state === "assessed").length,
        totalProjects: gaps.projects.length,
        demonstrated: gaps.projects.reduce((n, p) => n + p.demonstrated_skills.length, 0),
        gapCount: gaps.total_gap_count,
      }
    : null

  const reportRows = (projects ?? []).slice(0, REPORT_STATUS_CAP)

  return (
    <div data-testid="student-dashboard" style={{ maxWidth: 900, margin: "0 auto", padding: "32px 24px 64px" }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, color: "var(--ink)", letterSpacing: "-0.6px", margin: 0 }}>
          Student Dashboard
        </h1>
        <p
          data-testid="dashboard-project-context"
          style={{ fontSize: 14, color: "var(--ink-2)", opacity: 0.85, margin: "8px 0 0" }}
        >
          {projects === null
            ? "Loading your projects…"
            : projects.length === 0
              ? "No projects yet — your projects appear here as you add proof sources."
              : `${projects.length} project${projects.length === 1 ? "" : "s"} · latest: ${projects[0]?.title ?? ""}`}
        </p>
      </header>

      {proofListsFailed && (
        <div
          role="alert"
          style={{
            background: "var(--rose-soft)",
            border: "1px solid var(--rose)",
            borderRadius: 10,
            padding: "12px 16px",
            fontSize: 14,
            color: "var(--ink)",
            marginBottom: 20,
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <span>Some of your proofs couldn&apos;t be loaded right now — the tiles below may be incomplete.</span>
          <button
            type="button"
            onClick={() => {
              setProofListsFailed(false)
              setProjectsError(null)
              setReloadTick((t) => t + 1)
            }}
            style={{
              border: "1px solid var(--line)",
              background: "#fff",
              borderRadius: 8,
              padding: "6px 14px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {projectsError && (
        <div
          role="alert"
          style={{
            background: "var(--rose-soft)",
            border: "1px solid var(--rose)",
            borderRadius: 10,
            padding: "12px 16px",
            fontSize: 14,
            color: "var(--ink)",
            marginBottom: 20,
          }}
        >
          <span>{projectsError}</span>
          <button
            type="button"
            onClick={() => {
              setProofListsFailed(false)
              setProjectsError(null)
              setReloadTick((t) => t + 1)
            }}
            style={{
              border: "1px solid var(--line)",
              background: "#fff",
              borderRadius: 8,
              padding: "6px 14px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              marginLeft: 12,
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Primary next action */}
      <section aria-label="Next action" style={{ marginBottom: 28 }}>
        <div
          data-testid="dashboard-next-action"
          style={{
            ...cardStyle,
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 14,
            borderColor: "var(--line-strong, var(--line))",
          }}
        >
          <div style={{ flex: "1 1 260px" }}>
            <div className="vb-eyebrow" style={{ fontSize: 10, marginBottom: 4 }}>
              Next action
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>
              {nextAction ? nextAction.label : "Checking your current state…"}
            </div>
            {nextAction && (
              <p style={{ fontSize: 13, color: "var(--ink-2)", opacity: 0.85, margin: "4px 0 0", lineHeight: 1.5 }}>
                {nextAction.description}
              </p>
            )}
          </div>
          {nextAction && (
            <Link href={nextAction.href} data-testid="dashboard-next-action-link" style={primaryLinkStyle}>
              {nextAction.label}
            </Link>
          )}
        </div>
      </section>

      {/* Proofs */}
      <section
        id="proofs"
        ref={proofsRef}
        aria-label="Proofs"
        data-testid="dashboard-proofs-section"
        style={{
          marginBottom: 28,
          scrollMarginTop: 80,
          ...(focusSection === "proofs" ? { outline: "2px solid var(--indigo)", outlineOffset: 8, borderRadius: 12 } : {}),
        }}
      >
        <SectionTitle>Proofs</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12 }}>
          {proofCards.map((card) => (
            <div key={card.key} data-testid={`proof-card-${card.key}`} style={{ ...cardStyle, display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 20 }}>{card.icon}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)" }}>{card.title}</div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", flex: 1 }}>
                <span style={{ ...chipStyle, ...stateChipColor(card.state) }}>
                  {card.count === null
                    ? proofListsFailed
                      ? "Unavailable"
                      : "Loading…"
                    : card.state}
                </span>
                {card.count !== null && card.count > 0 && (
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>
                    {card.count} {card.count === 1 ? "record" : "records"}
                  </span>
                )}
              </div>
              <div>
                <Link href={card.href} style={actionLinkStyle}>
                  {card.cta}
                </Link>
              </div>
            </div>
          ))}
        </div>

        {/* Website Proof needs the Chrome recorder — surface it with the
            proof tiles so a new student learns this before starting. */}
        <div style={{ marginTop: 12 }}>
          <RecorderExtensionCard />
        </div>
      </section>

      {/* Resume / recent checkpoints */}
      {(checkpoints?.length ?? 0) > 0 && (
        <section aria-label="Resume where you left off" data-testid="dashboard-resume-section" style={{ marginBottom: 28 }}>
          <SectionTitle>Resume where you left off</SectionTitle>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {checkpoints!.map((checkpoint) => (
              <div
                key={checkpoint.sessionId}
                style={{ ...cardStyle, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}
              >
                <div style={{ flex: "1 1 220px" }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{checkpoint.projectTitle}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>Walkthrough recording in progress</div>
                </div>
                <Link href={`/student/vbr/sessions/${checkpoint.sessionId}`} style={actionLinkStyle}>
                  Continue recording
                </Link>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Skills & Gaps */}
      <section aria-label="Skills and gaps" data-testid="dashboard-skills-section" style={{ marginBottom: 28 }}>
        <SectionTitle>Skills &amp; Gaps</SectionTitle>
        <div style={{ ...cardStyle, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
          <div style={{ flex: "1 1 260px", fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6 }}>
            {gapsFailed ? (
              "Skill gap assessment is unavailable right now."
            ) : gapSummary === null ? (
              "Loading your evidence-derived skill assessment…"
            ) : gapSummary.totalProjects === 0 ? (
              "No projects assessed yet — add proof sources to build your skill evidence."
            ) : (
              <>
                <strong style={{ color: "var(--ink)" }}>{gapSummary.demonstrated}</strong> demonstrated skill
                {gapSummary.demonstrated === 1 ? "" : "s"} across {gapSummary.assessedProjects} assessed project
                {gapSummary.assessedProjects === 1 ? "" : "s"}
                {" · "}
                <strong style={{ color: gapSummary.gapCount > 0 ? "#92400e" : "var(--ink)" }}>
                  {gapSummary.gapCount}
                </strong>{" "}
                open gap{gapSummary.gapCount === 1 ? "" : "s"}
              </>
            )}
          </div>
          <Link href="/dashboard/skill-gaps" data-testid="dashboard-skill-gaps-link" style={actionLinkStyle}>
            Open Skills &amp; Gaps
          </Link>
        </div>
      </section>

      {/* Work Passport */}
      <section aria-label="Work passport" data-testid="dashboard-passport-section" style={{ marginBottom: 28 }}>
        <SectionTitle>Verified Work Passport</SectionTitle>
        <div style={{ ...cardStyle, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
          <div style={{ flex: "1 1 260px" }}>
            <span
              style={{
                ...chipStyle,
                ...(passport?.is_published
                  ? { background: "#ecfdf5", borderColor: "#a7f3d0", color: "#065f46" }
                  : {}),
              }}
            >
              {passportFailed
                ? "Status unavailable"
                : passport === null
                  ? "Loading…"
                  : passport.is_published
                    ? "Published"
                    : "Private draft"}
            </span>
            {passport?.is_published && passport.public_path && (
              <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: 10 }}>
                Public link active
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link href="/student/vbr/passport" data-testid="dashboard-passport-link" style={actionLinkStyle}>
              Open Work Passport
            </Link>
            <Link href="/student/vbr/passport/vault" style={actionLinkStyle}>
              Proof Vault
            </Link>
          </div>
        </div>
      </section>

      {/* Reports */}
      <section aria-label="Verified build reports" data-testid="dashboard-reports-section" style={{ marginBottom: 28 }}>
        <SectionTitle>Verified Build Reports</SectionTitle>
        {projects === null ? (
          <p style={{ fontSize: 13, color: "var(--ink-2)", opacity: 0.7 }}>Loading your projects…</p>
        ) : reportRows.length === 0 ? (
          <div style={cardStyle}>
            <p style={{ fontSize: 13, color: "var(--ink-2)", margin: 0, lineHeight: 1.6 }}>
              Reports are generated per project once proof sources are attached. Add a proof source to get
              started.
            </p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {reportRows.map((project) => {
              const status = reportStatuses?.[project.id]
              return (
                <div
                  key={project.id}
                  data-testid={`report-row-${project.id}`}
                  style={{ ...cardStyle, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}
                >
                  <div style={{ flex: "1 1 220px" }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{project.title}</div>
                    {project.repo_full_name && (
                      <div style={{ fontSize: 12, color: "var(--muted)" }}>{project.repo_full_name}</div>
                    )}
                  </div>
                  <span
                    style={{
                      ...chipStyle,
                      ...(status?.is_public
                        ? { background: "#ecfdf5", borderColor: "#a7f3d0", color: "#065f46" }
                        : {}),
                    }}
                  >
                    {reportStatuses === null ? "Loading…" : status ? (status.is_public ? "Published" : "Private") : "—"}
                  </span>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <Link href={`/student/vbr/projects/${project.id}/report`} style={actionLinkStyle}>
                      Open report
                    </Link>
                    {status?.is_public && status.public_path && (
                      <Link href={status.public_path} style={actionLinkStyle}>
                        View published
                      </Link>
                    )}
                  </div>
                </div>
              )
            })}
            {(projects?.length ?? 0) > REPORT_STATUS_CAP && (
              <p style={{ fontSize: 12, color: "var(--muted)", margin: 0 }}>
                Showing the {REPORT_STATUS_CAP} most recent projects — open the Work Passport for the full list.
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

export default function StudentDashboardPage() {
  // useSearchParams() requires a Suspense boundary during static generation.
  return (
    <Suspense fallback={null}>
      <StudentDashboardInner />
    </Suspense>
  )
}
