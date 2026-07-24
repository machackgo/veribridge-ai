"use client"

/**
 * Canonical Verified Build Report sections — the ONE report rendering system.
 *
 * The student (owner) report at /student/vbr/projects/[id]/report and the
 * public recruiter report at /vbr/report/[token] render the SAME sections from
 * the same shared evidence model. The only differences are authentication-safe
 * presentation ones (owner-only publish controls, owner-only original-file
 * access, private replay) which live in the two thin route views — never a
 * separate report design.
 *
 * Test-id contract: each surface passes its own `testIds` map so the existing
 * student ("skill-evidence-card", "safe-repo-link", …) and public
 * ("public-skill-row", "public-safe-repo-link", …) automated suites keep their
 * stable hooks while rendering identical canonical markup.
 */

import type { CSSProperties, ReactNode } from "react"
import {
  isSafePublicUrl,
  matrixTraceLabel,
  type EvidenceTrace,
  type VBRReportSkillEvidenceRow,
} from "@/lib/vbr-api"
import { Badge, Mono, TOKEN, type BadgeTone } from "./shared"

export const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Supporting evidence": "sky",
  "Evidence observed": "emerald",
  "Needs review": "rose",
  "Not assessed": "slate",
}

export const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

/** Canonical proof-source render order shared by every report surface. */
export const PROOF_SOURCE_ORDER = [
  "GitHub Proof",
  "Document Proof",
  "Website Proof",
  "Project Defense",
  "Video Evidence",
] as const

export type SkillCardTestIds = {
  card: string
  sources: string
  why: string
  verify: string
  limitations: string
  notAssessed: string
  groupsWrapper: string
  group: string
  jump: string
  skillCta: string
}

export const OWNER_SKILL_CARD_TEST_IDS: SkillCardTestIds = {
  card: "skill-evidence-card",
  sources: "skill-supporting-sources",
  why: "skill-why",
  verify: "skill-verify",
  limitations: "skill-limitations",
  notAssessed: "skill-not-assessed",
  groupsWrapper: "skill-evidence-groups",
  group: "skill-evidence-group",
  jump: "skill-evidence-jump",
  skillCta: "skill-report-cta",
}

export const PUBLIC_SKILL_CARD_TEST_IDS: SkillCardTestIds = {
  card: "public-skill-row",
  sources: "public-skill-supporting-sources",
  why: "public-skill-why",
  verify: "public-skill-verify",
  limitations: "public-skill-limitations",
  notAssessed: "public-skill-not-assessed",
  groupsWrapper: "public-skill-trace-links",
  group: "public-skill-evidence-group",
  jump: "public-skill-evidence-jump",
  skillCta: "public-skill-report-cta",
}

/**
 * One skill-first evidence card — the canonical report's main body unit.
 * Shows the skill's qualitative status, the proof sources supporting it in
 * THIS project, the plain-language explanation, evidence grouped by proof
 * source with jump links, honest limitations, and (optionally) a link to the
 * surface-appropriate full Skill Report.
 */
