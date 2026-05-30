/**
 * Unit tests for SequenceAnalysisPanel and related multimodal proof UI.
 *
 * Covers:
 * 1. Renders full sequence analysis data (all sections visible for student view)
 * 2. Handles missing / null sequence_analysis gracefully
 * 3. Public/recruiter view hides private fields
 * 4. Student/internal view shows allowed detail
 * 5. Incomplete/failed status shows appropriate notice
 * 6. Evidence strength / score rendered correctly
 * 7. No raw frame paths / storage paths exposed in output
 * 8. video keyframe evidence fields render when provided
 * 9. sequence_analysis.supported_skills vs unsupported_claims visibility by view
 */

import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { SequenceAnalysisPanel } from "../../components/skill-proof/sequence-analysis-panel"
import type { SequenceAnalysisResult } from "../lib/api"

// ── Fixtures ──────────────────────────────────────────────────────────────────

const COMPLETE_ANALYSIS: SequenceAnalysisResult = {
  sequence_analysis_status: "completed",
  analyzed_frame_count: 5,
  workflow_stage_summaries: [
    { stage: "Data Input", description: "User enters data into form", confidence: "strong" },
    { stage: "Processing", description: "System processes the request", confidence: "moderate" },
  ],
  input_action_output_chain: {
    inputs: ["Image file uploaded"],
    actions: ["Submitted form", "Clicked analyze"],
    outputs: ["Result: processed successfully"],
  },
  before_after_changes: ["Empty form → Filled form", "No result → Result visible"],
  observed_outputs: ["Result: processed successfully", "Status: complete"],
  supported_skills: ["Data Processing", "Web UI"],
  unsupported_claims: ["Real-time streaming"],
  evidence_strength: "strong",
  confidence_score: 82,
  public_safe_summary: "The candidate demonstrated a complete data processing workflow.",
  recruiter_safe_summary: "Strong evidence of web application usage and data processing.",
  limitations: ["Only 5 frames captured — more would improve confidence."],
}

const NOT_AVAILABLE_ANALYSIS: SequenceAnalysisResult = {
  sequence_analysis_status: "not_available",
  analyzed_frame_count: 0,
  workflow_stage_summaries: [],
  input_action_output_chain: {},
  before_after_changes: [],
  observed_outputs: [],
  supported_skills: [],
  unsupported_claims: [],
  evidence_strength: "insufficient",
  confidence_score: 0,
  public_safe_summary: "Sequence analysis was not run for this session.",
  recruiter_safe_summary: "Sequence analysis was not run for this session.",
  limitations: [],
}

const FAILED_ANALYSIS: SequenceAnalysisResult = {
  sequence_analysis_status: "insufficient_frames",
  analyzed_frame_count: 1,
  workflow_stage_summaries: [],
  input_action_output_chain: {},
  before_after_changes: [],
  observed_outputs: [],
  supported_skills: [],
  unsupported_claims: [],
  evidence_strength: "insufficient",
  confidence_score: 0,
  public_safe_summary: "Not enough frames.",
  recruiter_safe_summary: "Not enough frames to analyze.",
  limitations: ["Insufficient frames for analysis."],
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SequenceAnalysisPanel — student view (default)", () => {
  it("renders status badge for completed analysis", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText(/Sequence Analysis Complete/i)).toBeInTheDocument()
  })

  it("renders confidence score and analyzed frame count", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText(/82\/100/)).toBeInTheDocument()
    expect(screen.getByText(/5 frames analyzed/i)).toBeInTheDocument()
  })

  it("renders evidence strength badge", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    // The strength badge renders "strong evidence" — there may be multiple
    // elements matching "strong" so we use getAllByText and check count >= 1.
    const matches = screen.getAllByText(/strong evidence/i)
    expect(matches.length).toBeGreaterThanOrEqual(1)
  })

  it("renders supported skills", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText("Data Processing")).toBeInTheDocument()
    expect(screen.getByText("Web UI")).toBeInTheDocument()
  })

  it("renders unsupported claims in student view", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText("Real-time streaming")).toBeInTheDocument()
  })

  it("renders observed outputs", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText("Result: processed successfully")).toBeInTheDocument()
  })

  it("renders before/after changes in student view", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText("Empty form → Filled form")).toBeInTheDocument()
  })

  it("renders recruiter summary", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(
      screen.getByText(/Strong evidence of web application usage and data processing/i)
    ).toBeInTheDocument()
  })

  it("renders limitations section toggle button", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText(/Only 5 frames captured/i)).toBeInTheDocument()
  })

  it("does NOT expose raw frame paths or storage paths", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="student" />)
    const html = document.body.innerHTML
    expect(html).not.toMatch(/\/tmp\/|\/var\/|\/home\/|\/Users\//i)
    expect(html).not.toMatch(/\.png|\.jpg|\.jpeg|\.mp4/i)
    expect(html).not.toMatch(/storage_path|frame_path|private_/i)
  })
})

