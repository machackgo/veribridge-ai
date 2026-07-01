"use client"

import { useEffect, useRef, useState, type CSSProperties } from "react"
import Link from "next/link"
import {
  getPrivateWorkPassport,
  getWorkPassportStatus,
  publishWorkPassport,
  unpublishWorkPassport,
  publishVBRProjectReport,
  type PassportProjectSummary,
  type PrivateWorkPassport,
  type WorkPassportStatus,
} from "@/lib/vbr-api"
import {
  Badge,
  Card,
  CardHeader,
  ErrorState,
  LoadingState,
  Mono,
  PassportIdentityHeader,
  TOKEN,
  type BadgeTone,
} from "../../../../../components/passport/shared"
import { VaultSkillDashboard } from "../../../../../components/passport/VaultProofs"

const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

const primaryBtnStyle: CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: "none",
  background: TOKEN.indigo,
  color: "#fff",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
}

const secondaryBtnStyle: CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.inkSoft,
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  textDecoration: "none",
  display: "inline-block",
}

function PassportPublishControls({
  initialStatus,
  candidateName,
}: {
  initialStatus: WorkPassportStatus
  candidateName: string | null
}) {
  const [status, setStatus] = useState<WorkPassportStatus>(initialStatus)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const actedRef = useRef(false)

  useEffect(() => {
    getWorkPassportStatus()
      .then((s) => {
        if (!actedRef.current) setStatus(s)
      })
      .catch(() => {
        /* keep the server-rendered initial status */
      })
  }, [])

  const isPublished = Boolean(status.is_published && status.public_slug)
  const publicUrl =
    isPublished && status.public_slug
      ? `${typeof window !== "undefined" ? window.location.origin : ""}/p/${status.public_slug}`
      : ""

  const run = (action: () => Promise<WorkPassportStatus>) => {
    actedRef.current = true
    setBusy(true)
    setError(null)
    setCopied(false)
    action()
      .then(setStatus)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Action failed."))
      .finally(() => setBusy(false))
  }

  const copyLink = () => {
    if (!publicUrl) return
    void navigator.clipboard?.writeText(publicUrl)
    setCopied(true)
  }

  return (
    <Card>
      <div data-testid="passport-publish-controls" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <CardHeader title="Public Work Passport" eyebrow="Share with recruiters" icon="🪪" />
          {isPublished ? (
            <span data-testid="passport-public-badge">
              <Badge tone="emerald">Public passport live</Badge>
            </span>
          ) : (
            <span data-testid="passport-private-badge">
              <Badge tone="slate">Private only</Badge>
            </span>
          )}
        </div>

        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Publishing creates a recruiter-safe public profile recruiters can open without logging in. It links only to
          the VBR reports you have published — never your raw evidence, private files, or numeric scores. You can
          unpublish at any time without deleting any evidence or report links.
        </p>

        {error && (
          <p data-testid="passport-publish-error" style={{ fontSize: 12, color: TOKEN.rose, margin: 0 }}>
            {error}
          </p>
        )}

        {isPublished ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div
              data-testid="passport-public-link"
              style={{
                fontFamily: '"JetBrains Mono", monospace',
                fontSize: 12,
                color: TOKEN.ink,
                padding: "8px 10px",
                background: TOKEN.bg,
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
                wordBreak: "break-all",
              }}
            >
              {publicUrl}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" data-testid="copy-passport-link-button" onClick={copyLink} style={primaryBtnStyle}>
                {copied ? "Copied!" : "Copy public Passport link"}
              </button>
              <a
                data-testid="open-passport-link"
                href={publicUrl || "#"}
                target="_blank"
                rel="noreferrer"
                style={secondaryBtnStyle}
              >
                Open public Passport
              </a>
              <button
                type="button"
                data-testid="unpublish-passport-button"
                disabled={busy}
                onClick={() => run(() => unpublishWorkPassport())}
                style={secondaryBtnStyle}
              >
                {busy ? "Working…" : "Unpublish public Passport"}
              </button>
            </div>
          </div>
        ) : (
          <div>
            <button
              type="button"
              data-testid="publish-passport-button"
              disabled={busy}
              onClick={() => run(() => publishWorkPassport())}
              style={primaryBtnStyle}
            >
              {busy ? "Publishing…" : "Publish public Passport"}
            </button>
          </div>
        )}

        <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
          Featured projects default to every project with a published recruiter-safe VBR report
          {candidateName ? ` for ${candidateName}` : ""}. Publish a project report below to feature it.
        </p>
      </div>
    </Card>
  )
}

