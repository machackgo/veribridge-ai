"use client"

import { useEffect, useMemo, useRef, useState, type ChangeEvent, type CSSProperties, type MouseEvent } from "react"
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
  uploadPassportPhoto,
  removePassportPhoto,
  validatePassportPhoto,
  PROOF_CHAIN_STEPS,
  type EvidenceGraphOverview,
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
  TOKEN,
  type BadgeTone,
} from "../../../../../components/passport/shared"
import { buildPassportGraph, type PassportSkillNode } from "./passport-graph"
import { PassportCard } from "../../../../../components/passport/PassportCard"
import { QrModal } from "../../../../../components/passport/QrModal"
import { buildPrivateCardModel, publicSafeAvatarUrl, type PassportCardCapability } from "@/lib/passport-card"
import { downloadPassportCardImage } from "@/lib/card-image"

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

/** Compact proof-type labels for select options / summaries (an HTML <option>
 *  is plain text, so the long "GitHub Proof" reads as clutter in a list). */
const PROOF_SHORT_LABEL: Record<string, string> = {
  "GitHub Proof": "GitHub",
  "Website Proof": "Website",
  "Document Proof": "Document",
  "Project Defense": "Defense",
  "Video Evidence": "Video",
}

/** "GitHub · Website · Defense" from canonical proof-type labels. */
function shortProofList(sources: string[]): string {
  return sources.map((s) => PROOF_SHORT_LABEL[s] ?? s).join(" · ")
}

/** The evaluator "Explore evidence" dropdown controls share one look. */
const selectStyle: CSSProperties = {
  padding: "7px 10px",
  borderRadius: 8,
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.ink,
  fontSize: 12,
  fontWeight: 600,
  maxWidth: 340,
  cursor: "pointer",
}

const controlLabelStyle: CSSProperties = {
  fontSize: 10,
  color: TOKEN.muted,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
}

/** Rows shown per skill block before the "Show N more projects" expander, so a
 *  skill demonstrated by 20–30 projects never floods the page in all-skills mode. */
