"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import {
  getProjectDefenseContext,
  listEligibleDefenseProjects,
  type DefenseEvidenceTypeSummary,
  type DefenseStatus,
  type EligibleProjectResponse,
  type ProjectDefenseContextResponse,
} from "@/lib/vbr-api"
import { ProjectDefensePanel } from "./ProjectDefensePanel"
import { Badge, Btn, Card, ErrorState, LoadingState, Mono, TOKEN } from "./shared"

const DEFENSE_STATUS_LABEL: Record<DefenseStatus, { label: string; tone: "slate" | "amber" | "emerald" }> = {
  not_started: { label: "Project Defense not started", tone: "slate" },
  in_progress: { label: "Project Defense in progress", tone: "amber" },
  completed: { label: "Project Defense completed", tone: "emerald" },
}

// CTA copy reflects where the defense already stands — a completed defense
// should never still read "Defend this project".
const DEFENSE_CTA_LABEL: Record<DefenseStatus, string> = {
  not_started: "Defend this project",
  in_progress: "Continue defense",
  completed: "Review defense",
}

const STATUS_RANK: Record<DefenseStatus, number> = { not_started: 1, in_progress: 2, completed: 3 }

function normalizeText(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase().replace(/\s+/g, " ")
}

// Conservative canonical identity: the normalized project TITLE is the primary
// discriminator. A shared repository can strengthen a match but must never merge
// two different project titles on its own — a single monorepo can hold many
// distinct projects (a Billing Service and an Analytics Dashboard both in
// "acme/mono" must stay separate). Two rows collapse only when title AND repo
// agree; an untitled row falls back to repo + description prefix + skill set.
function canonicalKey(project: EligibleProjectResponse): string {
  const title = normalizeText(project.title)
  const repo = normalizeText(project.repo_full_name).replace(/^\/+|\/+$/g, "")
  if (title) return `title-repo:${title}|${repo}`
  const skills = [...project.claimed_skills].map((s) => s.toLowerCase()).sort().join(",")
  return `repo-desc:${repo}|${normalizeText(project.description).slice(0, 120)}|${skills}`
}

function mergeEvidenceType(
  group: EligibleProjectResponse[],
  pick: (p: EligibleProjectResponse) => DefenseEvidenceTypeSummary,
): DefenseEvidenceTypeSummary {
  return group.reduce<DefenseEvidenceTypeSummary>(
    (acc, project) => {
      const item = pick(project)
      return {
        attached: acc.attached || item.attached,
        count: Math.max(acc.count, item.count),
        label: acc.label || (item.attached ? item.label : ""),
      }
    },
    { attached: false, count: 0, label: "" },
  )
}

/**
 * Collapse duplicate/historical project rows into one canonical card per logical
 * project, merging their evidence. The backend already dedupes; this is a
 * defensive client-side merge so the selection list never renders the same
 * logical project twice and a card never regresses to a weaker duplicate.
 */
export function dedupeEligibleProjects(projects: EligibleProjectResponse[]): EligibleProjectResponse[] {
  const groups = new Map<string, EligibleProjectResponse[]>()
  const order: string[] = []
  for (const project of projects) {
    const key = canonicalKey(project)
    if (!groups.has(key)) {
      groups.set(key, [])
      order.push(key)
    }
    groups.get(key)!.push(project)
  }

  return order.map((key) => {
    const group = groups.get(key)!
    // Canonical row: strongest status → has GitHub → most recently updated.
    const canonical = [...group].sort((a, b) => {
      const byStatus = STATUS_RANK[b.defense_status] - STATUS_RANK[a.defense_status]
      if (byStatus !== 0) return byStatus
      const byGithub =
        (b.evidence.github_proof.attached ? 1 : 0) - (a.evidence.github_proof.attached ? 1 : 0)
      if (byGithub !== 0) return byGithub
      return (b.updated_at ?? "").localeCompare(a.updated_at ?? "")
    })[0]

    const defense_status = group.reduce<DefenseStatus>(
      (best, p) => (STATUS_RANK[p.defense_status] > STATUS_RANK[best] ? p.defense_status : best),
      "not_started",
    )

    return {
      ...canonical,
      description: group.reduce((longest, p) => (p.description.length > longest.length ? p.description : longest), ""),
      claimed_skills: Array.from(new Set(group.flatMap((p) => p.claimed_skills))),
      defense_status,
      report_ready: group.some((p) => p.report_ready),
      evidence: {
        github_proof: mergeEvidenceType(group, (p) => p.evidence.github_proof),
        documents: mergeEvidenceType(group, (p) => p.evidence.documents),
        website_proof: mergeEvidenceType(group, (p) => p.evidence.website_proof),
        project_defense: mergeEvidenceType(group, (p) => p.evidence.project_defense),
      },
    }
  })
}