describe("SequenceAnalysisPanel — recruiter view", () => {
  it("renders public/recruiter summary only", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="recruiter" />)
    expect(
      screen.getByText(/Strong evidence of web application usage and data processing/i)
    ).toBeInTheDocument()
  })

  it("does NOT render unsupported claims in recruiter view", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="recruiter" />)
    expect(screen.queryByText("Real-time streaming")).not.toBeInTheDocument()
  })

  it("does NOT render before/after changes in recruiter view", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="recruiter" />)
    expect(screen.queryByText("Empty form → Filled form")).not.toBeInTheDocument()
  })

  it("does NOT render Input→Action→Output chain button in recruiter view", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="recruiter" />)
    expect(screen.queryByText(/Input.*Action.*Output Chain/i)).not.toBeInTheDocument()
  })

  it("does NOT render workflow stages button in recruiter view", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="recruiter" />)
    expect(screen.queryByText(/Show Workflow Stages/i)).not.toBeInTheDocument()
  })

  it("still renders supported skills", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="recruiter" />)
    expect(screen.getByText("Data Processing")).toBeInTheDocument()
  })

  it("still renders observed outputs", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="recruiter" />)
    expect(screen.getByText("Result: processed successfully")).toBeInTheDocument()
  })
})

describe("SequenceAnalysisPanel — public view", () => {
  it("behaves identically to recruiter view", () => {
    render(<SequenceAnalysisPanel analysis={COMPLETE_ANALYSIS} viewMode="public" />)
    expect(screen.queryByText("Real-time streaming")).not.toBeInTheDocument()
    expect(screen.queryByText("Empty form → Filled form")).not.toBeInTheDocument()
    expect(screen.getByText("Data Processing")).toBeInTheDocument()
  })
})

describe("SequenceAnalysisPanel — null / missing analysis", () => {
  it("renders graceful fallback when analysis is null", () => {
    render(<SequenceAnalysisPanel analysis={null} />)
    expect(screen.getByText(/Sequence analysis not available/i)).toBeInTheDocument()
  })

  it("renders graceful fallback when analysis is undefined", () => {
    render(<SequenceAnalysisPanel analysis={undefined} />)
    expect(screen.getByText(/Sequence analysis not available/i)).toBeInTheDocument()
  })
})

describe("SequenceAnalysisPanel — not_available status", () => {
  it("renders status badge for not_available", () => {
    render(<SequenceAnalysisPanel analysis={NOT_AVAILABLE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText(/Sequence Analysis: Not Available/i)).toBeInTheDocument()
  })

  it("renders explanation notice for not_available", () => {
    render(<SequenceAnalysisPanel analysis={NOT_AVAILABLE_ANALYSIS} viewMode="student" />)
    expect(screen.getByText(/Re-record with video capture enabled/i)).toBeInTheDocument()
  })
})

describe("SequenceAnalysisPanel — insufficient_frames status", () => {
  it("renders correct notice for insufficient_frames", () => {
    render(<SequenceAnalysisPanel analysis={FAILED_ANALYSIS} viewMode="student" />)
    expect(screen.getByText(/Not enough video keyframes were captured/i)).toBeInTheDocument()
  })
})
