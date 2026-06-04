import { fireEvent, render, screen } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { ExtensionProofPanel, FinalEvaluatorCard, FinalRecommendationsSection, ProjectDefenseResultCard } from "../../components/skill-proof/extension-proof-panel"
import type { FinalEvaluationResult, ProjectDefenseAnalysisResponse } from "../lib/api"

const learningAction = {
  title: "Add performance metrics",
  reason: "Geometry optimization should show measurable improvement.",
  action: "Display vertex count, face count, FPS, and render time.",
  skill_learned: "performance profiling, graphics optimization",
  evidence_to_record: "Show metrics changing when simplification is applied.",
  difficulty: "intermediate" as const,
  estimated_time: "1–2 hr" as const,
  priority: "medium" as const,
  source_reason: "Triggered by detected project type: 3d/graphics/webgl.",
  action_type: "learning_3d_metrics",
}

const proofAction = {
  title: "Add GitHub URL",
  reason: "React is claimed but no GitHub repository URL was provided.",
  action: "Add a public GitHub repository URL to enable code evidence analysis.",
  skill_learned: "React",
  evidence_to_record: "No recording required; run or upload the missing evidence source.",
  difficulty: "beginner" as const,
  estimated_time: "30 min" as const,
  priority: "high" as const,
  source_reason: "Triggered by github evidence: status=not_run, score=0/100.",
  action_type: "add_github_url",
}

function evaluation(overrides: Partial<FinalEvaluationResult>): FinalEvaluationResult {
  return {
    proof_session_id: "s1",
    final_score: 75,
    confidence: "medium",
    evidence_sources_used: [],
    evidence_sources_missing: [],
    per_skill_scores: {},
    evidence_source_breakdown: [],
    final_recruiter_summary: "",
    final_student_summary: "",
    next_best_actions: [],
    strong_proof: false,
    ...overrides,
  }
}

describe("FinalRecommendationsSection", () => {
  it("renders Recommended Next Actions for scores under 80", () => {
    render(
      <FinalRecommendationsSection
        evaluation={evaluation({
          final_score: 72,
          recommendations: { mode: "proof_repair", proof_actions: [proofAction], learning_actions: [learningAction] },
        })}
        sessionId="s1"
      />,
    )
    expect(screen.getByText("Recommended Next Actions")).toBeInTheDocument()
    expect(screen.getAllByText("Add GitHub URL").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Optional learning opportunities")).toBeInTheDocument()
  })

  it("renders Personalized Project Improvement Plan for scores 80 or higher", () => {
    render(
      <FinalRecommendationsSection
        evaluation={evaluation({
          final_score: 85,
          strong_proof: true,
          recommendations: { mode: "project_growth", proof_actions: [], learning_actions: [learningAction] },
        })}
        sessionId="s1"
      />,
    )
    expect(screen.getByText("Personalized Project Improvement Plan")).toBeInTheDocument()
    expect(screen.getByText(/Your proof is strong/)).toBeInTheDocument()
    expect(screen.queryByText("Recommended Next Actions")).not.toBeInTheDocument()
  })

  it("shows learning card fields when expanded", () => {
    render(
      <FinalRecommendationsSection
        evaluation={evaluation({
          final_score: 88,
          strong_proof: true,
          recommendations: { mode: "project_growth", proof_actions: [], learning_actions: [learningAction] },
        })}
        sessionId="s1"
      />,
    )
    fireEvent.click(screen.getByText(/Add performance metrics/))
    expect(screen.getByText(/Why:/)).toBeInTheDocument()
    expect(screen.getByText(/Build:/)).toBeInTheDocument()
    expect(screen.getByText(/Skill learned:/)).toBeInTheDocument()
    expect(screen.getByText(/Evidence to record:/)).toBeInTheDocument()
    expect(screen.getByText("intermediate")).toBeInTheDocument()
    expect(screen.getByText("1–2 hr")).toBeInTheDocument()
    expect(screen.getByText("Save as learning goal")).toBeInTheDocument()
    expect(screen.getByText("Start follow-up proof")).toBeInTheDocument()
    expect(screen.getByText("Copy task prompt")).toBeInTheDocument()
  })

  it("keeps the existing proof recommendation fallback working", () => {
    render(
      <FinalRecommendationsSection
        evaluation={evaluation({
          final_score: 70,
          next_best_actions: [{
            action_type: "record_followup_proof",
            target_skill: "React",
            reason: "React visual evidence is weak.",
            objective: "Record a focused demo.",
            button_label: "Record Follow-up Proof",
            priority: "medium",
            is_recording: true,
            recommended_duration: "30–60 seconds",
          }],
        })}
        sessionId="s1"
      />,
    )
    expect(screen.getByText("Recommended Next Actions")).toBeInTheDocument()
    expect(screen.getByText("React")).toBeInTheDocument()
  })
})

describe("Final report consistency", () => {
  it("Project Defense does not show contradictory scores", () => {
    const analysis = {
      id: "pd1",
      user_id: "u1",
      proof_session_id: "s1",
      video_url: null,
      media_url: null,
      media_type: null,
      media_filename: null,
      media_storage_path: null,
      transcription_status: "analysis_complete",
      transcript_reviewed: true,
      transcript_text: "I built the WebGL mesh simplifier.",
      raw_transcript: null,
      refined_transcript: null,
      transcript_correction_summary: [],
      transcript_glossary_matches: [],
      transcript_refinement_status: "not_started",
      transcript_needs_review: false,
      transcript_summary: "Student explained the project.",
      skills_mentioned: ["Three.js"],
      skills_explained_well: ["Three.js"],
      skills_missing_from_explanation: [],
      consistency_with_evidence_score: 70,
      explanation_clarity_score: 75,
      ownership_signal_score: 72,
      technical_depth_score: 74,
      overall_defense_score: 73,
      risk_flags: [],
      recruiter_summary: "Clear defense.",
      recommended_improvements: [],
      privacy_scan_status: "clean",
      created_at: null,
      updated_at: null,
    } as ProjectDefenseAnalysisResponse

    render(
      <ProjectDefenseResultCard
        analysis={analysis}
        sourceScore={{ score: 73, status: "pass" }}
      />,
    )

    expect(screen.getByText("Project Defense Score: 73/100")).toBeInTheDocument()
    expect(screen.queryByText("Defense Score")).not.toBeInTheDocument()
    expect(screen.queryByText("40/100")).not.toBeInTheDocument()
  })

  it("does not render Cross-Evidence Skill Summary in normal student flow", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
      "utf8",
    )
    expect(source).not.toMatch(/<CombinedEvidenceSummaryCard[\s>]/)
  })

  it("includes filtered unrelated activity notice in the workflow report source", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
      "utf8",
    )
    expect(source).toContain("Filtered unrelated activity")
    expect(source).toContain("were excluded from scoring")
  })

  it("shows Qwen filtered source as neutral instead of 0/100", () => {
    render(
      <FinalEvaluatorCard
        sessionId="s1"
        hideActions
        evaluation={evaluation({
          final_score: 79,
          evidence_source_breakdown: [{
            key: "qwen_visual_reasoning",
            status: "not_run",
            score: 0,
            weight: 0.1,
            notes: "non-target frames excluded from scoring",
          }],
        })}
      />,
    )
    expect(screen.getByText(/qwen visual reasoning/i)).toBeInTheDocument()
    expect(screen.getByText(/non-target frames excluded from scoring/)).toBeInTheDocument()
    expect(screen.queryByText("0/100")).not.toBeInTheDocument()
  })

  it("keeps disabled final-report feature labels out of normal UI source", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
      "utf8",
    )
    expect(source).not.toMatch(/Live Tutor|Scan Website|Guided Overlay/)
  })
})

