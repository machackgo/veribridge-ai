import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { createElement } from "react"
import { EvidenceObjectItem, FutureProofModulesSection, getGitHubTraceActionLabel } from "../../components/skill-proof/extension-proof-panel"
import type { EvidenceObject } from "../lib/api"

const baseEvidence: EvidenceObject = {
  evidence_type: "github_file",
  source_name: "GitHub",
  confidence: "high",
  short_summary: "Code evidence",
  recruiter_safe: true,
}

describe("Website Proof GitHub evidence labels", () => {
  it("renders Open GitHub lines when line URL data exists", () => {
    expect(getGitHubTraceActionLabel({
      github_url: "https://github.com/mrdoob/three.js/blob/dev/examples/webgl_materials_video.html#L82-L104",
      file_path: "examples/webgl_materials_video.html",
      line_start: 82,
      line_end: 104,
    })).toBe("Open GitHub lines")
  })

  it("renders Open GitHub file only when a file path and URL exist without lines", () => {
    expect(getGitHubTraceActionLabel({
      github_url: "https://github.com/mrdoob/three.js/blob/dev/examples/webgl_materials_video.html",
      file_path: "examples/webgl_materials_video.html",
      line_start: null,
      line_end: null,
    })).toBe("Open GitHub file")
  })

  it("renders Open GitHub repo for repo-level fallback", () => {
    expect(getGitHubTraceActionLabel({
      github_url: "https://github.com/mrdoob/three.js",
      file_path: null,
      line_start: null,
      line_end: null,
    })).toBe("Open GitHub repo")
  })
})

describe("Website Proof inline OCR/Qwen evidence", () => {
  it("renders OCR snippet inline without coming soon", () => {
    render(createElement(EvidenceObjectItem, { obj: {
      ...baseEvidence,
      evidence_type: "ocr_text",
      source_name: "OCR",
      short_summary: "OCR found relevant text",
      text_snippet: "Three.js demo controls visible",
      trace_action: "view_ocr",
      action_available: false,
    } }))
    expect(screen.getByText(/OCR snippet: "Three\.js demo controls visible"/)).toBeInTheDocument()
    expect(document.body.innerHTML).not.toMatch(/coming soon/i)
  })

  it("renders OCR unavailable text without a placeholder button", () => {
    render(createElement(EvidenceObjectItem, { obj: {
      ...baseEvidence,
      evidence_type: "ocr_text",
      source_name: "OCR",
      short_summary: "OCR was limited on canvas output",
      trace_action: "view_ocr",
      action_available: false,
    } }))
    expect(screen.getByText("OCR snippet not available")).toBeInTheDocument()
    expect(document.body.innerHTML).not.toMatch(/View OCR snippet|coming soon/i)
  })

  it("renders Qwen observation inline without coming soon", () => {
    render(createElement(EvidenceObjectItem, { obj: {
      ...baseEvidence,
      evidence_type: "qwen_visual",
      source_name: "Qwen",
      short_summary: "Three.js WebGL video demo with a rotating object",
      trace_action: "view_qwen",
      action_available: false,
    } }))
    expect(screen.getByText(/Qwen observation: Three\.js WebGL video demo/)).toBeInTheDocument()
    expect(document.body.innerHTML).not.toMatch(/coming soon/i)
  })

  it("renders Qwen unavailable text when observation is absent", () => {
    render(createElement(EvidenceObjectItem, { obj: {
      ...baseEvidence,
      evidence_type: "qwen_visual",
      source_name: "Qwen",
      short_summary: "",
      trace_action: "view_qwen",
      action_available: false,
    } }))
    expect(screen.getByText("Qwen observation not available")).toBeInTheDocument()
    expect(document.body.innerHTML).not.toMatch(/View Qwen observation|coming soon/i)
  })
})

describe("Optional evidence boosters", () => {
  it("renders only project document booster without failure language", () => {
    render(createElement(FutureProofModulesSection, {}))
    expect(screen.getByText("Documents / PDF / Reports Evidence")).toBeInTheDocument()
    expect(screen.queryByText("LinkedIn / Profile Proof")).not.toBeInTheDocument()
    expect(screen.queryByText("Certificates / Transcript Proof")).not.toBeInTheDocument()
    expect(screen.getAllByText("Optional — can strengthen your profile").length).toBe(1)
    expect(document.body.innerHTML).not.toMatch(/failed|missing required/i)
  })

  it("renders document page trace", () => {
    render(createElement(EvidenceObjectItem, { obj: {
      ...baseEvidence,
      evidence_type: "document_snippet",
      source_name: "Document",
      short_summary: "Supported by document text",
      text_snippet: "Built REST APIs using FastAPI.",
      page_number: 3,
    } }))
    expect(screen.getByText("Page 3")).toBeInTheDocument()
    expect(screen.getByText(/Built REST APIs using FastAPI/)).toBeInTheDocument()
  })

  it("renders LinkedIn profile trace", () => {
    render(createElement(EvidenceObjectItem, { obj: {
      ...baseEvidence,
      evidence_type: "profile_snippet",
      source_name: "LinkedIn/Profile",
      short_summary: "Inferred from profile text",
      text_snippet: "Data Science intern working on recommendation systems.",
      profile_url: "https://linkedin.com/in/example",
      section_label: "Experience",
    } }))
    expect(screen.getByText("Section: Experience")).toBeInTheDocument()
    expect(screen.getByText("Open profile")).toBeInTheDocument()
  })

  it("renders certificate issuer course and date trace", () => {
    render(createElement(EvidenceObjectItem, { obj: {
      ...baseEvidence,
      evidence_type: "certificate_or_transcript_snippet",
      source_name: "Certificate/Transcript",
      short_summary: "Supported by certificate text",
      text_snippet: "Completed Machine Learning course.",
      issuer: "Coursera",
      title: "Machine Learning",
      date: "2024",
    } }))
    expect(screen.getByText("Issuer: Coursera")).toBeInTheDocument()
    expect(screen.getByText("Title: Machine Learning")).toBeInTheDocument()
    expect(screen.getByText("Date: 2024")).toBeInTheDocument()
  })
})