function EvidenceRow({ label, summary }: { label: string; summary: DefenseEvidenceTypeSummary }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
      <Mono style={{ fontSize: 11, color: TOKEN.muted, minWidth: 96 }}>{label}</Mono>
      {summary.attached ? (
        <Badge tone="emerald">{summary.count > 1 ? `${summary.count} attached` : "Attached"}</Badge>
      ) : (
        <Badge tone="slate">Missing</Badge>
      )}
      {summary.attached && summary.label && (
        <span style={{ color: TOKEN.inkSoft, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {summary.label}
        </span>
      )}
    </div>
  )
}

function ProjectCard({
  project,
  onDefend,
}: {
  project: EligibleProjectResponse
  onDefend: (id: string) => void
}) {
  const status = DEFENSE_STATUS_LABEL[project.defense_status] ?? DEFENSE_STATUS_LABEL.not_started
  return (
    <Card>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>{project.title}</h3>
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>

        {project.description && (
          <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            {project.description}
          </p>
        )}

        {project.claimed_skills.length > 0 && (
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {project.claimed_skills.map((s) => (
              <Badge key={s} tone="indigo">{s}</Badge>
            ))}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <EvidenceRow label="GitHub Proof" summary={project.evidence.github_proof} />
          <EvidenceRow label="Document Proof" summary={project.evidence.documents} />
          <EvidenceRow label="Website Proof" summary={project.evidence.website_proof} />
        </div>

        <div>
          <Btn variant="primary" onClick={() => onDefend(project.id)}>
            {DEFENSE_CTA_LABEL[project.defense_status] ?? DEFENSE_CTA_LABEL.not_started}
          </Btn>
        </div>
      </div>
    </Card>
  )
}

function EmptyState() {
  return (
    <Card>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
          No projects ready for defense yet.
        </h3>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Project Defense strengthens an existing project. Create a project from one of your proofs to
          begin.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Link href="/student/proofs/github" style={{ textDecoration: "none" }}>
            <Btn variant="secondary">Create project from GitHub Proof</Btn>
          </Link>
          <Link href="/student/proofs/documents" style={{ textDecoration: "none" }}>
            <Btn variant="secondary">Create project from Document Proof</Btn>
          </Link>
          <Link href="/student/proofs/website" style={{ textDecoration: "none" }}>
            <Btn variant="secondary">Create project from Website Proof</Btn>
          </Link>
        </div>
      </div>
    </Card>
  )
}

export function ProjectDefenseHome() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const [projects, setProjects] = useState<EligibleProjectResponse[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Selection is local-state driven (source of truth) so the workspace opens
  // immediately on click; the URL is kept in sync for deep-linking / refresh.
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("projectId"))
  const [context, setContext] = useState<ProjectDefenseContextResponse | null>(null)
  const [contextError, setContextError] = useState<string | null>(null)

  useEffect(() => {
    listEligibleDefenseProjects()
      .then((rows) => setProjects(dedupeEligibleProjects(rows)))
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  // Load the selected project's defense context whenever the selection changes.
  useEffect(() => {
    if (!selectedId) {
      setContext(null)
      setContextError(null)
      return
    }
    let active = true
    setContext(null)
    setContextError(null)
    getProjectDefenseContext(selectedId)
      .then((ctx) => {
        if (active) setContext(ctx)
      })
      .catch((e: Error) => {
        if (active) setContextError(e.message)
      })
    return () => {
      active = false
    }
  }, [selectedId])

  const handleDefend = (id: string) => {
    setSelectedId(id)
    router.push(`/student/proofs/project-defense?projectId=${encodeURIComponent(id)}`)
  }

  const handleBack = () => {
    setSelectedId(null)
    router.push("/student/proofs/project-defense")
  }

  // ── Selected project workspace ──────────────────────────────────────────────
  if (selectedId) {
    if (contextError) {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <button
            type="button"
            onClick={handleBack}
            style={{ alignSelf: "flex-start", background: "none", border: "none", padding: 0, fontSize: 13, color: TOKEN.indigo, cursor: "pointer" }}
          >
            ← Back to project selection
          </button>
          <ErrorState message={contextError} />
        </div>
      )
    }
    if (!context) {
      return <LoadingState label="Loading project evidence…" />
    }
    return <ProjectDefensePanel initialContext={context} onBack={handleBack} />
  }

  // ── Project selection ───────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
          Choose a project to defend
        </h2>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "6px 0 0", lineHeight: 1.5 }}>
          Project Defense strengthens an existing project by asking questions grounded in its GitHub,
          document, and website evidence.
        </p>
      </div>

      {loadError && <ErrorState message={loadError} />}

      {projects === null && !loadError && <LoadingState label="Loading your projects…" />}

      {projects !== null && projects.length === 0 && <EmptyState />}

      {projects !== null && projects.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} onDefend={handleDefend} />
          ))}
        </div>
      )}
    </div>
  )
}