const MAX_DEFAULT_SKILL_ROWS = 3

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
      ? `${typeof window !== "undefined" ? window.location.origin : ""}/vbr/report/${report.public_token}`
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
            <div data-testid="project-top-skills" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {topSkills.map((row) => {
                const href = row.skill_report_path ?? skillReportPath(row.skill_slug || fallbackSkillSlug(row.skill))
                // The proof types supporting THIS skill in THIS project — closed,
                // skill-specific labels (fail-closed to what the mapping recorded).
                const proofTypes = row.supporting_proof_types ?? []
                return (
                  <div
                    key={row.skill}
                    data-testid="project-top-skill-row"
                    data-skill={row.skill}
                    style={{ display: "flex", flexDirection: "column", gap: 3 }}
                  >
                    <Link
                      href={href}
                      data-testid="project-top-skill"
                      title={`Open the ${row.skill} evidence this project contributes`}
                      style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}
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
                    {proofTypes.length > 0 && (
                      <div
                        data-testid="project-skill-proof-chips"
                        data-skill={row.skill}
                        style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}
                      >
                        {proofTypes.map((label) => (
                          <span key={label} data-testid="project-skill-proof-chip" data-source={label}>
                            <Badge tone={SOURCE_TONE[label] ?? "slate"}>{label}</Badge>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
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

// ── Skills Evidence Map (skill-first primary body) ────────────────────────────

/**
 * One skill block in the Skills Evidence Map: the skill, its overall qualitative
 * status, the projects that demonstrate it (each with the proof that supports
 * this exact skill in that project), and — kept strictly separate — any
 * vault-only evidence that is not attached to a project.
 *
 * `focusProjectId`, when set, narrows the block to a single project's row (the
 * project-filter mode) and hides the vault-only section, which is not tied to
 * that project.
 */
function SkillCard({
  node,
  selected,
  focusProjectId,
  proofFilter,
  onToggleSelect,
}: {
  node: PassportSkillNode
  selected: boolean
  focusProjectId: string | null
  proofFilter: string | null
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
        // and operable by Enter/Space so keyboard users get the same focus as a
        // mouse click. Inner links keep their own behaviour.
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`${selected ? "Clear focus on" : "Focus"} the ${node.name} skill block`}
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
          <span style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink }}>{node.name}</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontSize: 11, color: TOKEN.muted }}>Overall status:</span>
            <Badge tone={SKILL_STATUS_TONE[node.status] ?? "slate"}>{node.status}</Badge>
          </span>
          <span data-testid="skill-project-count" style={{ fontSize: 11, color: TOKEN.muted }}>
            Connected projects: {node.projectCount}
          </span>
        </div>

        {/* Skill → Project link: where this skill is most strongly evidenced. */}
        {topProject && (
          <p data-testid="skill-top-project" style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            Strongest in <strong>{topProject}</strong>
            {node.strongest?.status ? ` — ${node.strongest.status}` : ""}
          </p>
        )}

        {/* Skill → Project → Evidence: each project row shows the proof that
            supports THIS skill in THAT project; vault-only evidence is rendered
            separately and clearly labelled as not attached to a project. */}
        <SkillEvidenceNav node={node} focusProjectId={focusProjectId} proofFilter={proofFilter} />

        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Link
            href={skillReportPath(node.slug)}
            data-testid="view-skill-report"
            title={`Open the full ${node.name} evidence across every project`}
            style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
          >
            Open full {node.name} skill report →
          </Link>
        </div>
      </div>
    </Card>
  )
}

/** Canonical proof-type chips for one skill→project (or vault-only) context. */
function ProofTypeChips({
  sources,
  testid,
  chipTestid,
  projectId,
}: {
  sources: string[]
  testid: string
  chipTestid: string
  projectId?: string
}) {
  return (
    <div
      data-testid={testid}
      data-project-id={projectId}
      style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}
    >
      {sources.map((label) => (
        <span key={label} data-testid={chipTestid} data-source={label}>
          <Badge tone={SOURCE_TONE[label] ?? "slate"}>{label}</Badge>
        </span>
      ))}
    </div>
  )
}

/**
 * The skill block's Skill → Project → Evidence map. Each attached project is one
 * row showing the proof that supports THIS skill in THAT project, its per-project
 * status, and CTAs into the project's report. Vault-only (standalone) evidence is
 * rendered in a separate, clearly-labelled section so it is never counted as
 * project proof. A skill whose evidence is ONLY in the vault renders the
 * vault-only state and never fronts a project-report CTA.
 */
function SkillEvidenceNav({
  node,
  focusProjectId,
  proofFilter,
}: {
  node: PassportSkillNode
  focusProjectId: string | null
  proofFilter: string | null
}) {
  const [expanded, setExpanded] = useState(false)
  const allRows = node.projectEvidence
  // Rows narrow to the active project and/or proof-type filter. A proof-type
  // filter shows only rows whose evidence for THIS skill in THAT project actually
  // includes that proof — never a row that merely has the proof project-wide.
  let rows = allRows
  if (focusProjectId) rows = rows.filter((r) => r.projectId === focusProjectId)
  if (proofFilter) rows = rows.filter((r) => r.evidenceSources.includes(proofFilter))

  // No attached project demonstrates this skill yet — its evidence lives only in
  // the vault. Never front a project-report CTA for loose vault evidence.
  if (allRows.length === 0) {
    return (
      <div
        data-testid="skill-vault-only"
        style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12, lineHeight: 1.5 }}
      >
        <p style={{ margin: 0, color: TOKEN.muted, fontWeight: 600 }}>
          Vault-only evidence — not attached to any project here, so it is not counted for a project.
        </p>
        {node.vaultOnlySources.length > 0 && (
          <ProofTypeChips sources={node.vaultOnlySources} testid="skill-vault-only-chips" chipTestid="skill-vault-only-chip" />
        )}
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

  // Scale to many-project skills: show the strongest few rows by default and let
  // the reader expand the rest. A single-project filter is already one row, so
  // capping only applies in the broader (all-skills / proof) modes.
  const capped = !focusProjectId && !expanded && rows.length > MAX_DEFAULT_SKILL_ROWS
  const shownRows = capped ? rows.slice(0, MAX_DEFAULT_SKILL_ROWS) : rows
  const hiddenCount = rows.length - shownRows.length

  return (
    <div data-testid="skill-evidence-nav" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <p
        data-testid="skill-projects-heading"
        style={{ fontSize: 11, color: TOKEN.ink, margin: 0, fontWeight: 700 }}
      >
        Projects demonstrating this skill
      </p>
      {rows.length > 1 && (
        <p
          data-testid="skill-multi-project-heading"
          style={{ fontSize: 11, color: TOKEN.muted, margin: 0, fontWeight: 600 }}
        >
          This skill appears in {rows.length} project reports
        </p>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {shownRows.map((row) => (
          <div
            key={row.projectId}
            data-testid="skill-project-evidence-row"
            data-project-id={row.projectId}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              padding: "8px 10px",
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 8,
              background: TOKEN.bg,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>{row.projectTitle}</span>
              {row.skillStatus && (
                <span data-testid="skill-project-status" data-project-id={row.projectId} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <span style={{ fontSize: 10, color: TOKEN.muted }}>Status in this project:</span>
                  <Badge tone={SKILL_STATUS_TONE[row.skillStatus] ?? "slate"}>{row.skillStatus}</Badge>
                </span>
              )}
            </div>
            {/* The exact proof types supporting THIS skill in THIS project
                (fail-closed — a chip only shows where the evidence mapping
                recorded it). The heading is always shown so the reader knows the
                chips are scoped to this skill, never the whole project's proof. */}
            <span
              data-testid="skill-project-evidence-heading"
              data-project-id={row.projectId}
              style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted }}
            >
              Evidence for this skill in this project:
            </span>
            {row.evidenceSources.length > 0 ? (
              <ProofTypeChips
                sources={row.evidenceSources}
                testid="skill-project-proof-chips"
                chipTestid="skill-project-proof-chip"
                projectId={row.projectId}
              />
            ) : row.projectHasProjectLevelProof ? (
              <span
                data-testid="skill-project-proof-unmapped"
                data-project-id={row.projectId}
                style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.4 }}
              >
                Project-level proof exists, but is not mapped to this skill yet.
              </span>
            ) : (
              <span
                data-testid="skill-project-proof-unclassified"
                data-project-id={row.projectId}
                style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.4 }}
              >
                No skill-specific evidence attached for this project yet.
              </span>
            )}
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
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
              <Link
                href={row.reportPath}
                data-testid="skill-project-evidence-link"
                data-project-id={row.projectId}
                title={`Open ${node.name} evidence inside the ${row.projectTitle} report`}
                style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
              >
                View {node.name} evidence in {row.projectTitle} report →
              </Link>
              <Link
                href={row.reportPath}
                data-testid="skill-open-project-report"
                data-project-id={row.projectId}
                style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, textDecoration: "none" }}
              >
                Open project report →
              </Link>
            </div>
          </div>
        ))}
      </div>

      {/* Many-project scalability: reveal the remaining project rows on demand. */}
      {capped ? (
        <button
          type="button"
          data-testid="skill-show-more-projects"
          onClick={() => setExpanded(true)}
          style={{ ...secondaryBtnStyle, alignSelf: "flex-start", padding: "5px 10px", fontSize: 12 }}
        >
          Show {hiddenCount} more {hiddenCount === 1 ? "project" : "projects"}
        </button>
      ) : !focusProjectId && expanded && rows.length > MAX_DEFAULT_SKILL_ROWS ? (
        <button
          type="button"
          data-testid="skill-show-fewer-projects"
          onClick={() => setExpanded(false)}
          style={{ ...secondaryBtnStyle, alignSelf: "flex-start", padding: "5px 10px", fontSize: 12 }}
        >
          Show fewer projects
        </button>
      ) : null}

      {/* Vault-only (standalone) evidence for this skill, kept SEPARATE from the
          project rows above so it is never counted as project-attached proof.
          Hidden in project-filter / proof-type mode (it is not project-attached). */}
      {!focusProjectId && !proofFilter && node.vaultOnlySources.length > 0 && (
        <div
          data-testid="skill-standalone-evidence"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 6,
            paddingTop: 8,
            borderTop: `1px dashed ${TOKEN.line}`,
          }}
        >
          <span style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted }}>
            Vault-only evidence — not attached to a project report.
          </span>
          <ProofTypeChips sources={node.vaultOnlySources} testid="skill-standalone-proof-chips" chipTestid="skill-standalone-proof-chip" />
          <Link
            href={skillReportPath(node.slug)}
            data-testid="skill-standalone-skill-report"
            style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
          >
            Open full {node.name} skill report →
          </Link>
        </div>
      )}
    </div>
  )
}

