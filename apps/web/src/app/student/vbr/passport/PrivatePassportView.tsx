"use client"

import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react"
import Link from "next/link"
import {
  fallbackSkillSlug,
  getPrivateWorkPassport,
  getWorkPassportStatus,
  publishWorkPassport,
  unpublishWorkPassport,
  publishVBRProjectReport,
  proofChainFromSources,
  skillReportPath,
  PROOF_CHAIN_STEPS,
  type EvidenceGraphOverview,
  type PassportProjectSummary,
  type PrivateWorkPassport,
  type WorkPassportStatus,
} from "@/lib/vbr-api"
import { buildPublicAppUrl } from "@/lib/api"
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
import { buildPassportGraph, type PassportSkillNode } from "./passport-graph"

const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

const SKILL_STATUS_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Evidence observed": "emerald",
  "Supporting evidence": "sky",
  "Needs review": "rose",
  "Not assessed": "slate",
}

const CHAIN_LABEL_TONE: Record<string, BadgeTone> = {
  "Strong chain": "emerald",
  "Good chain": "sky",
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
      ? buildPublicAppUrl(`/p/${status.public_slug}`)
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

// ── Evidence Graph Overview (Projects ↔ Skills ↔ Proofs) ─────────────────────

function OverviewStat({ stat, label, value }: { stat: string; label: string; value: number }) {
  return (
    <div
      data-testid="overview-stat"
      data-stat={stat}
      style={{
        flex: "1 1 120px",
        minWidth: 108,
        padding: "10px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 10,
        background: TOKEN.bg,
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}
    >
      <span style={{ fontSize: 20, fontWeight: 700, color: TOKEN.ink, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </span>
      <span style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.3 }}>{label}</span>
    </div>
  )
}

/**
 * The compact evidence-graph summary at the top of the Passport: how many
 * projects, published reports, evidence-backed skills, and attached proof
 * sources exist. Counts only — never a numeric trust score. Proof-maintenance
 * detail (unattached/suggested counts, next actions) lives in the Proof Vault.
 */
function EvidenceGraphOverviewCard({ passport }: { passport: PrivateWorkPassport }) {
  const overview: EvidenceGraphOverview = passport.evidence_graph_overview ?? {
    project_count: passport.project_count,
    published_report_count: passport.published_report_count,
    skills_with_evidence: passport.vault_skill_summaries?.length ?? passport.skills.length,
    proof_count: passport.vault_proof_count ?? 0,
    attached_proof_count: (passport.vault_proof_count ?? 0) - (passport.vault_unattached_count ?? 0),
    unattached_proof_count: passport.vault_unattached_count ?? 0,
    next_actions: [],
  }
  const sourceCounts = Object.entries(passport.evidence_source_counts).filter(([, n]) => n > 0)

  return (
    <Card>
      <div data-testid="evidence-graph-overview" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <CardHeader title="Evidence Graph Overview" eyebrow="Projects ↔ skills ↔ proofs" icon="🕸️" />
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Your Passport connects projects to skills through evidence-backed proof.
        </p>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <OverviewStat stat="projects" label="Projects" value={overview.project_count} />
          <OverviewStat stat="published-reports" label="Published reports" value={overview.published_report_count} />
          <OverviewStat stat="skills-with-evidence" label="Skills with evidence" value={overview.skills_with_evidence} />
          <OverviewStat stat="attached-proofs" label="Attached proof sources" value={overview.attached_proof_count} />
        </div>

        {/* Evidence by source */}
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
      </div>
    </Card>
  )
}

// ── Improve Passport (doorway to the Proof Vault) ─────────────────────────────

/**
 * The compact, single-card replacement for the old inline Proof Attachment
 * Intelligence / Evidence Vault sections. All suggested-attachment and
 * unattached-evidence review now lives on the private Proof Vault page.
 */
function ImprovePassportCard({ passport }: { passport: PrivateWorkPassport }) {
  const unattachedCount =
    passport.attachment_overview?.unattached_count ?? passport.vault_unattached_count ?? 0
  const suggestedCount =
    passport.attachment_overview?.suggested_count ??
    passport.unattached_proof_summary?.suggestion_count ??
    0

  return (
    <Card>
      <div data-testid="improve-passport-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <CardHeader title="Improve Passport" eyebrow="Private proof maintenance" icon="🧰" />
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {suggestedCount > 0 && (
              <span data-testid="improve-passport-suggested-count">
                <Badge tone="sky">{suggestedCount} suggested</Badge>
              </span>
            )}
            {unattachedCount > 0 && (
              <span data-testid="improve-passport-unattached-count">
                <Badge tone="amber">{unattachedCount} unattached</Badge>
              </span>
            )}
          </div>
        </div>
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Review suggested attachments and unattached evidence in Proof Vault.
        </p>
        <Link data-testid="open-proof-vault-link" href="/student/vbr/passport/vault" style={{ ...secondaryBtnStyle, alignSelf: "flex-start" }}>
          Open Proof Vault
        </Link>
      </div>
    </Card>
  )
}

// ── Projects panel ────────────────────────────────────────────────────────────

/** The five-step proof-chain completeness row on a project card. */
function ProofChainRow({ project }: { project: PassportProjectSummary }) {
  const chain = project.proof_chain ?? proofChainFromSources(project.evidence_sources)
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
          Proof chain · {chain.attached_count} of {chain.total_count} sources attached
        </Mono>
        {project.chain_label && (
          <span data-testid="project-chain-label">
            <Badge tone={CHAIN_LABEL_TONE[project.chain_label] ?? "amber"}>{project.chain_label}</Badge>
          </span>
        )}
      </div>
      <div data-testid="project-proof-chain" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {PROOF_CHAIN_STEPS.map((step) => (
          <span
            key={step.key}
            data-testid="proof-chain-item"
            data-source={step.label}
            data-present={chain[step.key] ? "true" : "false"}
          >
            <Badge tone={chain[step.key] ? (SOURCE_TONE[step.label] ?? "emerald") : "slate"}>
              {chain[step.key] ? "✓ " : "– "}
              {step.label}
            </Badge>
          </span>
        ))}
      </div>
    </div>
  )
}

const MAX_PROJECT_TOP_SKILLS = 5

/** True when the click landed on an interactive child (link/button) — those
 *  keep their own behavior and never toggle the card selection. */
function clickedInteractiveChild(e: MouseEvent<HTMLElement>): boolean {
  return Boolean((e.target as HTMLElement).closest?.("a, button"))
}

function ProjectCard({
  project,
  passportPublished,
  selected,
  connectedSkillCount,
  onToggleSelect,
}: {
  project: PassportProjectSummary
  passportPublished: boolean
  selected: boolean
  connectedSkillCount: number
  onToggleSelect: () => void
}) {
  const [report, setReport] = useState(project.report)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isPublic = Boolean(report.is_public && report.public_token)
  const publicUrl =
    isPublic && report.public_token
      ? buildPublicAppUrl(`/vbr/report/${report.public_token}`)
      : ""
  const topSkills = (project.top_skills ?? []).slice(0, MAX_PROJECT_TOP_SKILLS)
  const chain = project.proof_chain ?? proofChainFromSources(project.evidence_sources)
  // A project with no attached proof sources has nothing for a recruiter-safe
  // report to show yet — its report state is "Needs report", not "private".
  const hasEvidence = chain.attached_count > 0

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
    <Card
      style={{
        border: selected ? `1px solid ${TOKEN.indigo}` : undefined,
        cursor: "pointer",
      }}
    >
      <div
        data-testid="passport-project-card"
        data-project-id={project.project_id}
        data-selected={selected ? "true" : "false"}
        onClick={(e) => {
          if (!clickedInteractiveChild(e)) onToggleSelect()
        }}
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
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
            <span
              data-testid="project-report-state"
              data-state={isPublic ? "published" : hasEvidence ? "private" : "needs-report"}
            >
              {isPublic ? (
                <Badge tone="emerald">Report published</Badge>
              ) : hasEvidence ? (
                <Badge tone="slate">Report private</Badge>
              ) : (
                <Badge tone="amber">Needs report</Badge>
              )}
            </span>
          </div>
        </div>

        {project.project_summary && (
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{project.project_summary}</p>
        )}

        {/* Proof chain completeness */}
        <ProofChainRow project={project} />

        {/* Project → Skill links: the strongest evidence-backed skills this
            project demonstrates, each linking into its full Skill Report. */}
        {topSkills.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Top skills demonstrated
            </Mono>
            <div data-testid="project-top-skills" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {topSkills.map((row) => {
                const href = row.skill_report_path ?? skillReportPath(row.skill_slug || fallbackSkillSlug(row.skill))
                return (
                  <Link
                    key={row.skill}
                    href={href}
                    data-testid="project-top-skill"
                    title={`Open the ${row.skill} evidence this project contributes`}
                    style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4 }}
                  >
                    <Badge tone={SKILL_STATUS_TONE[row.status] ?? "slate"}>
                      {row.skill} · {row.status}
                    </Badge>
                    <span
                      data-testid="project-skill-evidence-label"
                      style={{ fontSize: 11, fontWeight: 600, color: TOKEN.indigo }}
                    >
                      View {row.skill} evidence in this project →
                    </span>
                  </Link>
                )
              })}
            </div>
            {project.evidence_relationship_note && (
              <p
                data-testid="project-relationship-note"
                style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
              >
                {project.evidence_relationship_note}
              </p>
            )}
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
            <>
              <button type="button" data-testid="copy-report-link-button" onClick={copyLink} style={primaryBtnStyle}>
                {copied ? "Copied!" : "Copy public report link"}
              </button>
              <a
                data-testid="open-public-report-link"
                href={publicUrl || "#"}
                target="_blank"
                rel="noreferrer"
                style={secondaryBtnStyle}
              >
                Open public report
              </a>
            </>
          ) : (
            hasEvidence && (
              <button
                type="button"
                data-testid="publish-report-button"
                disabled={busy}
                onClick={publish}
                style={primaryBtnStyle}
              >
                {busy ? "Publishing…" : "Publish recruiter-safe report"}
              </button>
            )
          )}
          {connectedSkillCount > 0 && (
            <button
              type="button"
              data-testid="view-connected-skills-button"
              onClick={onToggleSelect}
              style={secondaryBtnStyle}
            >
              {selected ? "Clear skill highlight" : `View connected skills (${connectedSkillCount})`}
            </button>
          )}
        </div>

        {/* Public-passport visibility: report publishing and Passport publishing
            are independent. A published report's public link is always live by
            direct URL, but it is only featured on the public Passport while the
            Passport itself is published. The copy must stay correct in both states. */}
        <p
          data-testid="report-visibility-note"
          data-visibility={isPublic ? "public" : "private"}
          data-passport-published={isPublic ? String(passportPublished) : undefined}
          style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
        >
          {isPublic
            ? "This report’s public link is live and it is featured whenever your public Passport is published."
            : hasEvidence
              ? "This project will not appear on your public Passport until you publish its recruiter-safe report."
              : "This project has no attached proof yet, so there is no report to publish — it will not appear on your public Passport. Attach proof or record a Project Defense first."}
        </p>
      </div>
    </Card>
  )
}

