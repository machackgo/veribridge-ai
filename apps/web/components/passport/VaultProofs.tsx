"use client"

import { useState, type ReactNode } from "react"
import Link from "next/link"

import {
  fallbackSkillSlug,
  isSafePublicUrl,
  PROOF_SOURCE_RELATIONSHIP,
  skillReportPath,
  type ProofAttachmentEntry,
  type ProofAttachmentOverview,
  type SkillProofSynthesisStatement,
  type SkillProofSynthesisUnlinkedItem,
  type SkillReport,
  type SkillReportDefenseGroup,
  type SkillReportDocumentCorrelation,
  type SkillReportEvidenceItem,
  type SkillReportProjectChain,
  type SkillReportStandaloneGitHubGroup,
  type SkillReportStandaloneGitHubRow,
  type SkillSynthesisResult,
  type VaultProofItem,
  type VaultSkillGroup,
  type VaultSkillPreview,
  type VaultSkillSummary,
} from "@/lib/vbr-api"
import { Badge, Mono, TOKEN, type BadgeTone } from "./shared"
import { WebsiteRuntimeInspectionCard } from "./WebsiteRuntimeInspectionCard"
import { DocumentProofInspectionCard } from "./DocumentProofInspectionCard"
import { ProjectDefenseInspectionSection } from "./ProjectDefenseInspectionCard"
import { EvidenceRelationshipBadge, EvidenceTierSection } from "./ProofRelationshipGuide"
import {
  EvidenceLimitations,
  ProjectContextEvidenceList,
  ProofInspectActions,
  SkillEvidenceThesis,
  SkillProofMatrix,
  UnmappedProofNotice,
  VaultSuggestedEvidenceList,
  type SkillReportIntelligenceContext,
} from "./SkillReportIntelligence"

const PROOF_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "Skill Graph": "slate",
}

// The Passport's category headings, in display order (mirrors the backend's
// skill_normalization.CATEGORY_ORDER).
const CATEGORY_ORDER = [
  "AI / Machine Learning",
  "GenAI / LLM",
  "MLOps / Deployment",
  "Backend / APIs",
  "Frontend",
  "Data / Analytics",
  "Database",
  "Cloud / DevOps",
  "Programming Language",
  "Security / Privacy",
  "Product / System Design",
  "Other",
]

// ── Safe link helper ──────────────────────────────────────────────────────────

function SafeLink({ url, label }: { url?: string | null; label: string }) {
  if (!url || !isSafePublicUrl(url)) return null
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="evidence-public-link"
      style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "underline", wordBreak: "break-all" }}
    >
      {label}
    </a>
  )
}

// ── Vault proof card (used by the per-project "Other student proofs") ──────────

/**
 * One safe Student Proof Vault item: its source badge, a clear "attached" vs
 * "not attached to a VBR project" marker, the safe location/summary. Vault items
 * never carry raw evidence; we only render the already-sanitized fields.
 */
export function VaultProofCard({ proof }: { proof: VaultProofItem }) {
  return (
    <div
      data-testid="vault-proof"
      data-proof-type={proof.proof_type}
      data-attached={proof.is_attached_to_project ? "true" : "false"}
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
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={PROOF_TONE[proof.proof_type] ?? "slate"}>{proof.proof_type}</Badge>
        {proof.is_attached_to_project ? (
          <span data-testid="vault-attached-badge">
            <Badge tone="emerald">Attached to a project</Badge>
          </span>
        ) : (
          <span data-testid="vault-unattached-badge">
            <Badge tone="amber">Not attached to a VBR project</Badge>
          </span>
        )}
        {proof.safe_location && (
          <Mono data-testid="vault-proof-location" style={{ fontSize: 11, color: TOKEN.muted }}>
            📍 {proof.safe_location}
          </Mono>
        )}
      </div>

      {proof.title && <div style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>{proof.title}</div>}

      {proof.safe_summary && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{proof.safe_summary}</p>
      )}
      {proof.safe_snippet && (
        <p
          data-testid="vault-proof-snippet"
          style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}
        >
          “{proof.safe_snippet}”
        </p>
      )}

      {proof.limitation && (
        <div style={{ fontSize: 11, color: TOKEN.muted }}>
          <strong style={{ color: TOKEN.inkSoft }}>Limitation: </strong>
          {proof.limitation}
        </div>
      )}
    </div>
  )
}

