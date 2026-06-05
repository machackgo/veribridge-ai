import { fireEvent, render, screen } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { beforeEach, describe, expect, it } from "vitest"
import {
  DetectedSkillProfileSection,
  ExtensionProofPanel,
  FinalEvaluatorCard,
  FinalRecommendationsSection,
  FutureProofModulesSection,
  LiveWebsiteCheckCard,
  ProjectDefenseResultCard,
  buildWorkflowAnalysisProgress,
  clearActiveExtensionProofSession,
  doesWorkflowProgressOverrideRecordingUi,
  hasActiveExtensionProofSession,
  loadActiveExtensionProofSession,
  mergeVisibleSourceScores,
  saveActiveExtensionProofSession,
  shouldShowWorkflowAnalysisProgress,
  websiteProofProgressReducer,
} from "../../components/skill-proof/extension-proof-panel"
import type { FinalEvaluationResult, LiveWebsiteCheckResponse, ProjectDefenseAnalysisResponse } from "../lib/api"

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
})

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

  it("does not render disabled coming-soon labels for unsupported recommendation buttons", () => {
    render(
      <FinalRecommendationsSection
        evaluation={evaluation({
          final_score: 70,
          next_best_actions: [{
            action_type: "upload_document",
            target_skill: "Deployment evidence",
            reason: "Local/private URL detected; live website check is not applicable.",
            objective: "Add setup instructions or deployment evidence.",
            button_label: "Add deployment/setup evidence",
            priority: "medium",
            is_recording: false,
            recommended_duration: null,
          }],
        })}
        sessionId="s1"
      />,
    )
    expect(screen.getByText("Add deployment/setup evidence")).toBeInTheDocument()
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument()
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

describe("Workflow Evidence Analysis progress card", () => {
  it("is hidden during recording", () => {
    expect(shouldShowWorkflowAnalysisProgress({
      lifecycle: "recording",
    })).toBe(false)
    expect(buildWorkflowAnalysisProgress({ lifecycle: "recording" }).stages).toHaveLength(0)
  })

  it("appears immediately when upload starts after Stop & Send Proof", () => {
    const lifecycle = websiteProofProgressReducer("recording", { type: "stop_send_clicked" })
    expect(lifecycle).toBe("upload_starting")
    expect(shouldShowWorkflowAnalysisProgress({ lifecycle })).toBe(true)
    const model = buildWorkflowAnalysisProgress({
      lifecycle,
    })
    expect(model.title).toBe("Uploading workflow proof")
    expect(model.percent).toBeGreaterThanOrEqual(5)
    expect(model.stages).toEqual([{ key: "uploading", label: "Uploading proof recording", status: "active" }])
    expect(model.currentMessage).toBe("Uploading proof recording — keep this tab open.")
  })

  it("uploading state does not show analysis stages", () => {
    const model = buildWorkflowAnalysisProgress({
      lifecycle: "uploading",
    })
    const labels = model.stages.map((stage) => stage.label).join(" ")
    expect(labels).toContain("Uploading proof recording")
    expect(labels).not.toMatch(/Extracting keyframes|OCR|Qwen|timeline|report/i)
  })

  it("upload success with manual analysis required shows upload complete and no static analysis checklist", () => {
    const lifecycle = websiteProofProgressReducer("uploading", { type: "upload_succeeded" })
    expect(lifecycle).toBe("upload_complete_manual_analysis_required")
    expect(shouldShowWorkflowAnalysisProgress({ lifecycle })).toBe(true)
    const model = buildWorkflowAnalysisProgress({ lifecycle })
    expect(model.title).toBe("Uploading workflow proof")
    expect(model.currentMessage).toBe("Proof uploaded. Click Analyze Workflow Evidence to start workflow analysis.")
    expect(model.stages).toEqual([{ key: "uploading", label: "Uploading proof recording", status: "complete" }])
    expect(model.stages.map((stage) => stage.label).join(" ")).not.toMatch(/OCR|Qwen|timeline|report/i)
  })

  it("is hidden when the Workflow Evidence Analysis report exists", () => {
    const lifecycle = websiteProofProgressReducer("generating_workflow_report", { type: "workflow_report_exists" })
    expect(lifecycle).toBe("workflow_report_ready")
    expect(shouldShowWorkflowAnalysisProgress({ lifecycle })).toBe(false)
    expect(buildWorkflowAnalysisProgress({ lifecycle }).stages).toHaveLength(0)
  })

  it("clicking Analyze Workflow Evidence immediately starts analysis progress", () => {
    const lifecycle = websiteProofProgressReducer("upload_complete_manual_analysis_required", { type: "analyze_clicked" })
    const model = buildWorkflowAnalysisProgress({ lifecycle })
    expect(lifecycle).toBe("analysis_starting")
    expect(model.title).toBe("Workflow Evidence Analysis in Progress")
    expect(model.currentMessage).toContain("Starting workflow evidence analysis")
    expect(model.stages).toEqual([{ key: "extracting_keyframes", label: "Extracting keyframes", status: "active" }])
  })

  it("advances analysis stages stage-by-stage instead of showing all pending rows", () => {
    const thirtySeconds = websiteProofProgressReducer("analysis_starting", { type: "analysis_polling_result", elapsedMs: 30_000 })
    expect(thirtySeconds).toBe("running_qwen_visual")
    const model = buildWorkflowAnalysisProgress({ lifecycle: thirtySeconds, activeElapsedMs: 30_000 })
    expect(model.stages.map((stage) => stage.label)).toEqual([
      "Extracting keyframes",
      "Running OCR / visual evidence checks",
      "Running Qwen visual reasoning",
    ])
    expect(model.stages.map((stage) => stage.status)).toEqual(["complete", "complete", "active"])
    expect(model.stages.map((stage) => stage.label).join(" ")).not.toContain("Generating recruiter-safe workflow report")
  })

  it("contains workflow-only analysis stages", () => {
    const model = buildWorkflowAnalysisProgress({ lifecycle: "generating_workflow_report", activeElapsedMs: 61_000 })
    const labels = model.stages.map((stage) => stage.label).join(" ")
    expect(labels).toContain("Extracting keyframes")
    expect(labels).toContain("Running OCR / visual evidence checks")
    expect(labels).toContain("Running Qwen visual reasoning")
    expect(labels).toContain("Matching browser workflow timeline to claimed skills")
    expect(labels).toContain("Generating recruiter-safe workflow report")
    expect(labels).not.toMatch(/GitHub|Project Defense|Documents|Final Evidence Score|Live Website Check/i)
  })

  it("shows failed workflow analysis as retryable in the compact card model", () => {
    const model = buildWorkflowAnalysisProgress({
      lifecycle: "analysis_failed",
    })
    expect(model.failed).toBe(true)
    expect(model.stages.some((stage) => stage.status === "failed")).toBe(true)
    expect(model.currentMessage).toContain("failed")
  })

  it("shows failed upload state without activating analysis stages", () => {
    const model = buildWorkflowAnalysisProgress({
      lifecycle: "upload_failed",
      uploadError: "Network error",
    })
    expect(model.failed).toBe(true)
    expect(model.currentMessage).toBe("Proof upload failed. Please retry.")
    expect(model.stages.find((stage) => stage.key === "uploading")?.status).toBe("failed")
    expect(model.stages.map((stage) => stage.label).join(" ")).not.toMatch(/OCR|Qwen|timeline|report/i)
  })

  it("shows a friendly still-uploading note for long uploads", () => {
    const model = buildWorkflowAnalysisProgress({
      lifecycle: "uploading",
      activeElapsedMs: 61_000,
    })
    expect(model.showSlowWarning).toBe(true)
    expect(model.slowWarningMessage).toContain("Still uploading")
  })

  it("shows a friendly still-working note for long-running workflow analysis", () => {
    const model = buildWorkflowAnalysisProgress({
      lifecycle: "generating_workflow_report",
      activeElapsedMs: 91_000,
    })
    expect(model.showSlowWarning).toBe(true)
    expect(model.slowWarningMessage).toContain("Still analyzing")
  })

  it("regression: upload progress is visible before any proofUploaded result arrives", () => {
    const lifecycle = websiteProofProgressReducer("recording", { type: "upload_started" })
    const model = buildWorkflowAnalysisProgress({ lifecycle, activeElapsedMs: 45_000 })
    expect(shouldShowWorkflowAnalysisProgress({ lifecycle })).toBe(true)
    expect(model.title).toBe("Uploading workflow proof")
    expect(model.currentMessage).toBe("Uploading proof recording — keep this tab open.")
  })

  it("uploading state has priority over recording UI", () => {
    expect(doesWorkflowProgressOverrideRecordingUi("recording")).toBe(false)
    expect(doesWorkflowProgressOverrideRecordingUi("upload_starting")).toBe(true)
    expect(doesWorkflowProgressOverrideRecordingUi("uploading")).toBe(true)
    expect(doesWorkflowProgressOverrideRecordingUi("upload_complete_manual_analysis_required")).toBe(true)
  })

  it("regression: recording card is not rendered while lifecycle is uploading", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
      "utf8",
    )
    const overrideIndex = source.indexOf("const workflowProgressOverridesRecordingUi")
    const statusIndex = source.indexOf("!workflowProgressOverridesRecordingUi &&", overrideIndex)
    const recordingTextIndex = source.indexOf("VeriBridge Extension is recording")
    expect(overrideIndex).toBeGreaterThan(-1)
    expect(statusIndex).toBeGreaterThan(overrideIndex)
    expect(recordingTextIndex).toBeGreaterThan(-1)
  })

  it("does not jump directly to upload 100 without first rendering upload-start state", () => {
    const started = websiteProofProgressReducer("recording", { type: "upload_started" })
    const startedModel = buildWorkflowAnalysisProgress({ lifecycle: started })
    expect(started).toBe("uploading")
    expect(startedModel.percent).toBeLessThan(100)
    expect(startedModel.currentMessage).toBe("Uploading proof recording — keep this tab open.")

    const completed = websiteProofProgressReducer(started, { type: "upload_succeeded" })
    const completedModel = buildWorkflowAnalysisProgress({ lifecycle: completed })
    expect(completed).toBe("upload_complete_manual_analysis_required")
    expect(completedModel.percent).toBe(100)
  })

  it("extension emits upload-start before async upload success can occur", () => {
    const source = readFileSync(
      join(process.cwd(), "../extension/src/background.ts"),
      "utf8",
    )
    const sendProofIndex = source.indexOf("async function sendProof")
    const uploadingIndex = source.indexOf('state.status = "uploading"', sendProofIndex)
    const startedIndex = source.indexOf("broadcastProofUploadStarted()", sendProofIndex)
    const fetchIndex = source.indexOf("await fetch(", sendProofIndex)
    const successIndex = source.indexOf('state.status = "uploaded"', sendProofIndex)
    expect(sendProofIndex).toBeGreaterThan(-1)
    expect(uploadingIndex).toBeGreaterThan(sendProofIndex)
    expect(startedIndex).toBeGreaterThan(uploadingIndex)
    expect(fetchIndex).toBeGreaterThan(startedIndex)
    expect(successIndex).toBeGreaterThan(fetchIndex)
    expect(source).toContain('type: "PROOF_UPLOAD_STARTED"')
  })

  it("content script forwards upload-started to the page before relying on upload success", () => {
    const source = readFileSync(
      join(process.cwd(), "../extension/src/content.ts"),
      "utf8",
    )
    expect(source).toContain('msg.type === "PROOF_UPLOAD_STARTED"')
    expect(source).toContain('type: "VERIBRIDGE_PROOF_UPLOAD_STARTED"')
    expect(source).toContain("proofSessionId")
    expect(source).toContain('}, "*")')
    const forwardIndex = source.indexOf('type: "VERIBRIDGE_PROOF_UPLOAD_STARTED"')
    const sendProofIndex = source.indexOf('type: "SEND_PROOF"')
    expect(forwardIndex).toBeGreaterThan(-1)
    expect(sendProofIndex).toBeGreaterThan(-1)
  })

  it("web listener handles upload-started event directly", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
      "utf8",
    )
    const eventIndex = source.indexOf('data.type === "VERIBRIDGE_PROOF_UPLOAD_STARTED"')
    const stateIndex = source.indexOf('status: "uploading"', eventIndex)
    const reducerIndex = source.indexOf('transitionWebsiteProofProgress({ type: "upload_started" })', eventIndex)
    expect(eventIndex).toBeGreaterThan(-1)
    expect(stateIndex).toBeGreaterThan(eventIndex)
    expect(reducerIndex).toBeGreaterThan(stateIndex)
  })

  it("is placed after Verification Checklist and before the workflow report source", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
      "utf8",
    )
    const checklistIndex = source.indexOf("<EvidenceChecklist")
    const progressIndex = source.indexOf("<WorkflowAnalysisProgressCard")
    const reportIndex = source.indexOf("<WorkflowAnalysisCard")
    expect(checklistIndex).toBeGreaterThan(-1)
    expect(progressIndex).toBeGreaterThan(checklistIndex)
    expect(reportIndex).toBeGreaterThan(progressIndex)
    expect(source).not.toContain("Verification Progress")
  })
})

