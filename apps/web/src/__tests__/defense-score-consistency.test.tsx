/**
 * Project Defense score display coherence — regression tests.
 *
 * Historical bug (real production analysis): the UI showed
 * "Overall Defense Score 100/100" while the component gauges beside it read
 * Ownership 60/100, Technical Depth 65/100, Clarity 75/100. The stored
 * overall was an additive checklist score, not derivable from the displayed
 * components. Stored prod rows are never mutated, so the display must cap
 * the overall at what the components can support:
 *
 *   bound = 20 + 20 + 10 + 20·consistency/100 + 15·ownership/100 + 15·depth/100
 *
 * Covered here:
 *  1. coherentOverallDefenseScore clamps the exact prod-row values (100 → 89)
 *     and is the identity for coherent payloads.
 *  2. ProjectDefenseResultCard can never render an overall of 100 beside
 *     components 60/65/75.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  coherentOverallDefenseScore,
  maxCoherentOverallDefenseScore,
} from "@/lib/defense-score"
import { ProjectDefenseResultCard } from "../../components/skill-proof/extension-proof-panel"
import { AnalysisResults } from "../../components/passport/ProjectDefensePanel"
import type { ProjectDefenseAnalysisResponse } from "@/lib/api"
import type { DefenseAnalysisResponse } from "@/lib/vbr-api"

/** The exact values stored on the real prod row (session bdae349b…). */
const PROD_ROW_SCORES = {
  consistency_with_evidence_score: 100,
  explanation_clarity_score: 75,
  ownership_signal_score: 60,
  technical_depth_score: 65,
  overall_defense_score: 100,
}

function vbrAnalysisFixture(
  overrides: Partial<DefenseAnalysisResponse> = {},
): DefenseAnalysisResponse {
  return {
    transcript_summary: "Transcript (1035 words): architecture explanation.",
    skills_mentioned: ["React"],
    skills_explained_well: [],
    skills_missing_from_explanation: [],
    ...PROD_ROW_SCORES,
    risk_flags: [],
    recruiter_summary: "Project defense transcript analyzed.",
    recommended_improvements: [],
    privacy_scan_status: "clean",
    ...overrides,
  }
}

function defenseAnalysisFixture(
  overrides: Partial<ProjectDefenseAnalysisResponse> = {},
): ProjectDefenseAnalysisResponse {
  return {
    id: "analysis-1",
    user_id: "user-1",
    proof_session_id: "session-1",
    video_url: null,
    media_url: null,
    media_type: null,
    media_filename: null,
    media_storage_path: null,
    transcription_status: "completed",
    transcript_reviewed: true,
    transcript_text: "I built the analytics dashboard.",
    raw_transcript: null,
    refined_transcript: null,
    transcript_correction_summary: [],
    transcript_glossary_matches: [],
    transcript_refinement_status: "not_started",
    transcript_needs_review: false,
    transcript_summary: "Transcript (1035 words): architecture explanation.",
    skills_mentioned: ["React"],
    skills_explained_well: [],
    skills_missing_from_explanation: [],
    // The exact values stored on the real prod row (session bdae349b…):
    consistency_with_evidence_score: 100,
    explanation_clarity_score: 75,
    ownership_signal_score: 60,
    technical_depth_score: 65,
    overall_defense_score: 100,
    risk_flags: [],
    recruiter_summary: "Project defense transcript analyzed.",
    recommended_improvements: [],
    privacy_scan_status: "clean",
    created_at: "2026-07-21T00:00:00Z",
    updated_at: null,
    ...overrides,
  } as ProjectDefenseAnalysisResponse
}

