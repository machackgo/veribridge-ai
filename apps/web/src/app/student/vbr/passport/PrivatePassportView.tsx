"use client"

import { useEffect, useRef, useState, type CSSProperties } from "react"
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
  type ProofAttachmentSuggestion,
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
import {
  AttachmentOverviewSection,
  VaultSkillDashboard,
  type StrongestProjectRef,
} from "../../../../../components/passport/VaultProofs"

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
 * projects, published reports, evidence-backed skills, and proof sources exist,
 * plus the top next actions. Counts only — never a numeric trust score.
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
          Your passport is an evidence graph: each project proves skills, and each skill points back to concrete,
          inspectable proof. This is where it stands today.
        </p>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <OverviewStat stat="projects" label="Projects" value={overview.project_count} />
          <OverviewStat stat="published-reports" label="Published reports" value={overview.published_report_count} />
          <OverviewStat stat="skills-with-evidence" label="Skills with evidence" value={overview.skills_with_evidence} />
          <OverviewStat stat="attached-proofs" label="Proofs attached to projects" value={overview.attached_proof_count} />
          {typeof overview.suggested_proof_count === "number" && overview.suggested_proof_count > 0 && (
            <OverviewStat
              stat="suggested-proofs"
              label="Suggested — not counted until attached"
              value={overview.suggested_proof_count}
            />
          )}
          <OverviewStat stat="unattached-proofs" label="Unattached proofs" value={overview.unattached_proof_count} />
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

        {overview.next_actions.length > 0 && (
          <div data-testid="overview-next-actions" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Next actions
            </Mono>
            <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
              {overview.next_actions.map((action, i) => (
                <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                  {action}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}

// ── Proof Attachment Intelligence (owner-only) ────────────────────────────────

/** Closed qualitative confidence labels → badge tone (never numeric). */
const CONFIDENCE_TONE: Record<string, BadgeTone> = {
  "Likely match": "emerald",
  "Possible match": "sky",
  "Needs review": "amber",
}

const CHAIN_LABEL_TONE: Record<string, BadgeTone> = {
  "Strong chain": "emerald",
  "Good chain": "sky",
}

const MAX_RENDERED_SUGGESTIONS = 6

/** One suggested-attachment card: proof → likely project, why, basis chips,
 *  honest limitation, and non-destructive review actions only. */
function SuggestionCard({ suggestion }: { suggestion: ProofAttachmentSuggestion }) {
  return (
    <div
      data-testid="attachment-suggestion"
      data-proof-type={suggestion.proof_type}
      data-confidence={suggestion.confidence_label}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <Badge tone={SOURCE_TONE[suggestion.proof_type] ?? "slate"}>{suggestion.proof_type}</Badge>
        <span data-testid="suggestion-confidence">
          <Badge tone={CONFIDENCE_TONE[suggestion.confidence_label] ?? "slate"}>
            {suggestion.confidence_label}
          </Badge>
        </span>
        {suggestion.proof_count > 1 && (
          <span style={{ fontSize: 11, color: TOKEN.muted }}>{suggestion.proof_count} proof items grouped</span>
        )}
      </div>

      <div style={{ fontSize: 13, color: TOKEN.ink }}>
        <strong>{suggestion.proof_title}</strong>
        <span style={{ color: TOKEN.muted }}> → </span>
        <span data-testid="suggestion-project">{suggestion.likely_project_title}</span>
      </div>

      {suggestion.likely_skill_names.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {suggestion.likely_skill_names.map((skill) => (
            <span key={skill} data-testid="suggestion-skill">
              <Badge tone="indigo">{skill}</Badge>
            </span>
          ))}
        </div>
      )}

      <p data-testid="suggestion-reason" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
        {suggestion.suggestion_reason}
      </p>

      {suggestion.evidence_basis_chips.length > 0 && (
        <div data-testid="suggestion-basis-chips" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: TOKEN.muted }}>Based on:</span>
          {suggestion.evidence_basis_chips.map((chip) => (
            <span key={chip} data-testid="suggestion-basis-chip">
              <Badge tone="slate">{chip}</Badge>
            </span>
          ))}
        </div>
      )}

      {suggestion.limitation && (
        <p data-testid="suggestion-limitation" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          {suggestion.limitation}
        </p>
      )}

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span data-testid="suggestion-action-label" style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft }}>
          {suggestion.action_label}
        </span>
        {suggestion.likely_project_ref_safe && (
          <Link
            href={suggestion.likely_project_ref_safe}
            data-testid="suggestion-open-project"
            style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
          >
            Open project report →
          </Link>
        )}
      </div>
    </div>
  )
}