function ProjectCard({ project }: { project: PassportProjectSummary }) {
  const [report, setReport] = useState(project.report)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isPublic = Boolean(report.is_public && report.public_token)
  const publicUrl =
    isPublic && report.public_token
      ? `${typeof window !== "undefined" ? window.location.origin : ""}/vbr/report/${report.public_token}`
      : ""

  const publish = () => {
    setBusy(true)
    setError(null)
    publishVBRProjectReport(project.project_id)
      .then((s) => setReport(s))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to publish report."))
      .finally(() => setBusy(false))
  }

  const copyLink = () => {
    if (!publicUrl) return
    void navigator.clipboard?.writeText(publicUrl)
    setCopied(true)
  }

  return (
    <Card>
      <div data-testid="passport-project-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink }}>{project.project_title || "Untitled project"}</div>
            {project.repo_full_name && (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{project.repo_full_name}</Mono>
            )}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            {project.attempt_count > 1 && (
              <span data-testid="attempt-count-badge" title="Evidence from multiple Project Defense attempts is merged into one card">
                <Badge tone="slate">{project.attempt_count} attempts merged</Badge>
              </span>
            )}
            {isPublic ? (
              <Badge tone="emerald">Report public</Badge>
            ) : (
              <Badge tone="slate">Report private</Badge>
            )}
          </div>
        </div>

        {project.project_summary && (
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{project.project_summary}</p>
        )}

        {/* Evidence source badges */}
        {project.evidence_sources.length > 0 && (
          <div data-testid="project-evidence-sources" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {project.evidence_sources.map((src) => (
              <span key={src} data-testid="evidence-source-badge">
                <Badge tone={SOURCE_TONE[src] ?? "slate"}>{src}</Badge>
              </span>
            ))}
          </div>
        )}

        {error && (
          <p data-testid="project-report-error" style={{ fontSize: 12, color: TOKEN.rose, margin: 0 }}>
            {error}
          </p>
        )}

        {/* Report actions */}
        <div data-testid="project-report-actions" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <Link
            data-testid="view-report-preview-link"
            href={`/student/vbr/projects/${project.project_id}/report`}
            style={secondaryBtnStyle}
          >
            View report preview
          </Link>
          {isPublic ? (
            <button type="button" data-testid="copy-report-link-button" onClick={copyLink} style={primaryBtnStyle}>
              {copied ? "Copied!" : "Copy public report link"}
            </button>
          ) : (
            <button
              type="button"
              data-testid="publish-report-button"
              disabled={busy}
              onClick={publish}
              style={primaryBtnStyle}
            >
              {busy ? "Publishing…" : "Publish recruiter-safe report"}
            </button>
          )}
        </div>
      </div>
    </Card>
  )
}

export function PrivatePassportView() {
  const [passport, setPassport] = useState<PrivateWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getPrivateWorkPassport()
      .then(setPassport)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load passport."))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  if (loading) return <LoadingState label="Loading your Work Passport…" />
  if (error || !passport) return <ErrorState message={error ?? "Passport not found."} onRetry={load} />

  const status: WorkPassportStatus = {
    is_published: passport.is_published,
    public_slug: passport.public_slug,
    public_path: passport.public_path,
    published_at: passport.published_at,
    headline: passport.headline,
    summary: passport.summary,
  }

  const sourceCounts = Object.entries(passport.evidence_source_counts).filter(([, n]) => n > 0)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Candidate identity header — passport-style identity area */}
      <Card>
        <div data-testid="passport-header" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <PassportIdentityHeader
            identity={passport.identity}
            fallbackName={passport.candidate_display_name}
            fallbackHeadline={passport.headline}
          />
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>{passport.summary}</p>
        </div>
      </Card>

      {/* Publish controls */}
      <PassportPublishControls initialStatus={status} candidateName={passport.candidate_display_name} />

      {/* Evidence source counts */}
      <Card>
        <CardHeader title="Evidence by Source" eyebrow="Across all your projects" icon="📎" />
        {sourceCounts.length === 0 ? (
          <p data-testid="passport-no-evidence" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
            No evidence assessed yet. Add proof sources and run a Project Defense to populate your passport.
          </p>
        ) : (
          <div data-testid="evidence-source-counts" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {sourceCounts.map(([label, count]) => (
              <span key={label} data-testid="evidence-source-count">
                <Badge tone={SOURCE_TONE[label] ?? "slate"}>
                  {label} · {count}
                </Badge>
              </span>
            ))}
          </div>
        )}
      </Card>

      {/* Student Proof Vault — Layer 1: a COMPACT skill-intelligence dashboard.
          Every proof you own is grouped by canonical skill (attached AND
          unattached) into compact cards under category headings. The main page
          shows only counts + a few previews; the full stored evidence for one
          skill loads lazily when you click "View Skill Report". */}
      {(passport.vault_skill_summaries?.length ?? 0) > 0 && (
        <Card>
          <CardHeader
            title="Skill Intelligence"
            eyebrow="Every proof you own, distilled into compact skill cards"
            icon="🗂️"
          />
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px", lineHeight: 1.5 }}>
            All your safe proof evidence — GitHub, Document, Website, Project Defense, Video, and Skill Graph — grouped
            by skill. Open any skill to see its concrete, recruiter-verifiable evidence. Proofs you have not attached to
            a VBR project are clearly labelled <strong>not attached to a VBR project</strong>, so nothing you have built
            is ever lost.
            {typeof passport.vault_unattached_count === "number" && passport.vault_unattached_count > 0 && (
              <span data-testid="vault-unattached-summary">
                {" "}
                You have {passport.vault_unattached_count} unattached proof item(s).
              </span>
            )}
          </p>
          <VaultSkillDashboard summaries={passport.vault_skill_summaries} />
        </Card>
      )}

      {/* Projects */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Project Evidence</h2>
        {passport.projects.length === 0 ? (
          <Card>
            <p data-testid="passport-no-projects" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No projects yet. Create a Project Defense to start building your passport.
            </p>
          </Card>
        ) : (
          passport.projects.map((project) => <ProjectCard key={project.project_id} project={project} />)
        )}
      </section>

      {/* Limitations */}
      <Card>
        <CardHeader title="Transparency" eyebrow="Be honest" icon="⚠️" />
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {passport.limitations.map((line, i) => (
            <li key={i} style={{ fontSize: 12, color: TOKEN.muted }}>
              {line}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
