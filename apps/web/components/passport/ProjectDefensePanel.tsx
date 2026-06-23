"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
  clearProjectDefenseDraft,
  readProjectDefenseDraft,
  saveProjectDefenseDraft,
  type ProjectDefenseDraft,
} from "./project-defense-draft"
import {
  createProjectDefense,
  generateDefenseQuestions,
  getVBRSession,
  getVBRSessionRecordingReadiness,
  submitDefenseAnswers,
  syncProjectDefenseToSkillGraph,
  type DefenseAnalysisResponse,
  type ProjectDefenseCreateResponse,
  type SubmitDefenseAnswersResponse,
  type VBRRecordingReadinessResponse,
  type VBRSessionQuestionResponse,
  type VideoEvidenceChip,
} from "@/lib/vbr-api"
import {
  listDocumentProofs,
  listGitHubProofs,
  listWebsiteProofs,
  recommendWebsiteProofs,
  type DocumentProofResponse,
  type GitHubProofResponse,
  type RecommendedWebsiteProofResponse,
  type WebsiteProofRecommendationResponse,
  type WebsiteProofSummaryResponse,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  ErrorState,
  LoadingState,
  Mono,
  ProgressBar,
  TOKEN,
} from "./shared"

type AnswerMode = "combined" | "per_question"

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  border: `1px solid ${TOKEN.line}`,
  borderRadius: 8,
  fontSize: 13,
  background: TOKEN.paper,
  boxSizing: "border-box",
}

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: TOKEN.inkSoft,
  display: "block",
  marginBottom: 4,
}

function QuestionCard({ question }: { question: VBRSessionQuestionResponse }) {
  const kind = String(question.target_ref?.kind || "")
  const skill = question.target_ref?.skill ? String(question.target_ref.skill) : null
  return (
    <div style={{ padding: "10px 12px", border: `1px solid ${TOKEN.line}`, borderRadius: 8, background: TOKEN.bg }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
        {kind && <Badge tone="slate">{kind.replace(/_/g, " ")}</Badge>}
        {skill && <Badge tone="indigo">{skill}</Badge>}
      </div>
      <p style={{ fontSize: 13, color: TOKEN.ink, margin: 0, lineHeight: 1.5 }}>{question.question_text}</p>
    </div>
  )
}

function ScoreStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
          {label}
        </Mono>
        <Mono style={{ fontSize: 11, color: TOKEN.inkSoft, fontWeight: 700 }}>{value}/100</Mono>
      </div>
      <ProgressBar value={value} />
    </div>
  )
}

type EvidenceStatusTone = "slate" | "emerald" | "amber"

type VideoDefenseStatus = "not_started" | "checking" | "storage_not_configured" | "ready" | "recorded"

const VIDEO_DEFENSE_STATUS: Record<VideoDefenseStatus, { label: string; tone: EvidenceStatusTone }> = {
  not_started: { label: "Not started", tone: "slate" },
  checking: { label: "Checking…", tone: "slate" },
  storage_not_configured: { label: "Storage not configured", tone: "amber" },
  ready: { label: "Ready to record", tone: "emerald" },
  recorded: { label: "Recorded", tone: "emerald" },
}

function EvidenceStatusCard({
  label,
  status,
  tone,
}: {
  label: string
  status: string
  tone: EvidenceStatusTone
}) {
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
      }}
    >
      <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
        {label}
      </Mono>
      <Badge tone={tone}>{status}</Badge>
    </div>
  )
}