describe("Website Proof form state", () => {
  it("opens normal Website Proof with blank fields", () => {
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

  it("persists and clears the active Website Proof session for return restoration", () => {
    saveActiveExtensionProofSession({
      sessionId: "s-localhost-3000",
      form: {
        websiteUrl: "http://localhost:3000",
        githubUrl: "https://github.com/machackgo/veribridge-ai",
        skillName: "Next.js, React",
        proofObjective: "Demonstrate local app navigation stays attached to this proof session",
      },
      savedAt: "2026-06-05T12:00:00.000Z",
    })

    expect(hasActiveExtensionProofSession()).toBe(true)
    expect(loadActiveExtensionProofSession()).toMatchObject({
      sessionId: "s-localhost-3000",
      form: {
        websiteUrl: "http://localhost:3000",
        githubUrl: "https://github.com/machackgo/veribridge-ai",
        skillName: "Next.js, React",
      },
    })

    clearActiveExtensionProofSession()
    expect(hasActiveExtensionProofSession()).toBe(false)
  })

  it("parent proof modal can auto-restore directly into Website Proof mode", () => {
    const source = readFileSync(
      join(process.cwd(), "components/skill-proof/student-proof-submission-panel.tsx"),
      "utf8",
    )
    expect(source).toContain("hasActiveExtensionProofSession()")
    expect(source).toContain('setProofMode("extension_proof")')
    expect(source).toContain("setOpen(true)")
  })
})