// ── Skills panel ──────────────────────────────────────────────────────────────

function SkillCard({
  node,
  selected,
  onToggleSelect,
}: {
  node: PassportSkillNode
  selected: boolean
  onToggleSelect: () => void
}) {
  const topProject = node.strongest?.title ?? null

  return (
    <Card
      style={{
        border: selected ? `1px solid ${TOKEN.indigo}` : undefined,
        cursor: "pointer",
      }}
    >
      <div
        data-testid="passport-skill-card"
        data-skill={node.name}
        data-selected={selected ? "true" : "false"}
        // Real selection-control semantics: focusable, togglable with the card,
        // and operable by Enter/Space so keyboard users get the same highlight
        // as a mouse click. Inner links keep their own behaviour.
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`${selected ? "Clear" : "Show"} projects connected to ${node.name}`}
        onClick={(e) => {
          if (!clickedInteractiveChild(e)) onToggleSelect()
        }}
        onKeyDown={(e) => {
          // Only the card itself toggles — a keypress bubbling up from a focused
          // inner link must not hijack that link's own activation.
          if (e.target !== e.currentTarget) return
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            onToggleSelect()
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: 8 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: TOKEN.ink }}>{node.name}</span>
          <Badge tone={SKILL_STATUS_TONE[node.status] ?? "slate"}>{node.status}</Badge>
          <span data-testid="skill-project-count" style={{ fontSize: 11, color: TOKEN.muted }}>
            {node.projectCount} project{node.projectCount === 1 ? "" : "s"}
          </span>
        </div>

        {/* Proof-type chips: which proof sources back this skill (labels only). */}
        {node.proofTypes.length > 0 && (
          <div data-testid="skill-proof-chips" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {node.proofTypes.map((label) => (
              <span key={label} data-testid="skill-proof-chip" data-source={label}>
                <Badge tone={SOURCE_TONE[label] ?? "slate"}>{label}</Badge>
              </span>
            ))}
          </div>
        )}

        {/* Skill → Project link: where this skill is most strongly evidenced. */}
        {topProject && (
          <p data-testid="skill-top-project" style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            Strongest in <strong>{topProject}</strong>
            {node.strongest?.status ? ` — ${node.strongest.status}` : ""}
          </p>
        )}

        {/* Contextual proof → project → skill navigation. Every attached CTA names
            the exact project and routes into that project's report where the
            skill's evidence lives; vault-only skills route to the Proof Vault
            instead, never to a project report. */}
        <SkillEvidenceNav node={node} />

        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Link
            href={skillReportPath(node.slug)}
            data-testid="view-skill-report"
            title={`Open the full ${node.name} evidence across every project`}
            style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
          >
            View {node.name} evidence →
          </Link>
        </div>
      </div>
    </Card>
  )
}

