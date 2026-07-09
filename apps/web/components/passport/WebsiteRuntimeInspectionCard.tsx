"use client"

import { isSafePublicUrl, type WebsiteEvidenceCard } from "@/lib/vbr-api"

import { WebsiteFramesGallery } from "./OriginalProofAccess"
import { Badge, Mono, TOKEN } from "./shared"

/**
 * Website Runtime Inspection — the recruiter-facing deep-inspection card that
 * makes a Website Proof as inspectable as a GitHub Proof. It renders six honest
 * sections, all from closed-vocabulary labels, already-safe derived summaries
 * and revalidated safe public URLs (never raw DOM/OCR/provider payloads, storage
 * paths, signed URLs, private hosts, or numeric scores):
 *
 *   1. Runtime claim observed   — a concise skill-specific runtime claim.
 *   2. What VeriBridge observed  — target site / app context, page context,
 *      user action, visible output, safe OCR/DOM/visual summaries, workflow.
 *   3. Skill relevance           — how this evidence supports THIS skill.
 *   4. Recruiter verification    — live "open & reproduce" checklist, or a
 *      recorded-replay-only explanation + deployment recommendation.
 *   5. Recorded evidence package — safe frame/OCR/DOM/visual findings + status.
 *   6. Limitation                — what it does NOT prove + missing-evidence note.
 *
 * Every field is optional and fail-soft: an older/thinner card that lacks the
 * runtime-inspection fields still renders its available sections.
 */
