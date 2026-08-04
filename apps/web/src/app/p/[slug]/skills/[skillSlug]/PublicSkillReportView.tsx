"use client"

import { useEffect, useState } from "react"

import {
  getPublicSkillReport,
  type PublicSkillReport,
  type PublicSkillReportChain,
  type PublicSkillReportEvidence,
  type PublicSkillSynthesisResult,
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
import { RecruiterCta } from "../../../../../../components/passport/RecruiterCta"
import {
  RecruiterReviewChecklist,
} from "../../../../../../components/passport/RecruiterTrustFraming"

/**
 * The PUBLIC, recruiter-facing Skill Report (`/p/{slug}/skills/{skillSlug}`).
 *
 * Renders ONLY the backend's centralized public projection: linked proof
 * chains, cited synthesis claims, the capped unlinked bucket, and honest
 * limitations. There are no owner controls, no edit/publish buttons, no
 * private routes — the only outbound links are revalidated public http(s)
 * URLs the projection chose to keep. Evidence that is not publicly openable
 * renders an explicit "verified summary only" label instead of a link.
 */

const STATUS_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Evidence observed": "emerald",
  "Supporting evidence": "sky",
  "Needs review": "rose",
  "Not assessed": "slate",
}

const TIER_TONE: Record<string, BadgeTone> = {
  "Strongly corroborated": "emerald",
  Corroborated: "emerald",
  "Supporting evidence": "sky",
  "Needs review": "rose",
  "Insufficient evidence": "slate",
}

const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  website: "Website",
  document: "Documents",
  defense: "Project Defense",
  video: "Video",
  skill_graph: "Skill Graph",
}

const SOURCE_TONE: Record<string, BadgeTone> = {
  github: "indigo",
  website: "purple",
  document: "sky",
  defense: "emerald",
  video: "amber",
}

/** Honest, recruiter-readable label for a qualitative proof-strength key. */
const STRENGTH_LABELS: Record<string, string> = {
  precise_code: "Precise code evidence",
  runtime_behavior: "Runtime behaviour evidence",
  self_explanation: "Candidate explanation",
  supporting_moment: "Supporting moment",
  repo_level: "Repository-level evidence",
  aggregated: "Aggregated evidence",
  corroboration: "Corroboration",
}