describe("coherentOverallDefenseScore", () => {
  it("caps the exact legacy prod-row values: overall 100 beside 60/65 becomes 89", () => {
    expect(
      coherentOverallDefenseScore({
        overall_defense_score: 100,
        consistency_with_evidence_score: 100,
        ownership_signal_score: 60,
        technical_depth_score: 65,
      }),
    ).toBe(89) // 20+20+10 + 20·1.00 + round(15·0.60)=9 + round(15·0.65)=10
  })

  it("is the identity for a coherent payload", () => {
    expect(
      coherentOverallDefenseScore({
        overall_defense_score: 72,
        consistency_with_evidence_score: 80,
        ownership_signal_score: 90,
        technical_depth_score: 70,
      }),
    ).toBe(72)
  })

  it("allows a full overall only when the gauged components are full", () => {
    expect(
      coherentOverallDefenseScore({
        overall_defense_score: 100,
        consistency_with_evidence_score: 100,
        ownership_signal_score: 100,
        technical_depth_score: 100,
      }),
    ).toBe(100)
    expect(
      maxCoherentOverallDefenseScore({
        consistency_with_evidence_score: 100,
        ownership_signal_score: 90,
        technical_depth_score: 100,
      }),
    ).toBeLessThan(100)
  })

  it("fails closed on missing or out-of-range values", () => {
    expect(
      coherentOverallDefenseScore({
        overall_defense_score: 100,
        consistency_with_evidence_score: 0,
        ownership_signal_score: 0,
        technical_depth_score: 0,
      }),
    ).toBe(50)
    expect(
      coherentOverallDefenseScore({
        overall_defense_score: -10,
        consistency_with_evidence_score: 60,
        ownership_signal_score: 60,
        technical_depth_score: 60,
      }),
    ).toBe(0)
    expect(
      coherentOverallDefenseScore({
        overall_defense_score: 100,
        consistency_with_evidence_score: 500,
        ownership_signal_score: 100,
        technical_depth_score: 100,
      }),
    ).toBe(100)
  })
})

describe("AnalysisResults (ProjectDefensePanel) — numeric overall coherence", () => {
  const noop = () => undefined

  it("never renders Overall 100/100 beside components 60/65/75 (legacy prod row)", () => {
    render(
      <AnalysisResults
        analysis={vbrAnalysisFixture()}
        videoEvidenceChips={[]}
        syncStatus="idle"
        syncSkills={[]}
        syncError={null}
        onSync={noop}
      />,
    )
    // Component stats render as stored.
    expect(screen.getByText("Ownership signal").parentElement?.textContent).toContain("60/100")
    expect(screen.getByText("Technical depth").parentElement?.textContent).toContain("65/100")
    expect(screen.getByText("Explanation clarity").parentElement?.textContent).toContain("75/100")
    // The overall shows the coherently derived 89/100, never the stored 100/100.
    const overall = screen.getByText("Overall Defense Score").parentElement?.parentElement
    expect(overall?.textContent).toContain("89/100")
    expect(overall?.textContent).not.toContain("100/100")
  })

  it("renders a coherent stored overall unchanged", () => {
    render(
      <AnalysisResults
        analysis={vbrAnalysisFixture({
          overall_defense_score: 70,
          consistency_with_evidence_score: 80,
          ownership_signal_score: 80,
          technical_depth_score: 80,
        })}
        videoEvidenceChips={[]}
        syncStatus="idle"
        syncSkills={[]}
        syncError={null}
        onSync={noop}
      />,
    )
    const overall = screen.getByText("Overall Defense Score").parentElement?.parentElement
    expect(overall?.textContent).toContain("70/100")
  })
})

describe("ProjectDefenseResultCard — qualitative badge coherence", () => {
  it("a legacy stored overall cannot upgrade the badge beyond what components support", () => {
    // Stored overall=100 would read "strong evidence" (pass ≥ 60), but the
    // components only support a bound of 54 → "partial evidence".
    render(
      <ProjectDefenseResultCard
        analysis={defenseAnalysisFixture({
          overall_defense_score: 100,
          consistency_with_evidence_score: 0,
          ownership_signal_score: 10,
          technical_depth_score: 15,
        })}
      />,
    )
    const badge = screen.getByText(/Project Defense Score/i)
    expect(badge.textContent).toContain("partial evidence")
    expect(badge.textContent).not.toContain("strong evidence")
  })

  it("a coherent high analysis still reads strong evidence", () => {
    render(
      <ProjectDefenseResultCard
        analysis={defenseAnalysisFixture({
          overall_defense_score: 85,
          consistency_with_evidence_score: 100,
          ownership_signal_score: 90,
          technical_depth_score: 90,
        })}
      />,
    )
    expect(screen.getByText(/Project Defense Score/i).textContent).toContain("strong evidence")
  })
})
