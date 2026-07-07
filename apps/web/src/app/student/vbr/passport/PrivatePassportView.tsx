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
  type PassportWebsiteProofContext,
  type ProjectLevelProofContext,
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
  TOKEN,
  type BadgeTone,
} from "../../../../../components/passport/shared"
import { buildPassportGraph, type PassportSkillNode } from "./passport-graph"
import { PassportCard } from "../../../../../components/passport/PassportCard"
import { QrModal } from "../../../../../components/passport/QrModal"
import {
  buildPrivateCardModel,
  cardRoleAreasStorageKey,
  MAX_CARD_ROLE_AREAS,
  publicSafeAvatarUrl,
  type PassportCardCapability,
} from "@/lib/passport-card"
import { downloadPassportCardImage } from "@/lib/card-image"
import {
  buildCapabilityAggregates,
  capabilityRowKeys,
  filterAggregateByProof,
  presentCapabilities,
  type CapabilityAggregate,
} from "@/lib/passport-capabilities"

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

/** Canonical Website Proof proof-type label (matches the backend + graph). */
const WEBSITE_PROOF_LABEL = "Website Proof"

/** Canonical GitHub Proof proof-type label (matches the backend + graph). */
const GITHUB_PROOF_LABEL = "GitHub Proof"

/**
 * Recruiter-safe empty copy for an active Proof Type filter that matches no
 * skill→project row. Website / GitHub get a specific explanation that their
 * project-level or vault-only evidence is intentionally kept separate until it is
 * attached to a specific project skill (so the reader never reads the empty state
 * as "no such proof exists"); every other proof type gets the generic line.
 */
function proofFilterEmptyCopy(proofFilter: string): string {
  if (proofFilter === WEBSITE_PROOF_LABEL)
    return "No exact skill-project evidence matches Website Proof. Project-level or vault-only Website Proof is kept separate until it is attached to a specific project skill."
  if (proofFilter === GITHUB_PROOF_LABEL)
    return "No exact skill-project evidence matches GitHub Proof. Repository references or vault-only GitHub evidence are kept separate until attached to a specific project skill."
  return "No skill-project evidence matches the current filters."
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
  roleProjectIds,
  onToggleSelect,
}: {
  node: PassportSkillNode
  selected: boolean
  focusProjectId: string | null
  proofFilter: string | null
  roleProjectIds: string[] | null
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
        <SkillEvidenceNav node={node} focusProjectId={focusProjectId} proofFilter={proofFilter} roleProjectIds={roleProjectIds} />

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
  roleProjectIds,
}: {
  node: PassportSkillNode
  focusProjectId: string | null
  proofFilter: string | null
  /** When a Role Area filter is active, the exact project ids whose row supports
   *  THIS skill for that role area — a contextual skill (e.g. ML under Computer
   *  Vision) shows only its role-relevant project rows, never every project it
   *  touches. null when no role area is selected. */
  roleProjectIds: string[] | null
}) {
  const [expanded, setExpanded] = useState(false)
  const allRows = node.projectEvidence
  // Rows narrow to the active project, role area, and/or proof-type filter. A
  // proof-type filter shows only rows whose evidence for THIS skill in THAT
  // project actually includes that proof — never a row that merely has the proof
  // project-wide. The role-area filter fails closed to the exact skill→project
  // rows the capability mapping recorded, so an unrelated project never leaks in.
  let rows = allRows
  if (focusProjectId) rows = rows.filter((r) => r.projectId === focusProjectId)
  if (roleProjectIds) rows = rows.filter((r) => roleProjectIds.includes(r.projectId))
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
                // Precise Website Proof behaviour for THIS skill in THIS project,
                // derived from the safe website pipeline summaries (workflow /
                // recruiter / demonstrated-action / page-context / OCR-visual
                // fields) via the canonical Website→skill mapping — never raw
                // DOM/OCR/provider text. Falls back to an honest limited-detail
                // note when the capture was too thin to derive specifics.
                data-source-classified={row.websiteEvidenceSummary ? "true" : "false"}
                style={{ fontSize: 11, color: TOKEN.inkSoft, lineHeight: 1.4 }}
              >
                {row.websiteEvidenceSummary ??
                  "Website Proof supports runtime/product behavior for this skill, but detailed website evidence is limited."}
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
          Hidden in project / role-area / proof-type mode (it is not project-attached). */}
      {!focusProjectId && !proofFilter && !roleProjectIds && node.vaultOnlySources.length > 0 && (
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

// ── Project-level-only Website Proof (Diagnosis-C explainer) ──────────────────

/**
 * Shown when the evaluator filters Proof type = Website Proof but NO skill→project
 * row maps it, yet the passport DOES carry project-level Website Proof. Instead of
 * the generic "nothing here" copy, it states the honest truth: Website Proof
 * exists, it just hasn't been mapped to a specific skill because the observed
 * behaviour was navigation/layout-only — then tells the student exactly how to
 * strengthen it. It never renders these as skill evidence and never counts them.
 */
function WebsiteProofProjectLevelEmptyState({
  contexts,
}: {
  contexts: PassportWebsiteProofContext[]
}) {
  return (
    <div
      data-testid="website-proof-project-level-empty"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <Card>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <Badge tone="purple">Website Proof</Badge>
            <span style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted }}>Project-level only</span>
          </div>
          <p
            data-testid="website-proof-empty-headline"
            style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}
          >
            Website Proof exists, but it has not been mapped to specific skills yet.
          </p>
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            Current website evidence was classified as navigation/layout, which proves the site can
            be inspected but does not strongly demonstrate a specific skill. Record a stronger
            Website Proof showing runtime behavior such as model prediction, API response, dashboard
            interaction, route recommendation, or workflow completion.
          </p>
        </div>
      </Card>

      {/* Project-level Website Proof cards — informational, never skill evidence. */}
      {contexts.map((ctx) => (
        <Card key={`${ctx.project_id}:${ctx.focus_key}`}>
          <div
            data-testid="website-proof-project-context-card"
            style={{ display: "flex", flexDirection: "column", gap: 6 }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>
                {ctx.project_title || "Untitled project"}
              </span>
              <span style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted }}>
                Website Proof: Project-level only
              </span>
            </div>
            {ctx.explanation && (
              <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{ctx.explanation}</p>
            )}
            {ctx.reason && (
              <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                Reason: {ctx.reason}
                {ctx.focus_label ? ` · ${ctx.focus_label}` : ""}
              </p>
            )}
            {ctx.action_guidance && (
              <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
                Action: {ctx.action_guidance}
              </p>
            )}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 2 }}>
              {ctx.report_path && (
                <Link
                  data-testid="website-proof-context-open-report"
                  href={ctx.report_path}
                  style={{ ...secondaryBtnStyle, padding: "5px 10px", fontSize: 12 }}
                >
                  Open project report →
                </Link>
              )}
              <Link
                data-testid="website-proof-context-open-vault"
                href="/student/vbr/passport/vault"
                style={{ ...secondaryBtnStyle, padding: "5px 10px", fontSize: 12 }}
              >
                Open Proof Vault →
              </Link>
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}