describe("Website Proof form state", () => {
  it("opens normal Website Proof with blank fields", () => {
    sessionStorage.clear()
    render(<ExtensionProofPanel onBack={() => undefined} />)
    expect(screen.queryByText("Follow-up Proof Recording")).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i)).toHaveValue("")
    expect(screen.getByPlaceholderText("https://github.com/username/repo")).toHaveValue("")
    expect(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning")).toHaveValue("")
    expect(screen.getByPlaceholderText(/Describe what you'll walk through/i)).toHaveValue("")
  })

  it("starts follow-up Website Proof with banner and prefilled fields", async () => {
    sessionStorage.setItem("vb_followup_intent", JSON.stringify({
      parentSessionId: "s-parent",
      skill: "model monitoring, production ML operations",
      objective: "Log inference latency, input count, prediction distribution, and failed requests",
    }))
    render(<ExtensionProofPanel onBack={() => undefined} />)
    expect(await screen.findByText("Follow-up Proof Recording")).toBeInTheDocument()
    expect(screen.getByDisplayValue("model monitoring, production ML operations")).toBeInTheDocument()
    expect(screen.getByDisplayValue("Log inference latency, input count, prediction distribution, and failed requests")).toBeInTheDocument()
  })

  it("clears follow-up draft after closing then opening normal Website Proof", async () => {
    sessionStorage.setItem("vb_followup_intent", JSON.stringify({
      parentSessionId: "s-parent",
      skill: "model monitoring",
      objective: "Log inference latency and failed requests",
    }))
    const { unmount } = render(<ExtensionProofPanel onBack={() => undefined} />)
    expect(await screen.findByText("Follow-up Proof Recording")).toBeInTheDocument()
    fireEvent.click(screen.getByText("← Back to AI Proof Builder"))
    unmount()
    render(<ExtensionProofPanel onBack={() => undefined} />)
    expect(screen.queryByText("Follow-up Proof Recording")).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning")).toHaveValue("")
    expect(screen.getByPlaceholderText(/Describe what you'll walk through/i)).toHaveValue("")
  })
})