/** One skill group of vault proofs: the skill, an attached/unattached count, and its proof cards. */
export function VaultSkillGroupCard({ group }: { group: VaultSkillGroup }) {
  return (
    <div data-testid="vault-skill-group" data-skill={group.skill} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>{group.skill}</span>
        {group.attached_count > 0 && <Badge tone="emerald">{group.attached_count} attached</Badge>}
        {group.has_unattached && (
          <span data-testid="vault-group-unattached">
            <Badge tone="amber">{group.unattached_count} not attached</Badge>
          </span>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {group.proofs.map((proof) => (
          <VaultProofCard key={`${proof.source_table}-${proof.source_id}-${proof.skill_name ?? ""}`} proof={proof} />
        ))}
      </div>
    </div>
  )
}

/**
 * The skill-grouped Student Proof Vault list, used by the per-project report's
 * "Other student proofs for related skills" section. Renders nothing when empty.
 */
export function VaultProofList({ groups }: { groups?: VaultSkillGroup[] | null }) {
  if (!groups || groups.length === 0) return null
  return (
    <div data-testid="vault-proof-list" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {groups.map((group) => (
        <VaultSkillGroupCard key={group.skill} group={group} />
      ))}
    </div>
  )
}

/**
 * Compact "Other student proofs" rows for the per-project report (Section J):
 * one row per matched skill with attached/unattached counts, proof-source
 * counts, and a link to the SEPARATE Skill Report — never a full evidence dump.
 */
export function VaultSkillLinkList({ groups }: { groups?: VaultSkillGroup[] | null }) {
  if (!groups || groups.length === 0) return null
  return (
    <div data-testid="vault-skill-link-list" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {groups.map((group) => {
        const slug = fallbackSlug(group.skill)
        const counts = new Map<string, number>()
        for (const p of group.proofs) counts.set(p.proof_type, (counts.get(p.proof_type) ?? 0) + 1)
        return (
          <div
            key={group.skill}
            data-testid="vault-skill-link"
            data-skill={group.skill}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              justifyContent: "space-between",
              padding: "10px 12px",
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 8,
              background: "#fff",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>{group.skill}</span>
              {[...counts.entries()].map(([src, n]) => (
                <Badge key={src} tone={PROOF_TONE[src] ?? "slate"}>
                  {src}: {n}
                </Badge>
              ))}
              {group.has_unattached && (
                <span data-testid="vault-unattached-badge">
                  <Badge tone="amber">{group.unattached_count} not attached to a VBR project</Badge>
                </span>
              )}
            </div>
            <Link
              href={skillReportPath(slug)}
              data-testid="other-proof-skill-report-link"
              style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none", whiteSpace: "nowrap" }}
            >
              View Skill Report →
            </Link>
          </div>
        )
      })}
    </div>
  )
}

// ── Layer 2: Skill Report — actual stored evidence, grouped by source ─────────

function statusTone(status: string): BadgeTone {
  if (status === "Demonstrated") return "emerald"
  if (status === "Evidence observed" || status === "Partially demonstrated") return "sky"
  if (status === "Needs review" || status === "Not assessed") return "amber"
  return "slate"
}

/** A safe code snippet block for precise GitHub evidence. */
function GitHubSnippet({ snippet }: { snippet: string }) {
  return (
    <pre
      data-testid="github-snippet"
      style={{
        fontSize: 11,
        background: TOKEN.bg,
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 6,
        padding: 8,
        margin: 0,
        overflowX: "auto",
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {snippet}
    </pre>
  )
}

/**
 * GitHub evidence rendered from the backend's explicit ``display_mode``:
 *
 * * ``code_line`` + ``has_precise_line_evidence`` + STRONG grade → a "Precise
 *   code evidence" badge, the file/function/line location, the safe snippet, and
 *   a "View code lines →" link to the exact ``github_line_url`` (never falls
 *   back to the repo URL unless the line URL is missing).
 * * ``code_line`` with a WEAK or missing grade → a "Needs review —
 *   repository-level signal" badge that KEEPS the safe file/line location, the
 *   descriptive block label (``code_block_purpose_label``, else
 *   ``code_role_label``, else a grade-derived fallback), the short safe purpose
 *   summary when present, and the "View code lines →" link — inspectable, but
 *   never implementation proof.
 * * ``repo_level`` → a "Repo-level support only" badge, the repo name, a clear
 *   limitation, and a "View repository →" link to ``repo_url`` — NO snippet, NO
 *   line range, and never implies precise implementation proof.
 * * legacy payloads with no ``display_mode`` keep the prior heuristic.
 */
function GitHubEvidence({ item, ghLocation }: { item: SkillReportEvidenceItem; ghLocation: string | null }) {
  // A code_line row only renders as "Precise code evidence" when its quality grade
  // is explicitly STRONG (implementation_body / supporting_logic). It FAILS CLOSED:
  // any WEAK grade (import/docstring/config/route-decorator/fallback) AND any
  // MISSING / ungraded grade render as a conservative "Needs review —
  // repository-level signal" that keeps the safe file/line location, the
  // descriptive role label ("Documentation / usage header", …) and the "View
  // code lines" link — but never claims primary implementation proof.
  const grade = item.evidence_quality_grade
  const strongGrade = !!grade && STRONG_GITHUB_GRADES.has(grade)
  const isCodeLine = item.display_mode === "code_line" && item.has_precise_line_evidence === true
  const precise = isCodeLine && strongGrade
  const repoLevel = item.display_mode === "repo_level"
  const needsReview = isCodeLine && !strongGrade

  if (precise) {
    return (
      <>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span data-testid="github-precise-badge">
            <Badge tone="emerald">Precise code evidence</Badge>
          </span>
          {item.subskill_name && (
            <span data-testid="github-subskill">
              <Badge tone="indigo">{item.subskill_name}</Badge>
            </span>
          )}
        </div>
        {ghLocation && (
          <Mono data-testid="github-location" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
            {ghLocation}
          </Mono>
        )}
        {item.commit_sha && <Mono style={{ fontSize: 11, color: TOKEN.muted }}>commit {item.commit_sha}</Mono>}
        {item.selection_reason && (
          <div data-testid="github-selection-reason" style={{ fontSize: 11, color: TOKEN.muted }}>
            <strong style={{ color: TOKEN.inkSoft }}>Why selected: </strong>
            {item.selection_reason}
          </div>
        )}
        {item.safe_snippet && <GitHubSnippet snippet={item.safe_snippet} />}
        <SafeLink url={item.github_line_url ?? item.public_url} label="View code lines →" />
      </>
    )
  }

  if (repoLevel) {
    // Honest repo-level support: no snippet, no line range, no precise-proof claim.
    return (
      <>
        <span data-testid="github-repo-level-badge">
          <Badge tone="amber">Repo-level support only</Badge>
        </span>
        <SafeLink url={item.repo_url ?? item.public_url} label="View repository →" />
      </>
    )
  }

  if (needsReview) {
    // Weak-graded or ungraded precise line: fail closed. The exact location stays
    // inspectable — safe file/line label, descriptive role label ("Documentation /
    // usage header", "Imports / setup context", …) and the "View code lines" link —
    // but the row is clearly a repository-level signal, NOT validated primary /
    // precise implementation proof. No "Precise code evidence" badge, no snippet
    // framed as proof, and never the raw ``selection_reason`` (which can overclaim).
    return (
      <>
        <span data-testid="github-needs-review-badge">
          <Badge tone="amber">Needs review — repository-level signal</Badge>
        </span>
        <p
          data-testid="github-needs-review-note"
          style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
        >
          This code link is a repository-level signal and has not been validated as primary implementation proof.
        </p>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
          {ghLocation && (
            <Mono data-testid="github-location" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
              {ghLocation}
            </Mono>
          )}
          <span data-testid="github-code-role-label" style={{ fontSize: 11, color: TOKEN.muted }}>
            {ghLocation ? "— " : ""}
            {weakRowDescriptiveLabel(item)}
          </span>
        </div>
        {item.code_block_purpose_summary && (
          <p
            data-testid="github-purpose-summary"
            style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
          >
            {item.code_block_purpose_summary}
          </p>
        )}
        {item.skill_relevance_label && (
          <p
            data-testid="github-skill-relevance"
            title={item.skill_relevance_summary || undefined}
            style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}
          >
            {item.skill_relevance_label}
          </p>
        )}
        <SafeLink
          url={item.github_line_url ?? item.public_url}
          label={item.github_line_url ? "View code lines →" : "View on GitHub →"}
        />
      </>
    )
  }

  // Legacy payload (no display_mode): keep the prior safe heuristic.
  return (
    <>
      {ghLocation && (
        <Mono data-testid="github-location" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
          {ghLocation}
        </Mono>
      )}
      {item.commit_sha && <Mono style={{ fontSize: 11, color: TOKEN.muted }}>commit {item.commit_sha}</Mono>}
      {item.safe_snippet && <GitHubSnippet snippet={item.safe_snippet} />}
      <SafeLink url={item.public_url} label={ghLocation ? "View on GitHub →" : "View repository →"} />
    </>
  )
}


/** One rich evidence item rendering the concrete stored fields for its source. */
function SkillEvidenceItem({ item }: { item: SkillReportEvidenceItem }) {
  const isGitHub = item.proof_type === "GitHub Proof"
  const isWebsite = item.proof_type === "Website Proof"
  const isDocument = item.proof_type === "Document Proof"

  // GitHub location label (file · lines / function).
  const ghLocation = (() => {
    if (!isGitHub || !item.file_path) return null
    let loc = item.file_path
    if (item.function_name) loc += ` · ${item.function_name}()`
    else if (item.line_start) loc += ` · lines ${item.line_start}${item.line_end && item.line_end !== item.line_start ? `-${item.line_end}` : ""}`
    return loc
  })()

  return (
    <div
      data-testid="skill-evidence-item"
      data-proof-type={item.proof_type}
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
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={PROOF_TONE[item.proof_type] ?? "slate"}>{item.proof_type}</Badge>
        {item.is_attached_to_project ? (
          <Badge tone="emerald">Attached</Badge>
        ) : (
          <span data-testid="vault-unattached-badge">
            <Badge tone="amber">Not attached to a VBR project</Badge>
          </span>
        )}
        {item.project_titles?.map((t, i) => (
          <span key={`${t}-${i}`} style={{ fontSize: 11, color: TOKEN.muted }}>
            {t}
          </span>
        ))}
      </div>

      {item.title && <div style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>{item.title}</div>}

      {/* C — GitHub: render from the backend's explicit display_mode (never
          re-inferred). "code_line" → precise file/line/function/snippet with a
          "View code lines" link; "repo_level" → an honest repo-level card (no
          snippet/line range) with a "View repository" link + clear limitation. */}
      {isGitHub && <GitHubEvidence item={item} ghLocation={ghLocation} />}

      {/* D — Website: prefer the structured, recruiter-inspectable Website
          Evidence Card (closed vocabularies + basis chips + honest screenshot
          status); legacy payloads without a card keep the prior summary rows. */}
      {isWebsite && item.website_evidence_card && (
        <WebsiteRuntimeInspectionCard card={item.website_evidence_card} fallbackUrl={item.public_url} />
      )}
      {isWebsite && !item.website_evidence_card && (
        <>
          {item.website_purpose_label && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span data-testid="website-purpose-label">
                <Badge tone="purple">{item.website_purpose_label}</Badge>
              </span>
            </div>
          )}
          {item.website_purpose_summary && (
            <p
              data-testid="website-purpose-summary"
              style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
            >
              {item.website_purpose_summary}
            </p>
          )}
          {item.website_skill_relevance_label && (
            <p
              data-testid="website-skill-relevance"
              title={item.website_skill_relevance_summary || undefined}
              style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}
            >
              {item.website_skill_relevance_label}
            </p>
          )}
          {item.workflow_summary && (
            <p data-testid="website-workflow" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
              <strong>Workflow: </strong>
              {item.workflow_summary}
            </p>
          )}
          {item.workflow_steps?.length > 0 && (
            <div data-testid="website-steps" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
              <strong>Demonstrated: </strong>
              {item.workflow_steps.join(" → ")}
            </div>
          )}
          {item.ocr_summary && (
            <p data-testid="website-ocr" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              <strong>On-screen text: </strong>
              {item.ocr_summary}
            </p>
          )}
          {item.dom_summary && (
            <p data-testid="website-dom" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              <strong>Page content: </strong>
              {item.dom_summary}
            </p>
          )}
          {item.visual_summary && (
            <p data-testid="website-visual" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              <strong>Visual analysis: </strong>
              {item.visual_summary}
            </p>
          )}
          {item.live_check && (
            <div data-testid="website-live" style={{ fontSize: 11, color: TOKEN.muted }}>
              <strong>Live check: </strong>
              {(item.live_check as { is_reachable?: boolean }).is_reachable ? "reachable" : "checked"}
            </div>
          )}
          <SafeLink url={item.public_url} label="Open live site →" />
        </>
      )}

      {/* E — Document: page / section / citation / snippet */}
      {isDocument && (
        <>
          {(item.page_number || item.citation) && (
            <Mono data-testid="document-citation" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
              {item.page_number ? `Page ${item.page_number}` : ""}
              {item.page_number && item.citation ? " · " : ""}
              {item.citation ?? ""}
            </Mono>
          )}
          {item.safe_snippet && (
            <p data-testid="document-snippet" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
              “{item.safe_snippet}”
            </p>
          )}
          <div style={{ fontSize: 11, color: TOKEN.muted }}>
            The document itself is kept private — only this safe citation is shown.
          </div>
        </>
      )}

      {/* F/G — Defense / Video: question / answer / timestamp */}
      {(item.proof_type === "Project Defense" || item.proof_type === "Video Evidence") && (
        <>
          {item.question_text && (
            <p data-testid="defense-question" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>
              <strong>Q: </strong>
              {item.question_text}
            </p>
          )}
          {item.answer_excerpt && (
            <p data-testid="defense-answer" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
              “{item.answer_excerpt}”
            </p>
          )}
          {item.timestamp_label && (
            <Mono data-testid="video-timestamp" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
              ⏱ {item.timestamp_label}
            </Mono>
          )}
        </>
      )}

      {item.safe_summary && !isWebsite && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{item.safe_summary}</p>
      )}
      {item.safe_location && !isGitHub && !isDocument && (
        <Mono style={{ fontSize: 11, color: TOKEN.muted }}>📍 {item.safe_location}</Mono>
      )}
      {/* The Website Runtime Inspection card renders its own Section 6
          limitation, so the row-level limitation is suppressed for a website
          proof that carries a card (avoids a duplicate limitation line). */}
      {item.limitation && !(isWebsite && item.website_evidence_card) && (
        <div style={{ fontSize: 11, color: TOKEN.muted }}>
          <strong style={{ color: TOKEN.inkSoft }}>Limitation: </strong>
          {item.limitation}
        </div>
      )}
    </div>
  )
}

function SkillReportSection({
  testId,
  title,
  items,
}: {
  testId: string
  title: string
  items: SkillReportEvidenceItem[]
}) {
  if (!items || items.length === 0) return null
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>{title}</h4>
      {items.map((item) => (
        <SkillEvidenceItem key={`${item.proof_type}-${item.source_id}`} item={item} />
      ))}
    </div>
  )
}

/**
 * The connected-chain GitHub section for LEGACY payloads that carry a flat
 * ``github_evidence`` list (no ``github_groups``). It FAILS CLOSED like the grouped
 * path: the section is titled "Code implementation" ONLY when at least one row is a
 * graded ``implementation_body``. When every row is ungraded / missing
 * ``evidence_quality_grade`` (or only weak-graded), the honest "GitHub code signals"
 * title is used with a conservative note — such repository-level links have not been
 * validated as primary implementation proof.
 */
function ConnectedFlatGitHubSection({ items }: { items: SkillReportEvidenceItem[] }) {
  if (!items || items.length === 0) return null
  const hasPrimary = items.some((r) => isImplementationBody(r.evidence_quality_grade))
  return (
    <div data-testid="chain-github" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
        {hasPrimary ? "Code implementation" : "GitHub code signals"}
      </h4>
      {!hasPrimary && (
        <p
          data-testid="chain-github-flat-no-primary"
          style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
        >
          These code links are repository-level signals and have not been validated as primary implementation proof.
        </p>
      )}
      {items.map((item) => (
        <SkillEvidenceItem key={`${item.proof_type}-${item.source_id}`} item={item} />
      ))}
    </div>
  )
}

/**
 * The grouped "Defense / video explanation" section: ONE concise explanation,
 * the combined cited moments/chips, a single limitation and the grouped count —
 * so repeated defense attempts never render as many near-identical cards.
 */