// ── Project-level proof attached, not skill-mapped yet (GitHub + Website) ─────

/** Proof-type-specific intro copy for the project-level-proof section. */
function projectLevelIntroCopy(proofType: string): string {
  if (proofType === GITHUB_PROOF_LABEL)
    return "These projects have GitHub Proof attached at the project level, but VeriBridge has not yet mapped that repository evidence to a specific skill in the Passport. Open the project report to inspect the repo evidence or improve skill mapping."
  if (proofType === WEBSITE_PROOF_LABEL)
    return "These projects have Website Proof attached at the project level, but VeriBridge has not yet mapped the runtime evidence to a specific skill in the Passport. Open the project report to inspect the website evidence or improve skill mapping."
  return "These projects have proof attached at the project level, but it is not mapped to a specific Passport skill yet."
}

/**
 * The "Project-level proof attached, not skill-mapped yet" section, shown under
 * the GitHub / Website Proof filter. Each card is INFORMATIONAL context about a
 * project whose GitHub/Website proof stays project-level: it is NEVER a skill
 * card, NEVER counted under Skills, and NEVER implies the skill is demonstrated.
 * It links to the project report so the reader can inspect the evidence or improve
 * the skill mapping. Hidden when a specific skill/role filter is active (see the
 * caller) so project-level proof is never presented as supporting that skill/role.
 */
function ProjectLevelProofSection({
  proofType,
  contexts,
}: {
  proofType: string
  contexts: ProjectLevelProofContext[]
}) {
  if (contexts.length === 0) return null
  return (
    <div
      data-testid="project-level-proof-section"
      data-proof-type={proofType}
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <h4
          data-testid="project-level-proof-title"
          style={{ fontSize: 14, fontWeight: 700, color: TOKEN.ink, margin: 0 }}
        >
          Project-level proof attached, not skill-mapped yet
        </h4>
        <span data-testid="project-level-proof-count">
          <Badge tone="amber">Project-level matches ({contexts.length})</Badge>
        </span>
      </div>
      <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5, maxWidth: 620 }}>
        {projectLevelIntroCopy(proofType)}
      </p>
      {contexts.map((ctx) => (
        <Card key={`${ctx.proof_type}:${ctx.project_id}:${ctx.safe_source_label}`}>
          <div
            data-testid="project-level-proof-card"
            data-project-id={ctx.project_id}
            data-proof-type={ctx.proof_type}
            style={{ display: "flex", flexDirection: "column", gap: 6 }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>
                {ctx.project_title || "Untitled project"}
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Badge tone={SOURCE_TONE[ctx.proof_type] ?? "slate"}>{ctx.proof_type}</Badge>
                <span data-testid="project-level-proof-status">
                  <Badge tone="amber">{ctx.status || "Needs skill mapping"}</Badge>
                </span>
              </span>
            </div>
            {ctx.summary && (
              <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{ctx.summary}</p>
            )}
            {ctx.safe_source_label && (
              <Mono data-testid="project-level-proof-source" style={{ fontSize: 11, color: TOKEN.muted }}>
                {ctx.safe_source_label}
              </Mono>
            )}
            {ctx.reason_not_skill_mapped && (
              <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.4 }}>
                {ctx.reason_not_skill_mapped}
              </p>
            )}
            {/* Explicit, honest label — never presented as skill evidence. */}
            <span
              data-testid="project-level-proof-not-skill-evidence"
              style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 600 }}
            >
              Not counted as skill evidence — needs skill mapping.
            </span>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 2 }}>
              {ctx.report_url && (
                <Link
                  data-testid="project-level-proof-open-report"
                  data-project-id={ctx.project_id}
                  href={ctx.report_url}
                  style={{ ...secondaryBtnStyle, padding: "5px 10px", fontSize: 12 }}
                >
                  Open project report →
                </Link>
              )}
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}

// ── Role-area capability evidence summary ─────────────────────────────────────

