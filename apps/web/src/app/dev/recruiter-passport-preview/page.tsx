"use client"

/**
 * DEV PREVIEW ONLY — not linked in production navigation.
 *
 * Renders RecruiterWorkPassportPreview using backend recruiter-safe data when
 * the backend is available, or falls back to mock data when it is not.
 *
 * URL: http://localhost:3000/dev/recruiter-passport-preview
 */

import { useState, useEffect } from "react"
import { listRecruiterSkillEvidencePipelines } from "@/lib/api"
import { RecruiterWorkPassportPreview } from "../../../../components/recruiter-passport/RecruiterWorkPassportPreview"
import {
  createAccessRequest,
  clearMockEvidenceAccessRequests,
  DEMO_PASSPORT_SLUG,
} from "../../../lib/mock-evidence-access-store"
import type { RecruiterPassportViewResponse } from "../../../lib/passport-api"
import type { EvidenceAccessFormData } from "../../../../components/recruiter-passport/EvidenceAccessRequestModal"

// ── Mock data ─────────────────────────────────────────────────────────────────
// All fields are recruiter-safe: no media_storage_path, no access tokens,
// no raw transcripts, no admin notes, no private URLs, no debug metadata.

const MOCK_VIEW: RecruiterPassportViewResponse = {
  public_slug: DEMO_PASSPORT_SLUG,
  student_display_name: "Maya Reyes",
  field: "Artificial Intelligence / Data Science",
  public_title: "AI Engineer Intern — WPI",
  public_summary:
    "Graduate student at WPI specialising in machine learning, browser-based AI, and data visualisation. " +
    "Built and deployed multiple evidence-backed AI projects including an in-browser ML classifier, " +
    "a 3D WebGL rendering pipeline, and a conversational LLM interface.",
  overall_score: 87,
  evidence_confidence: "high",
  verification_status: "Evidence reviewed",
  readiness_level: "Strongly Ready",
  project_type: "ML / AI Engineer",

  skill_groups: [
    {
      group_name: "AI / Machine Learning",
      category: "AI/ML",
      confidence: "high",
      evidence_count: 6,
      source_labels: ["Website Workflow", "GitHub", "AI Visual Analysis", "Documents"],
      skills: [
        {
          skill: "Machine Learning",
          confidence: "high",
          status_label: "claimed — strongly supported",
          source_labels: ["Website Workflow", "GitHub", "Documents"],
        },
        {
          skill: "NLP / Large Language Models",
          confidence: "medium",
          status_label: "claimed — partially supported",
          source_labels: ["Website Workflow", "AI Visual Analysis"],
        },
        {
          skill: "TensorFlow.js / Browser ML",
          confidence: "high",
          status_label: "claimed — strongly supported",
          source_labels: ["Website Workflow", "GitHub"],
        },
      ],
    },
    {
      group_name: "JavaScript / Frontend",
      category: "FRONTEND",
      confidence: "high",
      evidence_count: 4,
      source_labels: ["GitHub", "Website Workflow", "OCR"],
      skills: [
        {
          skill: "JavaScript",
          confidence: "high",
          status_label: "claimed — strongly supported",
          source_labels: ["GitHub"],
        },
        {
          skill: "Three.js / WebGL",
          confidence: "high",
          status_label: "claimed — strongly supported",
          source_labels: ["Website Workflow", "AI Visual Analysis", "GitHub"],
        },
        {
          skill: "React",
          confidence: "medium",
          status_label: "inferred from evidence",
          source_labels: ["GitHub"],
        },
      ],
    },
    {
      group_name: "Data & Visualization",
      category: "DATA",
      confidence: "medium",
      evidence_count: 3,
      source_labels: ["Website Workflow", "OCR", "Documents"],
      skills: [
        {
          skill: "Data Visualization",
          confidence: "medium",
          status_label: "claimed — partially supported",
          source_labels: ["Website Workflow", "OCR"],
        },
        {
          skill: "D3.js",
          confidence: "medium",
          status_label: "inferred from evidence",
          source_labels: ["GitHub"],
        },
      ],
    },
    {
      group_name: "DevOps / Deployment",
      category: "DEVOPS",
      confidence: "low",
      evidence_count: 1,
      source_labels: ["Documents"],
      skills: [
        {
          skill: "DevOps / Deployment",
          confidence: "low",
          status_label: "claimed — needs more evidence",
          source_labels: ["Documents"],
        },
      ],
    },
  ],

  verified_skills: [
    "Machine Learning",
    "TensorFlow.js / Browser ML",
    "JavaScript",
    "Three.js / WebGL",
  ],
  partially_verified_skills: [
    "NLP / Large Language Models",
    "Data Visualization",
    "D3.js",
    "React",
  ],
  skills_needing_review: ["DevOps / Deployment"],

  proof_sources: [
    { key: "website_workflow",      label: "Website Workflow",    status: "pass",    score: 82, is_run: true  },
    { key: "github",                label: "GitHub",              status: "pass",    score: 78, is_run: true  },
    { key: "video_keyframes",       label: "Video Keyframes",     status: "pass",    score: 90, is_run: true  },
    { key: "qwen_visual_reasoning", label: "AI Visual Analysis",  status: "partial", score: 65, is_run: true  },
    { key: "ocr",                   label: "OCR",                 status: "partial", score: 55, is_run: true  },
    { key: "project_defense",       label: "Project Defense",     status: "partial", score: 70, is_run: true  },
    { key: "uploaded_documents",    label: "Documents",           status: "pass",    score: 80, is_run: true  },
    { key: "live_website_check",    label: "Live Website",        status: "not_run", score: 0,  is_run: false },
  ],

  why_credible: [
    "GitHub repository evidence confirms code-level implementation of machine learning and browser-based AI.",
    "Website workflow recordings demonstrate real-time model inference in a browser environment.",
    "AI visual analysis observed interactive 3D WebGL rendering consistent with claimed skills.",
    "Project defense transcript was analyzed and shows strong ownership and technical clarity.",
    "Document evidence (project report) corroborates training pipeline and evaluation methodology.",
  ],

  strongest_skills: [
    "Machine Learning",
    "TensorFlow.js / Browser ML",
    "Three.js / WebGL",
    "JavaScript",
  ],

  areas_needing_review: [
    "DevOps / Deployment — only document evidence; no live deployment recorded",
    "Some visual evidence was partial — chat/response chain not fully captured",
    "Backend architecture requires GitHub or source-code evidence",
    "Private media (project defense recording) requires access approval",
  ],

  suggested_interview_questions: [
    "Can you explain how your model inference flow works end to end — from input to prediction output?",
    "Which parts of the ML pipeline did you implement yourself vs. use a library for?",
    "How would you improve monitoring or reliability in a production version of your project?",
    "Walk me through the WebGL rendering pipeline in your Three.js project.",
    "Your chatbot UI shows a prompt being submitted — what happens on the backend from that point?",
  ],

  public_project_links: [
    {
      label: "Browser ML Demo — Teachable Machine",
      url: "https://teachablemachine.withgoogle.com/",
    },
    {
      label: "Three.js WebGL Geometry Demo",
      url: "https://threejs.org/examples/",
    },
    {
      label: "HuggingChat LLM Interface",
      url: "https://huggingface.co/chat/",
    },
  ],

  access_request_available: true,
  has_protected_evidence: true,
  disclosure_note:
    "This is a recruiter-safe summary. Protected evidence — including full workflow recordings, " +
    "private project defense media, and detailed skill reports — requires student-approved access. " +
    "No private links, credentials, raw transcripts, or internal diagnostics are exposed here.",
}