function DefenseGroupSection({ group }: { group: SkillReportDefenseGroup }) {
  if (!group || group.grouped_count === 0) return null
  return (
    <div data-testid="chain-defense" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Defense / video explanation</h4>
        {group.grouped_count > 1 && (
          <span data-testid="defense-grouped-count">
            <Badge tone="slate">{group.grouped_count} defense moments grouped</Badge>
          </span>
        )}
      </div>
      {group.explanation && (
        <p data-testid="defense-explanation" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          {group.explanation}
        </p>
      )}
      {group.moments.length > 0 && (
        <div data-testid="defense-moments" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {group.moments.map((m, i) => (
            <div
              key={`${m.source_id}-${m.timestamp_label ?? ""}-${m.question_text ?? ""}-${i}`}
              data-testid="defense-moment"
              style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}
            >
              {m.timestamp_label && <Mono style={{ fontSize: 11, color: TOKEN.indigo }}>⏱ {m.timestamp_label}</Mono>}
              <span style={{ fontSize: 12, color: TOKEN.ink, fontWeight: 600 }}>{m.label}</span>
              {m.short_summary && <span style={{ fontSize: 12, color: TOKEN.inkSoft }}>— {m.short_summary}</span>}
            </div>
          ))}
        </div>
      )}
      {group.limitation && (
        <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>{group.limitation}</p>
      )}
    </div>
  )
}

/**
 * A document shown as connected *corroboration*: it answers "what does this
 * document corroborate?" — never a raw line-by-line dump. The raw document is
 * always private; only a safe citation/snippet is shown.
 */
function DocumentCorrelationCard({ corr }: { corr: SkillReportDocumentCorrelation }) {
  // Prefer the skill-specific Document Proof inspection card when the backend
  // supplied one (what the document says, where, and why it supports THIS skill).
  // Fall back to the compact inline corroboration layout for legacy payloads.
  if (corr.inspection_card) {
    return (
      <div data-testid="document-correlation">
        <DocumentProofInspectionCard card={corr.inspection_card} />
      </div>
    )
  }
  return (
    <div
      data-testid="document-correlation"
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
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={PROOF_TONE["Document Proof"]}>Document Proof</Badge>
        <Badge tone="amber">{corr.support_label || "Supporting evidence"}</Badge>
        {corr.corroborates && (
          <span data-testid="document-corroborates">
            <Badge tone="slate">Corroborates: {corr.corroborates}</Badge>
          </span>
        )}
        {corr.correlation_confidence && (
          <span data-testid="document-confidence" style={{ fontSize: 11, color: TOKEN.muted }}>
            {corr.correlation_confidence}
          </span>
        )}
      </div>
      {corr.document_title && <div style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>{corr.document_title}</div>}
      {(corr.page_number || corr.citation || corr.figure_reference) && (
        <Mono data-testid="document-citation" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
          {corr.page_number ? `Page ${corr.page_number}` : ""}
          {corr.page_number && corr.citation ? " · " : ""}
          {corr.citation ?? ""}
          {corr.figure_reference ? `${corr.page_number || corr.citation ? " · " : ""}${corr.figure_reference}` : ""}
        </Mono>
      )}
      {corr.safe_snippet && (
        <p data-testid="document-snippet" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
          “{corr.safe_snippet}”
        </p>
      )}
      {(corr.why_supported || corr.reason) && (
        <p data-testid="document-why" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          {corr.why_supported || corr.reason}
        </p>
      )}
      {corr.document_access_note && (
        <div data-testid="document-access-note" style={{ fontSize: 11, color: corr.full_document_available ? TOKEN.inkSoft : TOKEN.muted }}>
          <strong style={{ color: TOKEN.inkSoft }}>🔒 </strong>
          {corr.document_access_note}
        </div>
      )}
      {corr.limitation && (
        <div style={{ fontSize: 11, color: TOKEN.muted }}>
          <strong style={{ color: TOKEN.inkSoft }}>Limitation: </strong>
          {corr.limitation}
        </div>
      )}
    </div>
  )
}

function DocumentCorrelations({
  testId,
  items,
  moreCount,
}: {
  testId: string
  items: SkillReportDocumentCorrelation[]
  moreCount: number
}) {
  if (!items || items.length === 0) return null
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Document corroboration</h4>
      {items.map((corr) => (
        <DocumentCorrelationCard key={`${corr.source_id}-${corr.page_number ?? ""}-${corr.safe_snippet ?? ""}`} corr={corr} />
      ))}
      {moreCount > 0 && (
        <span data-testid="document-more" style={{ fontSize: 11, color: TOKEN.muted }}>
          +{moreCount} more supporting document citation{moreCount === 1 ? "" : "s"}
        </span>
      )}
    </div>
  )
}

const SOURCE_TONE: Record<string, BadgeTone> = PROOF_TONE

/** Qualitative confidence tier → badge tone (never a numeric score). */
function tierTone(tier?: string): BadgeTone {
  if (tier === "Strongly corroborated") return "emerald"
  if (tier === "Corroborated") return "sky"
  if (tier === "Supporting evidence") return "indigo"
  if (tier === "Needs review") return "amber"
  return "slate"
}

// ── Audit-grade synthesis: evidence citation chips + claim cards ───────────────

// Normalized source_type (Evidence Normalization Engine) → recruiter-facing
// label + chip tone. Mirrors the per-proof PROOF_TONE so a citation chip reads
// the same as the proof card it points at.
const NORMALIZED_SOURCE_LABEL: Record<string, string> = {
  github: "GitHub",
  website: "Website",
  document: "Document",
  defense: "Defense",
  video: "Video",
  skill_graph: "Skill Graph",
}
const NORMALIZED_SOURCE_TONE: Record<string, BadgeTone> = {
  github: "indigo",
  website: "purple",
  document: "sky",
  defense: "emerald",
  video: "amber",
  skill_graph: "slate",
}

type ResolvedEvidence = { label: string; sourceType: string }
type EvidenceResolver = (id: string) => ResolvedEvidence | null

/** A safe one-line locator for a per-chain proof item (never a raw id/payload). */
function evidenceItemLabel(item: SkillReportEvidenceItem): string {
  if (item.file_path) {
    let loc = item.file_path
    if (item.function_name) loc += ` · ${item.function_name}()`
    else if (item.line_start) loc += ` · lines ${item.line_start}${item.line_end && item.line_end !== item.line_start ? `-${item.line_end}` : ""}`
    return loc
  }
  return item.safe_location || item.title || item.safe_summary || ""
}

/**
 * Resolve the evidence ids cited by a chain's ``synthesis_statements`` (which
 * reference that chain's own proof items) to a safe source + locator. Document
 * correlations carry no per-item id, so only the rendered proof items are mapped.
 */
function buildChainEvidenceResolver(chain: SkillReportProjectChain): EvidenceResolver {
  const map = new Map<string, ResolvedEvidence>()
  const add = (items: SkillReportEvidenceItem[] | undefined, sourceType: string) => {
    for (const item of items ?? []) {
      if (!item.source_id) continue
      map.set(item.source_id, { sourceType, label: evidenceItemLabel(item) })
    }
  }
  add(chain.github_evidence, "github")
  add(chain.website_evidence, "website")
  add(chain.defense_evidence, "defense")
  add(chain.video_evidence, "video")
  for (const art of chain.normalized_evidence ?? []) {
    if (!art.evidence_id) continue
    map.set(art.evidence_id, {
      sourceType: art.source_type,
      label: art.exact_location || art.source_label || NORMALIZED_SOURCE_LABEL[art.source_type] || "",
    })
  }
  return (id) => map.get(id) ?? null
}

/**
 * One audit citation chip for a single evidence id. Renders the *resolved* safe
 * source + locator — never the raw id (the underlying source_id may be private),
 * never a score. Falls back to a neutral "Cited evidence" chip when the id can't
 * be resolved to a safe label.
 */
function EvidenceCitationChip({ id, resolver }: { id: string; resolver?: EvidenceResolver }) {
  const resolved = resolver?.(id) ?? null
  const sourceType = resolved?.sourceType
  const tone = (sourceType && NORMALIZED_SOURCE_TONE[sourceType]) || "slate"
  const prefix = (sourceType && NORMALIZED_SOURCE_LABEL[sourceType]) || "Cited evidence"
  const detail = resolved?.label && resolved.label !== prefix ? resolved.label : ""
  return (
    <span data-testid="evidence-citation-chip" data-source-type={sourceType ?? "unknown"}>
      <Badge tone={tone}>{detail ? `${prefix} · ${detail}` : prefix}</Badge>
    </span>
  )
}

/** The citation chips row for a set of evidence ids. Renders nothing when empty. */
function EvidenceCitations({ ids, resolver }: { ids: string[]; resolver?: EvidenceResolver }) {
  if (!ids || ids.length === 0) return null
  return (
    <div data-testid="evidence-citations" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <span style={{ fontSize: 11, color: TOKEN.muted }}>Cited evidence:</span>
      {ids.map((id, i) => (
        <EvidenceCitationChip key={`${id}-${i}`} id={id} resolver={resolver} />
      ))}
    </div>
  )
}

/** A calm, audit-grade empty state (no data yet / nothing public-safe to show). */
function EmptyState({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <div
      data-testid={testId}
      style={{
        fontSize: 12,
        color: TOKEN.muted,
        fontStyle: "italic",
        padding: "10px 12px",
        border: `1px dashed ${TOKEN.line}`,
        borderRadius: 8,
        background: TOKEN.bg,
      }}
    >
      {children}
    </div>
  )
}

/**
 * One evidence-cited synthesis statement for a chain: the plain-language
 * statement with the audit citation chips for the exact evidence it was built
 * from. Statements with no citations are not shown (every shown claim must cite).
 */
function SynthesisStatementList({
  statements,
  resolver,
}: {
  statements?: SkillProofSynthesisStatement[]
  resolver?: EvidenceResolver
}) {
  const cited = (statements ?? []).filter((s) => s.text && s.evidence_ids?.length > 0)
  if (cited.length === 0) return null
  return (
    <div data-testid="chain-synthesis-statements" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {cited.map((s, i) => (
        <div
          key={`${s.text}-${i}`}
          data-testid="chain-synthesis-statement"
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{s.text}</p>
          <EvidenceCitations ids={s.evidence_ids} resolver={resolver} />
        </div>
      ))}
    </div>
  )
}

/**
 * The compact "VeriBridge agent summary" block. The detailed, evidence-cited
 * synthesis is embedded PER CHAIN above (each chain card carries its own
 * ``synthesis_result`` / cited statements), so this section is intentionally just
 * a short recruiter-facing summary — one line per synthesized chain — never the
 * old wall of repeated claim cards with repeated limitations and duplicated
 * GitHub citation chips. ``publicSafe`` drops any non-public-safe result.
 */