/**
 * Collapse duplicate-looking suggestions — same proof type + title pointing at
 * the same target project — into one card, summing the honest grouped
 * proof_count and merging named skills. The backend already dedupes by display
 * identity; this is a defensive render-layer net so a repeated card never
 * appears even if a payload slips through. Distinct target projects and
 * distinct titles stay separate rows.
 */
function dedupeSuggestions(suggestions: ProofAttachmentSuggestion[]): ProofAttachmentSuggestion[] {
  const byIdentity = new Map<string, ProofAttachmentSuggestion>()
  const order: string[] = []
  for (const s of suggestions) {
    const key = `${s.proof_type}|${s.proof_title.trim().toLowerCase()}|${s.likely_project_ref_safe ?? ""}`
    const existing = byIdentity.get(key)
    if (!existing) {
      byIdentity.set(key, { ...s, likely_skill_names: [...s.likely_skill_names] })
      order.push(key)
      continue
    }
    existing.proof_count += s.proof_count
    for (const skill of s.likely_skill_names) {
      if (!existing.likely_skill_names.includes(skill)) existing.likely_skill_names.push(skill)
    }
  }
  return order.map((k) => byIdentity.get(k)!)
}

/**
 * The owner-only "Proof Attachment Intelligence" section: suggested proof
 * attachments (deterministic safe-metadata matches, qualitative labels only),
 * the projects worth strengthening next, and the skills whose evidence is
 * still unattached. Review-only — nothing here mutates or attaches anything.
 */
function ProofAttachmentIntelligenceCard({ passport }: { passport: PrivateWorkPassport }) {
  const summary = passport.unattached_proof_summary
  const suggestions = dedupeSuggestions(summary?.suggestions ?? [])
  const unattachedCount = summary?.unattached_count ?? passport.vault_unattached_count ?? 0
  // Prominent "no safe project match" copy uses the clean, deduplicated
  // attachment-overview count (duplicate rows collapsed) — never the raw
  // vault-derived unmatched_count, which can balloon into the 519-style row
  // count and contradict the Evidence Graph Overview. unmatched_count is kept
  // only as a backward-compatible fallback for older payloads with no overview.
  const unmatchedCount =
    passport.attachment_overview?.unattached_count ?? summary?.unmatched_count ?? 0
  if (suggestions.length === 0 && unattachedCount === 0) return null

  const projectsToStrengthen = passport.projects.filter((p) => p.next_best_action).slice(0, 4)
  const skillsWithUnattached = (passport.vault_skill_summaries ?? [])
    .filter((s) => s.has_unattached)
    .slice(0, 6)
  const moreSuggestions = Math.max(0, suggestions.length - MAX_RENDERED_SUGGESTIONS)

  return (
    <Card>
      <div data-testid="proof-attachment-intelligence" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <CardHeader title="Proof Attachment Intelligence" eyebrow="What to attach next" icon="🧭" />
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          VeriBridge matched your unattached proof to the projects it likely belongs to using safe metadata only
          (repository, website domain, titles, shared skills). Suggestions are qualitative and never applied
          automatically — you review and attach.
        </p>

        {suggestions.length > 0 && (
          <div data-testid="suggested-attachments" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Suggested attachments
            </Mono>
            {suggestions.slice(0, MAX_RENDERED_SUGGESTIONS).map((s) => (
              <SuggestionCard key={s.suggestion_id_safe} suggestion={s} />
            ))}
            {moreSuggestions > 0 && (
              <span data-testid="suggestions-more" style={{ fontSize: 11, color: TOKEN.muted }}>
                +{moreSuggestions} more suggestion{moreSuggestions === 1 ? "" : "s"}
              </span>
            )}
          </div>
        )}

        {projectsToStrengthen.length > 0 && (
          <div data-testid="projects-to-strengthen" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Projects to strengthen
            </Mono>
            {projectsToStrengthen.map((p) => (
              <div
                key={p.project_id}
                data-testid="project-to-strengthen"
                style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", fontSize: 12, color: TOKEN.inkSoft }}
              >
                <strong style={{ color: TOKEN.ink }}>{p.project_title || "Untitled project"}</strong>
                {p.chain_label && (
                  <Badge tone={CHAIN_LABEL_TONE[p.chain_label] ?? "amber"}>{p.chain_label}</Badge>
                )}
                <span>{p.next_best_action}</span>
              </div>
            ))}
          </div>
        )}

        {skillsWithUnattached.length > 0 && (
          <div data-testid="skills-with-unattached" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Skills with unattached evidence
            </Mono>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {skillsWithUnattached.map((s) => (
                <Link
                  key={s.skill}
                  href={skillReportPath(s.skill_slug || fallbackSkillSlug(s.skill))}
                  data-testid="skill-with-unattached"
                  style={{ textDecoration: "none" }}
                >
                  <Badge tone="amber">
                    {s.skill} · {s.unattached_count} unattached
                  </Badge>
                </Link>
              ))}
            </div>
          </div>
        )}

        {unmatchedCount > 0 && (
          <p data-testid="suggestions-unmatched-note" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
            {unmatchedCount} unattached proof item(s) had no safe project match. They stay in your vault
            under their skill — nothing is guessed onto a project.
          </p>
        )}
      </div>
    </Card>
  )
}

