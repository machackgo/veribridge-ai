import { fireEvent, render, screen } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { DetectedSkillProfileSection, ExtensionProofPanel, FinalEvaluatorCard, FinalRecommendationsSection, FutureProofModulesSection, LiveWebsiteCheckCard, mergeVisibleSourceScores, ProjectDefenseResultCard } from "../../components/skill-proof/extension-proof-panel"
import type { FinalEvaluationResult, LiveWebsiteCheckResponse, ProjectDefenseAnalysisResponse } from "../lib/api"

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

function liveCheck(overrides: Partial<LiveWebsiteCheckResponse>): LiveWebsiteCheckResponse {
  return {
    id: "live1",
    proof_session_id: "s1",
    status: "complete",
    website_url: "https://open-meteo.com/",
    final_url: null,
    status_code: 200,
    response_time_ms: 120,
    content_type: "text/html",
    page_title: "Open-Meteo",
    is_reachable: true,
    confidence: "high",
    risk_flags: [],
    recruiter_summary: "Website is reachable and returned HTTP 200.",
    error_message: null,
    checked_at: "2026-06-05T00:00:00Z",
    progress: 100,
    current_stage: "Complete",
    stages: [{ key: "saving_result", label: "Saving result", status: "complete" }],
    ...overrides,
  }
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
  it("renders public live website check complete as the green success card", () => {
    render(
      <LiveWebsiteCheckCard
        check={liveCheck({})}
        onRetry={() => undefined}
        sourceScore={{ score: 90, status: "pass" }}
      />,
    )
    expect(screen.getByText("Live Website Check — Complete")).toBeInTheDocument()
    expect(screen.getByText("Site is publicly reachable")).toBeInTheDocument()
    expect(screen.getByText("Live Website Score: 90/100")).toBeInTheDocument()
  })

  it("renders local private live website check as a neutral not-applicable card", () => {
    render(
      <LiveWebsiteCheckCard
        check={liveCheck({
          status: "not_applicable",
          website_url: "http://localhost:3000",
          status_code: null,
          response_time_ms: null,
          is_reachable: false,
          confidence: "not_applicable",
          recruiter_summary: "Local/private website detected — public live website check is not applicable.",
          current_stage: "Not applicable",
        })}
        onRetry={() => undefined}
        sourceScore={{ score: null, status: "not_applicable", notes: "Local/private website detected" }}
      />,
    )
    expect(screen.getByText("Live Website Check — Not applicable")).toBeInTheDocument()
    expect(screen.getByText("Public live check is not applicable for this URL")).toBeInTheDocument()
    expect(screen.getByText("Live Website Score: not applicable")).toBeInTheDocument()
    expect(screen.queryByText("Re-run Check")).not.toBeInTheDocument()
  })

  it("shows final live website source as not applicable without a 0 score", () => {
    render(
      <FinalEvaluatorCard
        sessionId="s1"
        hideActions
        evaluation={evaluation({
          final_score: 64,
          evidence_source_breakdown: [{
            key: "live_website_check",
            status: "not_applicable",
            score: null,
            weight: 0.05,
            notes: "Local/private website detected — public live website check is not applicable.",
          }],
        })}
      />,
    )
    expect(screen.getAllByText(/live website check/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/not applicable/i)).toBeInTheDocument()
    expect(screen.queryByText("0/100")).not.toBeInTheDocument()
  })

  it("keeps local private proof source sections visible alongside not-applicable live check", () => {
    render(
      <FinalEvaluatorCard
        sessionId="s1"
        hideActions
        evaluation={evaluation({
          final_score: 72,
          evidence_source_breakdown: [
            { key: "website_workflow", status: "pass", score: 72, weight: 0.25, notes: "workflow confidence=good" },
            { key: "github", status: "pass", score: 80, weight: 0.15, notes: "" },
            { key: "project_defense", status: "partial", score: 55, weight: 0.1, notes: "" },
            { key: "live_website_check", status: "not_applicable", score: null, weight: 0.05, notes: "Local/private website detected" },
          ],
        })}
      />,
    )
    expect(screen.getByText(/website workflow/i)).toBeInTheDocument()
    expect(screen.getByText(/github/i)).toBeInTheDocument()
    expect(screen.getByText(/project defense/i)).toBeInTheDocument()
    expect(screen.getByText(/live website check/i)).toBeInTheDocument()
    expect(screen.getByText(/not applicable/i)).toBeInTheDocument()
  })

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

  it("shows the score for a source that has analyzed (partial) evidence", () => {
    render(
      <FinalEvaluatorCard
        sessionId="s1"
        hideActions
        evaluation={evaluation({
          final_score: 62,
          evidence_source_breakdown: [{
            key: "qwen_visual_reasoning",
            status: "partial",
            score: 50,
            weight: 0.1,
            notes: "Qwen detected chatbot target content",
          }],
        })}
      />,
    )
    // Source with analyzed evidence must surface its score, never "not run".
    expect(screen.getByText(/qwen visual reasoning/i)).toBeInTheDocument()
    expect(screen.getByText(/50\/100/)).toBeInTheDocument()
    expect(screen.queryByText(/^not run$/i)).not.toBeInTheDocument()
  })

  it("merges visible source scores into stale final source cards", () => {
    const merged = mergeVisibleSourceScores(
      evaluation({
        final_score: 62,
        evidence_source_breakdown: [
          { key: "website_workflow", status: "not_run", score: 0, weight: 0.18, notes: "stale" },
          { key: "dom_visible_evidence", status: "not_run", score: 0, weight: 0.15, notes: "stale" },
          { key: "ocr", status: "not_run", score: 0, weight: 0.08, notes: "stale" },
          { key: "qwen_visual_reasoning", status: "not_run", score: 0, weight: 0.1, notes: "stale" },
          { key: "project_defense", status: "not_run", score: 0, weight: 0.15, notes: "stale" },
        ],
      }),
      {
        evidence_strength_score: 29,
        workflow_confidence: "low",
        visible_evidence_status: "not_captured",
        dom_evidence_status: "partial",
        demonstrated_actions: [],
        top_result_snippets: ["Leaflet marker popup"],
        observed_demonstration: {
          target_app: "leafletjs.com",
          summary: "DOM evidence partial",
          visible_evidence_status: "partial",
          dom_evidence_status: "partial",
          top_result_snippets: ["Leaflet marker popup"],
          steps: [],
        },
        frame_ocr_evidence_summary: {
          has_ocr_evidence: true,
          top_ocr_snippets: ["Leaflet map marker"],
          detected_page_context: "map page",
          skill_signals: [],
        },
        visual_analysis_status: "analyzed",
        video_keyframe_count: 2,
        visual_reasoning_summary: { status: "analyzed", frames_analyzed: 2 },
      } as any,
      {
        overall_defense_score: 67,
        consistency_with_evidence_score: 65,
        explanation_clarity_score: 70,
        ownership_signal_score: 60,
        technical_depth_score: 72,
      } as any,
    )

    expect(merged).not.toBeNull()
    const byKey = Object.fromEntries((merged!.evidence_source_breakdown ?? []).map((source) => [source.key, source]))
    expect(byKey.website_workflow?.score).toBe(29)
    expect(byKey.dom_visible_evidence?.score).toBe(50)
    expect(byKey.ocr?.score).toBe(50)
    expect(byKey.qwen_visual_reasoning?.score).toBe(80)
    expect(byKey.project_defense?.score).toBe(67)
    expect(byKey.website_workflow?.status).not.toBe("not_run")
    expect(byKey.dom_visible_evidence?.status).toBe("partial")
    expect(byKey.ocr?.status).not.toBe("not_run")
    expect(byKey.qwen_visual_reasoning?.status).not.toBe("not_run")
    expect(byKey.project_defense?.status).not.toBe("not_run")
  })

  it("keeps source-level skill diagnostics out of normal UI source", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
      "utf8",
    )
    expect(source).not.toMatch(/OCR evidence per skill|Qwen-detected signals|Skills Mentioned in Defense/)
  })

  it("shows unrelated Project Defense warning clearly", () => {
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
      transcript_text: "This is about Three.js mesh simplification.",
      raw_transcript: null,
      refined_transcript: null,
      transcript_correction_summary: [],
      transcript_glossary_matches: [],
      transcript_refinement_status: "not_started",
      transcript_needs_review: false,
      transcript_summary: "Technical but unrelated.",
      skills_mentioned: ["Three.js"],
      skills_explained_well: ["Three.js"],
      skills_missing_from_explanation: [],
      consistency_with_evidence_score: 20,
      explanation_clarity_score: 60,
      ownership_signal_score: 50,
      technical_depth_score: 60,
      overall_defense_score: 20,
      risk_flags: ["transcript appears unrelated to submitted proof"],
      recruiter_summary: "Transcript appears unrelated to submitted proof.",
      recommended_improvements: [],
      privacy_scan_status: "clean",
      created_at: null,
      updated_at: null,
    } as ProjectDefenseAnalysisResponse

    render(
      <ProjectDefenseResultCard
        analysis={analysis}
        sourceScore={{ score: 20, status: "partial", notes: "transcript appears unrelated to submitted proof" }}
      />,
    )

    expect(screen.getByText(/Transcript appears unrelated to the submitted proof/i)).toBeInTheDocument()
  })

  it("shows unrelated document warning clearly", () => {
    render(
      <FutureProofModulesSection
        sessionId="s1"
        documentScore={{ score: 0, status: "partial", notes: "document appears unrelated to submitted proof" }}
      />,
    )

    expect(screen.getByText(/Document appears unrelated to the submitted proof/i)).toBeInTheDocument()
  })
})

describe("Detected Skill Profile (grouped skill evidence)", () => {
  it("renders grouped skill evidence as the single skill summary", () => {
    render(
      <DetectedSkillProfileSection
        evaluation={evaluation({
          grouped_skill_evidence: [{
            group_name: "JavaScript / Frontend",
            category: "FRONTEND",
            confidence: "high",
            evidence_count: 2,
            sources_count: 2,
            source_labels: ["GitHub", "Recording"],
            skills: [{
              skill: "Chatbot UI",
              confidence: "high",
              evidence_support: "Supported by GitHub repository analysis",
              sources: ["GitHub"],
              is_inferred: false,
              status_label: "claimed — strongly supported",
              keyframe_evidence: [],
              github_evidence: [],
              category: "FRONTEND",
              source_labels: ["GitHub"],
              evidence_count: 1,
              sources_count: 1,
              evidence_objects: [],
            }],
          }],
        })}
      />,
    )
    // Grouped skill evidence section renders with its group (single skill summary).
    expect(screen.getByText(/Review grouped skill evidence/i)).toBeInTheDocument()
    expect(screen.getByText(/JavaScript \/ Frontend/i)).toBeInTheDocument()
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
