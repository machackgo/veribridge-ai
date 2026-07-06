"use client"

/**
 * Proof Vault — the private proof-maintenance area for the Work Passport.
 *
 * Everything here MOVED out of the main Passport page so the Passport itself
 * stays a clean Projects ↔ Skills identity graph: Proof Attachment
 * Intelligence (suggested attachments, projects to strengthen, skills with
 * unattached evidence), the full Skill Intelligence dashboard, and the
 * Attached / Suggested / Unattached evidence overview. Owner-only, review-only
 * — nothing here mutates or attaches anything, and none of it ever appears on
 * the public Passport.
 */

import { useEffect, useState } from "react"
import Link from "next/link"
import {
  fallbackSkillSlug,
  getPrivateWorkPassport,
  skillReportPath,
  type PrivateWorkPassport,
  type ProofAttachmentSuggestion,
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
} from "../../../../../../components/passport/shared"
import {
  AttachmentOverviewSection,
  VaultSkillDashboard,
} from "../../../../../../components/passport/VaultProofs"
import { strongestProjectBySkill } from "../passport-graph"

const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

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
 * the projects worth strengthening next — including their proof-chain gaps and
 * per-project suggestions — and the skills whose evidence is still unattached.
 * Review-only — nothing here mutates or attaches anything.
 */
function ProofAttachmentIntelligenceCard({ passport }: { passport: PrivateWorkPassport }) {
  const summary = passport.unattached_proof_summary
  const suggestions = dedupeSuggestions(summary?.suggestions ?? [])
  const unattachedCount = summary?.unattached_count ?? passport.vault_unattached_count ?? 0
  // Prominent "no safe project match" copy uses the clean, deduplicated
  // attachment-overview count (duplicate rows collapsed) — never the raw
  // vault-derived unmatched_count, which can balloon into the 519-style row
  // count and contradict the vault overview. unmatched_count is kept only as a
  // backward-compatible fallback for older payloads with no overview.
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
          <div data-testid="projects-to-strengthen" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Projects to strengthen
            </Mono>
            {projectsToStrengthen.map((p) => (
              <div
                key={p.project_id}
                data-testid="project-to-strengthen"
                style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: TOKEN.inkSoft }}
              >
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <strong style={{ color: TOKEN.ink }}>{p.project_title || "Untitled project"}</strong>
                  {p.chain_label && (
                    <span data-testid="project-chain-label">
                      <Badge tone={CHAIN_LABEL_TONE[p.chain_label] ?? "amber"}>{p.chain_label}</Badge>
                    </span>
                  )}
                </div>
                <p data-testid="project-next-action" style={{ margin: 0, lineHeight: 1.5 }}>
                  <strong style={{ color: TOKEN.ink }}>Suggested next action: </strong>
                  {p.next_best_action}
                </p>
                {(p.proof_chain_gaps?.length ?? 0) > 0 && (
                  <ul data-testid="project-chain-gaps" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}>
                    {p.proof_chain_gaps!.map((gap) => (
                      <li key={gap.source} data-testid="project-chain-gap" data-source={gap.source} style={{ fontSize: 11, color: TOKEN.muted }}>
                        <strong style={{ color: TOKEN.inkSoft }}>{gap.gap_label}: </strong>
                        {gap.action}
                      </li>
                    ))}
                  </ul>
                )}
                {(p.suggested_attachments?.length ?? 0) > 0 && (
                  <div data-testid="project-suggested-attachments" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {p.suggested_attachments!.map((s) => (
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

function VaultStat({ stat, label, value }: { stat: string; label: string; value: number }) {
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

/** Vault-level counts + next actions — the maintenance half of the old
 *  Evidence Graph Overview (the main Passport keeps only the identity chips). */
function VaultOverviewCard({ passport }: { passport: PrivateWorkPassport }) {
  const overview = passport.evidence_graph_overview
  const attachedCount =
    overview?.attached_proof_count ??
    (passport.vault_proof_count ?? 0) - (passport.vault_unattached_count ?? 0)
  const suggestedCount =
    overview?.suggested_proof_count ?? passport.attachment_overview?.suggested_count ?? 0
  const unattachedCount =
    passport.attachment_overview?.unattached_count ??
    overview?.unattached_proof_count ??
    passport.vault_unattached_count ??
    0
  const nextActions = overview?.next_actions ?? []

  return (
    <Card>
      <div data-testid="vault-overview" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <CardHeader title="Proof Vault" eyebrow="Private proof maintenance" icon="🧰" />
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Every proof you own is preserved here — attached to a project or not. Unattached proofs still appear
          under their skill, but they do not count as project evidence and never feature in a recruiter report
          until you attach them. Nothing here is ever shown on your public Passport.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <VaultStat stat="attached-proofs" label="Proofs attached to projects" value={attachedCount} />
          {suggestedCount > 0 && (
            <VaultStat
              stat="suggested-proofs"
              label="Suggested — not counted until attached"
              value={suggestedCount}
            />
          )}
          <VaultStat stat="unattached-proofs" label="Unattached proofs" value={unattachedCount} />
        </div>
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
        {nextActions.length > 0 && (
          <div data-testid="overview-next-actions" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Next actions
            </Mono>
            <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
              {nextActions.map((action, i) => (
                <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                  {action}
                </li>
              ))}
            </ul>
          </div>
        )}
        <Link
          href="/student/vbr/passport"
          data-testid="back-to-passport-link"
          style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
        >
          ← Back to Work Passport
        </Link>
      </div>
    </Card>
  )
}

export function ProofVaultView() {
  const [passport, setPassport] = useState<PrivateWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getPrivateWorkPassport()
      .then(setPassport)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load Proof Vault."))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  if (loading) return <LoadingState label="Loading your Proof Vault…" />
  if (error || !passport) return <ErrorState message={error ?? "Proof Vault not found."} onRetry={load} />

  const strongestBySkill = strongestProjectBySkill(passport)
  // Prominent user-facing copy uses the clean, deduplicated attachment-overview
  // count (duplicate rows of the same proof collapsed) so it never contradicts
  // the vault overview. The raw vault_unattached_count is kept only for
  // backward-compatible payloads, not headline copy.
  const unattachedCount =
    passport.attachment_overview?.unattached_count ?? passport.vault_unattached_count ?? 0
  const hasVault =
    (passport.vault_proof_count ?? 0) > 0 || (passport.vault_unattached_count ?? 0) > 0

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 1 — Vault overview: counts + next actions */}
      <VaultOverviewCard passport={passport} />

      {/* 2 — Proof Attachment Intelligence: suggested attachments, projects to
          strengthen, skills with unattached evidence (owner-only, review-only). */}
      <ProofAttachmentIntelligenceCard passport={passport} />

      {/* 3 — Skill Intelligence: every proof grouped by canonical skill into
          COMPACT cards; the full stored evidence for one skill loads lazily on
          the Skill Report page. */}
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

      {/* 4 — Evidence Vault: attached / suggested / unattached proof entries */}
      {hasVault && (
        <Card>
          <div data-testid="evidence-vault-section" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <CardHeader title="Evidence Vault" eyebrow="Unattached proof management" icon="🗄️" />
            {/* Attached / Suggested / Unattached — deduplicated, clearly separated
                sections. Suggested evidence is never counted until attached. */}
            <AttachmentOverviewSection overview={passport.attachment_overview} />
          </div>
        </Card>
      )}
    </div>
  )
}
