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
  type PassportSkillSummary,
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
  TOKEN,
  type BadgeTone,
} from "../../../../../components/passport/shared"

const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Evidence observed": "emerald",
  "Supporting evidence": "sky",
  "Needs review": "rose",
  "Not assessed": "slate",
}

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

function SkillRow({ skill }: { skill: PassportSkillSummary }) {
  const [open, setOpen] = useState(false)
  const hasDetail =
    skill.projects.length > 0 ||
    skill.evidence_sources.length > 0 ||
    skill.evidence_chips.length > 0 ||
    Boolean(skill.notes)

  return (
    <div data-testid="passport-skill" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <button
        type="button"
        data-testid="skill-expand-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        disabled={!hasDetail}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          justifyContent: "space-between",
          flexWrap: "wrap",
          background: "none",
          border: "none",
          padding: 0,
          cursor: hasDetail ? "pointer" : "default",
          width: "100%",
          textAlign: "left",
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>
          {hasDetail && <span style={{ color: TOKEN.muted, marginRight: 6 }}>{open ? "▾" : "▸"}</span>}
          {skill.skill}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {skill.evidence_chip_count > 0 && (
            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{skill.evidence_chip_count} chips</Mono>
          )}
          <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
            {skill.project_count} {skill.project_count === 1 ? "project" : "projects"}
          </Mono>
          <Badge tone={QUALITATIVE_LABEL_TONE[skill.status] ?? "slate"}>{skill.status}</Badge>
        </div>
      </button>

      {open && hasDetail && (
        <div
          data-testid="skill-detail"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: "10px 12px",
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 8,
          }}
        >
          {skill.evidence_sources.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {skill.evidence_sources.map((src) => (
                <Badge key={src} tone={SOURCE_TONE[src] ?? "slate"}>
                  {src}
                </Badge>
              ))}
            </div>
          )}

          {skill.notes && (
            <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{skill.notes}</p>
          )}

          {skill.projects.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                Related projects
              </Mono>
              {skill.projects.map((p, i) => (
                <div
                  key={`${p.project_title}-${i}`}
                  data-testid="skill-project-ref"
                  style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
                >
                  <span style={{ fontSize: 12, color: TOKEN.ink, fontWeight: 600 }}>{p.project_title}</span>
                  {p.project_id && (
                    <Link
                      href={`/student/vbr/projects/${p.project_id}/report`}
                      style={{ fontSize: 11, color: TOKEN.indigo, textDecoration: "none" }}
                    >
                      View report preview →
                    </Link>
                  )}
                  {p.report_is_public && <Badge tone="emerald">Public report</Badge>}
                </div>
              ))}
            </div>
          )}

          {skill.evidence_chips.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                Evidence snippets
              </Mono>
              {skill.evidence_chips.map((c, i) => (
                <div key={`${c.label}-${i}`} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                  <Mono style={{ fontSize: 11, color: TOKEN.ink }}>{c.label}</Mono> — {c.short_summary}
                </div>
              ))}
            </div>
          )}

          {skill.limitations.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {skill.limitations.map((line, i) => (
                <li key={i} style={{ fontSize: 11, color: TOKEN.muted }}>
                  {line}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
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
      {/* Candidate header */}
      <Card>
        <div data-testid="passport-header" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {passport.candidate_display_name && (
            <h2 style={{ fontSize: 20, color: TOKEN.ink, margin: 0 }}>{passport.candidate_display_name}</h2>
          )}
          <p style={{ fontSize: 14, color: TOKEN.inkSoft, margin: 0, fontWeight: 600 }}>{passport.headline}</p>
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

      {/* Evidence-backed skills */}
      <Card>
        <CardHeader title="Evidence-Backed Skills" eyebrow="Grouped by skill" icon="🧩" />
        {passport.skills.length === 0 ? (
          <p data-testid="passport-no-skills" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
            No skills assessed yet.
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {passport.skills.map((skill) => (
              <SkillRow key={skill.skill} skill={skill} />
            ))}
          </div>
        )}
      </Card>

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