export function CanonicalSkillEvidenceCard({
  row,
  tracesById,
  testIds,
  skillHref,
  skillCtaLabel = "View full skill evidence →",
  renderSkillLink,
}: {
  row: VBRReportSkillEvidenceRow
  tracesById: Map<string, EvidenceTrace>
  testIds: SkillCardTestIds
  /** Surface-appropriate Skill Report href; omit to render no CTA. */
  skillHref?: string | null
  skillCtaLabel?: string
  /** Optional custom renderer for the CTA (e.g. Next <Link>). */
  renderSkillLink?: (href: string, label: string) => ReactNode
}) {
  const sources = row.supporting_sources ?? []
  const limitations = row.limitations ?? []
  const traceRefs = (row.evidence_traces ?? [])
    .map((id) => tracesById.get(id))
    .filter((t): t is EvidenceTrace => Boolean(t))

  // Group this skill's evidence rows by proof source (canonical order). Each
  // group only appears when the backend actually attached a trace of that
  // source to THIS skill.
  const groups = PROOF_SOURCE_ORDER.map((source) => ({
    source,
    traces: traceRefs.filter((t) => t.source_type === source),
  })).filter((g) => g.traces.length > 0)

  const notAssessed = sources.length === 0 && groups.length === 0

  return (
    <div
      data-testid={testIds.card}
      data-skill={row.skill}
      data-status={row.status}
      style={{
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 10,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        background: notAssessed ? TOKEN.bg : "#fff",
        minWidth: 0,
      }}
    >
      {/* Skill name + status */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TOKEN.ink, overflowWrap: "anywhere" }}>
          {row.skill}
        </h4>
        <Badge tone={QUALITATIVE_LABEL_TONE[row.status] ?? "slate"}>{row.status}</Badge>
      </div>

      {/* Proof source chips supporting this skill IN THIS PROJECT */}
      {sources.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
            Supported in this project by
          </Mono>
          <div data-testid={testIds.sources} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {sources.map((src) => (
              <Badge key={src} tone={SOURCE_TONE[src] ?? "slate"}>
                {src}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Short plain-language explanation */}
      {(row.why_this_status || row.notes) && (
        <p data-testid={testIds.why} style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          {row.why_this_status || row.notes}
        </p>
      )}

      {/* Evidence rows grouped by proof source */}
      {groups.length > 0 && (
        <div data-testid={testIds.groupsWrapper} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {groups.map((group) => (
            <div
              key={group.source}
              data-testid={testIds.group}
              data-source-type={group.source}
              style={{ display: "flex", flexDirection: "column", gap: 4 }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Badge tone={SOURCE_TONE[group.source] ?? "slate"}>{group.source}</Badge>
              </div>
              <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
                {group.traces.map((t) => (
                  <li key={t.trace_id} style={{ fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.45, overflowWrap: "anywhere" }}>
                    {t.safe_summary}{" "}
                    <a
                      href={`#${t.evidence_anchor}`}
                      data-testid={testIds.jump}
                      style={{ fontSize: 11, color: TOKEN.indigo, textDecoration: "none", whiteSpace: "nowrap" }}
                    >
                      {matrixTraceLabel(t)} →
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {/* Not assessed: state what is missing rather than implying support */}
      {notAssessed && (
        <p data-testid={testIds.notAssessed} style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          No proof source in this project has been attached to this skill yet — it is a claim pending
          more evidence.
        </p>
      )}

      {/* Limitations — what this evidence does NOT prove */}
      {limitations.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
            Limitations
          </Mono>
          <ul data-testid={testIds.limitations} style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 2 }}>
            {limitations.map((line, i) => (
              <li key={i} style={{ fontSize: 11, color: TOKEN.muted }}>
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {row.recruiter_can_verify && (
        <p data-testid={testIds.verify} style={{ fontSize: 11, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
          {row.recruiter_can_verify}
        </p>
      )}

      {/* CTA into the surface-appropriate full Skill Report. */}
      {skillHref &&
        (renderSkillLink ? (
          renderSkillLink(skillHref, skillCtaLabel)
        ) : (
          <div>
            <a
              href={skillHref}
              data-testid={testIds.skillCta}
              style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
            >
              {skillCtaLabel}
            </a>
          </div>
        ))}
    </div>
  )
}

/** One compact proof-source stat tile for the Project Evidence Summary grid. */
export function EvidencePackageStat({ label, value, tone }: { label: string; value: string; tone: BadgeTone }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: TOKEN.bg,
        display: "flex",
        flexDirection: "column",
        gap: 6,
        minWidth: 0,
      }}
    >
      <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
        {label}
      </Mono>
      <Badge tone={tone}>{value}</Badge>
    </div>
  )
}

/** The canonical Project Evidence Summary grid (proof sources attached). */
export function EvidenceSummaryGrid({
  pkg,
  testId,
}: {
  pkg: {
    github_proof_attached: boolean
    documents_count: number
    website_proofs_count: number
    project_defense_completed: boolean
    video_defense_recorded: boolean
    video_evidence_chip_count: number
  }
  testId?: string
}) {
  return (
    <div
      data-testid={testId}
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
        gap: 10,
      }}
    >
      <EvidencePackageStat
        label="GitHub Proof"
        value={pkg.github_proof_attached ? "Attached" : "Not attached"}
        tone={pkg.github_proof_attached ? "emerald" : "slate"}
      />
      <EvidencePackageStat
        label="Documents"
        value={pkg.documents_count > 0 ? `${pkg.documents_count} attached` : "None"}
        tone={pkg.documents_count > 0 ? "emerald" : "slate"}
      />
      <EvidencePackageStat
        label="Website Proof"
        value={pkg.website_proofs_count > 0 ? `${pkg.website_proofs_count} attached` : "Not attached"}
        tone={pkg.website_proofs_count > 0 ? "emerald" : "slate"}
      />
      <EvidencePackageStat
        label="Project Defense"
        value={pkg.project_defense_completed ? "Completed" : "Not completed"}
        tone={pkg.project_defense_completed ? "emerald" : "slate"}
      />
      <EvidencePackageStat
        label="Video Defense"
        value={pkg.video_defense_recorded ? "Recorded" : "Not recorded"}
        tone={pkg.video_defense_recorded ? "emerald" : "slate"}
      />
      <EvidencePackageStat
        label="Video Evidence Chips"
        value={`${pkg.video_evidence_chip_count}`}
        tone={pkg.video_evidence_chip_count > 0 ? "emerald" : "slate"}
      />
    </div>
  )
}

/** Canonical in-page jump navigation (pill links). */
export function ReportJumpNav({ items, testId = "report-jump-nav" }: { items: { href: string; label: string }[]; testId?: string }) {
  return (
    <nav data-testid={testId} style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {items.map((item) => (
        <a
          key={item.href}
          href={item.href}
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: TOKEN.indigo,
            textDecoration: "none",
            padding: "4px 10px",
            borderRadius: 999,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
          }}
        >
          {item.label}
        </a>
      ))}
    </nav>
  )
}

const directLinkStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "8px 12px",
  borderRadius: 8,
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.indigo,
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
}

/**
 * Canonical "Direct Links" body: a public GitHub repo (only when genuinely
 * public + safe) and live site targets. Returns null when nothing is safely
 * linkable, so a surface never advertises an empty verification section.
 */
export function DirectLinksBody({
  repoUrl,
  liveLinks,
  repoTestId,
  liveTestId,
}: {
  repoUrl: string | null
  liveLinks: string[]
  repoTestId: string
  liveTestId: string
}) {
  if (!repoUrl && liveLinks.length === 0) return null
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {repoUrl && (
        <a data-testid={repoTestId} href={repoUrl} target="_blank" rel="noreferrer" style={directLinkStyle}>
          🐙 View public repository
        </a>
      )}
      {liveLinks.map((url) => (
        <a key={url} data-testid={liveTestId} href={url} target="_blank" rel="noreferrer" style={directLinkStyle}>
          🌐 Open live site
        </a>
      ))}
    </div>
  )
}

/**
 * Compute the safely-linkable targets for the Direct Links section — the ONE
 * shared truth gate: repo link only when the GitHub Proof says the repo is
 * public AND the URL passes the safe-public-url check; live links from the
 * deployed URL + website proof targets, deduped, safe-only.
 */
export function safeDirectLinks(report: {
  github_proof?: { repo_is_public?: boolean; repo_url?: string | null; disclosure?: string | null } | null
  deployed_url?: string | null
  website_proofs: { target_website: string }[]
}): { repoUrl: string | null; liveLinks: string[] } {
  // Candidate disclosure gate: a summary-only GitHub disclosure never links
  // the repository, even if a URL somehow arrives in the payload.
  const repoAccessShared = report.github_proof?.disclosure !== "summary"
  const repoUrl =
    repoAccessShared && report.github_proof?.repo_is_public && isSafePublicUrl(report.github_proof.repo_url ?? null)
      ? (report.github_proof.repo_url as string)
      : null
  const websiteTargets = report.website_proofs.map((w) => w.target_website).filter(isSafePublicUrl)
  const liveLinks = Array.from(
    new Set([report.deployed_url ?? null, ...websiteTargets].filter(isSafePublicUrl) as string[]),
  )
  return { repoUrl, liveLinks }
}

/**
 * Canonical GitHub Proof block for the "Evidence by Source" section, with the
 * three honest truth states:
 *   1. Public repo → repo identity as a clickable link.
 *   2. Proof attached, repo private → identity + explicit private-repo label.
 *   3. No GitHub Proof → explicit "not attached" (never a repo identity that
 *      looks like an available repository).
 */
export function GithubProofBlock({
  githubProof,
  notAttachedNote = "GitHub Proof not attached — no verified repository for this project.",
  linkTestId = "github-proof-repo-link",
}: {
  githubProof:
    | {
        repo_url?: string | null
        repo_owner?: string | null
        repo_name?: string | null
        repo_is_public?: boolean
        public_safe_summary?: string | null
        detected_skills?: string[]
        status?: string | null
        disclosure?: string | null
      }
    | null
    | undefined
  notAttachedNote?: string
  linkTestId?: string
}) {
  if (!githubProof) {
    return (
      <p data-testid="github-proof-not-attached" style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>
        {notAttachedNote}
      </p>
    )
  }
  // Candidate disclosure: summary-only GitHub evidence renders the verified
  // summary with NO repository identity or link — an intentional sharing
  // choice, never an error state.
  if (githubProof.disclosure === "summary") {
    return (
      <div data-testid="github-proof-summary-disclosure" style={{ marginTop: 4, minWidth: 0 }}>
        <p style={{ fontSize: 12.5, color: TOKEN.inkSoft, margin: "0 0 4px", lineHeight: 1.5 }}>
          Verified GitHub evidence summary — repository access is not enabled by the candidate.
        </p>
        {githubProof.public_safe_summary && (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 6px" }}>{githubProof.public_safe_summary}</p>
        )}
        {(githubProof.detected_skills?.length ?? 0) > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {githubProof.detected_skills!.map((skill) => (
              <Badge key={skill} tone="slate">
                {skill}
              </Badge>
            ))}
          </div>
        )}
      </div>
    )
  }
  const identity =
    githubProof.repo_owner && githubProof.repo_name
      ? `${githubProof.repo_owner}/${githubProof.repo_name}`
      : githubProof.repo_url ?? "Repository"
  const openable = Boolean(githubProof.repo_is_public) && isSafePublicUrl(githubProof.repo_url ?? null)
  return (
    <div style={{ marginTop: 4, minWidth: 0 }}>
      <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "0 0 4px", overflowWrap: "anywhere" }}>
        {openable ? (
          <a
            data-testid={linkTestId}
            href={githubProof.repo_url as string}
            target="_blank"
            rel="noreferrer"
            style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
          >
            {identity} ↗
          </a>
        ) : (
          <>
            {identity}{" "}
            <Badge tone="slate">Private repository — analyzed by the GitHub Proof scanner, not publicly openable</Badge>
          </>
        )}
        {githubProof.status ? ` — ${githubProof.status}` : ""}
      </p>
      {githubProof.public_safe_summary && (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 6px" }}>{githubProof.public_safe_summary}</p>
      )}
      {(githubProof.detected_skills?.length ?? 0) > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {githubProof.detected_skills!.map((skill) => (
            <Badge key={skill} tone="slate">
              {skill}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
