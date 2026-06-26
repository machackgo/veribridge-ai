"use client"

import Link from "next/link"

import {
  isSafePublicUrl,
  skillReportPath,
  type SkillProofSynthesisUnlinkedItem,
  type SkillReport,
  type SkillReportDocumentCorrelation,
  type SkillReportEvidenceItem,
  type SkillReportProjectChain,
  type VaultProofItem,
  type VaultSkillGroup,
  type VaultSkillPreview,
  type VaultSkillSummary,
} from "@/lib/vbr-api"
import { Badge, Mono, TOKEN, type BadgeTone } from "./shared"

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
 * * ``code_line`` + ``has_precise_line_evidence`` → a "Precise code evidence"
 *   badge, the file/function/line location, the safe snippet, and a "View code
 *   lines →" link to the exact ``github_line_url`` (never falls back to the repo
 *   URL unless the line URL is missing).
 * * ``repo_level`` → a "Repo-level support only" badge, the repo name, a clear
 *   limitation, and a "View repository →" link to ``repo_url`` — NO snippet, NO
 *   line range, and never implies precise implementation proof.
 * * legacy payloads with no ``display_mode`` keep the prior heuristic.
 */
function GitHubEvidence({ item, ghLocation }: { item: SkillReportEvidenceItem; ghLocation: string | null }) {
  const precise = item.display_mode === "code_line" && item.has_precise_line_evidence === true
  const repoLevel = item.display_mode === "repo_level"

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

      {/* D — Website: workflow / OCR / DOM / visual / live-check summaries */}
      {isWebsite && (
        <>
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
      {item.limitation && (
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
 * A document shown as connected *corroboration*: it answers "what does this
 * document corroborate?" — never a raw line-by-line dump. The raw document is
 * always private; only a safe citation/snippet is shown.
 */
function DocumentCorrelationCard({ corr }: { corr: SkillReportDocumentCorrelation }) {
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
      {(corr.page_number || corr.citation) && (
        <Mono data-testid="document-citation" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
          {corr.page_number ? `Page ${corr.page_number}` : ""}
          {corr.page_number && corr.citation ? " · " : ""}
          {corr.citation ?? ""}
        </Mono>
      )}
      {corr.safe_snippet && (
        <p data-testid="document-snippet" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
          “{corr.safe_snippet}”
        </p>
      )}
      {corr.reason && <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{corr.reason}</p>}
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

/** One project's connected proof chain: artifacts + corroborating documents. */
function ProjectChainCard({ chain }: { chain: SkillReportProjectChain }) {
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
      <SkillReportSection testId="chain-github" title="Code implementation" items={chain.github_evidence} />
      <SkillReportSection testId="chain-website" title="Runtime / website behavior" items={chain.website_evidence} />
      <SkillReportSection testId="chain-defense" title="Defense / video explanation" items={chain.defense_evidence} />
      <SkillReportSection testId="chain-video" title="Video evidence" items={chain.video_evidence} />
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

/** The full Skill Report for one skill — connected proof chains, never a dump. */
export function SkillReportView({ report }: { report: SkillReport }) {
  // Prefer the Proof Synthesis Agent's project-anchored chains; fall back to the
  // attached project chains for older payloads without synthesis fields.
  const attachedChains = report.proof_chains ?? report.projects?.filter((p) => p.attached) ?? []
  const unlinked = report.unlinked_supporting_evidence
  const std = report.standalone_evidence
  const hasStandalone = Boolean(
    std &&
      (std.github.length ||
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
        {report.synthesis_summary && (
          <p data-testid="skill-report-synthesis-summary" style={{ fontSize: 12, color: TOKEN.ink, margin: 0, fontWeight: 600 }}>
            {report.synthesis_summary}
          </p>
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

      {/* B — Connected proof chains, one per project where the skill appears. */}
      {attachedChains.length > 0 && (
        <div data-testid="skill-report-chains" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Connected proof chains
          </h3>
          {attachedChains.map((chain, i) => (
            <ProjectChainCard key={`${chain.project_id ?? "p"}-${i}`} chain={chain} />
          ))}
        </div>
      )}

      {/* C — Unlinked supporting evidence (synthesis): capped, clearly separated
          from the strong chains so unrelated proofs are never folded into them. */}
      {unlinked && unlinked.items.length > 0 && (
        <div data-testid="skill-report-unlinked" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Unlinked supporting evidence
          </h3>
          {unlinked.items.map((item) => (
            <UnlinkedEvidenceCard key={`${item.proof_type}-${item.source_id}`} item={item} />
          ))}
          {unlinked.more_count > 0 && (
            <span data-testid="unlinked-more" style={{ fontSize: 11, color: TOKEN.muted }}>
              +{unlinked.more_count} more supporting proof{unlinked.more_count === 1 ? "" : "s"} not shown
            </span>
          )}
        </div>
      )}

      {/* D — Standalone supporting proofs (not attached to a VBR project). */}
      {hasStandalone && (
        <div data-testid="skill-report-standalone" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: TOKEN.muted, margin: 0, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Standalone supporting proofs (not attached to a VBR project)
          </h3>
          <SkillReportSection testId="skill-report-github" title="GitHub evidence" items={std.github} />
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
    </div>
  )
}

// ── Layer 1: compact skill summary card (main Passport) ───────────────────────

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
function fallbackSlug(skill: string): string {
  return skill.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "skill"
}

/**
 * Layer 1 — a compact skill card. Shows counts + a few previews, and a
 * "View Skill Report" link that NAVIGATES to the separate Skill Report page
 * (the full evidence — and the expensive website hydration — only loads there).
 * Never renders the full report inline.
 */
export function VaultSkillSummaryCard({ summary }: { summary: VaultSkillSummary }) {
  const sourceCounts = Object.entries(summary.proof_source_counts ?? {})
  const slug = summary.skill_slug || fallbackSlug(summary.skill)

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

      {summary.summary && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{summary.summary}</p>
      )}

      {/* Top representative previews (capped) */}
      {summary.previews?.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {summary.previews.map((p, i) => (
            <PreviewRow key={`${p.proof_type}-${i}`} preview={p} />
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
export function VaultSkillDashboard({ summaries }: { summaries?: VaultSkillSummary[] | null }) {
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
              <VaultSkillSummaryCard key={summary.skill} summary={summary} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
