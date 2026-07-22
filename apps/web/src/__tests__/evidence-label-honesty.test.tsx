/**
 * Evidence label honesty — regression tests.
 *
 * Production runs in degraded mode (no AI provider keys): every stored
 * workflow analysis is `analysis_type = "timeline_only"` (deterministic
 * browser-event/timeline analysis). The UI previously hardcoded an
 * "AI Reviewed" chip for ANY completed analysis — including timeline_only —
 * falsely implying an AI model reviewed the evidence.
 *
 * Contract under test:
 *  1. Every backend-enumerable analysis_type maps to an honest review label.
 *  2. Unknown/legacy values fall back to a neutral, honest label.
 *  3. A timeline_only analysis can NEVER render an AI-implying label
 *     (guarded both at the helper level and at the rendered-card level).
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL,
  WORKFLOW_ANALYSIS_REVIEW_LABELS,
  labelImpliesAiReview,
  workflowAnalysisReviewLabel,
} from "@/lib/analysis-review-labels"
import { WorkflowAnalysisCard } from "../../components/skill-proof/extension-proof-panel"
import type { WorkflowAnalysisResponse } from "@/lib/api"

// All values of the backend WorkflowAnalysisType Literal
// (apps/api/app/schemas/extension_proof_workflow_analysis.py).
const BACKEND_ANALYSIS_TYPES = [
  "timeline_only",
  "video_frame_analysis",
  "full_multimodal_analysis",
] as const

function analysisFixture(
  overrides: Partial<WorkflowAnalysisResponse> = {},
): WorkflowAnalysisResponse {
  return {
    id: "analysis-1",
    proof_session_id: "session-1",
    analysis_type: "timeline_only",
    analyzer_version: "workflow-analysis-v4",
    workflow_summary: "The recording shows a walkthrough of the target website.",
    demonstrated_actions: ["Opened the dashboard"],
    supported_skills: ["React"],
    weakly_supported_skills: [],
    unsupported_skills: [],
    evidence_strength_score: 57,
    workflow_confidence: "high",
    missing_evidence: [],
    risk_flags: [],
    recruiter_summary: "Recording shows a website walkthrough.",
    student_improvement_suggestions: [],
    human_review_needed: false,
    ...overrides,
  } as WorkflowAnalysisResponse
}

describe("workflowAnalysisReviewLabel — status → label mapping", () => {
  it("maps timeline_only to Timeline Evidence (no AI claim)", () => {
    expect(workflowAnalysisReviewLabel("timeline_only")).toBe("Timeline Evidence")
  })

  it("maps video_frame_analysis to Video Frame Evidence (no AI claim)", () => {
    expect(workflowAnalysisReviewLabel("video_frame_analysis")).toBe("Video Frame Evidence")
  })

  it("maps full_multimodal_analysis to AI Reviewed (the only type where AI ran)", () => {
    expect(workflowAnalysisReviewLabel("full_multimodal_analysis")).toBe("AI Reviewed")
  })

  it("falls back to an honest neutral label for unknown/legacy/missing values", () => {
    expect(workflowAnalysisReviewLabel("workflow_timeline")).toBe(
      WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL,
    )
    expect(workflowAnalysisReviewLabel("")).toBe(WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL)
    expect(workflowAnalysisReviewLabel(null)).toBe(WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL)
    expect(workflowAnalysisReviewLabel(undefined)).toBe(WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL)
  })

  it("covers every backend-enumerable analysis type explicitly (no silent fallback)", () => {
    for (const type of BACKEND_ANALYSIS_TYPES) {
      expect(WORKFLOW_ANALYSIS_REVIEW_LABELS[type]).toBeTruthy()
    }
  })
})

describe("guard — non-AI analysis types can never get an AI-implying label", () => {
  it("only full_multimodal_analysis may imply an AI review", () => {
    for (const type of BACKEND_ANALYSIS_TYPES) {
      const label = workflowAnalysisReviewLabel(type)
      if (type === "full_multimodal_analysis") {
        expect(labelImpliesAiReview(label)).toBe(true)
      } else {
        expect(labelImpliesAiReview(label)).toBe(false)
      }
    }
  })

  it("the unknown-value fallback never implies an AI review", () => {
    expect(labelImpliesAiReview(WORKFLOW_ANALYSIS_REVIEW_FALLBACK_LABEL)).toBe(false)
    expect(labelImpliesAiReview(workflowAnalysisReviewLabel("something_new"))).toBe(false)
  })

  it("labelImpliesAiReview detects AI-review claims", () => {
    expect(labelImpliesAiReview("AI Reviewed")).toBe(true)
    expect(labelImpliesAiReview("ai reviewed")).toBe(true)
    expect(labelImpliesAiReview("Timeline Evidence")).toBe(false)
    expect(labelImpliesAiReview("Analyzed")).toBe(false)
  })
})

describe("WorkflowAnalysisCard — rendered chip honesty", () => {
  it("timeline_only analysis renders Timeline Evidence and never AI Reviewed", () => {
    render(<WorkflowAnalysisCard analysis={analysisFixture({ analysis_type: "timeline_only" })} />)
    expect(screen.getByText(/Timeline Evidence · Workflow Timeline Analysis/)).toBeInTheDocument()
    expect(screen.queryByText(/AI Reviewed/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/AI reviewed/)).not.toBeInTheDocument()
  })

  it("video_frame_analysis renders Video Frame Evidence and never AI Reviewed", () => {
    render(
      <WorkflowAnalysisCard
        analysis={analysisFixture({ analysis_type: "video_frame_analysis" })}
      />,
    )
    expect(screen.getByText(/Video Frame Evidence · Video Frame Analysis/)).toBeInTheDocument()
    expect(screen.queryByText(/AI Reviewed/i)).not.toBeInTheDocument()
  })

  it("full_multimodal_analysis is the only type that renders AI Reviewed", () => {
    render(
      <WorkflowAnalysisCard
        analysis={analysisFixture({ analysis_type: "full_multimodal_analysis" })}
      />,
    )
    expect(screen.getByText(/AI Reviewed · Full Multimodal Analysis/)).toBeInTheDocument()
  })
})