function VideoEvidenceSection({ chips }: { chips: VideoEvidenceChip[] }) {
  return (
    <div>
      <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
        Video Evidence
      </Mono>
      {chips.length === 0 ? (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>
          Timestamped evidence will appear after transcript analysis.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          {chips.map((chip, i) => (
            <div
              key={`${chip.label}-${i}`}
              data-testid="video-evidence-chip"
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 8,
                fontSize: 12,
                color: TOKEN.inkSoft,
                lineHeight: 1.4,
              }}
            >
              <Mono style={{ fontSize: 11, color: TOKEN.ink, whiteSpace: "nowrap" }}>{chip.label}</Mono>
              <span>— {chip.short_summary}</span>
              {chip.related_skill && <Badge tone="slate">{chip.related_skill}</Badge>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function AnalysisResults({
  analysis,
  videoEvidenceChips,
  syncStatus,
  syncSkills,
  onSync,
}: {
  analysis: DefenseAnalysisResponse
  videoEvidenceChips: VideoEvidenceChip[]
  syncStatus: "idle" | "syncing" | "saved" | "error"
  syncSkills: string[]
  onSync: () => void
}) {
  return (
    <Card style={{ border: `1px solid ${TOKEN.indigo}40`, background: TOKEN.indigoSoft }}>
      <CardHeader title="Project Defense Analysis" eyebrow="Step E · Deterministic analysis" icon="📊" />

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <ScoreStat label="Overall Defense Score" value={analysis.overall_defense_score} />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <ScoreStat label="Ownership signal" value={analysis.ownership_signal_score} />
          <ScoreStat label="Technical depth" value={analysis.technical_depth_score} />
          <ScoreStat label="Explanation clarity" value={analysis.explanation_clarity_score} />
          <ScoreStat label="Consistency with evidence" value={analysis.consistency_with_evidence_score} />
        </div>

        {analysis.recruiter_summary && (
          <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            {analysis.recruiter_summary}
          </p>
        )}

        {analysis.skills_mentioned.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Skills Mentioned
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {analysis.skills_mentioned.map((s) => (
                <Badge key={s} tone={analysis.skills_explained_well.includes(s) ? "emerald" : "slate"}>
                  {s}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {analysis.skills_missing_from_explanation.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Claimed Skills Not Yet Explained
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {analysis.skills_missing_from_explanation.map((s) => (
                <Badge key={s} tone="amber">{s}</Badge>
              ))}
            </div>
          </div>
        )}

        {analysis.recommended_improvements.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Suggested Improvements
            </Mono>
            <ul style={{ margin: "4px 0 0", padding: "0 0 0 14px" }}>
              {analysis.recommended_improvements.map((s, i) => (
                <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft, marginBottom: 2 }}>{s}</li>
              ))}
            </ul>
          </div>
        )}

        {analysis.risk_flags.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.rose, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Risk Flags
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {analysis.risk_flags.map((s, i) => (
                <Badge key={i} tone="rose">{s}</Badge>
              ))}
            </div>
          </div>
        )}

        <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
          Privacy scan: {analysis.privacy_scan_status}
        </Mono>

        <VideoEvidenceSection chips={videoEvidenceChips} />

        <div style={{ borderTop: `1px solid ${TOKEN.line}`, paddingTop: 12 }}>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 8px" }}>
            This explanation can be saved as supporting project defense evidence on your Skill Graph. It
            stays separate from your GitHub, website, and document proof — it never overwrites or
            downgrades stronger evidence you already have.
          </p>
          {syncStatus !== "saved" && (
            <Btn variant="primary" onClick={onSync} disabled={syncStatus === "syncing"}>
              {syncStatus === "syncing" ? "Saving…" : "Save explanation evidence to Skill Graph"}
            </Btn>
          )}
          {syncStatus === "saved" && (
            <Mono style={{ fontSize: 12, color: TOKEN.emerald }}>
              ✓ Saved as supporting evidence for {syncSkills.join(", ") || "your claimed skills"}
            </Mono>
          )}
          {syncStatus === "error" && (
            <Mono style={{ fontSize: 11, color: TOKEN.rose, display: "block", marginTop: 6 }}>
              Couldn&apos;t save to Skill Graph. Try again.
            </Mono>
          )}
        </div>
      </div>
    </Card>
  )
}

// ── Website Proof recommendation (deterministic, no AI) ──────────────────────
//
// Saved Website Proofs live at the account level, so a student's Project Defense
// form would otherwise dump every unrelated proof (threejs.org, tensorflow.org,
// generic docs) as if they were all recommendations. We rank saved proofs
// against the project the student is actually describing using simple word/URL
// overlap, and deprioritise generic doc/playground sites unless the project
// explicitly names them.

export type WebsiteProofMatchTier = "recommended" | "possible" | "other"

export type WebsiteProofMatchContext = {
  title: string
  description: string
  repoUrl: string
  studentRole: string
  claimedSkills: string[]
}

export type RankedWebsiteProof = {
  proof: WebsiteProofSummaryResponse
  tier: WebsiteProofMatchTier
  score: number
}

// Generic docs / playgrounds that are almost never the student's own project.
// Only treated as relevant when the project explicitly names the tool.
const GENERIC_WEBSITE_PROOF_DOMAINS = new Set([
  "teachablemachine.withgoogle.com",
  "vega.github.io",
  "threejs.org",
  "tensorflow.org",
  "playground.tensorflow.org",
  "ml5js.org",
  "observablehq.com",
  "p5js.org",
])

const STOP_DOMAIN_TOKENS = new Set([
  "com", "org", "net", "io", "dev", "app", "www", "co", "ai", "xyz",
  "github", "gitlab", "bitbucket", "vercel", "netlify", "pages", "herokuapp",
  "web", "withgoogle", "firebaseapp", "render", "fly",
])

// Generic words that, on their own, carry no project-specific signal. Generic
// skill overlap (e.g. "Machine Learning", "API") must never promote a saved
// Website Proof to a recommended/possible match — only project-specific
// keywords from the title/description/repo do. Mirrors the backend vocabulary.
const GENERIC_TOKENS = new Set([
  "website", "proof", "app", "apps", "demo", "project", "projects", "data",
  "api", "apis", "cloud", "google", "machine", "learning", "analysis",
  "high", "medium", "low", "confidence", "web", "site", "online", "platform",
  "tool", "tools", "system", "systems", "application",
  "the", "and", "for", "with", "that", "this", "you", "your", "its", "not",
  "only", "but", "use", "uses", "using", "used", "into", "instead", "than",
  "then", "over", "more", "are", "was", "were", "has", "have", "had", "their",
  "them", "they", "can", "will", "just", "also", "such", "like", "via", "per",
  "etc", "from", "out", "our",
])

// Library "dot-suffix" spellings (three.js, d3.js, node.ts, …) collapse their
// leading dot so "Three.js", "three.js", "threejs" and the "threejs" label in
// threejs.org all normalise to the same token. Mirrors the backend so a Three.js
// project recommends its threejs.org Website Proof. Real domain separators
// (".org", ".com") are left intact.
const LIB_SUFFIX_RE = /\.(js|jsx|mjs|cjs|ts|tsx)\b/g

function proofWords(text: string): string[] {
  return (
    (text || "")
      .toLowerCase()
      .replace(LIB_SUFFIX_RE, "$1")
      .match(/[a-z0-9]+/g)
      ?.filter((w) => w.length >= 3) ?? []
  )
}

/** Project-specific tokens — generic words stripped so they can't drive matches. */
function projectSpecificTokens(context: WebsiteProofMatchContext): Set<string> {
  const words = proofWords(
    [context.title, context.description, context.repoUrl, context.studentRole, context.claimedSkills.join(" ")].join(
      " ",
    ),
  )
  return new Set(words.filter((w) => !GENERIC_TOKENS.has(w)))
}

/**
 * Does the form have enough project-specific input to attempt proof matching?
 *
 * Saved Document Proofs live at the account level, so before the student has
 * described their project we have no meaningful basis to recommend (or to claim
 * "no match"). We require at least one project-specific signal: a real title, a
 * non-trivial description, a repo URL, or at least one non-generic claimed skill.
 */
export function hasEnoughProjectContext(context: WebsiteProofMatchContext): boolean {
  if (context.title.trim().length > 2) return true
  if (context.description.trim().length > 8) return true
  if (context.repoUrl.trim().length > 8) return true
  const skillTokens = proofWords(context.claimedSkills.join(" ")).filter((w) => !GENERIC_TOKENS.has(w))
  return skillTokens.length > 0
}

function proofDomainOf(url: string): string {
  const raw = (url || "").trim()
  try {
    return new URL(raw).hostname.replace(/^www\./, "").toLowerCase()
  } catch {
    return raw
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split("/")[0]
  }
}

/**
 * Rank saved Website Proofs against the project the student is describing.
 * Deterministic word/URL overlap only — never an AI/network call. Deduplicates
 * proofs that share the same normalized target URL (keeping the strongest).
 */
export function rankWebsiteProofs(
  proofs: WebsiteProofSummaryResponse[],
  context: WebsiteProofMatchContext,
): RankedWebsiteProof[] {
  // Deduplicate repeated URLs — keep the highest evidence-strength session.
  const byUrl = new Map<string, WebsiteProofSummaryResponse>()
  for (const proof of proofs) {
    const key = proofDomainOf(proof.target_website) + "|" + (proof.target_website || "").trim().toLowerCase()
    const existing = byUrl.get(key)
    if (!existing || (proof.evidence_strength_score ?? 0) > (existing.evidence_strength_score ?? 0)) {
      byUrl.set(key, proof)
    }
  }

  // Project-specific keywords only. Generic words (incl. generic skills) are
  // stripped, so generic skill overlap alone can never promote a proof.
  const projectTokens = projectSpecificTokens(context)

  const ranked = Array.from(byUrl.values()).map((proof): RankedWebsiteProof => {
    let projectScore = 0
    const matched = new Set<string>()

    const domain = proofDomainOf(proof.target_website)
    const url = (proof.target_website || "").toLowerCase()
    const isGeneric = GENERIC_WEBSITE_PROOF_DOMAINS.has(domain)

    // Project-specific keyword appearing as a domain label — strongest signal.
    const domainTokens = proofWords(domain).filter(
      (w) => !STOP_DOMAIN_TOKENS.has(w) && !GENERIC_TOKENS.has(w),
    )
    for (const token of domainTokens) {
      if (projectTokens.has(token) && !matched.has(token)) {
        projectScore += 2
        matched.add(token)
      }
    }

    // Project-specific keyword appearing anywhere in the URL (repo/deploy name).
    for (const token of projectTokens) {
      if (token.length >= 4 && url.includes(token) && !matched.has(token)) {
        projectScore += 1
        matched.add(token)
      }
    }

    // Known docs/playgrounds only count when the project clearly names them.
    if (isGeneric && projectScore < 2) projectScore = 0

    // Skill overlap is a tiebreaker for ordering only — it never sets the tier.
    let skillOverlap = 0
    for (const skill of proof.supported_skills ?? []) {
      const skillWords = proofWords(skill).filter((w) => !GENERIC_TOKENS.has(w))
      if (skillWords.some((w) => projectTokens.has(w))) skillOverlap += 1
    }

    const tier: WebsiteProofMatchTier =
      projectScore >= 2 ? "recommended" : projectScore === 1 ? "possible" : "other"
    return { proof, tier, score: projectScore * 10 + skillOverlap }
  })

  ranked.sort(
    (a, b) => b.score - a.score || (b.proof.evidence_strength_score ?? 0) - (a.proof.evidence_strength_score ?? 0),
  )
  return ranked
}

/** Map backend recommendation groups into the local RankedWebsiteProof shape. */
function rankedFromBackend(groups: WebsiteProofRecommendationResponse): RankedWebsiteProof[] {
  const out: RankedWebsiteProof[] = []
  const push = (rows: RecommendedWebsiteProofResponse[], tier: WebsiteProofMatchTier, base: number) => {
    rows.forEach((proof, i) => out.push({ proof, tier, score: base - i }))
  }
  push(groups.recommended_website_proofs, "recommended", 300)
  push(groups.possible_website_proofs, "possible", 200)
  push(groups.other_website_proofs, "other", 100)
  return out
}

const WEBSITE_PROOF_NEW_PATH = "/student/proofs/website"

// Where the proof-studio pages send the student back to after they add a new
// proof. Passed as a safe internal `returnTo` query param (validated on arrival).
const PROJECT_DEFENSE_RETURN_PATH = "/student/proofs/project-defense"

const TIER_BADGE: Record<WebsiteProofMatchTier, { label: string; tone: "emerald" | "amber" | "slate" }> = {
  recommended: { label: "Recommended", tone: "emerald" },
  possible: { label: "Possible match", tone: "amber" },
  other: { label: "Other saved website proof", tone: "slate" },
}

function WebsiteProofRow({
  ranked,
  selected,
  onToggle,
}: {
  ranked: RankedWebsiteProof
  selected: boolean
  onToggle: (id: string) => void
}) {
  const { proof, tier } = ranked
  return (
    <label
      style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: TOKEN.inkSoft }}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={() => onToggle(proof.proof_session_id)}
      />
      <span>
        {proof.target_website || "Website proof"} — {proof.workflow_confidence} confidence
      </span>
      <Badge tone={TIER_BADGE[tier].tone}>{TIER_BADGE[tier].label}</Badge>
    </label>
  )
}

function WebsiteProofSelector({
  proofs,
  selectedIds,
  onToggle,
  context,
}: {
  proofs: WebsiteProofSummaryResponse[]
  selectedIds: string[]
  onToggle: (id: string) => void
  context: WebsiteProofMatchContext
}) {
  const [search, setSearch] = useState("")

  // Deterministic local ranking — used immediately and as the fallback when the
  // backend recommendation endpoint is unavailable.
  const localRanked = useMemo(() => rankWebsiteProofs(proofs, context), [proofs, context])

  // Backend-supported recommendation groups (authoritative when available).
  const [backendRanked, setBackendRanked] = useState<RankedWebsiteProof[] | null>(null)
  const contextKey = JSON.stringify({
    t: context.title,
    d: context.description,
    r: context.repoUrl,
    s: context.claimedSkills,
  })

  useEffect(() => {
    if (typeof recommendWebsiteProofs !== "function" || proofs.length === 0) {
      setBackendRanked(null)
      return
    }
    let active = true
    const handle = setTimeout(() => {
      recommendWebsiteProofs({
        project_title: context.title,
        project_description: context.description,
        repo_url: context.repoUrl,
        claimed_skills: context.claimedSkills,
      })
        .then((groups: WebsiteProofRecommendationResponse) => {
          if (active) setBackendRanked(rankedFromBackend(groups))
        })
        .catch(() => {
          if (active) setBackendRanked(null)
        })
    }, 300)
    return () => {
      active = false
      clearTimeout(handle)
    }
    // contextKey captures the safe project fields the backend ranks against.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextKey, proofs])

  const ranked = backendRanked ?? localRanked

  const query = search.trim().toLowerCase()
  const filtered = query
    ? ranked.filter((r) => {
        const url = (r.proof.target_website || "").toLowerCase()
        const skills = (r.proof.supported_skills ?? []).join(" ").toLowerCase()
        return url.includes(query) || skills.includes(query)
      })
    : ranked

  const recommended = filtered.filter((r) => r.tier === "recommended")
  const possible = filtered.filter((r) => r.tier === "possible")
  const other = filtered.filter((r) => r.tier === "other")
  const top = [...recommended, ...possible]

  const addHref =
    `${WEBSITE_PROOF_NEW_PATH}?returnTo=${PROJECT_DEFENSE_RETURN_PATH}&from=project-defense` +
    (context.title ? `&title=${encodeURIComponent(context.title)}` : "") +
    (context.repoUrl ? `&repo=${encodeURIComponent(context.repoUrl)}` : "")

  // With many saved proofs, the unranked "other" list is collapsed by default so
  // the student isn't shown one giant confusing list.
  const collapseOtherByDefault = ranked.length > 8 || top.length > 0

  return (
    <div>
      <label style={labelStyle}>Attach website proof (optional)</label>
      <p style={{ fontSize: 11, color: TOKEN.muted, margin: "0 0 8px" }}>
        Attach a recommended saved proof, continue without one, or add a new Website Proof for this
        project. These are saved Website Proof sessions — they are not re-verified here.
      </p>

      {proofs.length >= 5 && (
        <input
          type="text"
          aria-label="Search saved website proofs by URL or skill"
          placeholder="Search saved website proofs by URL or skill…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ ...inputStyle, marginBottom: 10 }}
        />
      )}

      {top.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {recommended.length > 0 && (
            <div>
              <Mono
                style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}
              >
                Recommended Website Proofs
              </Mono>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
                {recommended.map((r) => (
                  <WebsiteProofRow
                    key={r.proof.proof_session_id}
                    ranked={r}
                    selected={selectedIds.includes(r.proof.proof_session_id)}
                    onToggle={onToggle}
                  />
                ))}
              </div>
            </div>
          )}
          {possible.length > 0 && (
            <div>
              <Mono
                style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}
              >
                Possible matches
              </Mono>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
                {possible.map((r) => (
                  <WebsiteProofRow
                    key={r.proof.proof_session_id}
                    ranked={r}
                    selected={selectedIds.includes(r.proof.proof_session_id)}
                    onToggle={onToggle}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        !query && (
          <p
            style={{
              fontSize: 12,
              color: TOKEN.inkSoft,
              background: TOKEN.bg,
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 6,
              padding: "8px 10px",
              margin: "0 0 4px",
            }}
          >
            No matching Website Proof found for this project. You can continue without one or add a new
            Website Proof.
          </p>
        )
      )}

      {query && filtered.length === 0 && (
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0" }}>
          No saved Website Proof matches “{search.trim()}”.
        </p>
      )}

      {other.length > 0 && (
        <details open={!collapseOtherByDefault} style={{ marginTop: 10 }}>
          <summary style={{ fontSize: 12, color: TOKEN.indigo, cursor: "pointer" }}>
            Browse all saved Website Proofs ({other.length})
          </summary>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
            {other.map((r) => (
              <WebsiteProofRow
                key={r.proof.proof_session_id}
                ranked={r}
                selected={selectedIds.includes(r.proof.proof_session_id)}
                onToggle={onToggle}
              />
            ))}
          </div>
        </details>
      )}

      <p style={{ fontSize: 12, color: TOKEN.muted, margin: "10px 0 0" }}>
        No relevant website proof?{" "}
        <Link href={addHref} style={{ color: TOKEN.indigo, textDecoration: "none", fontWeight: 600 }}>
          Add a new Website Proof
        </Link>
      </p>
    </div>
  )
}

// ── Document Proof recommendation (deterministic, no AI) ─────────────────────
//
// Saved Document Proofs also live at the account level, so the Project Defense
// form previously dumped every saved document as a flat list — which looked
// hardcoded (e.g. always the Boston documents) regardless of the project being
// defended. We group them like Website Proofs: documents whose safe metadata
// (title / filename / description / claimed skills) shares a project-specific
// keyword are Recommended; the rest collapse under "Browse all". Only safe
// summary fields are read — never raw document text, files, or storage paths.

const DOCUMENT_PROOF_NEW_PATH = "/student/proofs/documents"

export type DocumentProofMatchTier = "recommended" | "other"

export type RankedDocumentProof = {
  doc: DocumentProofResponse
  tier: DocumentProofMatchTier
  score: number
  matched: string[]
}

/** Project-specific tokens from a document's safe metadata only. */
function documentSpecificTokens(doc: DocumentProofResponse): Set<string> {
  const words = proofWords(
    [doc.title ?? "", doc.filename ?? "", doc.description ?? "", (doc.claimed_skills ?? []).join(" ")].join(" "),
  )
  return new Set(words.filter((w) => !GENERIC_TOKENS.has(w)))
}

/**
 * Rank saved Document Proofs against the project being described. Deterministic
 * project-keyword overlap only (generic words/skills stripped, so generic skill
 * overlap alone never recommends a document). Reads safe metadata only.
 */
export function rankDocumentProofs(
  docs: DocumentProofResponse[],
  context: WebsiteProofMatchContext,
): RankedDocumentProof[] {
  const projectTokens = projectSpecificTokens(context)
  const ranked = docs.map((doc): RankedDocumentProof => {
    const matched: string[] = []
    for (const token of documentSpecificTokens(doc)) {
      if (projectTokens.has(token) && !matched.includes(token)) matched.push(token)
    }
    const tier: DocumentProofMatchTier = matched.length >= 1 ? "recommended" : "other"
    return { doc, tier, score: matched.length, matched }
  })
  ranked.sort((a, b) => b.score - a.score)
  return ranked
}

function DocumentProofRow({
  doc,
  selected,
  onToggle,
}: {
  doc: DocumentProofResponse
  selected: boolean
  onToggle: (id: string) => void
}) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: TOKEN.inkSoft }}>
      <input type="checkbox" checked={selected} onChange={() => onToggle(doc.id)} />
      {doc.title || doc.filename || "Untitled document"}
    </label>
  )
}

function DocumentProofSelector({
  docs,
  selectedIds,
  onToggle,
  context,
}: {
  docs: DocumentProofResponse[]
  selectedIds: string[]
  onToggle: (id: string) => void
  context: WebsiteProofMatchContext
}) {
  const ranked = useMemo(() => rankDocumentProofs(docs, context), [docs, context])
  const recommended = ranked.filter((r) => r.tier === "recommended")
  const other = ranked.filter((r) => r.tier === "other")

  // Until the student has described their project, we have no meaningful basis to
  // recommend documents or to claim "no match". Without enough context we keep
  // every saved document collapsed behind "Browse all" and show only guidance —
  // so unrelated saved documents never look hardcoded/random on a blank form.
  const hasContext = hasEnoughProjectContext(context)

  // Add-new link carries a safe internal returnTo so the student lands back on
  // Project Defense after creating a Document Proof.
  const addHref = `${DOCUMENT_PROOF_NEW_PATH}?returnTo=${PROJECT_DEFENSE_RETURN_PATH}`

  return (
    <div>
      <label style={labelStyle}>Attach document proof (optional)</label>
      <p style={{ fontSize: 11, color: TOKEN.muted, margin: "0 0 8px" }}>
        Attach a recommended saved document, continue without one, or add a new Document Proof for this
        project. Document proof is optional.
      </p>

      {!hasContext ? (
        <p
          style={{
            fontSize: 12,
            color: TOKEN.inkSoft,
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 6,
            padding: "8px 10px",
            margin: "0 0 4px",
          }}
        >
          Add project details to find matching Document Proofs.
        </p>
      ) : recommended.length > 0 ? (
        <div>
          <Mono
            style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}
          >
            Recommended Document Proofs
          </Mono>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
            {recommended.map((r) => (
              <DocumentProofRow
                key={r.doc.id}
                doc={r.doc}
                selected={selectedIds.includes(r.doc.id)}
                onToggle={onToggle}
              />
            ))}
          </div>
        </div>
      ) : (
        <p
          style={{
            fontSize: 12,
            color: TOKEN.inkSoft,
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 6,
            padding: "8px 10px",
            margin: "0 0 4px",
          }}
        >
          No matching Document Proof found for this project. Document proof is optional — you can
          continue without one or add a new Document Proof.
        </p>
      )}

      {other.length > 0 && (
        // Other saved documents are always collapsed so the selector never looks
        // like a hardcoded dump of every saved document. Before there is enough
        // project context, every saved document lives here (collapsed).
        <details style={{ marginTop: 10 }}>
          <summary style={{ fontSize: 12, color: TOKEN.indigo, cursor: "pointer" }}>
            Browse all saved Document Proofs ({other.length})
          </summary>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
            {other.map((r) => (
              <DocumentProofRow
                key={r.doc.id}
                doc={r.doc}
                selected={selectedIds.includes(r.doc.id)}
                onToggle={onToggle}
              />
            ))}
          </div>
        </details>
      )}

      <p style={{ fontSize: 12, color: TOKEN.muted, margin: "10px 0 0" }}>
        No relevant document proof?{" "}
        <Link
          href={addHref}
          style={{ color: TOKEN.indigo, textDecoration: "none", fontWeight: 600 }}
        >
          Add a new Document Proof
        </Link>
      </p>
    </div>
  )
}

export function ProjectDefensePanel() {
  const router = useRouter()

  // Step A/B — project identity + attached proofs
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [claimedSkills, setClaimedSkills] = useState("")
  const [studentRole, setStudentRole] = useState("")
  const [repoUrl, setRepoUrl] = useState("")
  const [selectedGithubProofId, setSelectedGithubProofId] = useState("")
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [selectedWebsiteProofIds, setSelectedWebsiteProofIds] = useState<string[]>([])

  // Draft restore — when the student leaves to add a Document/Website Proof and
  // returns, the form is rehydrated from sessionStorage. `hydrated` gates the
  // save effect so it never overwrites a saved draft with the empty initial
  // state on first mount (before restoration has run).
  const [hydrated, setHydrated] = useState(false)

  const [githubProofs, setGithubProofs] = useState<GitHubProofResponse[] | null>(null)
  const [documentProofs, setDocumentProofs] = useState<DocumentProofResponse[] | null>(null)
  const [websiteProofs, setWebsiteProofs] = useState<WebsiteProofSummaryResponse[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [created, setCreated] = useState<ProjectDefenseCreateResponse | null>(null)

  // Step C — generated questions
  const [questions, setQuestions] = useState<VBRSessionQuestionResponse[] | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)

  // Step D — answers
  const [answerMode, setAnswerMode] = useState<AnswerMode>("combined")
  const [combinedText, setCombinedText] = useState("")
  const [perQuestionAnswers, setPerQuestionAnswers] = useState<Record<string, string>>({})

  // Step E — analysis
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<SubmitDefenseAnswersResponse | null>(null)

  // Step F — sync
  const [syncStatus, setSyncStatus] = useState<"idle" | "syncing" | "saved" | "error">("idle")
  const [syncSkills, setSyncSkills] = useState<string[]>([])

  // Project Evidence Package — Video Defense recording status
  const [recordingReadiness, setRecordingReadiness] = useState<VBRRecordingReadinessResponse | null>(null)
  const [recordingChunkCount, setRecordingChunkCount] = useState(0)

  useEffect(() => {
    if (!sessionId) return
    let active = true
    Promise.all([getVBRSessionRecordingReadiness(sessionId), getVBRSession(sessionId)])
      .then(([readiness, session]) => {
        if (!active) return
        setRecordingReadiness(readiness)
        setRecordingChunkCount(session?.chunk_count ?? 0)
      })
      .catch(() => {
        if (active) {
          setRecordingReadiness({ ready: false, code: null, message: "Recording status is unavailable." })
        }
      })
    return () => {
      active = false
    }
  }, [sessionId])

  useEffect(() => {
    // VBR uses the repo-wise GitHub Proof submissions (one proof per repo),
    // not the whole-account/profile GitHub scan.
    Promise.all([listGitHubProofs(), listDocumentProofs(), listWebsiteProofs()])
      .then(([gh, docs, websites]) => {
        setGithubProofs(gh.filter((p) => p.status === "analyzed" || p.status === "needs_more_evidence"))
        setDocumentProofs(docs.filter((d) => d.status === "analyzed"))
        setWebsiteProofs(websites)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  // Restore a saved draft once on mount (browser-only). Selected proof IDs are
  // kept even if the matching proof isn't in the freshly loaded list yet — the
  // checkbox simply re-checks once that proof renders.
  useEffect(() => {
    const draft = readProjectDefenseDraft()
    if (draft) {
      setTitle(draft.projectTitle)
      setDescription(draft.description)
      setClaimedSkills(draft.claimedSkills)
      setStudentRole(draft.roleContribution)
      setRepoUrl(draft.repositoryUrl)
      setSelectedGithubProofId(draft.selectedGithubProofId)
      setSelectedDocumentIds(draft.selectedDocumentIds)
      setSelectedWebsiteProofIds(draft.selectedWebsiteProofIds)
    }
    setHydrated(true)
  }, [])

  // Persist the draft on every form change so leaving to add a Document/Website
  // Proof (a full route change) never loses the entered details. Only safe form
  // values + selected IDs are stored. Skipped until hydration completes, and not
  // re-saved once the defense is created (the form is gone and the draft cleared).
  useEffect(() => {
    if (!hydrated || created) return
    const draft: ProjectDefenseDraft = {
      projectTitle: title,
      description,
      claimedSkills,
      roleContribution: studentRole,
      repositoryUrl: repoUrl,
      selectedGithubProofId,
      selectedDocumentIds,
      selectedWebsiteProofIds,
    }
    saveProjectDefenseDraft(draft)
  }, [
    hydrated,
    created,
    title,
    description,
    claimedSkills,
    studentRole,
    repoUrl,
    selectedGithubProofId,
    selectedDocumentIds,
    selectedWebsiteProofIds,
  ])

  const claimedSkillsList = () => claimedSkills.split(",").map((s) => s.trim()).filter(Boolean)

  const hasDraftContent =
    !!title.trim() ||
    !!description.trim() ||
    !!claimedSkills.trim() ||
    !!studentRole.trim() ||
    !!repoUrl.trim() ||
    !!selectedGithubProofId ||
    selectedDocumentIds.length > 0 ||
    selectedWebsiteProofIds.length > 0

  const handleClearDraft = () => {
    clearProjectDefenseDraft()
    setTitle("")
    setDescription("")
    setClaimedSkills("")
    setStudentRole("")
    setRepoUrl("")
    setSelectedGithubProofId("")
    setSelectedDocumentIds([])
    setSelectedWebsiteProofIds([])
    setCreateError(null)
  }

  const selectedGithubProof = githubProofs?.find((p) => p.id === selectedGithubProofId) ?? null

  const toggleDocument = (id: string) => {
    setSelectedDocumentIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  const toggleWebsiteProof = (id: string) => {
    setSelectedWebsiteProofIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  const handleCreate = async () => {
    setCreating(true)
    setCreateError(null)
    try {
      if (!title.trim()) {
        setCreateError("Give your project a title.")
        return
      }
      const response = await createProjectDefense({
        title: title.trim(),
        description: description.trim(),
        claimed_skills: claimedSkillsList(),
        student_role: studentRole.trim(),
        repo_url: selectedGithubProof ? null : repoUrl.trim() || null,
        attached_proofs: {
          github_proof_id: selectedGithubProofId || null,
          document_evidence_ids: selectedDocumentIds,
          website_proof_session_ids: selectedWebsiteProofIds,
        },
      })
      setCreated(response)
      // The defense now exists — the working draft has served its purpose.
      clearProjectDefenseDraft()
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : "Failed to create project defense.")
    } finally {
      setCreating(false)
    }
  }

  const handleGenerateQuestions = async () => {
    if (!created) return
    setGenerating(true)
    setGenerateError(null)
    try {
      const response = await generateDefenseQuestions(created.project.id)
      setQuestions(response.questions)
      setSessionId(response.session_id)
    } catch (e: unknown) {
      setGenerateError(e instanceof Error ? e.message : "Failed to generate defense questions.")
    } finally {
      setGenerating(false)
    }
  }

  const handleSubmitAnswers = async () => {
    if (!sessionId) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const body =
        answerMode === "combined"
          ? { combined_text: combinedText.trim() || null }
          : {
              answers: Object.entries(perQuestionAnswers)
                .filter(([, text]) => text.trim())
                .map(([questionId, text]) => ({ question_id: questionId, answer_text: text.trim() })),
            }
      const response = await submitDefenseAnswers(sessionId, body)
      setResult(response)
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Failed to submit defense answers.")
    } finally {
      setSubmitting(false)
    }
  }

  const handleSync = async () => {
    if (!sessionId) return
    setSyncStatus("syncing")
    try {
      const response = await syncProjectDefenseToSkillGraph(sessionId)
      if (response.ok && response.errors.length === 0) {
        setSyncSkills(response.skills_synced)
        setSyncStatus("saved")
      } else {
        setSyncStatus("error")
      }
    } catch {
      setSyncStatus("error")
    }
  }

  const attachedSummary = created?.metadata.attached_proofs ?? {}
  const githubAttached = attachedSummary["github_proof"] as
    | {
        repo_url?: string
        repo_owner?: string
        repo_name?: string
        status?: string
        detected_skills?: string[]
        public_safe_summary?: string
      }
    | undefined
  const documentsAttached = attachedSummary["documents"] as Array<{ title?: string }> | undefined
  const websiteProofsAttached = attachedSummary["website_proofs"] as
    | Array<{ target_website?: string; workflow_confidence?: string; evidence_strength_score?: number }>
    | undefined

  // Project Evidence Package — derived checklist statuses
  const githubProofAttached = !!githubAttached?.repo_url
  const documentsCount = documentsAttached?.length ?? 0
  const websiteProofsCount = websiteProofsAttached?.length ?? 0
  const analysisCompleted = !!result
  const skillGraphSaved = syncStatus === "saved"

  const videoDefenseStatus: VideoDefenseStatus = !sessionId
    ? "not_started"
    : recordingReadiness === null
      ? "checking"
      : recordingChunkCount > 0
        ? "recorded"
        : recordingReadiness.ready
          ? "ready"
          : "storage_not_configured"

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Project Defense</h2>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
          Explain your individual contribution to a project in your own words. VeriBridge generates
          deterministic defense questions from your attached proof, and the answers become supporting
          project defense evidence on your Skill Graph.
        </p>
      </div>

      {loadError && <ErrorState message={loadError} />}

      {/* Step A/B — Project identity + attached proofs */}
      {!created && (
        <Card>
          <CardHeader title="Project identity" eyebrow="Step A · Tell us about your project" icon="🧩" />
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={labelStyle}>Project title *</label>
              <input
                type="text"
                placeholder="e.g. Skill Evidence Tracker"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                style={inputStyle}
              />
            </div>

            <div>
              <label style={labelStyle}>Description (optional)</label>
              <textarea
                placeholder="What does this project do?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>

            <div>
              <label style={labelStyle}>Claimed skills (comma-separated)</label>
              <input
                type="text"
                placeholder="Python, React, PostgreSQL"
                value={claimedSkills}
                onChange={(e) => setClaimedSkills(e.target.value)}
                style={inputStyle}
              />
            </div>

            <div>
              <label style={labelStyle}>Your role / contribution (optional)</label>
              <textarea
                placeholder="What part of this project did you build?"
                value={studentRole}
                onChange={(e) => setStudentRole(e.target.value)}
                rows={2}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>

            {githubProofs !== null && githubProofs.length > 0 && (
              <div>
                <label style={labelStyle} htmlFor="project-defense-github-proof">Attach a GitHub proof (optional)</label>
                <select
                  id="project-defense-github-proof"
                  value={selectedGithubProofId}
                  onChange={(e) => setSelectedGithubProofId(e.target.value)}
                  style={inputStyle}
                >
                  <option value="">— None —</option>
                  {githubProofs.map((p) => {
                    const repoLabel = p.repo_owner ? `${p.repo_owner}/${p.repo_name}` : p.repo_url
                    const statusLabel = p.evidence_strength ? `${p.status} · ${p.evidence_strength}` : p.status
                    return (
                      <option key={p.id} value={p.id}>
                        {repoLabel} — {statusLabel}
                      </option>
                    )
                  })}
                </select>
                <p style={{ fontSize: 11, color: TOKEN.muted, margin: "4px 0 0" }}>
                  This is your repo-wise GitHub Proof evidence — analyzed for one specific repository.
                </p>
              </div>
            )}

            <div>
              <label style={labelStyle} htmlFor="project-defense-repo-url">
                {selectedGithubProof
                  ? "Repository URL (from attached GitHub Proof)"
                  : "Repository URL without attached GitHub Proof *"}
              </label>
              <input
                id="project-defense-repo-url"
                type="text"
                placeholder="https://github.com/owner/repo"
                value={selectedGithubProof ? selectedGithubProof.repo_url : repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                disabled={!!selectedGithubProof}
                style={
                  selectedGithubProof
                    ? { ...inputStyle, background: TOKEN.bg, color: TOKEN.muted }
                    : inputStyle
                }
              />
              {!selectedGithubProof && (
                <p style={{ fontSize: 11, color: TOKEN.muted, margin: "4px 0 0" }}>
                  Without an attached GitHub Proof, this URL is not verified GitHub evidence — it is only
                  used as the project&apos;s repository reference.
                </p>
              )}
            </div>

            {/* Render once document proofs have finished loading, including the
                empty array — the selector shows its own grouping, an honest
                "no matching proof" empty state, and the "Add a new Document
                Proof" path. Documents are recommended only when their safe
                metadata matches the project, so the list never looks hardcoded. */}
            {documentProofs !== null && (
              <DocumentProofSelector
                docs={documentProofs}
                selectedIds={selectedDocumentIds}
                onToggle={toggleDocument}
                context={{
                  title,
                  description,
                  repoUrl: selectedGithubProof ? selectedGithubProof.repo_url : repoUrl,
                  studentRole,
                  claimedSkills: claimedSkillsList(),
                }}
              />
            )}

            {/* Render once website proofs have finished loading, including the
                empty array — the selector shows its own "no matching proof"
                empty state and the optional "Add a new Website Proof" path. */}
            {websiteProofs !== null && (
              <WebsiteProofSelector
                proofs={websiteProofs}
                selectedIds={selectedWebsiteProofIds}
                onToggle={toggleWebsiteProof}
                context={{
                  title,
                  description,
                  repoUrl: selectedGithubProof ? selectedGithubProof.repo_url : repoUrl,
                  studentRole,
                  claimedSkills: claimedSkillsList(),
                }}
              />
            )}

            {createError && (
              <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6 }}>
                {createError}
              </p>
            )}

            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Btn variant="primary" onClick={handleCreate} disabled={creating}>
                {creating ? "Creating…" : "Create project defense"}
              </Btn>
              {hasDraftContent && (
                <Btn variant="secondary" onClick={handleClearDraft} disabled={creating}>
                  Clear draft
                </Btn>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Created project summary */}
      {created && (
        <Card>
          <CardHeader title={created.project.title} eyebrow="Project identity" icon="🧩" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {created.project.repo_full_name && (
              <Mono style={{ fontSize: 12, color: TOKEN.muted }}>{created.project.repo_full_name}</Mono>
            )}
            {created.metadata.claimed_skills.length > 0 && (
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {created.metadata.claimed_skills.map((s) => (
                  <Badge key={s} tone="indigo">{s}</Badge>
                ))}
              </div>
            )}
            {githubAttached?.repo_url && (
              <div>
                <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                  GitHub proof attached:{" "}
                  {githubAttached.repo_owner && githubAttached.repo_name
                    ? `${githubAttached.repo_owner}/${githubAttached.repo_name}`
                    : githubAttached.repo_url}
                  {githubAttached.status ? ` (${githubAttached.status})` : ""}
                </Mono>
                {githubAttached.detected_skills && githubAttached.detected_skills.length > 0 && (
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
                    {githubAttached.detected_skills.map((s) => (
                      <Badge key={s} tone="emerald">{s}</Badge>
                    ))}
                  </div>
                )}
              </div>
            )}
            {!githubAttached?.repo_url && created.project.repo_full_name && (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                Repository URL without attached GitHub Proof — not verified GitHub evidence.
              </Mono>
            )}
            {documentsAttached && documentsAttached.length > 0 && (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                {documentsAttached.length} document proof{documentsAttached.length === 1 ? "" : "s"} attached
              </Mono>
            )}
            {websiteProofsAttached && websiteProofsAttached.length > 0 && (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                {websiteProofsAttached.length} website proof{websiteProofsAttached.length === 1 ? "" : "s"} attached
              </Mono>
            )}
          </div>
        </Card>
      )}

      {/* Project Evidence Package — unified checklist + attached evidence summary */}
      {created && (
        <Card>
          <CardHeader
            title="Project Evidence Package"
            eyebrow="Evidence workspace"
            icon="🗂️"
            action={
              <Btn
                size="sm"
                variant="secondary"
                onClick={() => router.push(`/student/vbr/projects/${created.project.id}/report`)}
              >
                View VBR report preview
              </Btn>
            }
          />

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
              gap: 10,
              marginBottom: 14,
            }}
          >
            <EvidenceStatusCard
              label="GitHub Proof"
              status={githubProofAttached ? "Attached" : "Missing"}
              tone={githubProofAttached ? "emerald" : "slate"}
            />
            <EvidenceStatusCard
              label="Documents"
              status={documentsCount > 0 ? `${documentsCount} attached` : "Missing"}
              tone={documentsCount > 0 ? "emerald" : "slate"}
            />
            <EvidenceStatusCard
              label="Website Proof"
              status={websiteProofsCount > 0 ? `${websiteProofsCount} attached` : "Missing"}
              tone={websiteProofsCount > 0 ? "emerald" : "slate"}
            />
            <EvidenceStatusCard
              label="Manual Project Defense"
              status={analysisCompleted ? "Completed" : "Missing"}
              tone={analysisCompleted ? "emerald" : "slate"}
            />
            <EvidenceStatusCard
              label="Video Defense"
              status={VIDEO_DEFENSE_STATUS[videoDefenseStatus].label}
              tone={VIDEO_DEFENSE_STATUS[videoDefenseStatus].tone}
            />
            <EvidenceStatusCard
              label="Skill Graph"
              status={skillGraphSaved ? "Saved" : "Not saved"}
              tone={skillGraphSaved ? "emerald" : "slate"}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {githubProofAttached ? (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                GitHub Proof:{" "}
                {githubAttached?.repo_owner && githubAttached?.repo_name
                  ? `${githubAttached.repo_owner}/${githubAttached.repo_name}`
                  : githubAttached?.repo_url}
                {githubAttached?.status ? ` (${githubAttached.status})` : ""}
              </Mono>
            ) : (
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                Repository URL only — no attached GitHub Proof
                {created.project.repo_full_name ? `: ${created.project.repo_full_name}` : ""}
              </Mono>
            )}

            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
              Documents:{" "}
              {documentsCount > 0
                ? documentsAttached!.map((d) => d.title || "Untitled document").join(", ")
                : "none attached"}
            </Mono>

            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
              Website Proof:{" "}
              {websiteProofsCount > 0
                ? websiteProofsAttached!.map((w) => w.target_website || "Website proof").join(", ")
                : "none attached"}
            </Mono>

            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
              Defense questions: {questions ? `${questions.length} generated` : "not generated yet"}
            </Mono>

            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
              Analysis status: {analysisCompleted ? "completed" : "not yet run"}
            </Mono>

            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
              Skill Graph sync: {skillGraphSaved ? "saved" : "not saved"}
            </Mono>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
                Video Defense: {VIDEO_DEFENSE_STATUS[videoDefenseStatus].label}
                {videoDefenseStatus === "storage_not_configured" &&
                  " — pasting your explanation remains the primary available path."}
              </Mono>
              {sessionId && (
                <Btn
                  size="sm"
                  variant="secondary"
                  onClick={() => router.push(`/student/proofs/project-defense/record/${sessionId}`)}
                >
                  Record defense
                </Btn>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Step C — Generate questions */}
      {created && !questions && (
        <Card>
          <CardHeader title="Generate defense questions" eyebrow="Step B · Deterministic questions" icon="❓" />
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "0 0 12px" }}>
            VeriBridge will generate a short set of questions about your project&apos;s architecture, your
            individual contribution, your claimed skills, and any attached proof.
          </p>
          {generateError && (
            <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6, marginBottom: 8 }}>
              {generateError}
            </p>
          )}
          <Btn variant="primary" onClick={handleGenerateQuestions} disabled={generating}>
            {generating ? "Generating…" : "Generate questions"}
          </Btn>
        </Card>
      )}

      {/* Step C results + Step D — answers */}
      {questions && !result && (
        <Card>
          <CardHeader title="Defense questions" eyebrow="Step C · Answer in your own words" icon="❓" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
            {questions.map((q) => (
              <QuestionCard key={q.id} question={q} />
            ))}
          </div>

          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 16px" }}>
            Optionally record yourself answering these questions using the Record defense action in the
            Project Evidence Package above, or paste your explanation below.
          </p>

          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <Btn size="sm" variant={answerMode === "combined" ? "primary" : "secondary"} onClick={() => setAnswerMode("combined")}>
              Paste one explanation
            </Btn>
            <Btn size="sm" variant={answerMode === "per_question" ? "primary" : "secondary"} onClick={() => setAnswerMode("per_question")}>
              Answer each question
            </Btn>
          </div>

          {answerMode === "combined" ? (
            <div>
              <label style={labelStyle}>Your explanation</label>
              <textarea
                placeholder="Explain your project, your role, the architecture, and any challenges or improvements in your own words…"
                value={combinedText}
                onChange={(e) => setCombinedText(e.target.value)}
                rows={8}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {questions.map((q) => (
                <div key={q.id}>
                  <label style={labelStyle}>{q.question_text}</label>
                  <textarea
                    value={perQuestionAnswers[q.id] || ""}
                    onChange={(e) => setPerQuestionAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                    rows={3}
                    style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
                  />
                </div>
              ))}
            </div>
          )}

          {submitError && (
            <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6, marginTop: 12 }}>
              {submitError}
            </p>
          )}

          <div style={{ marginTop: 12 }}>
            <Btn variant="primary" onClick={handleSubmitAnswers} disabled={submitting}>
              {submitting ? "Analyzing…" : "Analyze my answers"}
            </Btn>
          </div>
        </Card>
      )}

      {/* Step E/F — analysis + save to Skill Graph */}
      {result && (
        <AnalysisResults
          analysis={result.analysis}
          videoEvidenceChips={result.video_evidence_chips}
          syncStatus={syncStatus}
          syncSkills={syncSkills}
          onSync={handleSync}
        />
      )}

      {!created && githubProofs === null && documentProofs === null && websiteProofs === null && !loadError && (
        <LoadingState label="Loading your proof sources…" />
      )}

      <p style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", marginTop: 4 }}>
        Project Defense is supporting explanation evidence — it never counts as fully verified proof on its
        own and does not change your existing GitHub, website, or document evidence.
      </p>
    </div>
  )
}