function AgentSummary({ results, publicSafe }: { results: SkillSynthesisResult[]; publicSafe: boolean }) {
  const lines: { title: string; summary: string }[] = []
  const seen = new Set<string>()
  for (const r of results) {
    if (publicSafe && !r.public_safe) continue
    const summary = (r.overall_summary || "").trim()
    if (!summary) continue
    const title = (r.project_title || r.canonical_skill_name || "").trim()
    const key = `${title}::${summary}`.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    lines.push({ title, summary })
  }
  if (lines.length === 0) return null
  return (
    <div data-testid="skill-report-agent-summary" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {lines.map((l, i) => (
        <p key={`${l.summary}-${i}`} style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          {l.title && <strong style={{ color: TOKEN.ink }}>{l.title}: </strong>}
          {l.summary}
        </p>
      ))}
    </div>
  )
}

/**
 * The proof-source relationship line for a connected chain: how each present
 * source relates to the claim, using the neutral, evidence-strength-safe
 * vocabulary in PROOF_SOURCE_RELATIONSHIP (source is *attached for review* —
 * never inferring implementation/authorship/time-based proof from presence
 * alone). Closed vocabulary, labels only.
 */
function ChainSourceRelationships({ sources }: { sources: string[] }) {
  const phrases = [...new Set(sources)]
    .map((src) => PROOF_SOURCE_RELATIONSHIP[src])
    .filter((p): p is string => Boolean(p))
  if (phrases.length === 0) return null
  return (
    <p data-testid="chain-source-relationships" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
      {phrases.join(" · ")}
    </p>
  )
}

/** One project's connected proof chain: artifacts + corroborating documents. */
function ProjectChainCard({ chain }: { chain: SkillReportProjectChain }) {
  const evidenceResolver = buildChainEvidenceResolver(chain)
  return (
    <div
      data-testid="skill-report-chain"
      data-project={chain.project_id ?? "standalone"}
      data-attached={chain.attached ? "true" : "false"}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "12px 14px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 10,
        background: TOKEN.bg,
      }}
    >
      {chain.attached && (
        <Mono
          data-testid="chain-connected-project-label"
          style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}
        >
          Connected project
        </Mono>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: TOKEN.ink }}>{chain.project_title}</span>
        {chain.confidence_tier && (
          <span data-testid="chain-confidence-tier">
            <Badge tone={tierTone(chain.confidence_tier)}>{chain.confidence_tier}</Badge>
          </span>
        )}
        <Badge tone={chain.attached ? "emerald" : "amber"}>{chain.attached_status}</Badge>
        {chain.sources.map((src, i) => (
          <Badge key={`${src}-${i}`} tone={SOURCE_TONE[src] ?? "slate"}>
            {src}
          </Badge>
        ))}
        {chain.subskills?.map((sub, i) => (
          <span key={`${sub}-${i}`} data-testid="chain-subskill">
            <Badge tone="indigo">{sub}</Badge>
          </span>
        ))}
        {(chain.collapsed_project_count ?? 1) > 1 && (
          <span data-testid="chain-collapsed-note">
            <Badge tone="slate">
              {chain.collapsed_project_count} repeated attempts collapsed
            </Badge>
          </span>
        )}
        {(chain.grouped_attempt_count ?? 1) > 1 && (
          <span data-testid="chain-grouped-note">
            <Badge tone="slate">
              {chain.grouped_attempt_count} related project attempts grouped
            </Badge>
          </span>
        )}
      </div>
      {/* How each proof source relates to this skill claim (safe labels only). */}
      <ChainSourceRelationships sources={chain.sources} />
      {chain.evidence_chain_summary && (
        <p data-testid="chain-summary" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          {chain.evidence_chain_summary}
        </p>
      )}
      {chain.synthesis_result && (
        <p
          data-testid="chain-synthesis-result"
          style={{ fontSize: 12, color: TOKEN.ink, margin: 0, lineHeight: 1.5, fontWeight: 600 }}
        >
          {chain.synthesis_result}
        </p>
      )}
      {chain.why_linked && (
        <p data-testid="chain-why-linked" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          <strong style={{ color: TOKEN.inkSoft }}>Why these sources are linked: </strong>
          {chain.why_linked}
        </p>
      )}
      {/* Evidence-cited synthesis statements: each plain-language statement shows
          the exact evidence chips it was built from (never an opaque id). */}
      <SynthesisStatementList statements={chain.synthesis_statements} resolver={evidenceResolver} />
      {/* C — GitHub: prefer the repository-grouped projection (one grouped block
          per canonical owner/repo with compact file/line rows), matching the
          standalone GitHub model. Fall back to the flat per-item list for older
          payloads that don't carry ``github_groups``. */}
      {(chain.github_groups?.length ?? 0) > 0 ? (
        <ConnectedGitHubGroups groups={chain.github_groups} />
      ) : (
        <ConnectedFlatGitHubSection items={chain.github_evidence} />
      )}
      {(chain.website_evidence?.length ?? 0) > 0 && chain.website_connection_note && (
        <p
          data-testid="chain-website-note"
          style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
        >
          <strong style={{ color: TOKEN.inkSoft }}>How the website connects: </strong>
          {chain.website_connection_note}
        </p>
      )}
      <SkillReportSection testId="chain-website" title="Runtime / website behavior" items={chain.website_evidence} />
      {chain.defense_group && chain.defense_group.grouped_count > 0 ? (
        <DefenseGroupSection group={chain.defense_group} />
      ) : (
        <>
          <SkillReportSection testId="chain-defense" title="Defense / video explanation" items={chain.defense_evidence} />
          <SkillReportSection testId="chain-video" title="Video evidence" items={chain.video_evidence} />
        </>
      )}
      {/* First-class Project Defense inspection: per-question explanation /
          corroboration evidence for this chain's skill (never implementation proof). */}
      <ProjectDefenseInspectionSection cards={chain.project_defense_inspection} testId="chain-defense-inspection" />
      <DocumentCorrelations
        testId="chain-documents"
        items={chain.document_correlations}
        moreCount={chain.document_more_count}
      />
      {chain.limitations.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11, color: TOKEN.muted }}>
          {chain.limitations.map((l, i) => (
            <li key={`${l}-${i}`}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── GitHub evidence quality bands ─────────────────────────────────────────────
//
// Only ``implementation_body`` and ``supporting_logic`` are STRONG grades fit to
// render as real code evidence. Every other grade (config/comment/docstring/
// import/route-decorator/repo-fallback) is a WEAK repository-level signal that
// must never appear under "Code implementation" or carry a "Precise code
// evidence" badge — it is surfaced only as a collapsed "Needs review /
// repository-level signals" summary.
const STRONG_GITHUB_GRADES = new Set(["implementation_body", "supporting_logic"])

// Skill-relevance keys (closed backend vocabulary) that mark a block as the
// REPORT's own implementation work. An implementation_body row may only sit
// under "Primary implementation evidence" when its relevance agrees — a
// cross-skill row (React UI code in a Machine Learning report), product-UI or
// deployment context can never render as this skill's primary proof, no matter
// how strong its grade. Rows WITHOUT a relevance key (older payloads) keep
// their grade-based placement.
const SKILL_IMPLEMENTATION_RELEVANCE = new Set(["direct_implementation", "supporting_implementation"])
// Relevance keys that POSITIVELY mark a block as another skill's code or
// non-code context — such rows are demoted to the Needs-review band even on a
// strong grade (mirrors the backend's non-skill-code exclusion set).
const NON_SKILL_CODE_RELEVANCE = new Set([
  "cross_skill_context",
  "product_ui_context",
  "deployment_context",
  "documentation_context",
  "setup_context",
])

/** True when a STRONG-graded row must be demoted to Needs review because its
 *  skill relevance says the code belongs to another skill / is context only. */
function isDemotedByRelevance(row: {
  evidence_quality_grade?: string | null
  skill_relevance_key?: string | null
}): boolean {
  const key = row.skill_relevance_key
  if (!key) return false // legacy payload without relevance → grade decides
  if (isImplementationBody(row.evidence_quality_grade)) {
    // Primary claims need the strict implementation allowlist.
    return !SKILL_IMPLEMENTATION_RELEVANCE.has(key)
  }
  if (row.evidence_quality_grade === "supporting_logic") {
    // Supporting claims are blocked only by a POSITIVE other-skill context.
    return NON_SKILL_CODE_RELEVANCE.has(key)
  }
  return false
}

// Conservative, grade-derived role labels for WEAK repository-level rows. A weak
// row must never echo its raw ``selection_reason`` (which can overclaim — e.g. "ML
// training call", "Cloud deployment command") because it was NOT validated as an
// implementation body. The backend now sends a role-aware ``code_role_label``
// ("Documentation / usage header", "Imports / setup context", "Deployment /
// serving context", …) describing what the block appears to be; this map is the
// fallback for stale payloads that carry only a grade. Either way the label is
// DESCRIPTIVE only — weak rows stay under Needs review and never promote.
const WEAK_GRADE_ROLE_LABEL: Record<string, string> = {
  comment_or_docstring: "Documentation / usage header",
  import_only: "Imports / setup context",
  config_or_constant: "Config / constants",
  route_decorator_only: "API route shell",
  repo_level_fallback: "Repository-level context",
}
// Preference order for the descriptive label on a WEAK row: the block-level
// ``code_block_purpose_label`` (the most specific safe explanation — "Documentation
// describing retraining pipeline", "Imports / dependency setup"), else the broader
// ``code_role_label``, else the conservative grade-derived fallback above. All
// three are closed backend vocabularies — never the raw ``selection_reason``.
function weakRowDescriptiveLabel(row: {
  code_block_purpose_label?: string | null
  code_role_label?: string | null
  evidence_quality_grade?: string | null
}): string {
  return (
    row.code_block_purpose_label ||
    row.code_role_label ||
    (row.evidence_quality_grade && WEAK_GRADE_ROLE_LABEL[row.evidence_quality_grade]) ||
    "Repository-level context"
  )
}

// Visible rows per quality band before a "+N more" control appears. Each band
// (primary / supporting / needs-review) caps independently, so a graded group can
// never render every row uncapped — and weak rows never surface above primary.
const GITHUB_BAND_CAP = 3

function isImplementationBody(grade?: string | null): boolean {
  return grade === "implementation_body"
}
/** A row with an explicit WEAK grade (config/comment/import/decorator/fallback).
 *  A missing/unknown grade is treated as NOT weak (older payloads keep their
 *  prior precise rendering rather than being demoted). */
function isWeakGitHubRow(row: { evidence_quality_grade?: string | null }): boolean {
  return !!row.evidence_quality_grade && !STRONG_GITHUB_GRADES.has(row.evidence_quality_grade)
}
function groupsHaveImplementationBody(groups?: SkillReportStandaloneGitHubGroup[] | null): boolean {
  // A cross-skill / context implementation body (relevance-demoted) does not let
  // the section claim "Code implementation" for THIS skill.
  return !!groups?.some((g) =>
    g.rows.some((r) => isImplementationBody(r.evidence_quality_grade) && !isDemotedByRelevance(r))
  )
}
/** Use the honest "GitHub code signals" title whenever NO group isolates a primary
 *  implementation body — whether the rows are weak-graded OR fully ungraded (legacy).
 *  Ungraded evidence fails closed too: without a validated implementation body the
 *  section must never claim "Code implementation" / precise "GitHub evidence".
 *  (Only reached with non-empty groups; the flat no-groups fallback is separate.) */
function useSignalsTitle(groups?: SkillReportStandaloneGitHubGroup[] | null): boolean {
  return !groupsHaveImplementationBody(groups)
}

/** One compact code-location row inside a standalone GitHub repository group.
 *  ``weak`` rows are repository-level signals — rendered muted, never framed as
 *  precise "View code lines" implementation proof. */
function StandaloneGitHubRowItem({ row, weak = false }: { row: SkillReportStandaloneGitHubRow; weak?: boolean }) {
  // Weak rows show the safest specific descriptive label — the block-level
  // purpose ("Documentation describing retraining pipeline", "Imports /
  // dependency setup"), else the broader role, else a grade-derived fallback —
  // never the raw ``selection_reason`` (which can overclaim). They still expose
  // the safe file/line label and a "View code lines" link so the location is
  // inspectable, but they are muted and never framed as primary implementation
  // proof. Strong rows keep their validated precise reason, falling back to the
  // purpose/role labels when no reason is stored. The short purpose summary
  // (a closed safe sentence, never code) rides as a hover tooltip so rows stay
  // compact and recruiter-readable.
  const reason = weak
    ? weakRowDescriptiveLabel(row)
    : row.selection_reason || row.code_block_purpose_label || row.code_role_label
  return (
    <div
      data-testid={weak ? "standalone-github-weak-row" : "standalone-github-row"}
      style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}
    >
      <Mono style={{ fontSize: 12, color: weak ? TOKEN.muted : TOKEN.inkSoft }}>{row.label}</Mono>
      {reason && (
        <span
          data-testid="github-row-purpose"
          title={row.code_block_purpose_summary || undefined}
          style={{ fontSize: 11, color: TOKEN.muted }}
        >
          — {reason}
        </span>
      )}
      {weak && row.skill_relevance_label && (
        // Compact skill-relevance helper on WEAK rows only ("Product UI context,
        // not Machine Learning implementation") — a closed backend template, so a
        // weak row honestly states its relation to the report's skill without
        // adding a paragraph per row. Strong rows keep their validated reason.
        <span
          data-testid="github-row-skill-relevance"
          title={row.skill_relevance_summary || undefined}
          style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}
        >
          · {row.skill_relevance_label}
        </span>
      )}
      <SafeLink
        url={row.github_line_url ?? row.public_url}
        label={weak && !row.github_line_url ? "View on GitHub →" : "View code lines →"}
      />
    </div>
  )
}

/** The "+N more code locations" / "Show fewer" toggle shared by every band. */
function RowMoreToggle({
  testId,
  expanded,
  moreCount,
  onToggle,
  noun = "code location",
}: {
  testId: string
  expanded: boolean
  moreCount: number
  onToggle: () => void
  noun?: string
}) {
  if (moreCount <= 0) return null
  return (
    <button
      type="button"
      data-testid={testId}
      aria-expanded={expanded}
      onClick={onToggle}
      style={{
        alignSelf: "flex-start",
        padding: 0,
        border: "none",
        background: "none",
        cursor: "pointer",
        fontSize: 11,
        color: TOKEN.indigo,
        fontWeight: 600,
      }}
    >
      {expanded
        ? `Show fewer ${noun}s`
        : `+${moreCount} more ${noun}${moreCount === 1 ? "" : "s"}`}
    </button>
  )
}

/**
 * A capped, expandable quality band (Primary / Supporting). Shows the first
 * ``GITHUB_BAND_CAP`` rows and a "+N more" control for the rest, so a graded group
 * never renders every strong row uncapped. Never renders weak rows — those go to
 * the Needs-review band below, so strong rows always sit above weak ones.
 */
function GitHubRowBand({
  testId,
  label,
  labelColor,
  rows,
}: {
  testId: string
  label: string
  labelColor: string
  rows: SkillReportStandaloneGitHubRow[]
}) {
  const [expanded, setExpanded] = useState(false)
  if (rows.length === 0) return null
  const moreCount = Math.max(0, rows.length - GITHUB_BAND_CAP)
  const visible = expanded ? rows : rows.slice(0, GITHUB_BAND_CAP)
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: labelColor }}>{label}</span>
      {visible.map((row, i) => (
        <StandaloneGitHubRowItem key={`${row.source_id}-${row.label}-${i}`} row={row} />
      ))}
      <RowMoreToggle testId={`${testId}-more`} expanded={expanded} moreCount={moreCount} onToggle={() => setExpanded((v) => !v)} />
    </div>
  )
}