function EvidenceRow({ item }: { item: PublicSkillReportEvidence }) {
  const strength = STRENGTH_LABELS[item.proof_strength] ?? "Evidence"
  return (
    <div
      data-testid="public-skill-evidence-item"
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
        <Badge tone={SOURCE_TONE[item.source_type] ?? "slate"}>{item.source_label || "Evidence"}</Badge>
        <Badge tone="slate">{strength}</Badge>
        {item.website_verification_mode_label && (
          <Badge tone="slate">{item.website_verification_mode_label}</Badge>
        )}
      </div>
      {item.website_behavior_claim && (
        <p style={{ fontSize: 12, color: TOKEN.ink, margin: 0, fontWeight: 600 }}>
          {item.website_behavior_claim}
        </p>
      )}
      {item.safe_summary && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{item.safe_summary}</p>
      )}
      {item.exact_location && (
        <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{item.exact_location}</Mono>
      )}
      {item.website_skill_relevance_label && (
        <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>{item.website_skill_relevance_label}</p>
      )}
      {/* Public access is honest and explicit: a real public link when the
          projection kept one, otherwise a compact "kept private" chip (the
          full explanation renders ONCE per chain, not per item). */}
      {item.public_url ? (
        <a
          data-testid="public-skill-evidence-link"
          href={item.public_url}
          target="_blank"
          rel="noreferrer noopener"
          style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
        >
          Open public evidence ↗
        </a>
      ) : (
        <span
          data-testid="public-skill-evidence-private"
          title="The original artifact is kept private by the candidate — a verified summary is shown instead."
          style={{ alignSelf: "flex-start" }}
        >
          <Badge tone="slate">Original kept private</Badge>
        </span>
      )}
      {item.website_screenshot_available === false && item.website_verification_note && (
        <span style={{ fontSize: 11, color: TOKEN.muted }}>{item.website_verification_note}</span>
      )}
      {item.limitations.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {item.limitations.map((line, i) => (
            <li key={i} style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
              {line}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ProofChainCard({ chain }: { chain: PublicSkillReportChain }) {
  const strengthLabel = chain.proof_strength_summary?.label ?? ""
  return (
    <Card>
      <div data-testid="public-skill-proof-chain" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: TOKEN.ink }}>
            {chain.project_title || chain.chain_label || "Connected proof chain"}
          </span>
          {chain.source_types_present.map((src) => (
            <Badge key={src} tone={SOURCE_TONE[src] ?? "slate"}>
              {SOURCE_LABELS[src] ?? src}
            </Badge>
          ))}
        </div>
        {strengthLabel && (
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{strengthLabel}</p>
        )}
        {chain.connection_reasons.length > 0 && (
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
            Why these sources are linked: {chain.connection_reasons.join(" · ")}
          </p>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {chain.evidence.map((item, i) => (
            <EvidenceRow key={item.evidence_id ?? `${item.source_type}-${i}`} item={item} />
          ))}
        </div>
        {/* ONE explanation line per chain for kept-private originals — never
            repeated on every evidence card. */}
        {chain.evidence.some((item) => !item.public_url) && (
          <p data-testid="public-skill-private-note" style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
            Items marked “Original kept private” show a verified summary — the candidate keeps the original
            artifact private.
          </p>
        )}
        {chain.limitations.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {chain.limitations.map((line, i) => (
              <li key={i} style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
                {line}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}

function SynthesisCard({ result }: { result: PublicSkillSynthesisResult }) {
  return (
    <div
      data-testid="public-skill-synthesis"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "10px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: TOKEN.bg,
      }}
    >
      {result.project_title && (
        <span style={{ fontSize: 12, fontWeight: 600, color: TOKEN.ink }}>{result.project_title}</span>
      )}
      {result.overall_summary && (
        <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
          {result.overall_summary}
        </p>
      )}
      {result.claims.map((claim, i) => (
        <div key={claim.claim_id ?? i} data-testid="public-skill-synthesis-claim" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <Badge tone={TIER_TONE[claim.qualitative_tier] ?? "slate"}>{claim.qualitative_tier}</Badge>
            <span style={{ fontSize: 12, color: TOKEN.ink }}>{claim.claim}</span>
          </div>
          {claim.why_connected && (
            <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>{claim.why_connected}</p>
          )}
        </div>
      ))}
    </div>
  )
}

export function PublicSkillReportView({ slug, skillSlug }: { slug: string; skillSlug: string }) {
  const [report, setReport] = useState<PublicSkillReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    getPublicSkillReport(slug, skillSlug)
      .then((data) => {
        if (!data) {
          setNotFound(true)
          return
        }
        setReport(data)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load skill report."))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, skillSlug])

  if (loading) return <LoadingState label="Loading public skill evidence…" />

  if (notFound) {
    return (
      <div
        data-testid="public-skill-report-not-found"
        style={{ maxWidth: 560, margin: "0 auto", padding: "64px 24px", textAlign: "center" }}
      >
        <span aria-hidden style={{ fontSize: 30, display: "block", marginBottom: 10 }}>🔒</span>
        <h1 style={{ fontSize: 20, color: TOKEN.ink, marginBottom: 10 }}>This skill report is not available</h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, lineHeight: 1.6 }}>
          The candidate’s Work Passport is currently private, or the link may be incorrect. Ask the candidate for
          an up-to-date Verified Work Passport link.
        </p>
        <a href={`/p/${encodeURIComponent(slug)}`} style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "none" }}>
          ← Back to the public Passport
        </a>
      </div>
    )
  }

  if (error || !report) return <ErrorState message={error ?? "Skill report not found."} onRetry={load} />

  const coverage = Object.entries(report.source_coverage)
  const hasAnyPublicEvidence =
    report.linked_proof_chains.length > 0 ||
    report.synthesis.length > 0 ||
    report.unlinked_supporting_evidence.items.length > 0

  return (
    <div
      data-testid="public-skill-report"
      style={{ maxWidth: 900, margin: "0 auto", padding: "clamp(16px, 5vw, 48px) clamp(12px, 4vw, 24px)", display: "flex", flexDirection: "column", gap: 16 }}
    >
      <a
        data-testid="public-skill-report-back"
        href={`/p/${encodeURIComponent(slug)}`}
        style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "none" }}
      >
        ← Back to the public Passport
      </a>

      {/* Header — the skill claim, its qualitative label, and the honest thesis */}
      <Card>
        <div data-testid="public-skill-report-header" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <h1 style={{ fontSize: 22, color: TOKEN.ink, margin: 0, letterSpacing: "-0.02em" }}>{report.skill}</h1>
            <Badge tone={STATUS_TONE[report.status] ?? "slate"}>{report.status}</Badge>
          </div>
          <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{report.category}</Mono>
          {report.synthesis_summary && (
            <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}>
              {report.synthesis_summary}
            </p>
          )}
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
            This is the public-safe view of the candidate&apos;s evidence for this skill. Private artifacts are
            summarized, never exposed — inspect the linked public evidence before making hiring decisions.
          </p>
        </div>
      </Card>

      {/* Evidence coverage — booleans only, never counts-as-scores */}
      {coverage.length > 0 && (
        <Card>
          <CardHeader title="Evidence Coverage" eyebrow="Across proof sources" icon="📎" />
          <div data-testid="public-skill-coverage" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {coverage.map(([key, present]) => (
              <span key={key} data-testid="public-skill-coverage-item" data-source={key} data-present={present ? "true" : "false"}>
                <Badge tone={present ? (SOURCE_TONE[key] ?? "emerald") : "slate"}>
                  {present ? "✓ " : "– "}
                  {SOURCE_LABELS[key] ?? key}
                </Badge>
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* Connected proof chains — the core evidence argument */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Connected Proof</h2>
        {report.linked_proof_chains.length === 0 ? (
          <Card>
            <p data-testid="public-skill-no-chains" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No public-safe connected proof chains are available for this skill.
            </p>
          </Card>
        ) : (
          report.linked_proof_chains.map((chain, i) => (
            <ProofChainCard key={chain.chain_id ?? i} chain={chain} />
          ))
        )}
      </section>

      {/* Cited synthesis — every claim keeps a traceable citation */}
      {report.synthesis.length > 0 && (
        <Card>
          <CardHeader title="What the Evidence Supports" eyebrow="Cited, qualitative" icon="🧾" />
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {report.synthesis.map((result, i) => (
              <SynthesisCard key={result.chain_id ?? i} result={result} />
            ))}
          </div>
        </Card>
      )}

      {/* Unlinked supporting evidence (capped, honest overflow) */}
      {report.unlinked_supporting_evidence.items.length > 0 && (
        <Card>
          <CardHeader title="Other Supporting Evidence" eyebrow="Not part of a proof chain" icon="🧷" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {report.unlinked_supporting_evidence.items.map((item, i) => (
              <div key={`${item.title}-${i}`} data-testid="public-skill-unlinked-item" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <Badge tone="slate">{item.proof_type}</Badge>
                  <span style={{ fontSize: 12, fontWeight: 600, color: TOKEN.ink }}>{item.title}</span>
                </div>
                {item.safe_summary && (
                  <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{item.safe_summary}</p>
                )}
                {item.limitation && (
                  <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>{item.limitation}</p>
                )}
              </div>
            ))}
            {report.unlinked_supporting_evidence.more_count > 0 && (
              <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                +{report.unlinked_supporting_evidence.more_count} more supporting proof
                {report.unlinked_supporting_evidence.more_count === 1 ? "" : "s"} not shown here.
              </p>
            )}
          </div>
        </Card>
      )}

      {/* Honest empty state when nothing public-safe survived the projection */}
      {!hasAnyPublicEvidence && (
        <Card>
          <p data-testid="public-skill-no-public-evidence" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
            This candidate has proof for this skill, but none of it is public-safe to show here. Ask the
            candidate to share more public-safe evidence, or request access through their Passport.
          </p>
        </Card>
      )}

      {/* Limitations / transparency */}
      {report.limitations.length > 0 && (
        <Card>
          <CardHeader title="Limitations / Transparency" eyebrow="In good faith" icon="⚠️" />
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
            {report.limitations.map((line, i) => (
              <li key={i} style={{ fontSize: 12, color: TOKEN.muted, lineHeight: 1.5 }}>
                {line}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <RecruiterReviewChecklist />
      <RecruiterCta />
    </div>
  )
}