/** Qualitative role-level status → chip tone (never a numeric score). */
const CAPABILITY_STATUS_TONE: Record<string, BadgeTone> = {
  "Evidence observed": "emerald",
  "Supporting evidence": "sky",
  "Partially demonstrated": "amber",
  "Insufficient evidence": "rose",
  "Not assessed": "slate",
}

/**
 * The visual evidence chain: a chip row connecting the role area to its supporting
 * evidence — [Skill] ─ [Skill] ─ [Project] ─ [Proof] ─ [Proof] — built with plain
 * styled divs and connector lines (no chart library). It makes a recruiter see at
 * a glance that a high-level skill is verified because multiple lower-level skills,
 * projects, and proofs connect together, not one isolated claim.
 */
function EvidenceChain({ nodes }: { nodes: string[] }) {
  if (nodes.length === 0) return null
  return (
    <div
      data-testid="capability-evidence-chain"
      style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 6 }}
    >
      {nodes.map((label, i) => (
        <span key={`${label}-${i}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {i > 0 && (
            <span
              aria-hidden
              style={{ width: 14, height: 2, borderRadius: 2, background: "#c7d2fe", display: "inline-block" }}
            />
          )}
          <span
            data-testid="capability-chain-node"
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "4px 10px",
              borderRadius: 999,
              fontSize: 11,
              fontWeight: 600,
              color: TOKEN.ink,
              background: "#fff",
              border: `1px solid ${TOKEN.indigo}`,
            }}
          >
            {label}
          </span>
        </span>
      ))}
    </div>
  )
}

/**
 * The role-level evidence view shown when a Role Area (high-level capability) is
 * selected. It answers, honestly and without a readiness guarantee:
 *   1. WHY this capability is supported (qualitative explanation + status label),
 *   2. a VISUAL evidence chain connecting skills → projects → proofs,
 *   3. the CONNECTED lower-level skills (each with its projects + proof),
 *   4. the CONNECTED projects (each with a reason, proof, and report links),
 *   5. WHAT gaps remain.
 *
 * Language is deliberately evidence-grounded: "supported by", "role-relevant
 * evidence", "supporting evidence", "needs stronger proof" — never "ready for
 * role", "verified" (unless proof is real), "score", or "rank". Every skill /
 * project / proof / link comes from the same evidence-backed Projects↔Skills graph
 * the map below renders — no fabricated skills, no unsafe raw fields.
 */
function CapabilitySummaryCard({ capability }: { capability: CapabilityAggregate }) {
  const statusTone = CAPABILITY_STATUS_TONE[capability.statusLabel] ?? "slate"
  const sectionLabel: CSSProperties = {
    fontSize: 10,
    color: TOKEN.muted,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
  }
  return (
    <Card
      style={{ background: "linear-gradient(160deg,#f5f7ff 0%,#eef2ff 100%)", borderColor: "#c7d2fe" }}
    >
      <div
        data-testid="capability-summary"
        data-capability={capability.label}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <span data-testid="capability-header" style={{ ...sectionLabel, color: TOKEN.indigo }}>
          High-level capability selected (1)
        </span>

        {/* Role name + qualitative status chip. */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <h3 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>{capability.label}</h3>
          <span data-testid="capability-status" data-status={capability.statusLabel}>
            <Badge tone={statusTone}>{capability.statusLabel}</Badge>
          </span>
          {capability.composite && (
            <span data-testid="capability-composite-note" style={{ fontSize: 11, color: TOKEN.muted, fontWeight: 600 }}>
              Multi-layer role
            </span>
          )}
        </div>

        {/* Counts line — connected skills / projects / proof sources (no scores). */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span data-testid="capability-skill-count">
            <Badge tone="slate">
              Connected skills: {capability.skills.length}
            </Badge>
          </span>
          <span data-testid="capability-project-count">
            <Badge tone="slate">
              Connected projects: {capability.projects.length}
            </Badge>
          </span>
          {capability.proofTypes.length > 0 && (
            <span data-testid="capability-proof-source-count">
              <Badge tone="slate">
                Proof sources: {capability.proofTypes.map((p) => PROOF_SHORT_LABEL[p] ?? p).join(", ")}
              </Badge>
            </span>
          )}
        </div>

        <p data-testid="capability-summary-text" style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.55 }}>
          {capability.summary}
        </p>

        {/* Why this role area is supported — rich, fact-grounded 1–2 paragraph
            narrative built from the exact connected skills, projects, and proof
            sources (never a score or fabricated claim). */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={sectionLabel}>Why this role area is supported</span>
          <div data-testid="capability-why" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {capability.narrative.map((paragraph, i) => (
              <p
                key={i}
                data-testid="capability-why-paragraph"
                style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}
              >
                {paragraph}
              </p>
            ))}
          </div>
        </div>

        {/* Visual connecting evidence chain. */}
        {capability.evidenceChain.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={sectionLabel}>Evidence chain</span>
            <EvidenceChain nodes={capability.evidenceChain} />
          </div>
        )}

        {/* Proof coverage across the whole capability. */}
        {capability.proofTypes.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={sectionLabel}>Proof coverage</span>
            <div data-testid="capability-proof-coverage" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {capability.proofTypes.map((label) => (
                <span key={label} data-testid="capability-proof-chip" data-source={label}>
                  <Badge tone={SOURCE_TONE[label] ?? "slate"}>{label}</Badge>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Connected lower-level skills — each with its projects + proof + report. */}
        {capability.skills.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={sectionLabel}>Connected lower-level skills</span>
            <div data-testid="capability-connected-skills" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {capability.skills.map((s) => (
                <div
                  key={s.skillKey}
                  data-testid="capability-skill"
                  data-skill={s.skillName}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 3,
                    padding: "7px 10px",
                    border: `1px solid ${TOKEN.line}`,
                    borderRadius: 8,
                    background: "#fff",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: TOKEN.ink }}>{s.skillName}</span>
                    <Badge tone={SKILL_STATUS_TONE[s.status] ?? "slate"}>{s.status}</Badge>
                    {s.contextual && (
                      <span data-testid="capability-skill-contextual" style={{ fontSize: 10, color: TOKEN.muted, fontWeight: 600 }}>
                        via project context
                      </span>
                    )}
                  </div>
                  <span style={{ fontSize: 11, color: TOKEN.inkSoft }}>
                    Attached to {s.projectTitles.join(", ")}
                  </span>
                  {/* Why this lower-level skill connects to the role area (honest). */}
                  <p
                    data-testid="capability-skill-reason"
                    data-skill={s.skillName}
                    style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
                  >
                    {s.reason}
                  </p>
                  {s.proofTypes.length > 0 && (
                    <div data-testid="capability-skill-proof" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {s.proofTypes.map((label) => (
                        <span key={label} data-testid="capability-skill-proof-chip" data-source={label}>
                          <Badge tone={SOURCE_TONE[label] ?? "slate"}>{label}</Badge>
                        </span>
                      ))}
                    </div>
                  )}
                  <Link
                    href={skillReportPath(s.skillSlug || fallbackSkillSlug(s.skillName))}
                    data-testid="capability-skill-report-link"
                    data-skill={s.skillName}
                    style={{ fontSize: 11.5, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none", alignSelf: "flex-start" }}
                  >
                    Open {s.skillName} skill report →
                  </Link>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Connected projects — reason + proof + links back to project-safe reports. */}
        {capability.projects.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={sectionLabel}>Connected projects</span>
            {capability.projects.map((proj, i) => (
              <div
                key={proj.projectId}
                data-testid="capability-project"
                data-project-id={proj.projectId}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  padding: "8px 10px",
                  border: `1px solid ${TOKEN.line}`,
                  borderRadius: 8,
                  background: "#fff",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>{proj.projectTitle}</span>
                  {i === 0 && (
                    <span data-testid="capability-strongest-project">
                      <Badge tone="emerald">Strongest evidence</Badge>
                    </span>
                  )}
                  {proj.contextual && (
                    <span data-testid="capability-project-contextual" title="Included via project context, not a directly-labelled skill">
                      <Badge tone="amber">Role-relevant context</Badge>
                    </span>
                  )}
                </div>
                <p data-testid="capability-project-reason" style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
                  {proj.reason}
                </p>
                <span style={{ fontSize: 11, color: TOKEN.muted }}>
                  Matched skills: {proj.skillNames.join(", ")}
                </span>
                <div data-testid="capability-project-proof" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {proj.proofTypes.map((label) => (
                    <span key={label} data-testid="capability-project-proof-chip" data-source={label}>
                      <Badge tone={SOURCE_TONE[label] ?? "slate"}>{label}</Badge>
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginTop: 2 }}>
                  <Link
                    href={proj.reportPath}
                    data-testid="capability-open-report"
                    data-project-id={proj.projectId}
                    style={{ fontSize: 11.5, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
                  >
                    Open project report →
                  </Link>
                  {proj.skillRefs.slice(0, 3).map((ref) => (
                    <Link
                      key={ref.slug}
                      href={skillReportPath(ref.slug || fallbackSkillSlug(ref.name))}
                      data-testid="capability-open-skill-report"
                      data-skill={ref.name}
                      style={{ fontSize: 11.5, fontWeight: 600, color: TOKEN.inkSoft, textDecoration: "none" }}
                    >
                      {ref.name} skill report →
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Honest gaps — what still needs stronger proof. */}
        {capability.gaps.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={sectionLabel}>Still needs stronger proof</span>
            <ul data-testid="capability-gaps" style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
              {capability.gaps.map((gap, i) => (
                <li key={i} data-testid="capability-gap" style={{ fontSize: 11.5, color: TOKEN.muted, lineHeight: 1.5 }}>
                  {gap}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p style={{ fontSize: 10.5, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Role-relevant evidence, not a readiness guarantee — capability is described qualitatively, never as a score or rank.
        </p>
      </div>
    </Card>
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
  selectedRoleAreaId,
  onSelectRoleAreaId,
}: {
  passport: PrivateWorkPassport
  passportPublished: boolean
  /** Controlled skill selection (Card preview deep-link). Defaults to internal. */
  selectedSkillKey?: string | null
  onSelectSkillKey?: (key: string | null) => void
  /** Controlled Role Area selection (Card role-chip deep-link). Defaults internal. */
  selectedRoleAreaId?: string | null
  onSelectRoleAreaId?: (id: string | null) => void
}) {
  const graph = useMemo(() => buildPassportGraph(passport), [passport])
  // High-level role-area aggregation over the SAME evidence-backed graph — one
  // canonical capability mapping (`@/lib/passport-capabilities`), shared with the
  // Passport Card role chips. Only role areas that actually have evidence become
  // selectable options.
  const capabilityAggregates = useMemo(() => buildCapabilityAggregates(graph.skills), [graph])
  const roleAreaOptions = useMemo(() => presentCapabilities(capabilityAggregates), [capabilityAggregates])

  // Four independent, combinable filters + a name search. Default is All skills.
  // The skill and role-area filters are controlled-or-internal so the top Card
  // preview can drive them (deep-link into this map) while standalone usage works.
  const [internalSkillFilter, setInternalSkillFilter] = useState<string | null>(null)
  const skillFilter = selectedSkillKey !== undefined ? selectedSkillKey : internalSkillFilter
  const setSkillFilter = onSelectSkillKey ?? setInternalSkillFilter
  const [internalRoleAreaFilter, setInternalRoleAreaFilter] = useState<string | null>(null)
  const roleAreaFilter = selectedRoleAreaId !== undefined ? selectedRoleAreaId : internalRoleAreaFilter
  const setRoleAreaFilter = onSelectRoleAreaId ?? setInternalRoleAreaFilter
  const [projectFilter, setProjectFilter] = useState<string | null>(null)
  const [proofFilter, setProofFilter] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  const query = search.trim().toLowerCase()
  const hasFilter = Boolean(roleAreaFilter || skillFilter || projectFilter || proofFilter || query)
  const clearFilters = () => {
    setRoleAreaFilter(null)
    setSkillFilter(null)
    setProjectFilter(null)
    setProofFilter(null)
    setSearch("")
  }
  // Card clicks stay in sync with the dropdowns (toggle the matching filter).
  const toggleSkill = (key: string) => setSkillFilter(skillFilter === key ? null : key)
  const toggleProject = (id: string) => setProjectFilter((c) => (c === id ? null : id))

  // The active role area's aggregate + the exact skill→project row keys it maps.
  // A selected role area that no longer has evidence (stale deep-link) resolves to
  // null and simply shows the honest empty state.
  const roleAggregate = roleAreaFilter
    ? capabilityAggregates.find((a) => a.id === roleAreaFilter) ?? null
    : null
  const roleRowKeys = useMemo(() => capabilityRowKeys(roleAggregate), [roleAggregate])
  // nodeKey → the project ids whose row supports THIS skill for the active role
  // area (a contextual skill shows only its role-relevant rows).
  const roleRowsByNode = useMemo(() => {
    const m = new Map<string, Set<string>>()
    for (const r of roleAggregate?.rows ?? []) {
      const set = m.get(r.skillKey) ?? new Set<string>()
      set.add(r.projectId)
      m.set(r.skillKey, set)
    }
    return m
  }, [roleAggregate])
  const roleProjectIdsFor = (node: PassportSkillNode): string[] | null =>
    roleAreaFilter ? [...(roleRowsByNode.get(node.key) ?? [])] : null
  const roleProjectIdSet = useMemo(
    () => new Set(roleAggregate?.rows.map((r) => r.projectId) ?? []),
    [roleAggregate],
  )
  const roleSkillKeys = useMemo(
    () => new Set(roleAggregate?.rows.map((r) => r.skillKey) ?? []),
    [roleAggregate],
  )

  // Recruiter-facing proof-type options: every proof type that exists anywhere in
  // the Passport evidence (overview counts, project sources, skill sources,
  // vault-only, and the skill→project map). An option does NOT disappear just
  // because the visible skill block lacks it — selecting one still fails closed to
  // the skill→project rows that actually map it (and to the empty state when none
  // do), so project-level proof is never overclaimed as skill-specific evidence.
  const availableProofTypes = graph.proofTypeOptions

  // Skill-dropdown options narrow to the active role area's underlying skills so
  // the skill filter reads as "underlying skills for this capability".
  const skillFilterOptions = roleAreaFilter
    ? graph.skills.filter((s) => roleSkillKeys.has(s.key))
    : graph.skills

  // Project-level-only Website Proof: attached Website Proofs that mapped no skill
  // (too-generic observed behaviour). Drives the honest Website-Proof empty state
  // below — informational context, NEVER counted or shown as skill evidence.
  const websiteProjectContext = passport.website_proof_project_context ?? []

  // Project-level-only proof (GitHub + Website): proof attached at the project
  // level that mapped NO skill. Shown under the GitHub / Website Proof filter as a
  // separate, clearly-labelled "not skill-mapped yet" section — NEVER counted as
  // skill evidence and NEVER shown while a specific skill/role filter is active
  // (so it can never read as supporting that skill/role). Filtered to the selected
  // proof type so a GitHub filter never shows Website project-level cards.
  const projectLevelContexts = passport.project_level_proof_context ?? []
  const projectLevelForProof =
    proofFilter && !skillFilter && !roleAreaFilter
      ? projectLevelContexts.filter((c) => c.proof_type === proofFilter)
      : []
  const showProjectLevelSection = projectLevelForProof.length > 0
  // The existing rich Website empty state owns the Website + no-rows case when the
  // passport carries the legacy per-focus website context; keep it authoritative
  // there so the two sections never both render.
  const websiteRichEmptyApplies =
    proofFilter === WEBSITE_PROOF_LABEL && websiteProjectContext.length > 0

  // Role-area / project / proof filters act on the skill's ROWS (not just its
  // identity). The role-area filter fails closed to the exact skill→project rows
  // the capability mapping recorded, so an unrelated project never leaks in and a
  // contextual skill (e.g. ML under Computer Vision) surfaces only its
  // role-relevant project rows.
  const effectiveRows = (node: PassportSkillNode) => {
    let rows = node.projectEvidence
    if (roleAreaFilter) rows = rows.filter((r) => roleRowKeys.has(`${node.key}::${r.projectId}`))
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
    // Role-area / project / proof filters require a surviving row; skill / search
    // alone keep vault-only skills (which have no project rows) visible.
    if (roleAreaFilter || projectFilter || proofFilter) return effectiveRows(node).length > 0
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
    if (roleAreaFilter && !roleProjectIdSet.has(p.project_id)) return false
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

  // The capability summary must respect an active Proof Type filter: it shows only
  // the portion of the role area backed by that proof (never another proof's chain
  // — e.g. no Document Proof chain while Website Proof is selected). When none of
  // the role area's evidence uses the selected proof, it resolves to null and an
  // honest empty note is shown instead of an unfiltered/overall summary.
  const proofScopedRoleAggregate = roleAggregate
    ? proofFilter
      ? filterAggregateByProof(roleAggregate, proofFilter)
      : roleAggregate
    : null

  const skillNode = skillFilter ? graph.skills.find((s) => s.key === skillFilter) ?? null : null
  const projectSummary = projectFilter
    ? passport.projects.find((p) => p.project_id === projectFilter) ?? null
    : null

  const skillsHeading = roleAreaFilter && roleAggregate
    ? `Skills supporting ${roleAggregate.label} (${visibleSkills.length})`
    : projectFilter
      ? `Skills for selected project (${visibleSkills.length})`
      : skillFilter
        ? `Selected skill (${visibleSkills.length})`
        : // A proof-type or search filter also narrows the visible skills, so the
          // heading must reflect the FILTERED count — never the full graph total.
          // e.g. Proof Type = Website Proof must read "Skills (3)", not "Skills (55)".
          // With no filter active the count is the full skill total, as before.
          hasFilter
          ? `Skills (${visibleSkills.length})`
        : `Skills (${graph.skills.length})`
  // The Projects heading count must never contradict the list below it: when ANY
  // evidence filter is active (role area, underlying skill, project, proof type,
  // or search) it reflects the FILTERED visibleProjects, so a Website/GitHub proof
  // filter with no matching skill-project row reads "Projects (0)", not the total.
  // With no filter active it shows the full passport.projects.length.
  const hasActiveEvidenceFilters = hasFilter
  const projectsHeadingCount = hasActiveEvidenceFilters ? visibleProjects.length : passport.projects.length
  const projectsHeading = skillFilter
    ? `Projects for selected skill (${visibleProjects.length})`
    : projectFilter
      ? `Selected project (${visibleProjects.length})`
      : `Projects (${projectsHeadingCount})`

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
            <span style={{ fontSize: 11, color: TOKEN.muted }}>Filter by role area, skill, project, or proof type.</span>
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
          {roleAreaOptions.length > 0 && (
            <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={controlLabelStyle}>Role area</span>
              <select
                data-testid="passport-role-area-filter"
                value={roleAreaFilter ?? ""}
                onChange={(e) => {
                  // Role area is a high-level lens: reset the skill filter so the
                  // capability aggregates across ALL its underlying skills, not a
                  // single leftover raw-skill selection.
                  setRoleAreaFilter(e.target.value || null)
                  setSkillFilter(null)
                }}
                style={selectStyle}
              >
                <option value="">All role areas</option>
                {roleAreaOptions.map((cap) => (
                  <option key={cap.id} value={cap.id}>
                    {cap.label} — {cap.projects.length} {cap.projects.length === 1 ? "project" : "projects"} ·{" "}
                    {cap.skillNames.length} {cap.skillNames.length === 1 ? "skill" : "skills"}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={controlLabelStyle}>{roleAreaFilter ? "Underlying skill" : "Skill"}</span>
            <select
              data-testid="passport-skill-filter"
              value={skillFilter ?? ""}
              onChange={(e) => setSkillFilter(e.target.value || null)}
              style={selectStyle}
            >
              <option value="">{roleAreaFilter ? "All underlying skills" : "All skills"}</option>
              {skillFilterOptions.map((s) => (
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

        {/* Selected-filter summaries carry role/skill/project/proof CONTEXT, not
            just a bare name (requirements #3–#5). */}
        {(roleAggregate || skillNode || projectSummary || proofFilter) && (
          <div
            data-testid="graph-filter-summary"
            style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 8, borderTop: `1px solid ${TOKEN.line}` }}
          >
            {roleAggregate && (
              <span data-testid="summary-role" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                Showing role-relevant evidence for: <strong>{roleAggregate.label}</strong> —{" "}
                {roleAggregate.projects.length} {roleAggregate.projects.length === 1 ? "project" : "projects"} ·{" "}
                {roleAggregate.skillNames.length} underlying {roleAggregate.skillNames.length === 1 ? "skill" : "skills"}
              </span>
            )}
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

      {/* Role-area capability summary — the role-level evidence view (why, which
          projects, which skills, which proof, what gaps). Shown above the map so a
          recruiter reads the aggregated capability first, then the supporting rows.
          Under an active Proof Type filter it is scoped to that proof (or an honest
          empty note when the role area has no evidence using it), so it never shows
          a proof chain that violates the selected Proof Type. */}
      {roleAggregate &&
        (proofScopedRoleAggregate ? (
          <CapabilitySummaryCard capability={proofScopedRoleAggregate} />
        ) : (
          <Card>
            <p
              data-testid="capability-proof-empty"
              style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
            >
              No exact evidence for this role area matches the selected proof type.
            </p>
          </Card>
        ))}

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
          websiteRichEmptyApplies ? (
            // Website Proof exists at project level but mapped no skill — explain
            // the honest gap + how to strengthen it, instead of the generic copy.
            <WebsiteProofProjectLevelEmptyState contexts={websiteProjectContext} />
          ) : showProjectLevelSection ? (
            // No exact skill rows, but the project has GitHub/Website proof at the
            // project level — show the honest project-level section, not blank.
            <ProjectLevelProofSection proofType={proofFilter as string} contexts={projectLevelForProof} />
          ) : (
            <Card>
              {proofFilter && roleAggregate ? (
                <p data-testid="skills-panel-role-proof-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                  No {roleAggregate.label} evidence uses {proofFilter}. Try all proof types, or attach{" "}
                  {(PROOF_SHORT_LABEL[proofFilter] ?? proofFilter).toLowerCase()} evidence to a project that supports this role area.
                </p>
              ) : proofFilter ? (
                <p data-testid="skills-panel-proof-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
                  {proofFilterEmptyCopy(proofFilter)}
                </p>
              ) : (
                <p data-testid="skills-panel-filtered-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
                  No matching skill-project evidence found. Clear filters to see all skills.
                </p>
              )}
            </Card>
          )
        ) : (
          visibleSkills.map((node) => (
            <SkillCard
              key={node.key}
              node={node}
              selected={skillFilter === node.key}
              focusProjectId={projectFilter}
              proofFilter={proofFilter}
              roleProjectIds={roleProjectIdsFor(node)}
              onToggleSelect={() => toggleSkill(node.key)}
            />
          ))
        )}

        {/* Project-level proof attached, not skill-mapped yet — shown ADDITIVELY
            below the exact skill rows when they exist (the empty case above renders
            it in place instead). Informational only; never counted as skill
            evidence and never shown under a specific skill/role filter. */}
        {visibleSkills.length > 0 && showProjectLevelSection && (
          <ProjectLevelProofSection proofType={proofFilter as string} contexts={projectLevelForProof} />
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
            <p data-testid="projects-panel-filtered-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
              {proofFilter ? `${proofFilterEmptyCopy(proofFilter)} ` : "No projects match these filters. "}
              Clear filters to see all projects.
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
 * barcode on the card face. Role chips are HIGH-LEVEL role areas: clicking one
 * drives the same-page Skills Evidence Map's "Role area" filter by the chip's
 * canonical roleAreaId (and resets the underlying-skill filter to all), never
 * selecting an arbitrary low-level skill. Publishing + share/download
 * controls (Copy link, Open Passport, Open Card, Download card, Web Share, optional
 * "Show QR" modal) live in ONE compact "Sharing controls" row directly below the
 * card — no second Public Work Passport block. Only recruiter-safe fields shown.
 */
function VerifiedPassportCardPreview({
  passport,
  initialStatus,
  onSelectRoleAreaId,
}: {
  passport: PrivateWorkPassport
  initialStatus: WorkPassportStatus
  /**
   * Select a HIGH-LEVEL role area in the same-page Skills Evidence Map. Card role
   * chips drive this (never a low-level skill), so clicking "Computer Vision"
   * filters by the role area — not by an arbitrary underlying skill like React or
   * Docker. The parent also resets the low-level skill filter to "all".
   */
  onSelectRoleAreaId: (roleAreaId: string) => void
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

  // ── Customize Passport Card: student-chosen role areas (max 6) ──────────────
  // The available role areas come from the SAME grouped high-level capability data
  // the card is built from (never a hardcoded list), and the default is the top
  // areas that data already ranks. Selection is persisted per-passport in
  // localStorage (frontend-only MVP — there is no backend field for this yet).
  const available = model.availableCapabilities
  const availableLabels = useMemo(() => available.map((c) => c.label), [available])
  const defaultLabels = useMemo(() => model.capabilities.map((c) => c.label), [model.capabilities])
  const stableId = model.slug ?? (model.name ? fallbackSkillSlug(model.name) : null)
  const storageKey = useMemo(() => cardRoleAreasStorageKey(stableId), [stableId])

  const [selectedLabels, setSelectedLabels] = useState<string[]>(defaultLabels)
  const [showRoleEditor, setShowRoleEditor] = useState(false)
  const loadedRef = useRef(false)

  // Load the saved selection on the client (localStorage is unavailable during
  // SSR). Invalid/stale labels are dropped; an empty/missing selection falls back
  // to the default top areas so the card is never blank.
  useEffect(() => {
    let stored: string[] | null = null
    try {
      const raw = window.localStorage.getItem(storageKey)
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) stored = parsed.filter((x): x is string => typeof x === "string")
      }
    } catch {
      /* localStorage blocked/unavailable — use the default selection. */
    }
    const valid = (stored ?? []).filter((l) => availableLabels.includes(l)).slice(0, MAX_CARD_ROLE_AREAS)
    setSelectedLabels(valid.length > 0 ? valid : defaultLabels)
    loadedRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey])

  // Persist after the initial load so we never clobber a saved selection with the
  // transient default on first paint.
  useEffect(() => {
    if (!loadedRef.current) return
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(selectedLabels))
    } catch {
      /* localStorage blocked — selection stays in-memory for this session. */
    }
  }, [selectedLabels, storageKey])

  // The card face shows only the selected role areas, ordered by the existing
  // role-area ranking and capped defensively.
  const displayedCapabilities = useMemo(
    () => available.filter((c) => selectedLabels.includes(c.label)).slice(0, MAX_CARD_ROLE_AREAS),
    [available, selectedLabels],
  )
  const atLimit = selectedLabels.length >= MAX_CARD_ROLE_AREAS

  const toggleRoleArea = (label: string) => {
    setSelectedLabels((prev) => {
      if (prev.includes(label)) return prev.filter((l) => l !== label)
      if (prev.length >= MAX_CARD_ROLE_AREAS) return prev // hard cap: never exceed 6
      return [...prev, label]
    })
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
  //   • Web Share API  → the OS share sheet (AirDrop, Messages, WhatsApp, …) with a
  //     copy-link fallback where `navigator.share` is unavailable (most desktops).
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

  // Same-page deep link: a card role chip is a HIGH-LEVEL role area, so it drives
  // the evidence map's "Role area" filter by the chip's canonical roleAreaId — it
  // must NEVER select an arbitrary low-level skill (React/Docker/Computer
  // Graphics). The parent resets the underlying-skill filter to "all" and this
  // scrolls to the map, so the high-level capability card + its connected
  // skills/projects/proof chain render for that role area.
  const onCapabilityClick = (cap: PassportCardCapability) => {
    onSelectRoleAreaId(cap.roleAreaId)
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
          capabilities={displayedCapabilities}
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

        {/* Customize Passport Card — choose which high-level role areas fill the
            card face (max 6). Options come from the same grouped capability data
            the card is built from; the choice is saved per-passport in
            localStorage and updates the preview above instantly. */}
        <div
          data-testid="customize-passport-card"
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
            <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>Customize Passport Card</span>
            <span
              data-testid="card-role-area-count"
              style={{ fontSize: 12, fontWeight: 600, color: atLimit ? TOKEN.indigo : TOKEN.muted }}
            >
              {selectedLabels.length} of {MAX_CARD_ROLE_AREAS} selected
            </span>
          </div>
          <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0, lineHeight: 1.6, maxWidth: 620 }}>
            Choose the role areas you want recruiters to notice first. The full passport still contains all evidence.
          </p>

          {available.length === 0 ? (
            <p data-testid="card-role-area-empty" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
              Role areas appear here once your skills have attached evidence. Attach proof to a project to unlock them.
            </p>
          ) : (
            <>
              <button
                type="button"
                data-testid="edit-card-role-areas"
                aria-expanded={showRoleEditor}
                onClick={() => setShowRoleEditor((v) => !v)}
                style={{
                  alignSelf: "flex-start",
                  fontSize: 12,
                  fontWeight: 600,
                  padding: "7px 12px",
                  borderRadius: 8,
                  cursor: "pointer",
                  border: `1px solid ${TOKEN.line}`,
                  background: "#fff",
                  color: TOKEN.inkSoft,
                }}
              >
                {showRoleEditor ? "Done editing role areas" : "Edit card role areas"}
              </button>

              {showRoleEditor && (
                <div
                  data-testid="card-role-area-options"
                  style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
                >
                  {available.map((cap) => {
                    const selected = selectedLabels.includes(cap.label)
                    const disabled = !selected && atLimit
                    return (
                      <button
                        key={cap.label}
                        type="button"
                        data-testid="card-role-area-option"
                        data-label={cap.label}
                        data-selected={selected ? "true" : "false"}
                        aria-pressed={selected}
                        disabled={disabled}
                        onClick={() => toggleRoleArea(cap.label)}
                        title={
                          disabled
                            ? `Deselect a role area first — you can show up to ${MAX_CARD_ROLE_AREAS}.`
                            : selected
                              ? `Remove ${cap.label} from the card`
                              : `Add ${cap.label} to the card`
                        }
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 7,
                          padding: "6px 11px",
                          borderRadius: 999,
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: disabled ? "not-allowed" : "pointer",
                          opacity: disabled ? 0.5 : 1,
                          border: `1px solid ${selected ? TOKEN.indigo : TOKEN.line}`,
                          background: selected ? TOKEN.indigo : "#fff",
                          color: selected ? "#fff" : TOKEN.inkSoft,
                        }}
                      >
                        <span aria-hidden style={{ fontSize: 12, lineHeight: 1 }}>{selected ? "✓" : "+"}</span>
                        {cap.label}
                        <span
                          data-testid="card-role-area-evidence-count"
                          style={{
                            fontSize: 10.5,
                            fontWeight: 600,
                            color: selected ? "rgba(255,255,255,0.85)" : TOKEN.muted,
                          }}
                        >
                          {cap.evidenceCount} {cap.evidenceCount === 1 ? "skill" : "skills"}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </>
          )}
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
  // The Skills Evidence Map's two deep-linkable filters, lifted here so the top
  // Passport Card preview can drive them: a low-level skill (unused by the card
  // now, kept for standalone selection) and the HIGH-LEVEL role area.
  const [selectedSkillKey, setSelectedSkillKey] = useState<string | null>(null)
  const [selectedRoleAreaId, setSelectedRoleAreaId] = useState<string | null>(null)

  // A Passport Card role chip sets the high-level Role Area filter AND resets the
  // low-level Skill filter to "all underlying skills" — so clicking "Computer
  // Vision" shows that role area's capability card + connected evidence and never
  // leaves an arbitrary underlying skill (React/Docker/Computer Graphics) selected.
  const selectRoleAreaFromCard = (roleAreaId: string) => {
    setSelectedRoleAreaId(roleAreaId)
    setSelectedSkillKey(null)
  }

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
      <VerifiedPassportCardPreview passport={passport} initialStatus={status} onSelectRoleAreaId={selectRoleAreaFromCard} />

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
        selectedRoleAreaId={selectedRoleAreaId}
        onSelectRoleAreaId={setSelectedRoleAreaId}
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