/**
 * The "Needs review / repository-level signals" band for a repo's WEAK (and, in a
 * mixed group, ungraded) GitHub rows — imports, comments, configuration, endpoint
 * scaffolding, or unvalidated legacy lines. These are never primary implementation
 * proof, so they stay muted, carry an honest "Needs review" heading + limitation
 * note, and never claim precise code evidence — always below any primary/supporting
 * rows.
 *
 * Crucially, the first ``GITHUB_BAND_CAP`` rows are ALWAYS visible (they render even
 * in a static / PDF snapshot with no JS interaction), so a recruiter/student can
 * still inspect the weak code locations — each row keeps its safe file/line label
 * and a "View code lines" link. Any remaining rows collapse behind a
 * "+N more weak code locations" toggle.
 */
function WeakGitHubSignals({ rows }: { rows: SkillReportStandaloneGitHubRow[] }) {
  const [showAll, setShowAll] = useState(false)
  if (rows.length === 0) return null
  const moreCount = Math.max(0, rows.length - GITHUB_BAND_CAP)
  const visible = showAll ? rows : rows.slice(0, GITHUB_BAND_CAP)
  return (
    <div data-testid="github-weak-signals" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span data-testid="github-weak-heading" style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted }}>
        Needs review — {rows.length} weak/repository-level signal{rows.length === 1 ? "" : "s"}
      </span>
      <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
        Mostly imports, comments, configuration, endpoint scaffolding, or code for a different skill — not
        primary implementation proof for this skill.
      </p>
      {visible.map((row, i) => (
        <StandaloneGitHubRowItem key={`${row.source_id}-${row.label}-${i}`} row={row} weak />
      ))}
      <RowMoreToggle
        testId="github-weak-more"
        expanded={showAll}
        moreCount={moreCount}
        onToggle={() => setShowAll((v) => !v)}
        noun="weak code location"
      />
    </div>
  )
}

/**
 * One repository group: the repo, an attached/unattached marker, an optional
 * "View repository" link (public repos only), and the compact code-line rows — so
 * several lines from one repo read as a single grouped block instead of one
 * repeated full card per line. ``attached`` distinguishes a connected proof-chain
 * group (the chain IS attached to a VBR project) from a standalone group.
 */