// ── Skills Evidence Map explorer (evaluator-grade skill proof browser) ─────────

/**
 * The main Passport body — a SKILL-FIRST evidence map built as a recruiter /
 * evaluator proof browser. A recruiter thinks "show me this candidate's proof for
 * Machine Learning", not "show me project X", so skills are the primary objects:
 * each block lists the projects that demonstrate it and the proof attached to that
 * project-skill relationship, with vault-only evidence kept separate.
 *
 * "Explore evidence" offers three combinable, scalable controls instead of a long
 * horizontal project-pill strip (which does not scale to 20–30 projects):
 *   • Skill      — narrow to one skill block.
 *   • Project    — narrow to skill blocks connected to that project, and to that
 *     project's row inside each block.
 *   • Proof type — narrow to skill→project rows whose proof for THAT skill in
 *     THAT project includes the type (never a project that merely has it broadly).
 * A search box matches skill or project names, and Clear filters resets to all
 * skills. All filtering is pure presentation over the already-safe payload — it
 * never fetches and never widens what the payload already exposes.
 */
function PassportGraphExplorer({
  passport,
  passportPublished,
  selectedSkillKey,
  onSelectSkillKey,
}: {
  passport: PrivateWorkPassport
  passportPublished: boolean
  /** Controlled skill selection (Card preview deep-link). Defaults to internal. */
  selectedSkillKey?: string | null
  onSelectSkillKey?: (key: string | null) => void
}) {
  const graph = useMemo(() => buildPassportGraph(passport), [passport])

  // Three independent, combinable filters + a name search. Default is All skills.
  // The skill filter is controlled-or-internal so the top Card preview can drive
  // it (deep-link a skill into this map) while standalone usage keeps working.
  const [internalSkillFilter, setInternalSkillFilter] = useState<string | null>(null)
  const skillFilter = selectedSkillKey !== undefined ? selectedSkillKey : internalSkillFilter
  const setSkillFilter = onSelectSkillKey ?? setInternalSkillFilter
  const [projectFilter, setProjectFilter] = useState<string | null>(null)
  const [proofFilter, setProofFilter] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  const query = search.trim().toLowerCase()
  const hasFilter = Boolean(skillFilter || projectFilter || proofFilter || query)
  const clearFilters = () => {
    setSkillFilter(null)
    setProjectFilter(null)
    setProofFilter(null)
    setSearch("")
  }
  // Card clicks stay in sync with the dropdowns (toggle the matching filter).
  const toggleSkill = (key: string) => setSkillFilter(skillFilter === key ? null : key)
  const toggleProject = (id: string) => setProjectFilter((c) => (c === id ? null : id))

  // Recruiter-facing proof-type options: every proof type that exists anywhere in
  // the Passport evidence (overview counts, project sources, skill sources,
  // vault-only, and the skill→project map). An option does NOT disappear just
  // because the visible skill block lacks it — selecting one still fails closed to
  // the skill→project rows that actually map it (and to the empty state when none
  // do), so project-level proof is never overclaimed as skill-specific evidence.
  const availableProofTypes = graph.proofTypeOptions

  // Project + proof filters act on the skill's ROWS (not just its identity), so a
  // proof type surfaces a skill only where that proof supports the skill in a
  // still-visible project — fail-closed to the skill→project mapping.
  const effectiveRows = (node: PassportSkillNode) => {
    let rows = node.projectEvidence
    if (projectFilter) rows = rows.filter((r) => r.projectId === projectFilter)
    if (proofFilter) rows = rows.filter((r) => r.evidenceSources.includes(proofFilter))
    return rows
  }
  const matchesSearch = (node: PassportSkillNode) =>
    !query ||
    node.name.toLowerCase().includes(query) ||
    node.projectEvidence.some((r) => r.projectTitle.toLowerCase().includes(query))

  const visibleSkills = graph.skills.filter((node) => {
    if (skillFilter && node.key !== skillFilter) return false
    if (!matchesSearch(node)) return false
    // Project / proof filters require a surviving row; skill / search alone keep
    // vault-only skills (which have no project rows) visible.
    if (projectFilter || proofFilter) return effectiveRows(node).length > 0
    return true
  })

  // The secondary project lens mirrors the same filters.
  const skillProjectIds = skillFilter ? new Set(graph.skillProjects.get(skillFilter) ?? []) : null
  const proofProjectIds = proofFilter
    ? new Set(
        graph.skills.flatMap((s) =>
          s.projectEvidence.filter((r) => r.evidenceSources.includes(proofFilter)).map((r) => r.projectId),
        ),
      )
    : null
  const visibleProjects = passport.projects.filter((p) => {
    if (projectFilter) return p.project_id === projectFilter
    if (skillProjectIds && !skillProjectIds.has(p.project_id)) return false
    if (proofProjectIds && !proofProjectIds.has(p.project_id)) return false
    if (
      query &&
      !p.project_title.toLowerCase().includes(query) &&
      !(graph.projectSkills.get(p.project_id) ?? []).some((k) => k.includes(query))
    )
      return false
    return true
  })

  const skillNode = skillFilter ? graph.skills.find((s) => s.key === skillFilter) ?? null : null
  const projectSummary = projectFilter
    ? passport.projects.find((p) => p.project_id === projectFilter) ?? null
    : null

  const skillsHeading = projectFilter
    ? `Skills for selected project (${visibleSkills.length})`
    : skillFilter
      ? `Selected skill (${visibleSkills.length})`
      : `Skills (${graph.skills.length})`
  const projectsHeading = skillFilter
    ? `Projects for selected skill (${visibleProjects.length})`
    : projectFilter
      ? `Selected project (${visibleProjects.length})`
      : `Projects (${passport.projects.length})`

  const panelHeading: CSSProperties = { fontSize: 15, fontWeight: 700, color: TOKEN.ink, margin: 0 }

  return (
    <section id="skills-evidence-map" data-testid="passport-graph-explorer" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Skills Evidence Map</h2>
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, maxWidth: 620, lineHeight: 1.5 }}>
          Each skill shows the projects that support it and the proof sources attached to that
          project-skill relationship. Vault-only evidence is listed separately.
        </p>
      </div>

      {/* Explore evidence — evaluator controls (skill / project / proof type +
          search). Compact and scalable: no long horizontal project-pill strip. */}
      <div
        data-testid="passport-evidence-controls"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: 12,
          border: `1px solid ${TOKEN.line}`,
          borderRadius: 12,
          background: TOKEN.bg,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>Explore evidence</span>
            <span style={{ fontSize: 11, color: TOKEN.muted }}>Filter by skill, project, or proof type.</span>
          </div>
          {hasFilter && (
            <button
              type="button"
              data-testid="clear-filters-button"
              onClick={clearFilters}
              style={{ ...secondaryBtnStyle, padding: "5px 10px", fontSize: 12 }}
            >
              Clear filters
            </button>
          )}
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={controlLabelStyle}>Skill</span>
            <select
              data-testid="passport-skill-filter"
              value={skillFilter ?? ""}
              onChange={(e) => setSkillFilter(e.target.value || null)}
              style={selectStyle}
            >
              <option value="">All skills</option>
              {graph.skills.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.name} — {s.projectCount} {s.projectCount === 1 ? "project" : "projects"}
                  {s.proofTypes.length > 0 ? ` · ${shortProofList(s.proofTypes)}` : ""}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={controlLabelStyle}>Project</span>
            <select
              data-testid="passport-project-filter"
              value={projectFilter ?? ""}
              onChange={(e) => setProjectFilter(e.target.value || null)}
              style={selectStyle}
            >
              <option value="">All projects</option>
              {passport.projects.map((p) => {
                const skillCount = graph.projectSkills.get(p.project_id)?.length ?? 0
                return (
                  <option key={p.project_id} value={p.project_id}>
                    {p.project_title || "Untitled project"} — {skillCount} {skillCount === 1 ? "skill" : "skills"}
                  </option>
                )
              })}
            </select>
          </label>

          {availableProofTypes.length > 0 && (
            <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={controlLabelStyle}>Proof type</span>
              <select
                data-testid="passport-proof-filter"
                value={proofFilter ?? ""}
                onChange={(e) => setProofFilter(e.target.value || null)}
                style={selectStyle}
              >
                <option value="">All proof types</option>
                {availableProofTypes.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label style={{ display: "flex", flexDirection: "column", gap: 3, flex: "1 1 200px", minWidth: 180 }}>
            <span style={controlLabelStyle}>Search</span>
            <input
              type="search"
              data-testid="passport-evidence-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search skills or projects…"
              style={{ ...selectStyle, cursor: "text", maxWidth: "none" }}
            />
          </label>
        </div>

        {/* Selected-filter summaries carry skill/project/proof CONTEXT, not just a
            bare name (requirements #3–#5). */}
        {(skillNode || projectSummary || proofFilter) && (
          <div
            data-testid="graph-filter-summary"
            style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 8, borderTop: `1px solid ${TOKEN.line}` }}
          >
            {skillNode && (
              <span data-testid="summary-skill" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                Showing evidence for: <strong>{skillNode.name}</strong> — {skillNode.projectCount}{" "}
                {skillNode.projectCount === 1 ? "project" : "projects"}
                {skillNode.proofTypes.length > 0 ? ` · ${shortProofList(skillNode.proofTypes)}` : ""}
              </span>
            )}
            {projectSummary && (
              <>
                <span data-testid="summary-project" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                  Showing skills from: <strong>{projectSummary.project_title || "Untitled project"}</strong>
                </span>
                {(projectSummary.evidence_sources?.length ?? 0) > 0 && (
                  <span data-testid="summary-project-proof" style={{ fontSize: 11, color: TOKEN.muted }}>
                    Project proof attached: {projectSummary.evidence_sources.join(" · ")}
                  </span>
                )}
              </>
            )}
            {proofFilter && (
              <span data-testid="summary-proof" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                Showing evidence with: <strong>{proofFilter}</strong>
              </span>
            )}
          </div>
        )}
      </div>

      {/* PRIMARY — the skill-first evidence map. */}
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
            {proofFilter ? (
              <p data-testid="skills-panel-proof-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                No skill-project evidence found for {proofFilter}. Try all proof types or attach{" "}
                {(PROOF_SHORT_LABEL[proofFilter] ?? proofFilter).toLowerCase()} evidence.
              </p>
            ) : (
              <p data-testid="skills-panel-filtered-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                No matching skill-project evidence found. Clear filters to see all skills.
              </p>
            )}
          </Card>
        ) : (
          visibleSkills.map((node) => (
            <SkillCard
              key={node.key}
              node={node}
              selected={skillFilter === node.key}
              focusProjectId={projectFilter}
              proofFilter={proofFilter}
              onToggleSelect={() => toggleSkill(node.key)}
            />
          ))
        )}
      </div>

      {/* SECONDARY — the project lens (report publishing / proof chain). */}
      <div data-testid="passport-projects-panel" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h3 style={panelHeading}>{projectsHeading}</h3>
        <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
          Manage each project&apos;s recruiter-safe report below.
        </p>
        {passport.projects.length === 0 ? (
          <Card>
            <p data-testid="passport-no-projects" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No projects yet. Create a Project Defense to start building your passport.
            </p>
          </Card>
        ) : visibleProjects.length === 0 ? (
          <Card>
            <p data-testid="projects-panel-filtered-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No projects match these filters. Clear filters to see all projects.
            </p>
          </Card>
        ) : (
          visibleProjects.map((project) => (
            <ProjectCard
              key={project.project_id}
              project={project}
              passportPublished={passportPublished}
              selected={projectFilter === project.project_id}
              connectedSkillCount={graph.projectSkills.get(project.project_id)?.length ?? 0}
              onToggleSelect={() => toggleProject(project.project_id)}
            />
          ))
        )}
      </div>
    </section>
  )
}