// ── Project Portfolio ─────────────────────────────────────────────────────────

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
      {chain.missing.length > 0 && (
        <p data-testid="project-gaps" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
          Not yet attached: {chain.missing.join(", ")}. Attach these sources to strengthen this project&apos;s
          evidence.
        </p>
      )}
      {(project.proof_chain_gaps?.length ?? 0) > 0 && (
        <ul data-testid="project-chain-gaps" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}>
          {project.proof_chain_gaps!.map((gap) => (
            <li key={gap.source} data-testid="project-chain-gap" data-source={gap.source} style={{ fontSize: 11, color: TOKEN.muted }}>
              <strong style={{ color: TOKEN.inkSoft }}>{gap.gap_label}: </strong>
              {gap.action}
            </li>
          ))}
        </ul>
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
  const topSkills = project.top_skills ?? []

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

        {/* Proof chain completeness + gaps */}
        <ProofChainRow project={project} />

        {/* Proof Attachment Intelligence: the single next best action for this
            project, plus the unattached proofs suggested for it (review-only). */}
        {project.next_best_action && (
          <p data-testid="project-next-action" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            <strong style={{ color: TOKEN.ink }}>Suggested next action: </strong>
            {project.next_best_action}
          </p>
        )}
        {(project.suggested_attachments?.length ?? 0) > 0 && (
          <div data-testid="project-suggested-attachments" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Suggested proof attachments
            </Mono>
            {project.suggested_attachments!.map((s) => (
              <div
                key={s.suggestion_id_safe}
                data-testid="project-suggested-attachment"
                style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap", fontSize: 11, color: TOKEN.muted }}
              >
                <Badge tone={SOURCE_TONE[s.proof_type] ?? "slate"}>{s.proof_type}</Badge>
                <Badge tone={CONFIDENCE_TONE[s.confidence_label] ?? "slate"}>{s.confidence_label}</Badge>
                <span style={{ color: TOKEN.inkSoft, fontWeight: 600 }}>{s.proof_title}</span>
                <span>{s.suggestion_reason}</span>
              </div>
            ))}
          </div>
        )}

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
                    title={`Open the ${row.skill} Skill Report`}
                    style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4 }}
                  >
                    <Badge tone={SKILL_STATUS_TONE[row.status] ?? "slate"}>
                      {row.skill} · {row.status}
                    </Badge>
                    <span
                      data-testid="project-skill-evidence-label"
                      style={{ fontSize: 11, fontWeight: 600, color: TOKEN.indigo }}
                    >
                      View skill evidence →
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
          {topSkills.length > 0 && (
            <a data-testid="view-connected-skills-link" href="#skill-intelligence" style={secondaryBtnStyle}>
              View connected skills ↓
            </a>
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

  // Connect the skill lens back to the project lens: for each skill, the
  // project where it is most strongly evidenced (from the passport aggregate),
  // including the owner-only project report route for "View project evidence".
  const strongestBySkill: Record<string, StrongestProjectRef> = {}
  for (const s of passport.skills) {
    if (s.strongest_project_title) {
      const link = s.strongest_project
      strongestBySkill[s.skill.toLowerCase()] = {
        title: s.strongest_project_title,
        status: s.strongest_project_status ?? "",
        reportPath:
          link?.project_report_path ??
          (link?.project_id ? `/student/vbr/projects/${link.project_id}/report` : null),
        publicPath: link?.public_report_path ?? null,
        reportIsPublic: link?.report_is_public ?? false,
      }
    }
  }

  // Prominent user-facing copy uses the clean, deduplicated attachment-overview
  // count (duplicate rows of the same proof collapsed) so it never contradicts
  // the Evidence Graph Overview. The raw vault_unattached_count is kept only for
  // backward-compatible payloads, not headline copy.
  const unattachedCount =
    passport.attachment_overview?.unattached_count ?? passport.vault_unattached_count ?? 0
  const hasVault =
    (passport.vault_proof_count ?? 0) > 0 || (passport.vault_unattached_count ?? 0) > 0

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

      {/* Publish controls */}
      <PassportPublishControls initialStatus={status} candidateName={passport.candidate_display_name} />

      {/* 2 — Evidence Graph Overview */}
      <EvidenceGraphOverviewCard passport={passport} />

      {/* 2b — Proof Attachment Intelligence: suggested attachments, projects to
          strengthen, skills with unattached evidence (owner-only, review-only). */}
      <ProofAttachmentIntelligenceCard passport={passport} />

      {/* 3 — Project Portfolio (first-class, no longer buried at the bottom) */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Project Portfolio</h2>
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

      {/* 4 — Skill Intelligence (the equal second lens on the same evidence graph).
          Layer 1 of the Student Proof Vault: every proof grouped by canonical
          skill into COMPACT cards; the full stored evidence for one skill loads
          lazily on the Skill Report page. */}
      {(passport.vault_skill_summaries?.length ?? 0) > 0 && (
        <Card id="skill-intelligence">
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
            {unattachedCount > 0 && (
              <span data-testid="vault-unattached-summary">
                {" "}
                You have {unattachedCount} unattached proof item(s).
              </span>
            )}
          </p>
          <VaultSkillDashboard summaries={passport.vault_skill_summaries} strongestBySkill={strongestBySkill} />
        </Card>
      )}

      {/* 5 — Evidence Vault: unattached proof management */}
      {hasVault && (
        <Card>
          <div data-testid="evidence-vault-section" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <CardHeader title="Evidence Vault" eyebrow="Unattached proof management" icon="🧰" />
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
              Every proof you own is preserved here — attached to a project or not. Unattached proofs still appear
              under their skill above, but they do not count as project evidence and never feature in a recruiter
              report until you attach them.
            </p>
            {unattachedCount > 0 ? (
              <p data-testid="vault-unattached-action" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
                <strong>Next action:</strong> you have {unattachedCount} unattached proof item(s). Attach them to a
                project when you create or update a Project Defense so they strengthen that project&apos;s proof
                chain.
              </p>
            ) : (
              <p data-testid="vault-all-attached" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>
                Every proof in your vault is attached to a project — nothing is sitting unused.
              </p>
            )}
            {/* Attached / Suggested / Unattached — deduplicated, clearly separated
                sections. Suggested evidence is never counted until attached. */}
            <AttachmentOverviewSection overview={passport.attachment_overview} />
          </div>
        </Card>
      )}

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