// ── Page ──────────────────────────────────────────────────────────────────────

function handleRequestCreated(data: EvidenceAccessFormData) {
  createAccessRequest(
    {
      requesterName: data.requester_name,
      requesterEmail: data.requester_email,
      company: data.company,
      role: data.role,
      reason: data.reason,
      requestedEvidenceTypes: data.requested_sections,
      messageToStudent: data.message_to_student,
    },
    MOCK_VIEW.public_slug,
  )
}

export default function DevRecruiterPassportPreviewPage() {
  const [accessRequested, setAccessRequested] = useState(false)
  // Incrementing resetKey remounts RecruiterWorkPassportPreview so its useEffect
  // re-reads the store after a reset.
  const [resetKey, setResetKey] = useState(0)
  // "loading" while the backend probe is in-flight; "available" when backend
  // responded (even with []); "unavailable" when the call failed or returned null.
  const [backendStatus, setBackendStatus] = useState<"loading" | "available" | "unavailable">("loading")

  useEffect(() => {
    let cancelled = false
    listRecruiterSkillEvidencePipelines().then((data) => {
      if (!cancelled) setBackendStatus(data !== null ? "available" : "unavailable")
    }).catch(() => {
      if (!cancelled) setBackendStatus("unavailable")
    })
    return () => { cancelled = true }
  }, [])

  const handleReset = () => {
    clearMockEvidenceAccessRequests()   // writes [] so sample-data pending never re-loads
    setAccessRequested(false)
    setResetKey((k) => k + 1)
  }

  // Strip skill groups and protected evidence from the view while loading or
  // when the backend is reachable, so the component uses the backend's own
  // recruiter-safe pipeline response (with real visibility enforcement) rather
  // than hardcoded mock groups. has_protected_evidence=false while loading
  // prevents the mock access store from showing stale approved/pending state
  // during the fetch. Only when the backend call explicitly fails do we fall
  // back to the full mock view.
  const activeView: RecruiterPassportViewResponse = backendStatus === "unavailable"
    ? MOCK_VIEW
    : {
        ...MOCK_VIEW,
        skill_groups: [],
        verified_skills: [],
        partially_verified_skills: [],
        skills_needing_review: [],
        has_protected_evidence: false,
      }

  return (
    <div style={{
      minHeight: "100vh",
      background: "#f8fafc",
      fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
    }}>
      {/* Dev banner */}
      <div style={{
        background: "#fef3c7",
        borderBottom: "2px solid #fbbf24",
        padding: "10px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 10,
        flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16 }}>🛠</span>
          <span style={{ fontWeight: 700, fontSize: 13, color: "#92400e" }}>
            Development preview
          </span>
          {backendStatus === "loading" && (
            <span
              data-testid="banner-loading-badge"
              style={{ fontSize: 12, color: "#b45309" }}
            >
              Connecting to backend…
            </span>
          )}
          {backendStatus === "available" && (
            <span
              data-testid="banner-backend-badge"
              style={{
                fontSize: 12, fontWeight: 700,
                color: "#166534", background: "#dcfce7",
                padding: "2px 10px", borderRadius: 999,
                border: "1px solid #bbf7d0",
              }}
            >
              Backend recruiter-safe data
            </span>
          )}
          {backendStatus === "unavailable" && (
            <span
              data-testid="banner-fallback-badge"
              style={{
                fontSize: 12, fontWeight: 700,
                color: "#92400e", background: "#fef3c7",
                padding: "2px 10px", borderRadius: 999,
                border: "1px solid #fbbf24",
              }}
            >
              Fallback mock preview
            </span>
          )}
          <span style={{ fontSize: 12, color: "#b45309" }}>
            · No private fields · Not linked in production
          </span>
        </div>
        {backendStatus === "unavailable" && (
          <button
            type="button"
            data-testid="banner-reset-btn"
            onClick={handleReset}
            style={{
              fontSize: 11, fontWeight: 600, color: "#92400e",
              background: "#fef3c7", border: "1px solid #f59e0b",
              borderRadius: 6, padding: "4px 10px", cursor: "pointer",
            }}
          >
            Reset mock access requests
          </button>
        )}
      </div>

      {/* Candidate header */}
      <div style={{
        background: "linear-gradient(135deg, #0a0e1a 0%, #1e293b 100%)",
        padding: "36px 24px 32px",
      }}>
        <div style={{ maxWidth: 860, margin: "0 auto" }}>
          <div style={{
            fontSize: 10, letterSpacing: "0.18em", color: "#64748b",
            textTransform: "uppercase", marginBottom: 8, fontFamily: "monospace",
          }}>
            Verified Work Passport · Recruiter View
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: "#fff", margin: "0 0 6px", letterSpacing: "-0.02em" }}>
            {MOCK_VIEW.student_display_name}
          </h1>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "0 0 4px" }}>
            {MOCK_VIEW.field}
          </p>
          <p style={{ fontSize: 13, color: "#64748b", margin: 0 }}>
            Target role: <strong style={{ color: "#a5b4fc" }}>AI Engineer Intern</strong>
            <span style={{ margin: "0 8px", color: "#334155" }}>·</span>
            WPI
          </p>

          {accessRequested && (
            <div style={{
              marginTop: 16, display: "inline-block",
              padding: "6px 14px", borderRadius: 999,
              background: "#dcfce7", color: "#166534",
              fontSize: 12, fontWeight: 700,
              border: "1px solid #bbf7d0",
            }}>
              ✅ Access request submitted — student has been notified
            </div>
          )}
        </div>
      </div>

      {/* Preview content */}
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "28px 20px 48px" }}>
        <RecruiterWorkPassportPreview
          key={resetKey}
          view={activeView}
          onRequestAccess={() => setAccessRequested(true)}
          onRequestCreated={handleRequestCreated}
          onReset={backendStatus === "unavailable" ? handleReset : undefined}
          defaultRequester={{
            name: "Stripe Early Talent",
            email: "recruiter@stripe.com",
            company: "Stripe",
            role: "Early Talent / AI Intern Hiring",
          }}
        />
      </div>
    </div>
  )
}