/**
 * The skill card's evidence navigation: turns each attached project → skill
 * relationship into a contextual "View [skill] evidence in [project] report"
 * CTA, states the Website evidence context when a project contributes it, and —
 * for skills whose evidence is only in the vault — clearly labels it unattached
 * and routes to the Proof Vault instead of any project report.
 */
function SkillEvidenceNav({ node }: { node: PassportSkillNode }) {
  const rows = node.projectEvidence

  // No attached project demonstrates this skill yet — its evidence lives only in
  // the vault. Never front a project-report CTA for loose vault evidence.
  if (rows.length === 0) {
    return (
      <div
        data-testid="skill-vault-only"
        style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12, lineHeight: 1.5 }}
      >
        <p style={{ margin: 0, color: TOKEN.muted }}>
          Vault evidence — not attached to a project report yet.
        </p>
        <Link
          href="/student/vbr/passport/vault"
          data-testid="skill-open-proof-vault"
          style={{ fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
        >
          Open Proof Vault →
        </Link>
      </div>
    )
  }

  return (
    <div data-testid="skill-evidence-nav" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {rows.length > 1 && (
        <p
          data-testid="skill-multi-project-heading"
          style={{ fontSize: 11, color: TOKEN.muted, margin: 0, fontWeight: 600 }}
        >
          This skill appears in {rows.length} project reports
        </p>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.map((row) => (
          <div
            key={row.projectId}
            data-testid="skill-project-evidence-row"
            data-project-id={row.projectId}
            style={{ display: "flex", flexDirection: "column", gap: 3 }}
          >
            <Link
              href={row.reportPath}
              data-testid="skill-project-evidence-link"
              data-project-id={row.projectId}
              title={`Open ${node.name} evidence inside the ${row.projectTitle} report`}
              style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
            >
              View {node.name} evidence in {row.projectTitle} report →
            </Link>
            {row.hasWebsiteProof && (
              <span
                data-testid="skill-website-evidence-note"
                data-skill={node.name}
                data-project={row.projectTitle}
                // Passport-level Website Proof carries no classified sub-source
                // (DOM / OCR / visual). Keep the label honest and generic here —
                // the project report is where any sub-source detail is shown.
                data-source-classified="false"
                style={{ fontSize: 11, color: TOKEN.inkSoft, lineHeight: 1.4 }}
              >
                Website evidence — shows observed runtime/product behavior
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Projects ↔ Skills interactive explorer ────────────────────────────────────

type GraphSelection = { kind: "project" | "skill"; id: string } | null

/**
 * The main Passport body: Projects on the left, Skills on the right. Selecting a
 * project filters the Skills panel down to ONLY the skills that project proves —
 * unrelated skills are removed from the DOM, not merely dimmed. Selecting a skill
 * filters the Projects panel down to ONLY the projects that demonstrate it.
 * Clearing selection restores both full lists. Pure presentation over the
 * already-safe passport payload — selection never fetches anything.
 */
function PassportGraphExplorer({
  passport,
  passportPublished,
}: {
  passport: PrivateWorkPassport
  passportPublished: boolean
}) {
  const [selection, setSelection] = useState<GraphSelection>(null)
  const graph = useMemo(() => buildPassportGraph(passport), [passport])

  const toggle = (kind: "project" | "skill", id: string) =>
    setSelection((cur) => (cur?.kind === kind && cur.id === id ? null : { kind, id }))

  const connectedSkillKeys =
    selection?.kind === "project" ? new Set(graph.projectSkills.get(selection.id) ?? []) : null
  const connectedProjectIds =
    selection?.kind === "skill" ? new Set(graph.skillProjects.get(selection.id) ?? []) : null

  // True filtering (not dimming): a selected project narrows the Skills panel to
  // its connected skills only; a selected skill narrows the Projects panel to its
  // connected projects only. The opposite panel always stays fully visible so the
  // user can pivot to another project/skill. No selection → everything shows.
  const visibleProjects = connectedProjectIds
    ? passport.projects.filter((p) => connectedProjectIds.has(p.project_id))
    : passport.projects
  const visibleSkills = connectedSkillKeys
    ? graph.skills.filter((s) => connectedSkillKeys.has(s.key))
    : graph.skills

  const selectionName =
    selection?.kind === "project"
      ? passport.projects.find((p) => p.project_id === selection.id)?.project_title ?? null
      : selection?.kind === "skill"
        ? graph.skills.find((s) => s.key === selection.id)?.name ?? null
        : null

  const projectsHeading =
    selection?.kind === "skill"
      ? `Projects for selected skill (${visibleProjects.length})`
      : `Projects (${passport.projects.length})`
  const skillsHeading =
    selection?.kind === "project"
      ? `Skills for selected project (${visibleSkills.length})`
      : `Skills (${graph.skills.length})`

  const panelHeading: CSSProperties = { fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }

  return (
    <section data-testid="passport-graph-explorer" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Projects ↔ Skills</h2>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
            Click a project to see the skills it proves — or a skill to see the projects that demonstrate it.
          </p>
        </div>
        {selection && (
          <div data-testid="graph-selection-summary" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: TOKEN.inkSoft }}>
              Showing connections for <strong>{selectionName}</strong>
            </span>
            <button
              type="button"
              data-testid="clear-selection-button"
              onClick={() => setSelection(null)}
              style={{ ...secondaryBtnStyle, padding: "5px 10px", fontSize: 12 }}
            >
              Clear selection
            </button>
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12, alignItems: "start" }}>
        {/* Left panel — Projects */}
        <div data-testid="passport-projects-panel" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3 style={panelHeading}>{projectsHeading}</h3>
          {passport.projects.length === 0 ? (
            <Card>
              <p data-testid="passport-no-projects" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                No projects yet. Create a Project Defense to start building your passport.
              </p>
            </Card>
          ) : visibleProjects.length === 0 ? (
            <Card>
              <p data-testid="projects-panel-filtered-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                No projects are connected to this skill yet. Clear the selection to see all projects.
              </p>
            </Card>
          ) : (
            visibleProjects.map((project) => {
              const selected = selection?.kind === "project" && selection.id === project.project_id
              return (
                <ProjectCard
                  key={project.project_id}
                  project={project}
                  passportPublished={passportPublished}
                  selected={selected}
                  connectedSkillCount={graph.projectSkills.get(project.project_id)?.length ?? 0}
                  onToggleSelect={() => toggle("project", project.project_id)}
                />
              )
            })
          )}
        </div>

        {/* Right panel — Skills */}
        <div data-testid="passport-skills-panel" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3 style={panelHeading}>{skillsHeading}</h3>
          {graph.skills.length === 0 ? (
            <Card>
              <p data-testid="skills-panel-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                No skills with evidence yet. Attach proof sources or record a Project Defense to build skill evidence.
              </p>
            </Card>
          ) : visibleSkills.length === 0 ? (
            <Card>
              <p data-testid="skills-panel-filtered-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                No evidence-backed skills are connected to this project yet. Clear the selection to see all skills.
              </p>
            </Card>
          ) : (
            visibleSkills.map((node) => {
              const selected = selection?.kind === "skill" && selection.id === node.key
              return (
                <SkillCard
                  key={node.key}
                  node={node}
                  selected={selected}
                  onToggleSelect={() => toggle("skill", node.key)}
                />
              )
            })
          )}
        </div>
      </div>
    </section>
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 1 — Candidate identity header */}
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

      {/* 2 — Publish controls */}
      <PassportPublishControls initialStatus={status} candidateName={passport.candidate_display_name} />

      {/* 3 — Evidence Graph Overview (summary chips only) */}
      <EvidenceGraphOverviewCard passport={passport} />

      {/* 4 — The main Passport body: Projects ↔ Skills interactive explorer */}
      <PassportGraphExplorer
        passport={passport}
        passportPublished={Boolean(passport.is_published && passport.public_slug)}
      />

      {/* 5 — Improve Passport: suggested attachments and unattached-evidence
          review moved to the private Proof Vault page. */}
      <ImprovePassportCard passport={passport} />

      {/* 6 — Limitations */}
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
