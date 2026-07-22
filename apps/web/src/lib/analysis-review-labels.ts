/**
 * Honest review labels for workflow evidence analysis.
 *
 * The chip shown next to a completed Workflow Evidence Analysis must describe
 * what actually happened. Production runs in degraded mode (no AI provider
 * keys), where every stored analysis is `analysis_type = "timeline_only"` —
 * a deterministic browser-event/timeline analysis with no AI involved.
 *
 * Backend enumeration (apps/api/app/schemas/extension_proof_workflow_analysis.py
 * `WorkflowAnalysisType`):
 *   - "timeline_only"            → deterministic timeline evidence, no AI
 *   - "video_frame_analysis"     → frame/OCR evidence (provider may be local
 *                                  OCR — not an AI-review claim)
 *   - "full_multimodal_analysis" → an AI multimodal provider actually ran;
 *                                  the ONLY type allowed to say "AI Reviewed"
 * Anything else (legacy/unknown) falls back to a neutral honest label.
 */

export const WORKFLOW_ANALYSIS_REVIEW_LABELS: Record<string, string> = {
  timeline_only: "Timeline Evidence",
  video_frame_analysis: "Video Frame Evidence",
  full_multimodal_analysis: "AI Reviewed",
}

export const WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL = "Evidence Recorded"

/**
 * The honest completed-review chip label for a workflow analysis.
 * Never implies an AI ran when it did not.
 */
export function workflowAnalysisReviewLabel(
  analysisType: string | null | undefined
): string {
  return (
    WORKFLOW_ANALYSIS_REVIEW_LABELS[String(analysisType ?? "")] ??
    WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL
  )
}

/** True when a label claims an AI review took place (used as a test guard). */
export function labelImpliesAiReview(label: string): boolean {
  return /\bAI[\s-]?(reviewed|review|analyzed|analysed)\b/i.test(label)
}

/**
 * Recruiter-facing badge labels for `verification_status`
 * (= `ai_domain_review_status` from the deterministic domain review — the
 * review is a rules engine, `llm_used: false`, so no label may claim an AI
 * model reviewed the evidence).
 *
 * Backend values (apps/api/app/services/verification_review_service.py
 * `_AI_STATUS_TO_DOMAIN`): ai_domain_reviewed, human_review_recommended,
 * privacy_blocked, needs_more_evidence.
 */
export const VERIFICATION_STATUS_BADGE_LABELS: Record<string, string> = {
  ai_domain_reviewed: "Evidence Reviewed",
  human_review_recommended: "Human Review Recommended",
  needs_more_evidence: "Needs More Evidence",
  privacy_blocked: "Privacy Review Required",
}

/**
 * Honest, human-readable badge label for a verification status.
 * Returns null for a missing status (no badge). Unknown/legacy slugs are
 * humanized (never rendered as raw machine identifiers, never as an AI claim).
 */
export function verificationStatusBadgeLabel(
  status: string | null | undefined
): string | null {
  if (!status) return null
  const known = VERIFICATION_STATUS_BADGE_LABELS[status]
  if (known) return known
  const humanized = status
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase())
  return labelImpliesAiReview(humanized) ? "Evidence Reviewed" : humanized
}
