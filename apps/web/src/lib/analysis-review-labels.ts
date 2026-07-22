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