function GitHubGroupCard({
  group,
  attached = false,
}: {
  group: SkillReportStandaloneGitHubGroup
  attached?: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  // Split this repo's rows into quality bands so weak repository-level signals
  // (imports/comments/config/route-decorator) never render beside real code as if
  // they were implementation proof. Primary = implementation_body AND
  // skill-relevant; Supporting = supporting_logic not positively cross-skill;
  // strong rows whose RELEVANCE marks them as another skill's code (a React form
  // in a Machine Learning report) are demoted to Needs review; the rest collapse
  // into the "Needs review" summary.
  const primaryRows = group.rows.filter(
    (r) => isImplementationBody(r.evidence_quality_grade) && !isDemotedByRelevance(r)
  )
  const supportingRows = group.rows.filter(
    (r) => r.evidence_quality_grade === "supporting_logic" && !isDemotedByRelevance(r)
  )
  const relevanceDemotedRows = group.rows.filter((r) => isDemotedByRelevance(r))
  const explicitWeakRows = group.rows.filter((r) => isWeakGitHubRow(r))
  const ungradedRows = group.rows.filter((r) => !r.evidence_quality_grade)
  // "Only fail closed when mixed": a MIXED group (at least one graded row) demotes
  // its ungraded rows into the Needs-review band — an unvalidated legacy line can
  // never sit under "Code implementation" beside real graded evidence. A
  // FULLY-ungraded (legacy) group keeps the prior flat "+N more" list unchanged.
  const hasGraded =
    primaryRows.length > 0 ||
    supportingRows.length > 0 ||
    explicitWeakRows.length > 0 ||
    relevanceDemotedRows.length > 0
  const needsReviewRows = hasGraded
    ? [...relevanceDemotedRows, ...explicitWeakRows, ...ungradedRows]
    : explicitWeakRows
  const legacyRows = hasGraded ? [] : ungradedRows
  // Legacy flat "+N more" expansion — ONLY for a fully-ungraded legacy group.
  const moreCount = group.row_more_count
  const canExpand = !hasGraded && moreCount > 0
  const visibleCount = canExpand ? legacyRows.length - moreCount : legacyRows.length
  const rows = expanded || !canExpand ? legacyRows : legacyRows.slice(0, visibleCount)
  return (
    <div
      data-testid={attached ? "chain-github-group" : "standalone-github-group"}
      data-repo={group.repo_label}
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
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={PROOF_TONE["GitHub Proof"]}>GitHub Proof</Badge>
        <span style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>{group.repo_label}</span>
        {attached ? (
          <Badge tone="emerald">Attached</Badge>
        ) : (
          <span data-testid="vault-unattached-badge">
            <Badge tone="amber">Not attached to a VBR project</Badge>
          </span>
        )}
        {group.repo_is_public && <SafeLink url={group.repo_url} label="View repository →" />}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {/* Primary (implementation_body) always first, then Supporting, then the
            Needs-review band — each capped independently so weak rows never surface
            above primary and no band renders every row uncapped. */}
        <GitHubRowBand
          testId="github-primary-band"
          label="Primary implementation evidence"
          labelColor={TOKEN.emerald}
          rows={primaryRows}
        />
        <GitHubRowBand
          testId="github-supporting-band"
          label="Supporting code evidence — useful context, not primary implementation proof"
          labelColor={TOKEN.inkSoft}
          rows={supportingRows}
        />
        {needsReviewRows.length > 0 && <WeakGitHubSignals rows={needsReviewRows} />}
        {/* Fully-ungraded legacy group → fail closed. With no validated grade these
            rows can never claim "Primary implementation" / "Precise code evidence",
            so they render under a conservative "Needs review / repository-level
            signals" heading that states they are not validated primary proof. The
            "View code lines" links remain, and the backend-driven "+N more" flat
            expansion is preserved unchanged. */}
        {legacyRows.length > 0 && (
          <div data-testid="github-ungraded-legacy" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span
              data-testid="github-ungraded-heading"
              style={{ fontSize: 11, fontWeight: 700, color: TOKEN.muted }}
            >
              Needs review / repository-level signals — not validated primary implementation proof
            </span>
            {rows.map((row, i) => (
              <StandaloneGitHubRowItem key={`u-${row.source_id}-${row.label}-${i}`} row={row} />
            ))}
            {canExpand && (
              <RowMoreToggle
                testId="standalone-github-more"
                expanded={expanded}
                moreCount={moreCount}
                onToggle={() => setExpanded((v) => !v)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Standalone GitHub evidence grouped by repository — compact row groups instead
 * of one full evidence card per code line. Renders nothing when empty (the caller
 * falls back to the flat per-item list for older payloads without groups).
 */
function StandaloneGitHubGroups({ groups }: { groups?: SkillReportStandaloneGitHubGroup[] | null }) {
  if (!groups || groups.length === 0) return null
  const signalsTitle = useSignalsTitle(groups)
  return (
    <div data-testid="skill-report-github" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
        {signalsTitle ? "GitHub code signals" : "GitHub evidence"}
      </h4>
      {signalsTitle && (
        <p data-testid="standalone-github-no-primary" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          No primary implementation body was isolated. The rows below are supporting or weak repository-level signals.
        </p>
      )}
      {groups.map((g, i) => (
        <GitHubGroupCard key={`${g.repo_label}-${i}`} group={g} />
      ))}
    </div>
  )
}

/**
 * A connected proof chain's "Code implementation" section, rendered through the
 * SAME repository-grouped GitHub model as standalone evidence: one grouped block
 * per canonical owner/repo with compact "file · lines" rows (the strongest row
 * first, as ordered by the backend's ML ranking) instead of a weaker single card.
 * Renders nothing when empty (the caller falls back to the flat per-item list for
 * older payloads without ``github_groups``).
 */
function ConnectedGitHubGroups({ groups }: { groups?: SkillReportStandaloneGitHubGroup[] | null }) {
  if (!groups || groups.length === 0) return null
  // When NO group isolated a primary implementation body, the section is honestly
  // titled "GitHub code signals" (not "Code implementation") with a note — the rows
  // below are supporting or weak repository-level signals, never primary proof.
  const signalsTitle = useSignalsTitle(groups)
  return (
    <div data-testid="chain-github" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
        {signalsTitle ? "GitHub code signals" : "Code implementation"}
      </h4>
      {signalsTitle && (
        <p data-testid="chain-github-no-primary" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          No primary implementation body was isolated. The rows below are supporting or weak repository-level signals.
        </p>
      )}
      {groups.map((g, i) => (
        <GitHubGroupCard key={`${g.repo_label}-${i}`} group={g} attached />
      ))}
    </div>
  )
}

/** One compact card for a proof that links to no chain (unlinked support). */
function UnlinkedEvidenceCard({ item }: { item: SkillProofSynthesisUnlinkedItem }) {
  return (
    <div
      data-testid="unlinked-evidence"
      data-proof-type={item.proof_type}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: "8px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone={PROOF_TONE[item.proof_type] ?? "slate"}>{item.proof_type}</Badge>
        {item.corroborates && <Badge tone="slate">Corroborates: {item.corroborates}</Badge>}
        {item.safe_location && <Mono style={{ fontSize: 11, color: TOKEN.muted }}>📍 {item.safe_location}</Mono>}
      </div>
      {item.title && <div style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>{item.title}</div>}
      {item.safe_summary && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{item.safe_summary}</p>
      )}
    </div>
  )
}

/**
 * Normalized fallback identity for evidence that has no stable `source_id` (older
 * payloads). Built ONLY from the safe, stable fields that both a standalone
 * evidence item AND its derived unlinked card carry (see backend `_unlinked_card`):
 * proof type, title/project title, location label (which already encodes repo /
 * file / line for code proofs), and a bounded summary hash (workflow summary
 * preferred, mirroring the backend precedence). No private ids, signed URLs,
 * tokens, raw file paths, or raw provider JSON are used. Used solely for in-memory
 * de-duplication so a proof never renders in BOTH the standalone and unlinked
 * sections.
 */
function evidenceFallbackIdentity(p: {
  proof_type?: string | null
  title?: string | null
  safe_location?: string | null
  safe_summary?: string | null
  workflow_summary?: string | null
}): string {
  const n = (v?: string | null) => (v ?? "").trim().toLowerCase()
  const summary = n(p.workflow_summary) || n(p.safe_summary)
  return [n(p.proof_type), n(p.title), n(p.safe_location), summary.slice(0, 160)].join("|")
}

// Closed status→claim map: the one-line recruiter-readable claim when the
// backend sent no synthesis_summary. Labels only — never a score, never a
// stronger word than the qualitative status itself supports.
const CLAIM_BY_STATUS: Record<string, string> = {
  Demonstrated: "The connected evidence below demonstrates this skill.",
  "Partially demonstrated": "The evidence below supports parts of this skill claim — see the limitations.",
  "Evidence observed": "Evidence supporting this skill was observed — see the limitations for what it does not prove.",
  "Needs review": "Evidence exists but needs review before it can support this claim.",
  "Not assessed": "This skill has not been assessed yet.",
  "Insufficient evidence": "There is not enough direct evidence yet to support this claim.",
}

/**
 * The full Skill Report for one skill — a recruiter-trust instrument structured
 * as an evidence ARGUMENT: skill claim → evidence thesis → direct skill
 * evidence (connected proof chains) → project-context / unmapped / vault-only
 * tiers (each honestly "not counted") → proof coverage matrix → limitations →
 * inspect actions. Never a raw dump.
 *
 * ``publicSafe`` (only true on a public surface) drops any synthesis
 * claim/chain that is not public-safe and every owner-only route.
 * ``context`` is the OWNER's passport-derived slice powering the project-context
 * and unmapped tiers plus the matrix's context cells; when absent those pieces
 * fail closed and the report renders from its own payload alone.
 */
export function SkillReportView({
  report,
  publicSafe = false,
  context = null,
}: {
  report: SkillReport
  publicSafe?: boolean
  context?: SkillReportIntelligenceContext | null
}) {
  // Prefer the Proof Synthesis Agent's project-anchored chains; fall back to the
  // attached project chains for older payloads without synthesis fields.
  const allChains = report.proof_chains ?? report.projects?.filter((p) => p.attached) ?? []
  // Direct skill evidence = chains attached to a project. An unattached chain is
  // vault-tier: its proof maps to the skill but is not project-connected, so it
  // renders under "Vault-only / suggested" and is never framed as counted.
  const attachedChains = allChains.filter((c) => c.attached)
  const vaultChains = allChains.filter((c) => !c.attached)
  const unlinked = report.unlinked_supporting_evidence
  const std = report.standalone_evidence
  // The "Unlinked supporting evidence" bucket is derived from the SAME standalone
  // proofs the canonical "Standalone supporting proofs" section (D) renders, so
  // the two sections would otherwise show the same proof twice. Deduplicate so the
  // standalone section stays canonical and a proof never renders in BOTH places.
  // Primary identity is the stable `source_id`; when a legacy payload has none we
  // fall back to a normalized identity built ONLY from safe, stable fields
  // (proof type + title + location + repo/file/line + a bounded summary hash) —
  // never a private id or signed URL. The standalone unlinked cards are built from
  // the SAME flat standalone arrays (see `_unlinked_card`), so the fallback
  // identity computed on each side matches for the same underlying proof.
  const standaloneSourceIds = new Set<string>()
  const standaloneFallbackIds = new Set<string>()
  if (std) {
    for (const g of std.github_groups ?? []) for (const r of g.rows) if (r.source_id) standaloneSourceIds.add(r.source_id)
    // The unlinked cards are built from these flat standalone arrays, so a fallback
    // identity computed here matches the one computed on the unlinked side for the
    // same proof — covering the github_groups projection too (it is built from the
    // SAME flat `github` array).
    for (const arr of [std.github, std.website, std.defense, std.video, std.skill_graph]) {
      for (const it of arr ?? []) {
        if (!it) continue
        if (it.source_id) standaloneSourceIds.add(it.source_id)
        standaloneFallbackIds.add(evidenceFallbackIdentity(it))
      }
    }
    for (const d of std.documents ?? []) {
      if (!d) continue
      if (d.source_id) standaloneSourceIds.add(d.source_id)
      standaloneFallbackIds.add(
        evidenceFallbackIdentity({
          proof_type: "Document Proof",
          title: d.document_title,
          safe_summary: d.reason,
          safe_location: d.citation ?? (d.page_number ? `Page ${d.page_number}` : null),
        }),
      )
    }
  }
  const unlinkedItems = (unlinked?.items ?? []).filter((it) =>
    it.source_id
      ? !standaloneSourceIds.has(it.source_id)
      : !standaloneFallbackIds.has(evidenceFallbackIdentity(it)),
  )
  // Step 4 synthesis — collapsed to a COMPACT agent summary (the detailed,
  // evidence-cited synthesis is embedded per chain above, so this is just a short
  // recruiter-facing summary, never the old wall of repeated claim cards).
  const synthesisResults = report.llm_synthesis ?? []
  const hasAgentSummary = synthesisResults.some(
    (r) => (!publicSafe || r.public_safe) && Boolean((r.overall_summary || "").trim()),
  )
  // Synthesis exists but, on a public surface, none of it is public-safe.
  const synthesisWithheld =
    !hasAgentSummary &&
    publicSafe &&
    synthesisResults.some((r) => Boolean((r.overall_summary || "").trim()))
  // Prefer the repository-grouped standalone GitHub projection; fall back to the
  // flat per-item list for older payloads that don't carry ``github_groups``.
  const stdGithubGroups = std?.github_groups ?? []
  const hasStandalone = Boolean(
    std &&
      (std.github.length ||
        stdGithubGroups.length ||
        std.website.length ||
        std.documents.length ||
        std.defense.length ||
        std.video.length ||
        std.skill_graph.length),
  )
  const sourceCounts = Object.entries(report.source_counts ?? {})
  const coverage = Object.entries(report.source_coverage ?? {})

  return (
    <div data-testid="skill-report" data-skill={report.skill} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* A — Overview */}
      <div data-testid="skill-report-overview" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Badge tone={statusTone(report.status)}>{report.status}</Badge>
          <span style={{ fontSize: 11, color: TOKEN.muted }}>{report.category}</span>
        </div>
        {report.synthesis_summary ? (
          <p data-testid="skill-report-synthesis-summary" style={{ fontSize: 12, color: TOKEN.ink, margin: 0, fontWeight: 600 }}>
            {report.synthesis_summary}
          </p>
        ) : (
          // No synthesis summary → the closed status-derived claim line, so the
          // report always opens with ONE recruiter-readable sentence.
          CLAIM_BY_STATUS[report.status] && (
            <p data-testid="skill-report-claim" style={{ fontSize: 12, color: TOKEN.ink, margin: 0, fontWeight: 600 }}>
              {CLAIM_BY_STATUS[report.status]}
            </p>
          )
        )}
        {(report.summary || report.overview?.why_supported) && (
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>
            {report.summary || report.overview?.why_supported}
          </p>
        )}
        {coverage.length > 0 && (
          <div data-testid="skill-report-coverage" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {coverage.map(([source, present]) => (
              <Badge key={source} tone={present ? (SOURCE_TONE[source] ?? "emerald") : "slate"}>
                {source}: {present ? "✓" : "—"}
              </Badge>
            ))}
          </div>
        )}
        {sourceCounts.length > 0 && (
          <div data-testid="skill-report-source-counts" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {sourceCounts.map(([source, count]) => (
              <Badge key={source} tone={SOURCE_TONE[source] ?? "slate"}>
                {source}: {count}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* B — Evidence thesis: one derived sentence stating what backs the claim
          plus the standing "only direct evidence counts" rule. */}
      <SkillEvidenceThesis report={report} directChains={attachedChains} />

      {/* C — Direct skill evidence: the connected proof chains. The skill, the
          project that supports it, and the code / runtime / document / defense
          evidence that corroborates the same claim. The ONLY tier counted for
          the claim. Always shown with a calm empty state so the report reads
          as an audit instrument even before any chain exists. */}
      <div data-testid="skill-report-chains" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Direct skill evidence
        </h3>
        <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Proof mapped to {report.skill}, connected through the project(s) below — the only evidence
          counted for this claim.
        </p>
        {attachedChains.length > 0 ? (
          <EvidenceTierSection kind="skill" testid="skill-report-direct">
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {attachedChains.map((chain, i) => (
                <ProjectChainCard key={`${chain.project_id ?? "p"}-${i}`} chain={chain} />
              ))}
            </div>
          </EvidenceTierSection>
        ) : (
          <EmptyState testId="skill-report-chains-empty">
            No linked proof chain yet — attach this skill&rsquo;s proofs to a VBR project to connect them.
          </EmptyState>
        )}
      </div>

      {/* B2 — VeriBridge agent summary (COMPACT): one short line per synthesized
          chain. The detailed, evidence-cited synthesis lives inside each chain
          card above, so this is no longer a wall of repeated claim cards. Hidden
          entirely unless there is a real summary (or a public-safe withhold). */}
      {(hasAgentSummary || synthesisWithheld) && (
        <div data-testid="skill-report-synthesis" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
            VeriBridge agent summary
          </h3>
          {hasAgentSummary ? (
            <AgentSummary results={synthesisResults} publicSafe={publicSafe} />
          ) : (
            <EmptyState testId="skill-report-synthesis-withheld">
              Evidence available but not public-safe — the full synthesis is shown on the private report.
            </EmptyState>
          )}
        </div>
      )}

      {/* D — Project proof (context only): sources attached to the same
          project(s) that are NOT mapped to this skill. Chips + honest label,
          never counted, never full evidence cards. Owner-only (needs the
          passport context) — fails closed on public/legacy surfaces. */}
      {!publicSafe && (
        <ProjectContextEvidenceList chains={attachedChains} context={context} skill={report.skill} />
      )}

      {/* E — Attached proof not yet skill-mapped: real analyzed proof on this
          skill's project(s) that no skill claim consumed. Owner-only; fails
          closed without the passport context. */}
      {!publicSafe && <UnmappedProofNotice chains={attachedChains} context={context} />}

      {/* C2 — Unlinked supporting evidence (synthesis): capped, clearly separated
          from the strong chains so unrelated proofs are never folded into them.
          Items already shown in the canonical standalone section (D) are dropped
          so the same proof never appears in both sections. */}
      {unlinked && unlinkedItems.length > 0 && (
        <div data-testid="skill-report-unlinked" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Unlinked supporting evidence
          </h3>
          {unlinkedItems.map((item) => (
            <UnlinkedEvidenceCard key={`${item.proof_type}-${item.source_id}`} item={item} />
          ))}
          {unlinked.more_count > 0 && (
            <span data-testid="unlinked-more" style={{ fontSize: 11, color: TOKEN.muted }}>
              +{unlinked.more_count} more supporting proof{unlinked.more_count === 1 ? "" : "s"} not shown
            </span>
          )}
        </div>
      )}

      {/* F — Vault-only / suggested evidence: proof saved in the vault (not
          attached to any VBR project), unattached proof chains, and vault
          suggestions naming this skill. Honestly labelled and never counted. */}
      {(hasStandalone || vaultChains.length > 0 || (context?.suggestedForSkill.length ?? 0) > 0) && (
        <div data-testid="skill-report-vault-only" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Vault-only / suggested evidence
            </h3>
            <EvidenceRelationshipBadge kind="vault" />
            <span data-testid="vault-only-not-counted">
              <Badge tone="amber">Not counted yet</Badge>
            </span>
          </div>
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
            Saved in the Proof Vault or suggested — not attached to a VBR project, so it does not
            count toward this skill claim until it is attached and skill-mapped.
          </p>
          <EvidenceTierSection kind="vault">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {vaultChains.map((chain, i) => (
                <ProjectChainCard key={`v-${chain.project_id ?? "p"}-${i}`} chain={chain} />
              ))}
              {hasStandalone && (
                <div data-testid="skill-report-standalone" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {stdGithubGroups.length > 0 ? (
                    <StandaloneGitHubGroups groups={stdGithubGroups} />
                  ) : (
                    <SkillReportSection testId="skill-report-github" title="GitHub evidence" items={std.github} />
                  )}
                  <SkillReportSection testId="skill-report-website" title="Website evidence" items={std.website} />
                  <DocumentCorrelations
                    testId="skill-report-documents"
                    items={std.documents}
                    moreCount={std.document_more_count}
                  />
                  <SkillReportSection testId="skill-report-defense" title="Project Defense evidence" items={std.defense} />
                  <SkillReportSection testId="skill-report-video" title="Video evidence" items={std.video} />
                  <SkillReportSection testId="skill-report-skill-graph" title="Skill Graph evidence" items={std.skill_graph} />
                </div>
              )}
              {!publicSafe && <VaultSuggestedEvidenceList entries={context?.suggestedForSkill} />}
            </div>
          </EvidenceTierSection>
        </div>
      )}

      {/* G — Proof coverage matrix: one row per direct-evidence project plus a
          vault row, one column per proof source, each cell the tier that source
          holds for THIS skill. Context cells fail closed without the passport
          context. */}
      <SkillProofMatrix
        directChains={attachedChains}
        standalone={std}
        context={context}
        suggested={context?.suggestedForSkill}
      />

      {/* H — Gaps / limitations */}
      {report.gaps?.length > 0 && (
        <div data-testid="skill-report-gaps" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Gaps / limitations</h4>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: TOKEN.muted }}>
            {report.gaps.map((g, i) => (
              <li key={`${g}-${i}`}>{g}</li>
            ))}
          </ul>
        </div>
      )}

      {/* I — Standing honesty block: what this report does not claim. */}
      <EvidenceLimitations skill={report.skill} />

      {/* J — Inspect actions: each direct-evidence project's report + the Proof
          Vault, deduplicated. Owner-only routes — never on a public surface. */}
      {!publicSafe && <ProofInspectActions directChains={attachedChains} />}
    </div>
  )
}

// ── Layer 1: compact skill summary card (main Passport) ───────────────────────

/**
 * Collapse preview rows that would render identically so a compact skill card
 * never repeats a duplicate-looking label. The dedupe identity is the ACTUAL
 * rendered text — PreviewRow shows `title || safe_summary` and `safe_location`.
 * Keying on that visible text (not title AND summary) collapses rows that render
 * identically even when a hidden safe_summary differs, mirroring the backend.
 * Distinct GitHub file/line locations and distinct document pages/sections carry
 * different safe locations, so they stay separate rows. The backend already
 * dedupes previews; this is a defensive render-layer net.
 */
function dedupePreviews(previews: VaultSkillPreview[]): VaultSkillPreview[] {
  const seen = new Set<string>()
  const out: VaultSkillPreview[] = []
  for (const p of previews) {
    const visible = ((p.title || "").trim() || (p.safe_summary || "")).trim().toLowerCase()
    const key = [p.proof_type, visible, (p.safe_location || "").trim().toLowerCase()].join("|")
    if (seen.has(key)) continue
    seen.add(key)
    out.push(p)
  }
  return out
}

function PreviewRow({ preview }: { preview: VaultSkillPreview }) {
  return (
    <div data-testid="vault-skill-preview" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <Badge tone={PROOF_TONE[preview.proof_type] ?? "slate"}>{preview.proof_type}</Badge>
      <span style={{ fontSize: 11, color: TOKEN.inkSoft }}>{preview.title || preview.safe_summary}</span>
      {preview.safe_location && (
        <Mono style={{ fontSize: 10, color: TOKEN.muted }}>{preview.safe_location}</Mono>
      )}
    </div>
  )
}

/** Slugify a skill name client-side as a fallback when the API omits the slug. */
const fallbackSlug = fallbackSkillSlug

/** The project where a skill is most strongly evidenced (from the passport
 *  project↔skill aggregate) — connects the skill lens back to the project lens.
 *  `reportPath` is the owner-only project report preview route; `publicPath`
 *  the published recruiter link (either may be absent). */
export type StrongestProjectRef = {
  title: string
  status: string
  reportPath?: string | null
  publicPath?: string | null
  reportIsPublic?: boolean
}

/**
 * Layer 1 — a compact skill card. Shows counts + a few previews, and a
 * "View Skill Report" link that NAVIGATES to the separate Skill Report page
 * (the full evidence — and the expensive website hydration — only loads there).
 * Never renders the full report inline.
 */
/** The five attachable proof sources, in canonical order, for the compact
 *  skill-card proof-chain preview. */
const SKILL_CHAIN_SOURCES = [
  "GitHub Proof",
  "Website Proof",
  "Document Proof",
  "Project Defense",
  "Video Evidence",
]

/**
 * Compact proof-chain preview for a skill card: which of the five attachable
 * proof sources back this skill (from the already-safe source counts). Labels
 * and check marks only — never raw evidence or a numeric score.
 */
function SkillProofChainPreview({ counts }: { counts: Record<string, number> }) {
  return (
    <div data-testid="skill-proof-chain-preview" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {SKILL_CHAIN_SOURCES.map((label) => {
        const present = (counts[label] ?? 0) > 0
        return (
          <span key={label} data-testid="skill-chain-item" data-source={label} data-present={present ? "true" : "false"}>
            <Badge tone={present ? (PROOF_TONE[label] ?? "emerald") : "slate"}>
              {present ? "✓ " : "– "}
              {label}
            </Badge>
          </span>
        )
      })}
    </div>
  )
}

export function VaultSkillSummaryCard({
  summary,
  strongestProject,
}: {
  summary: VaultSkillSummary
  strongestProject?: StrongestProjectRef | null
}) {
  const sourceCounts = Object.entries(summary.proof_source_counts ?? {})
  const slug = summary.skill_slug || fallbackSlug(summary.skill)
  // Honest unattached framing: when this skill is mostly (or only) supported
  // by unattached vault proof, that evidence must never read as project proof.
  const mostlyUnattached = summary.unattached_count > summary.attached_count

  return (
    <div
      data-testid="vault-skill-summary"
      data-skill={summary.skill}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "12px 14px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 10,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: TOKEN.ink }}>{summary.skill}</span>
        <Badge tone={statusTone(summary.status)}>{summary.status}</Badge>
        {summary.project_count > 0 && (
          <span data-testid="vault-summary-projects" style={{ fontSize: 11, color: TOKEN.muted }}>
            {summary.project_count} project{summary.project_count === 1 ? "" : "s"}
          </span>
        )}
        {summary.has_unattached && (
          <span data-testid="vault-summary-unattached">
            <Badge tone="amber">{summary.unattached_count} not attached</Badge>
          </span>
        )}
      </div>

      {/* Proof source counts */}
      <div data-testid="vault-summary-source-counts" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {sourceCounts.map(([source, count]) => (
          <Badge key={source} tone={PROOF_TONE[source] ?? "slate"}>
            {source}: {count}
          </Badge>
        ))}
      </div>

      {/* Compact proof-chain preview across the five attachable sources */}
      <SkillProofChainPreview counts={summary.proof_source_counts ?? {}} />

      {/* Skill → Project link: the project where this skill is most strongly
          evidenced, with a direct route into that project's evidence. */}
      {strongestProject && (
        <div
          data-testid="vault-summary-strongest-project"
          style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", fontSize: 11, color: TOKEN.inkSoft }}
        >
          <span>
            This skill is strongest in <strong>{strongestProject.title}</strong>
            {strongestProject.status ? ` — ${strongestProject.status}` : ""}
            {summary.project_count > 1 ? ` (+${summary.project_count - 1} related project${summary.project_count === 2 ? "" : "s"})` : ""}
          </span>
          {strongestProject.reportPath && (
            <Link
              href={strongestProject.reportPath}
              data-testid="strongest-project-evidence-link"
              style={{ fontSize: 11, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none", whiteSpace: "nowrap" }}
            >
              View project evidence →
            </Link>
          )}
        </div>
      )}

      {/* Unattached honesty: vault-only evidence never reads as project proof. */}
      {mostlyUnattached && (
        <p data-testid="vault-summary-unattached-note" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Additional vault evidence exists but is not attached to a project report.
        </p>
      )}

      {/* Proof Attachment Intelligence: owner-only strengthening actions —
          qualitative "do this next" sentences, never a score, never a mutation. */}
      {(summary.strengthening_actions?.length ?? 0) > 0 && (
        <div data-testid="skill-strengthening-actions" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {summary.strengthening_actions!.map((action, i) => (
            <p key={i} data-testid="skill-strengthening-action" style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
              💪 {action}
            </p>
          ))}
        </div>
      )}

      {summary.summary && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{summary.summary}</p>
      )}

      {/* Top representative previews (capped) */}
      {summary.previews?.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {dedupePreviews(summary.previews).map((p, i) => (
            <PreviewRow key={`${p.proof_type}-${p.safe_location ?? ""}-${i}`} preview={p} />
          ))}
          {summary.more_count > 0 && (
            <span data-testid="vault-summary-more" style={{ fontSize: 11, color: TOKEN.muted }}>
              +{summary.more_count} more proof{summary.more_count === 1 ? "" : "s"}
            </span>
          )}
        </div>
      )}

      <Link
        href={skillReportPath(slug)}
        data-testid="view-skill-report"
        style={{
          alignSelf: "flex-start",
          fontSize: 12,
          fontWeight: 600,
          color: TOKEN.indigo,
          background: TOKEN.indigoSoft,
          borderRadius: 6,
          padding: "6px 12px",
          textDecoration: "none",
        }}
      >
        View Skill Report →
      </Link>
    </div>
  )
}

/**
 * The compact Student Proof Vault dashboard for the main Private Work Passport:
 * skill summary cards grouped under category headings. Renders nothing when
 * there are no summaries.
 */
export function VaultSkillDashboard({
  summaries,
  strongestBySkill,
}: {
  summaries?: VaultSkillSummary[] | null
  /** skill (lowercased) → strongest related project, from the passport aggregate. */
  strongestBySkill?: Record<string, StrongestProjectRef>
}) {
  if (!summaries || summaries.length === 0) return null

  const byCategory = new Map<string, VaultSkillSummary[]>()
  for (const s of summaries) {
    const cat = s.category || "Other"
    if (!byCategory.has(cat)) byCategory.set(cat, [])
    byCategory.get(cat)!.push(s)
  }
  const orderedCategories = [
    ...CATEGORY_ORDER.filter((c) => byCategory.has(c)),
    ...[...byCategory.keys()].filter((c) => !CATEGORY_ORDER.includes(c)),
  ]

  return (
    <div data-testid="vault-skill-dashboard" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {orderedCategories.map((category) => (
        <div key={category} data-testid="vault-category" data-category={category} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {category}
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {byCategory.get(category)!.map((summary) => (
              <VaultSkillSummaryCard
                key={summary.skill}
                summary={summary}
                strongestProject={strongestBySkill?.[summary.skill.toLowerCase()] ?? null}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Attachment Intelligence Cleanup (Step 4): attached / suggested / unattached ─

const ATTACHMENT_STATE_TONE: Record<string, BadgeTone> = {
  attached: "emerald",
  suggested: "sky",
  unattached: "amber",
}

/**
 * One deduplicated attachment-overview entry: proof source, safe title, the
 * closed state/strength labels, why (reason label), the project link(s) for
 * attached/suggested entries, and an honest "×N duplicates collapsed" note.
 * Entries carry ONLY safe display fields — never a source id, path, or score.
 */
function AttachmentEntryCard({ entry }: { entry: ProofAttachmentEntry }) {
  return (
    <div
      data-testid="attachment-entry"
      data-attachment-state={entry.attachment_state}
      data-proof-type={entry.proof_type}
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
        <Badge tone={PROOF_TONE[entry.proof_type] ?? "slate"}>{entry.proof_type}</Badge>
        <span data-testid="attachment-entry-status">
          <Badge tone={ATTACHMENT_STATE_TONE[entry.attachment_state] ?? "slate"}>{entry.status_label}</Badge>
        </span>
        {entry.duplicate_count > 1 && (
          <span data-testid="attachment-entry-duplicates" style={{ fontSize: 11, color: TOKEN.muted }}>
            {entry.duplicate_count} duplicate rows collapsed
          </span>
        )}
      </div>

      <div style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>{entry.display_title}</div>

      {entry.reason_label && (
        <p data-testid="attachment-entry-reason" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          {entry.reason_label}
        </p>
      )}

      {entry.skill_names.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {entry.skill_names.map((skill) => (
            <span key={skill} data-testid="attachment-entry-skill">
              <Badge tone="indigo">{skill}</Badge>
            </span>
          ))}
        </div>
      )}

      {entry.project_titles.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 12 }}>
          <span style={{ color: TOKEN.muted }}>
            {entry.attachment_state === "attached" ? "Project:" : "Likely project:"}
          </span>
          {entry.project_titles.map((title, i) => {
            const ref = entry.project_refs_safe[i]
            return ref ? (
              <Link
                key={`${title}-${i}`}
                href={ref}
                data-testid="attachment-entry-project-link"
                style={{ fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
              >
                {title} →
              </Link>
            ) : (
              <span key={`${title}-${i}`} style={{ fontWeight: 600, color: TOKEN.inkSoft }}>
                {title}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

function AttachmentSection({
  testId,
  title,
  hint,
  entries,
}: {
  testId: string
  title: string
  hint: string
  entries: ProofAttachmentEntry[]
}) {
  if (!entries || entries.length === 0) return null
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <h4 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>{title}</h4>
        <span style={{ fontSize: 11, color: TOKEN.muted }}>{hint}</span>
      </div>
      {entries.map((entry) => (
        <AttachmentEntryCard key={entry.entry_id_safe} entry={entry} />
      ))}
    </div>
  )
}

/**
 * The owner-only attachment overview: Attached / Suggested / Unattached
 * evidence as three clearly separated, deduplicated sections. Suggested
 * evidence is explicitly "not counted until attached" — it is an improvement
 * opportunity, never verified proof. Renders nothing when every bucket is
 * empty.
 */
export function AttachmentOverviewSection({ overview }: { overview?: ProofAttachmentOverview | null }) {
  if (!overview) return null
  const total = overview.attached_count + overview.suggested_count + overview.unattached_count
  if (total === 0) return null
  return (
    <div data-testid="attachment-overview" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span data-testid="attachment-overview-attached-count">
          <Badge tone="emerald">{overview.attached_count} attached</Badge>
        </span>
        <span data-testid="attachment-overview-suggested-count">
          <Badge tone="sky">{overview.suggested_count} suggested (not counted)</Badge>
        </span>
        <span data-testid="attachment-overview-unattached-count">
          <Badge tone="amber">{overview.unattached_count} unattached</Badge>
        </span>
      </div>
      <AttachmentSection
        testId="attachment-attached-section"
        title="Attached evidence"
        hint="Explicitly attached to a project — counts as project evidence."
        entries={overview.attached}
      />
      <AttachmentSection
        testId="attachment-suggested-section"
        title="Suggested evidence"
        hint="Suggested — not counted until attached. Review before attaching; nothing is attached automatically."
        entries={overview.suggested}
      />
      <AttachmentSection
        testId="attachment-unattached-section"
        title="Unattached evidence"
        hint="In your vault, not linked to any project yet."
        entries={overview.unattached}
      />
    </div>
  )
}