export function WebsiteRuntimeInspectionCard({
  card,
  fallbackUrl,
  sessionId,
  ownerSurface = false,
}: {
  card: WebsiteEvidenceCard
  fallbackUrl?: string | null
  /** The website proof session id — enables the owner captured-frames gallery. */
  sessionId?: string | null
  /** True ONLY on the private owner surface; public projections fail closed. */
  ownerSurface?: boolean
}) {
  const openUrl = card.open_website_url ?? card.target_url_safe ?? fallbackUrl
  const frameUrl =
    card.screenshot_preview_url && isSafePublicUrl(card.screenshot_preview_url)
      ? card.screenshot_preview_url
      : null
  // A recruiter can DIRECTLY verify only when a public, safe live URL is
  // available (the GitHub-Proof "click through and inspect it yourself" path).
  // A localhost/private host never survives isSafePublicUrl, so it always falls
  // to the recorded-replay-only presentation below.
  const canOpenLive = Boolean(openUrl && isSafePublicUrl(openUrl))
  const isLiveVerifiable = card.verification_mode === "directly_verifiable_live" || canOpenLive
  const verificationLabel =
    card.verification_mode_label ?? (isLiveVerifiable ? "Directly verifiable live" : "Recorded replay only")
  const deploymentRecommended = card.deployment_recommended ?? !isLiveVerifiable
  const checklist = card.recruiter_checklist ?? []
  const hasEvidencePackage = Boolean(
    card.visual_evidence_summary ||
      card.ocr_evidence_summary_safe ||
      card.dom_evidence_summary_safe ||
      card.visible_text_observed ||
      card.observed_behavior_summary ||
      card.screenshot_available,
  )

  return (
    <div
      data-testid="website-evidence-card"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      {/* Inspection header — a title plus an honest live-verifiable vs
          recorded-replay-only status (never a numeric score). */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Mono
          data-testid="website-inspection-title"
          style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}
        >
          Website Runtime Inspection
        </Mono>
        <span data-testid="website-verification-mode" data-mode={isLiveVerifiable ? "live" : "recorded"}>
          <Badge tone={isLiveVerifiable ? "emerald" : "amber"}>{verificationLabel}</Badge>
        </span>
        <Badge tone="purple">Runtime behavior evidence</Badge>
      </div>

      {/* ── Section 1 — Runtime claim observed ─────────────────────────────── */}
      <Section label="Runtime claim observed">
        {card.runtime_claim_observed ? (
          <p
            data-testid="website-runtime-claim"
            style={{ fontSize: 13, color: TOKEN.ink, margin: 0, lineHeight: 1.5, fontWeight: 600 }}
          >
            {card.runtime_claim_observed}
          </p>
        ) : (
          card.behavior_claim && (
            <p
              data-testid="website-behavior-claim"
              style={{ fontSize: 13, color: TOKEN.ink, margin: 0, lineHeight: 1.5, fontWeight: 600 }}
            >
              Claim: {card.behavior_claim}
            </p>
          )
        )}
        {card.runtime_claim_observed && card.behavior_claim && (
          <p
            data-testid="website-behavior-claim"
            style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
          >
            Claim: {card.behavior_claim}
          </p>
        )}
      </Section>

      {/* ── Section 2 — What VeriBridge observed ───────────────────────────── */}
      <Section label="What VeriBridge observed">
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Mono data-testid="website-card-route" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
            Website Behavior Evidence · {card.route_or_page}
          </Mono>
          {card.observed_at && (
            <span data-testid="website-card-observed-at" style={{ fontSize: 11, color: TOKEN.muted }}>
              observed {card.observed_at}
            </span>
          )}
        </div>
        <ObservedFact testId="website-target-site" label="Target site" value={card.target_domain} />
        <ObservedFact testId="website-app-context" label="App context" value={card.app_context} />
        <ObservedFact testId="website-page-context" label="Page context" value={card.page_context_label} />
        {card.page_title && (
          <ObservedFact testId="website-card-page-title" label="Page title" value={card.page_title} />
        )}
        <ObservedFact testId="website-user-action" label="User action observed" value={card.user_action_observed} />
        <ObservedFact testId="website-output-observed" label="Output observed" value={card.output_observed} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 2 }}>
          <span data-testid="website-purpose-label">
            <Badge tone="purple">{card.website_purpose_label}</Badge>
          </span>
        </div>
        {card.evidence_basis_chips.length > 0 && (
          <div
            data-testid="website-evidence-chips"
            style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}
          >
            <span style={{ fontSize: 11, color: TOKEN.inkSoft, fontWeight: 600 }}>Evidence observed:</span>
            {card.evidence_basis_chips.map((chip) => (
              <span key={chip} data-testid="website-evidence-chip">
                <Badge tone="slate">{chip}</Badge>
              </span>
            ))}
          </div>
        )}
      </Section>

      {/* ── Section 3 — Skill relevance ────────────────────────────────────── */}
      <Section label="Skill relevance">
        <p
          data-testid="website-skill-relevance"
          title={card.skill_relevance_summary || undefined}
          style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}
        >
          <strong>Supports: </strong>
          {card.skill_relevance_label}
        </p>
        {card.skill_relevance_summary && (
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
            {card.skill_relevance_summary}
          </p>
        )}
        {card.corroboration_note && (
          <p
            data-testid="website-corroboration"
            style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}
          >
            <strong>Corroborates: </strong>
            {card.corroboration_note}
            {card.connected_project_title && (
              <span data-testid="website-connected-project" style={{ color: TOKEN.muted }}>
                {" "}
                (project: {card.connected_project_title})
              </span>
            )}
          </p>
        )}
      </Section>

      {/* ── Section 4 — Recruiter verification ─────────────────────────────── */}
      <Section label="Recruiter verification">
        {card.verification_note && (
          <p
            data-testid="website-verification-note"
            style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
          >
            {card.verification_note}
          </p>
        )}
        {checklist.length > 0 && (
          <ul
            data-testid="website-recruiter-checklist"
            style={{ margin: "2px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}
          >
            {checklist.map((step, i) => (
              <li
                key={i}
                data-testid="website-checklist-item"
                style={{ fontSize: 11, color: TOKEN.inkSoft, lineHeight: 1.5 }}
              >
                {step}
              </li>
            ))}
          </ul>
        )}
        {(canOpenLive || frameUrl) && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {canOpenLive && openUrl && (
              <span data-testid="website-open-live">
                <a
                  href={openUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="evidence-public-link"
                  style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "underline", wordBreak: "break-all" }}
                >
                  Open live website →
                </a>
              </span>
            )}
            {frameUrl && (
              <a
                href={frameUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "underline", wordBreak: "break-all" }}
              >
                View evidence frame →
              </a>
            )}
          </div>
        )}
        {deploymentRecommended && (
          <p
            data-testid="website-deployment-recommended"
            style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}
          >
            Deployment recommended for direct recruiter verification.
          </p>
        )}
      </Section>

      {/* ── Section 5 — Recorded evidence package ──────────────────────────── */}
      {hasEvidencePackage && (
        <Section label="Recorded evidence package">
          {(card.visual_evidence_summary ||
            card.ocr_evidence_summary_safe ||
            card.dom_evidence_summary_safe ||
            card.visible_text_observed) && (
            <div
              data-testid="website-visual-page-analysis"
              style={{ display: "flex", flexDirection: "column", gap: 2 }}
            >
              <span style={{ fontSize: 11, color: TOKEN.inkSoft, fontWeight: 600 }}>Visual and page analysis</span>
              {card.visual_evidence_summary && (
                <p data-testid="website-card-visual" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                  {card.visual_evidence_summary}
                </p>
              )}
              {(card.visible_text_observed || card.ocr_evidence_summary_safe) && (
                <p data-testid="website-card-ocr" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                  {card.visible_text_observed || card.ocr_evidence_summary_safe}
                </p>
              )}
              {card.dom_evidence_summary_safe && (
                <p data-testid="website-card-dom" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                  {card.dom_evidence_summary_safe}
                </p>
              )}
            </div>
          )}
          {card.observed_behavior_summary && (
            <p
              data-testid="website-observed-behavior"
              style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
            >
              {card.observed_behavior_summary}
            </p>
          )}
          {/* Captured frames: the OWNER sees the real frame gallery (streamed
              through the authorized thumbnail proxy — no storage paths/signed
              URLs in the DOM); every other surface keeps the honest
              permission-gated status line. Frames were captured exactly when a
              visual/OCR summary exists (`screenshot_available`). */}
          {card.screenshot_available && ownerSurface && sessionId ? (
            <WebsiteFramesGallery sessionId={sessionId} />
          ) : (
            card.screenshot_available &&
            (frameUrl ? null : (
              <span data-testid="website-screenshot-status" style={{ fontSize: 11, color: TOKEN.muted }}>
                🖼 Evidence frame available with candidate permission
              </span>
            ))
          )}
        </Section>
      )}

      {/* ── Section 6 — Limitation + honest missing-evidence note ──────────── */}
      {(card.limitation || card.missing_evidence_note) && (
        <Section label="Limitation">
          {card.limitation && (
            <p data-testid="website-card-limitation" style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
              {card.limitation}
            </p>
          )}
          {card.missing_evidence_note && (
            <p
              data-testid="website-missing-evidence"
              style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}
            >
              {card.missing_evidence_note}
            </p>
          )}
        </Section>
      )}
    </div>
  )
}

/** One titled section wrapper for the runtime inspection card. */
function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <Mono
        style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.14em" }}
      >
        {label}
      </Mono>
      {children}
    </div>
  )
}

/** One "Label: value" observed fact — renders nothing when the value is empty. */
function ObservedFact({
  testId,
  label,
  value,
}: {
  testId: string
  label: string
  value?: string | null
}) {
  if (!value) return null
  return (
    <p data-testid={testId} style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
      <strong>{label}: </strong>
      {value}
    </p>
  )
}