/**
 * Verified Passport Card Preview — the compact recruiter/career-fair credential
 * pinned to the top of the owner's private Passport. It renders the SAME
 * professional card a recruiter sees publicly (via {@link buildPrivateCardModel} →
 * {@link PassportCard}), so the student previews exactly what gets shared:
 * identity portrait, high-level role areas, and proof coverage — with no QR or
 * barcode on the card face. Role chips deep-link into the same-page Skills
 * Evidence Map. Publishing + share/download controls (Copy link, Open Passport,
 * Open Card, Download card, Web Share, optional "Show QR" modal) live in ONE
 * compact "Sharing controls" row directly below the card — no second Public Work
 * Passport block. Only recruiter-safe fields are ever shown.
 */
function VerifiedPassportCardPreview({
  passport,
  initialStatus,
  onSelectSkill,
}: {
  passport: PrivateWorkPassport
  initialStatus: WorkPassportStatus
  onSelectSkill: (key: string) => void
}) {
  const [status, setStatus] = useState<WorkPassportStatus>(initialStatus)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [qrOpen, setQrOpen] = useState(false)
  const [downloadNote, setDownloadNote] = useState<string | null>(null)
  const [downloadFallback, setDownloadFallback] = useState(false)
  const [shareNote, setShareNote] = useState<string | null>(null)
  // True when the shareable public link points at localhost/127.0.0.1 — used to
  // warn that such links only work on this computer (client-only to avoid an
  // SSR/hydration mismatch, since the URL derives from window.location).
  const [isLocalhostLink, setIsLocalhostLink] = useState(false)
  const actedRef = useRef(false)

  // Profile photo state. `avatarUrl` is the persisted public URL (seeded from the
  // passport payload); `localPreview` is a transient object-URL shown instantly
  // on selection and kept as a device-local fallback if server storage isn't set
  // up yet. The card's photo is fully controlled by this state so Remove clears
  // a previously-persisted photo too.
  const [avatarUrl, setAvatarUrl] = useState<string | null>(passport.identity?.avatar_url ?? null)
  const [localPreview, setLocalPreview] = useState<string | null>(null)
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [photoNote, setPhotoNote] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const localPreviewRef = useRef<string | null>(null)

  // Reconcile with the authoritative publish status (the passport payload's
  // is_published can lag). Skip once the student has acted here.
  useEffect(() => {
    getWorkPassportStatus()
      .then((s) => {
        if (!actedRef.current) setStatus(s)
      })
      .catch(() => {
        /* keep the server-rendered initial status */
      })
  }, [])

  // Revoke any outstanding object-URL preview on unmount (no memory leak).
  useEffect(() => {
    return () => {
      if (localPreviewRef.current) URL.revokeObjectURL(localPreviewRef.current)
    }
  }, [])

  const setPreview = (url: string | null) => {
    if (localPreviewRef.current) URL.revokeObjectURL(localPreviewRef.current)
    localPreviewRef.current = url
    setLocalPreview(url)
  }

  const baseModel = useMemo(() => buildPrivateCardModel(passport, status), [passport, status])
  // The photo is state-controlled: a live local preview wins, else the sanitized
  // persisted URL, else nothing (safe initials). Never falls back to the stale
  // payload photo, so Remove truly clears it.
  const model = useMemo(() => {
    const persisted = avatarUrl ? publicSafeAvatarUrl(avatarUrl) : null
    return { ...baseModel, profileImageUrl: localPreview ?? persisted }
  }, [baseModel, avatarUrl, localPreview])
  const hasPhoto = Boolean(model.profileImageUrl)

  // Flag a localhost share link (client-only) so we can warn it won't open on a
  // recruiter's phone. Checks the actual public URL, so a configured production
  // NEXT_PUBLIC_APP_URL correctly suppresses the note.
  useEffect(() => {
    const url = model.publicPassportUrl || model.cardUrl || ""
    setIsLocalhostLink(/\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(url))
  }, [model.publicPassportUrl, model.cardUrl])

  const onPickPhoto = () => {
    setPhotoError(null)
    fileInputRef.current?.click()
  }

  const onPhotoSelected = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = "" // allow re-selecting the same file
    if (!file) return

    const validationError = validatePassportPhoto(file)
    if (validationError) {
      setPhotoError(validationError)
      setPhotoNote(null)
      return
    }

    setPhotoError(null)
    setPhotoNote(null)
    setPhotoBusy(true)
    // Instant local preview so the card updates immediately on selection.
    setPreview(URL.createObjectURL(file))

    try {
      const result = await uploadPassportPhoto(file)
      if (result.persisted && result.avatar_url) {
        setAvatarUrl(result.avatar_url)
        setPreview(null) // swap the blob preview for the persisted public URL
        setPhotoNote("Profile photo updated")
      } else {
        // Storage isn't provisioned yet — keep the live local preview and be
        // honest that it hasn't been saved to the published card.
        setPhotoNote("Showing your photo on this device — connect photo storage to publish it.")
      }
    } catch {
      // Keep the local preview so the student still sees their photo on the card.
      setPhotoNote("Showing your photo on this device — it couldn't be saved just now.")
    } finally {
      setPhotoBusy(false)
    }
  }

  const onRemovePhoto = async () => {
    setPhotoError(null)
    setPhotoNote(null)
    setPhotoBusy(true)
    setPreview(null)
    try {
      await removePassportPhoto()
      setAvatarUrl(null)
      setPhotoNote("Profile photo removed")
    } catch {
      setAvatarUrl(null) // clear locally regardless
      setPhotoNote("Profile photo removed on this device.")
    } finally {
      setPhotoBusy(false)
    }
  }

  const runPublish = (action: () => Promise<WorkPassportStatus>) => {
    actedRef.current = true
    setBusy(true)
    setError(null)
    setCopied(false)
    action()
      .then(setStatus)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Action failed."))
      .finally(() => setBusy(false))
  }

  const copyLink = async () => {
    if (!model.publicPassportUrl) return
    try {
      await navigator.clipboard.writeText(model.publicPassportUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* Clipboard blocked — the link is still openable via the CTA below. */
    }
  }

  const scrollToMap = () => {
    document.getElementById("skills-evidence-map")?.scrollIntoView?.({ behavior: "smooth", block: "start" })
  }

  // ── Sharing architecture (what ships now vs. what comes later) ──────────────
  // NOW (real, web-safe, no fake magic):
  //   • Web Share API  → the OS share sheet (AirDrop, Messages, WhatsApp, …) so a
  //     student can hand the Passport to a nearby person/device today. Falls back
  //     to copy-link where `navigator.share` is unavailable (most desktops).
  //   • Download Passport Card  → an on-device PNG of the card only (never the
  //     page, never private data), so it can be saved to Photos / a portfolio.
  //   • Copy public link + open the public `/card/[slug]` display route.
  //   • Optional "Show QR" is a dismissible modal, never on the card face.

  // Download the card as a PNG rebuilt from the safe model (card only, not the
  // page). On any browser limitation we surface the manual save-as fallback
  // rather than producing a broken/blank file.
  const onDownloadCard = async () => {
    setDownloadNote(null)
    setDownloadFallback(false)
    try {
      await downloadPassportCardImage(model)
      setDownloadNote("Saved veribridge-passport-card.png")
    } catch {
      setDownloadFallback(true)
    }
  }

  // Web Share API (mobile share sheet) with a copy-link fallback where it's
  // unavailable. Never shares a private route — only the public Passport URL.
  const onSharePassport = async () => {
    const url = model.publicPassportUrl
    if (!url) return
    setShareNote(null)
    const nav = navigator as Navigator & { share?: (data: ShareData) => Promise<void> }
    if (typeof nav.share === "function") {
      try {
        await nav.share({ title: "Verified Work Passport", text: "My verified Work Passport", url })
        return
      } catch {
        /* Cancelled or unsupported — fall through to copy. */
      }
    }
    await copyLink()
    setShareNote("Sharing isn’t available here — link copied instead.")
  }

  // Same-page deep link: select the chip's strongest underlying skill in the
  // evidence map, then scroll to it (a real in-page selection, never a broken link).
  const onCapabilityClick = (cap: PassportCardCapability) => {
    if (cap.key) onSelectSkill(cap.key)
    scrollToMap()
  }

  const shareBtn: CSSProperties = {
    fontSize: 12,
    fontWeight: 600,
    padding: "7px 12px",
    borderRadius: 8,
    textDecoration: "none",
    cursor: "pointer",
    border: `1px solid ${TOKEN.line}`,
    background: "#fff",
    color: TOKEN.inkSoft,
    display: "inline-block",
  }

  return (
    <Card
      id="verified-passport-card-preview"
      style={{ background: "linear-gradient(160deg,#f7f8ff 0%,#eef0ff 100%)", borderColor: "#c7d2fe" }}
    >
      <div data-testid="verified-passport-card-preview" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Verified Passport Card Preview</h2>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.6, maxWidth: 620 }}>
            Share this recruiter-safe card with your public Work Passport. Save it as an image, copy the link, or open
            the full Passport. Tap a role area to jump to its evidence below.
          </p>
        </div>

        <PassportCard
          model={model}
          variant="private"
          onCapabilityClick={onCapabilityClick}
          footer={
            <button
              type="button"
              data-testid="passport-card-open-full"
              onClick={scrollToMap}
              style={{
                marginTop: 2,
                fontSize: 13,
                fontWeight: 600,
                padding: "10px 14px",
                borderRadius: 10,
                cursor: "pointer",
                border: "1px solid rgba(255,255,255,0.22)",
                background: "rgba(255,255,255,0.12)",
                color: "#fff",
              }}
            >
              Open full Work Passport ↓
            </button>
          }
        />

        {/* Profile photo control — upload/replace the portrait shown on the
            Passport Card. Client-side type/size validation runs before upload;
            the card updates immediately from a live preview. */}
        <div
          data-testid="passport-card-photo-control"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
            flexWrap: "wrap",
            padding: "10px 14px",
            borderRadius: 12,
            border: `1px dashed ${TOKEN.line}`,
            background: "#fff",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>
              {hasPhoto ? "Profile photo" : "Add a profile photo"}
            </span>
            <span style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
              Your profile photo appears on the Passport Card. Recruiter-safe summaries only — raw evidence is never
              exposed.
            </span>
            {photoError && (
              <span data-testid="passport-card-photo-error" style={{ fontSize: 11, color: TOKEN.rose, lineHeight: 1.5 }}>
                {photoError}
              </span>
            )}
            {photoNote && !photoError && (
              <span data-testid="passport-card-photo-note" style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
                {photoNote}
              </span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {hasPhoto && (
              <button
                type="button"
                data-testid="passport-card-remove-photo"
                onClick={onRemovePhoto}
                disabled={photoBusy}
                style={{ ...shareBtn, color: TOKEN.rose, opacity: photoBusy ? 0.6 : 1 }}
              >
                Remove photo
              </button>
            )}
            <button
              type="button"
              data-testid="passport-card-add-photo"
              onClick={onPickPhoto}
              disabled={photoBusy}
              style={{ ...shareBtn, opacity: photoBusy ? 0.6 : 1 }}
            >
              {photoBusy ? "Uploading…" : hasPhoto ? "Update profile photo" : "Add profile photo"}
            </button>
          </div>
          <input
            ref={fileInputRef}
            data-testid="passport-card-photo-input"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={onPhotoSelected}
            style={{ display: "none" }}
          />
        </div>

        {/* Sharing controls — secondary, compact row directly below the card
            (replaces the old separate "Public Work Passport" block). */}
        <div
          data-testid="passport-sharing-controls"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            padding: 14,
            borderRadius: 12,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>Sharing controls</span>
            {model.isPublished ? (
              <span data-testid="passport-public-badge">
                <Badge tone="emerald">Public passport live</Badge>
              </span>
            ) : (
              <span data-testid="passport-private-badge">
                <Badge tone="slate">Private only</Badge>
              </span>
            )}
          </div>

          {error && (
            <p data-testid="passport-publish-error" style={{ fontSize: 12, color: TOKEN.rose, margin: 0 }}>
              {error}
            </p>
          )}

          {/* Card actions available in any state — save the card as an image, and
              (once published) share it via the OS share sheet or an optional QR. */}
          <div data-testid="passport-card-actions" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <button type="button" data-testid="download-passport-card-button" onClick={onDownloadCard} style={shareBtn}>
              ⬇ Download Passport Card
            </button>
            {model.isPublished && model.publicPassportUrl && (
              <>
                <button type="button" data-testid="share-passport-button" onClick={onSharePassport} style={shareBtn}>
                  Share Passport
                </button>
                <button type="button" data-testid="show-qr-button" onClick={() => setQrOpen(true)} style={shareBtn}>
                  Show QR
                </button>
              </>
            )}
          </div>
          {downloadNote && (
            <p data-testid="download-passport-card-note" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
              {downloadNote}
            </p>
          )}
          {downloadFallback && (
            <p data-testid="download-passport-card-fallback" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
              Image download isn’t available in this browser. Right-click (or long-press on mobile) the card above and
              choose “Save image”.
            </p>
          )}
          {shareNote && (
            <p data-testid="share-passport-note" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
              {shareNote}
            </p>
          )}
          {isLocalhostLink && (
            <p data-testid="localhost-share-note" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
              Localhost links only work on this computer. For phone testing, use the Network URL or deploy to the
              production domain.
            </p>
          )}

          {model.isPublished && model.publicPassportUrl ? (
            <>
              <div
                data-testid="passport-public-link"
                style={{
                  fontFamily: '"JetBrains Mono", monospace',
                  fontSize: 12,
                  color: TOKEN.ink,
                  padding: "7px 10px",
                  background: TOKEN.bg,
                  border: `1px solid ${TOKEN.line}`,
                  borderRadius: 8,
                  wordBreak: "break-all",
                }}
              >
                {model.publicPassportUrl}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                <button type="button" data-testid="copy-passport-link-button" onClick={copyLink} style={{ ...shareBtn, background: TOKEN.indigo, color: "#fff", borderColor: TOKEN.indigo }}>
                  {copied ? "✓ Copied" : "Copy Passport link"}
                </button>
                <a data-testid="open-passport-link" href={model.publicPassportUrl} target="_blank" rel="noreferrer" style={shareBtn}>
                  Open public Passport ↗
                </a>
                {model.cardUrl && (
                  <a data-testid="passport-card-open-card" href={model.cardUrl} target="_blank" rel="noreferrer" style={shareBtn}>
                    Open Passport Card ↗
                  </a>
                )}
                <button
                  type="button"
                  data-testid="unpublish-passport-button"
                  disabled={busy}
                  onClick={() => runPublish(() => unpublishWorkPassport())}
                  style={{ ...shareBtn, opacity: busy ? 0.6 : 1 }}
                >
                  {busy ? "Working…" : "Unpublish"}
                </button>
              </div>
            </>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <p data-testid="passport-card-preview-publish-hint" style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
                Publish a recruiter-safe public card and shareable link. It links only to reports you have published —
                never raw evidence, private files, or numeric scores. Unpublish any time.
              </p>
              <button
                type="button"
                data-testid="publish-passport-button"
                disabled={busy}
                onClick={() => runPublish(() => publishWorkPassport())}
                style={{ ...shareBtn, alignSelf: "flex-start", background: TOKEN.indigo, color: "#fff", borderColor: TOKEN.indigo, opacity: busy ? 0.6 : 1 }}
              >
                {busy ? "Publishing…" : "Publish public Passport"}
              </button>
            </div>
          )}
        </div>
      </div>

      <QrModal value={model.publicPassportUrl} open={qrOpen} onClose={() => setQrOpen(false)} />
    </Card>
  )
}

export function PrivatePassportView() {
  const [passport, setPassport] = useState<PrivateWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedSkillKey, setSelectedSkillKey] = useState<string | null>(null)

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
      {/* 1 — Verified Passport Card preview: the compact recruiter/career-fair
          credential is the hero of the page (pinned to the very top) and now owns
          the sharing controls too, so there is no second "Public Work Passport" /
          "Verified candidate profile" block competing with it. */}
      <VerifiedPassportCardPreview passport={passport} initialStatus={status} onSelectSkill={setSelectedSkillKey} />

      {/* 2 — Candidate detail: education, public-status summary, and the full
          summary text that the compact card intentionally omits. */}
      <Card>
        <div data-testid="passport-header" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <CardHeader title="Candidate summary" eyebrow="Passport detail" icon="🎓" />
          <p style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
            {passport.identity?.display_name ?? passport.candidate_display_name ?? "Verified candidate profile"}
          </p>
          {(passport.identity?.education_summary?.trim() || "") && (
            <p data-testid="passport-education" style={{ fontSize: 13, color: TOKEN.muted, margin: 0 }}>
              🎓 {passport.identity?.education_summary}
            </p>
          )}
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.55 }}>{passport.summary}</p>
        </div>
      </Card>

      {/* 3 — Evidence Graph Overview (summary chips only) */}
      <EvidenceGraphOverviewCard passport={passport} />

      {/* 4 — The main Passport body: Projects ↔ Skills interactive explorer */}
      <PassportGraphExplorer
        passport={passport}
        passportPublished={Boolean(passport.is_published && passport.public_slug)}
        selectedSkillKey={selectedSkillKey}
        onSelectSkillKey={setSelectedSkillKey}
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
