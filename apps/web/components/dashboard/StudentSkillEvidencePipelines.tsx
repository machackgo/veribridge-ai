"use client"

import React, { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import {
  getSkillPipeline,
  type SkillEvidencePipeline,
} from "../recruiter-passport/RecruiterWorkPassportPreview"
import {
  listSkillEvidencePipelines,
  seedMockSkillEvidencePipelines,
  updateSkillPipelineVisibility,
  type BackendSkillPipeline,
  type BackendEvidenceSource,
} from "@/lib/api"

// ── Skill list (mock fallback) ────────────────────────────────────────────────

const SKILL_NAMES = [
  "AI / Machine Learning",
  "JavaScript / Frontend",
  "Data & Visualization",
  "DevOps / Deployment",
]

// ── Skill-specific next actions ────────────────────────────────────────────────

const NEXT_ACTION: Record<string, string> = {
  "AI / Machine Learning":
    "Add a model evaluation report or demo showing input/output and accuracy metrics.",
  "JavaScript / Frontend":
    "Add a UI test recording or show component state handling and accessibility coverage.",
  "Data & Visualization":
    "Show data source, transformation step, and chart output together in one recording or document.",
  "DevOps / Deployment":
    "Deploy the app and upload documentation such as a Dockerfile, CI config, or deployment guide.",
}

// ── Unified display type ──────────────────────────────────────────────────────
// Works for data from backend OR from the static mock.

type EvidenceSourceItem = {
  key: string
  label: string
  status: "supported" | "partial" | "missing" | "protected"
  score?: number | null
  reason: string
}

type DirectActionItem = {
  sourceType: string
  sourceTitle: string
  projectName: string
  visibility: string
  confidence: "high" | "medium" | "low"
  proofReason: string
  artifactStatus: string
}

type DisplayPipeline = {
  id: string
  backendId?: string
  skillName: string
  category: string
  confidence: "high" | "medium" | "low"
  supportStatus: string
  overallExplanation: string
  evidenceSources: EvidenceSourceItem[]
  strongestProof?: string
  weakestProof?: string
  stillNeedsReview: string[]
  nextAction: string
  directActions: DirectActionItem[]
  fromBackend: boolean
}

type VisibilitySaveState = "idle" | "saving" | "saved" | "error"

// ── Visibility ────────────────────────────────────────────────────────────────

type VisibilityMode = "public" | "protected" | "private"

// ── Adapters ──────────────────────────────────────────────────────────────────

function scoreToConfidence(score: number): "high" | "medium" | "low" {
  if (score >= 75) return "high"
  if (score >= 50) return "medium"
  return "low"
}

function backendToDisplay(b: BackendSkillPipeline): DisplayPipeline {
  const supportStatusMap: Record<string, string> = {
    strongly_supported: "Strongly supported",
    partially_supported: "Partially supported",
    needs_review: "Needs stronger proof",
  }
  return {
    id: b.skill_name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    backendId: b.id,
    skillName: b.skill_name,
    category: b.skill_category,
    confidence: scoreToConfidence(b.confidence_score),
    supportStatus: supportStatusMap[b.support_status] ?? b.support_status,
    overallExplanation: b.student_summary || b.recruiter_summary,
    evidenceSources: (b.evidence_sources ?? []).map((s: BackendEvidenceSource) => ({
      key: s.key,
      label: s.label,
      status: s.status,
      score: s.score ?? undefined,
      reason: s.reason,
    })),
    strongestProof: b.strongest_proof?.label
      ? `${b.strongest_proof.label}${b.strongest_proof.reason ? ` — ${b.strongest_proof.reason}` : ""}`
      : undefined,
    weakestProof: b.weakest_proof?.label
      ? `${b.weakest_proof.label}${b.weakest_proof.reason ? ` — ${b.weakest_proof.reason}` : ""}`
      : undefined,
    stillNeedsReview: b.missing_evidence ?? [],
    nextAction:
      (b.next_actions ?? [])[0] ??
      NEXT_ACTION[b.skill_name] ??
      "Add more evidence to improve this skill's proof.",
    directActions: [],
    fromBackend: true,
  }
}

function mockToDisplay(m: SkillEvidencePipeline): DisplayPipeline {
  const fa = m.finalAnalysis
  const statusMap: Record<string, string> = {
    "strongly supported": "Strongly supported",
    "partially supported": "Partially supported",
    "needs review": "Needs stronger proof",
  }
  return {
    id: m.skillId,
    skillName: m.skillName,
    category: m.category,
    confidence: m.confidence,
    supportStatus: statusMap[m.supportStatus] ?? m.supportStatus,
    overallExplanation: m.overallExplanation,
    evidenceSources: m.evidenceSources.map((s) => ({
      key: s.key,
      label: s.label,
      status: s.status as EvidenceSourceItem["status"],
      score: s.score,
      reason: s.reason,
    })),
    strongestProof: fa?.strongestProof,
    weakestProof: fa?.weakestProof,
    stillNeedsReview: fa?.stillNeedsReview ?? [],
    nextAction:
      NEXT_ACTION[m.skillName] ?? "Add more evidence to improve this skill's proof.",
    directActions: (m.directActions ?? []).map((d) => ({
      sourceType: d.sourceType,
      sourceTitle: d.sourceTitle,
      projectName: d.projectName,
      visibility: d.visibility,
      confidence: d.confidence,
      proofReason: d.proofReason,
      artifactStatus: d.artifactStatus,
    })),
    fromBackend: false,
  }
}

// ── Color helpers ──────────────────────────────────────────────────────────────

function confidenceColors(c: "high" | "medium" | "low") {
  if (c === "high") return { bg: "#d1fae5", color: "#065f46", border: "#bbf7d0" }
  if (c === "medium") return { bg: "#fef3c7", color: "#92400e", border: "#fde68a" }
  return { bg: "#fee2e2", color: "#991b1b", border: "#fecaca" }
}

function sourceStatusColors(s: string) {
  if (s === "supported") return { bg: "#d1fae5", color: "#065f46", border: "#bbf7d0" }
  if (s === "partial") return { bg: "#fef3c7", color: "#92400e", border: "#fde68a" }
  if (s === "missing") return { bg: "#f3f4f6", color: "#6b7280", border: "#e5e7eb" }
  return { bg: "#fee2e2", color: "#991b1b", border: "#fecaca" }
}

function visibilityColors(v: VisibilityMode) {
  if (v === "public") return { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" }
  if (v === "protected") return { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" }
  return { bg: "#f9fafb", color: "#6b7280", border: "#e5e7eb" }
}

function supportStatusColors(s: string) {
  if (s === "Strongly supported") return sourceStatusColors("supported")
  if (s === "Partially supported") return sourceStatusColors("partial")
  return sourceStatusColors("missing")
}

const SOURCE_TYPE_LABEL: Record<string, string> = {
  workflow: "Workflow",
  github: "GitHub",
  visual: "Visual",
  ocr: "OCR",
  dom: "DOM",
  qwen: "Visual AI",
  transcript: "Transcript",
  document: "Document",
}

// ── SkillPipelineCard ──────────────────────────────────────────────────────────

function SkillPipelineCard({
  pipeline,
  visibility,
  savingState,
  onVisibilityChange,
  onManage,
}: {
  pipeline: DisplayPipeline
  visibility: VisibilityMode
  savingState: VisibilitySaveState
  onVisibilityChange: (v: VisibilityMode) => void
  onManage: () => void
}) {
  const conf = confidenceColors(pipeline.confidence)
  const statusC = supportStatusColors(pipeline.supportStatus)
  const supportedCount = pipeline.evidenceSources.filter(
    (s) => s.status === "supported",
  ).length
  const totalCount = pipeline.evidenceSources.length

  return (
    <div
      data-testid={`skill-pipeline-card-${pipeline.id}`}
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 14,
        padding: "16px 18px",
        background: "#fff",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {/* Badges row */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span
          style={{
            fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em",
            padding: "2px 7px", borderRadius: 4,
            background: "#f3f4f6", color: "#374151", border: "1px solid #e5e7eb",
          }}
        >
          {pipeline.category}
        </span>
        <span
          data-testid={`skill-confidence-${pipeline.id}`}
          style={{
            fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
            background: conf.bg, color: conf.color, border: `1px solid ${conf.border}`,
          }}
        >
          {pipeline.confidence} confidence
        </span>
        <span
          data-testid={`skill-status-${pipeline.id}`}
          style={{
            fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
            background: statusC.bg, color: statusC.color, border: `1px solid ${statusC.border}`,
          }}
        >
          {pipeline.supportStatus}
        </span>
      </div>

      {/* Skill name + student-safe explanation */}
      <div>
        <div
          data-testid={`skill-name-${pipeline.id}`}
          style={{ fontSize: 15, fontWeight: 700, color: "#111827", marginBottom: 4 }}
        >
          {pipeline.skillName}
        </div>
        <div style={{ fontSize: 11, color: "#6b7280", lineHeight: 1.5 }}>
          Evidence suggests: {pipeline.overallExplanation}
        </div>
      </div>

      {/* Evidence count + source coverage chips */}
      <div>
        <div style={{
          fontSize: 10, fontWeight: 700, color: "#6b7280", marginBottom: 5,
          textTransform: "uppercase", letterSpacing: "0.06em",
        }}>
          Source coverage &middot; {supportedCount} of {totalCount} confirmed
        </div>
        <div data-testid={`source-coverage-${pipeline.id}`} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {pipeline.evidenceSources.map((src) => {
            const sc = sourceStatusColors(src.status)
            return (
              <span
                key={src.key}
                data-testid={`source-chip-${pipeline.id}-${src.key}`}
                style={{
                  fontSize: 10, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
                  background: sc.bg, color: sc.color, border: `1px solid ${sc.border}`,
                }}
                title={src.reason}
              >
                {src.label}
              </span>
            )
          })}
        </div>
      </div>

      {/* Strongest / Weakest / Missing */}
      <div style={{ display: "grid", gap: 5 }}>
        {pipeline.strongestProof && (
          <div
            data-testid={`strongest-proof-${pipeline.id}`}
            style={{
              fontSize: 10, color: "#065f46", background: "#f0fdf4",
              border: "1px solid #bbf7d0", borderRadius: 6, padding: "5px 8px", lineHeight: 1.4,
            }}
          >
            <strong>Strongest:</strong> {pipeline.strongestProof}
          </div>
        )}
        {pipeline.weakestProof && (
          <div
            data-testid={`weakest-proof-${pipeline.id}`}
            style={{
              fontSize: 10, color: "#92400e", background: "#fffbeb",
              border: "1px solid #fde68a", borderRadius: 6, padding: "5px 8px", lineHeight: 1.4,
            }}
          >
            <strong>Weakest:</strong> {pipeline.weakestProof}
          </div>
        )}
        {pipeline.stillNeedsReview.length > 0 && (
          <div
            data-testid={`missing-evidence-${pipeline.id}`}
            style={{
              fontSize: 10, color: "#991b1b", background: "#fef2f2",
              border: "1px solid #fecaca", borderRadius: 6, padding: "5px 8px", lineHeight: 1.4,
            }}
          >
            <strong>Missing:</strong> {pipeline.stillNeedsReview[0]}
          </div>
        )}
      </div>

      {/* Visibility controls */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: "#6b7280", marginBottom: 5 }}>
          Visibility
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
          {(["public", "protected", "private"] as VisibilityMode[]).map((v) => {
            const vc = visibilityColors(v)
            const active = visibility === v
            const label =
              v === "public" ? "Public summary" : v === "protected" ? "Protected evidence" : "Private only"
            return (
              <button
                key={v}
                type="button"
                data-testid={`visibility-btn-${pipeline.id}-${v}`}
                onClick={() => onVisibilityChange(v)}
                style={{
                  fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 6,
                  cursor: "pointer",
                  background: active ? vc.bg : "#f9fafb",
                  color: active ? vc.color : "#6b7280",
                  border: active ? `1px solid ${vc.border}` : "1px solid #e5e7eb",
                  outline: "none",
                }}
              >
                {label}
              </button>
            )
          })}
          {savingState === "saving" && (
            <span
              data-testid={`visibility-saving-${pipeline.id}`}
              style={{ fontSize: 10, color: "#6b7280" }}
            >
              Saving…
            </span>
          )}
          {savingState === "saved" && (
            <span
              data-testid={`visibility-saved-${pipeline.id}`}
              style={{ fontSize: 10, color: "#059669", fontWeight: 600 }}
            >
              Saved
            </span>
          )}
          {savingState === "error" && (
            <span
              data-testid={`visibility-error-${pipeline.id}`}
              style={{ fontSize: 10, color: "#dc2626" }}
            >
              Error saving
            </span>
          )}
        </div>
      </div>

      {/* Next action */}
      <div
        data-testid={`next-action-${pipeline.id}`}
        style={{
          fontSize: 11, color: "#1d4ed8", background: "#eff6ff",
          border: "1px solid #bfdbfe", borderRadius: 6, padding: "7px 10px", lineHeight: 1.5,
        }}
      >
        <strong>Next action:</strong> {pipeline.nextAction}
      </div>

      {/* Manage button */}
      <button
        type="button"
        data-testid={`manage-btn-${pipeline.id}`}
        onClick={onManage}
        style={{
          alignSelf: "flex-start",
          fontSize: 12, fontWeight: 700, padding: "8px 16px", borderRadius: 8,
          background: "#1e40af", color: "#fff", border: "none", cursor: "pointer",
        }}
      >
        Manage skill evidence &rarr;
      </button>
    </div>
  )
}

// ── ManageSkillModal ──────────────────────────────────────────────────────────

function ManageSkillModal({
  pipeline,
  visibility,
  savingState,
  onVisibilityChange,
  onClose,
}: {
  pipeline: DisplayPipeline
  visibility: VisibilityMode
  savingState: VisibilitySaveState
  onVisibilityChange: (v: VisibilityMode) => void
  onClose: () => void
}) {
  const visC = visibilityColors(visibility)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [onClose])

  const modal = (
    <div
      data-testid="manage-skill-modal"
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        data-testid="manage-skill-modal-content"
        style={{
          background: "#fff", borderRadius: 16,
          width: "100%", maxWidth: 580, maxHeight: "85vh",
          overflow: "auto", display: "flex", flexDirection: "column",
          boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "16px 20px", borderBottom: "1px solid #e5e7eb",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          position: "sticky", top: 0, background: "#fff", zIndex: 1,
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#111827" }}>
              {pipeline.skillName}
            </div>
            <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
              Manage skill evidence &middot; {pipeline.category}
              {pipeline.fromBackend && (
                <span style={{ marginLeft: 6, color: "#10b981", fontWeight: 600 }}>
                  · Live from backend
                </span>
              )}
            </div>
          </div>
          <button
            type="button"
            data-testid="manage-modal-close"
            onClick={onClose}
            style={{
              fontSize: 18, background: "none", border: "none",
              cursor: "pointer", color: "#6b7280", padding: "4px 8px", lineHeight: 1,
            }}
          >
            &times;
          </button>
        </div>

        <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 18 }}>

          {/* Source coverage detail */}
          <div>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.06em", color: "#6b7280", marginBottom: 8,
            }}>
              Evidence source coverage
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {pipeline.evidenceSources.map((src) => {
                const sc = sourceStatusColors(src.status)
                return (
                  <div
                    key={src.key}
                    data-testid={`modal-source-${src.key}`}
                    style={{
                      display: "flex", alignItems: "flex-start", gap: 10,
                      padding: "8px 10px", border: `1px solid ${sc.border}`,
                      borderRadius: 8, background: sc.bg,
                    }}
                  >
                    <span style={{
                      fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                      background: "#fff", color: sc.color, border: `1px solid ${sc.border}`,
                      whiteSpace: "nowrap", marginTop: 1, flexShrink: 0,
                    }}>
                      {src.status}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: "#111827" }}>
                        {src.label}
                      </span>
                      {src.score != null && (
                        <span style={{ fontSize: 10, color: "#6b7280", marginLeft: 6 }}>
                          {src.score}/100
                        </span>
                      )}
                      <div style={{ fontSize: 10, color: "#374151", marginTop: 2, lineHeight: 1.4 }}>
                        {src.reason}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Evidence artifacts (mock-only — backend artifacts loaded separately) */}
          {pipeline.directActions.length > 0 && (
            <div>
              <div style={{
                fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                letterSpacing: "0.06em", color: "#6b7280", marginBottom: 8,
              }}>
                Evidence artifacts ({pipeline.directActions.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {pipeline.directActions.map((item, i) => {
                  const sc = sourceStatusColors(item.artifactStatus)
                  const conf = confidenceColors(item.confidence)
                  const visLabel =
                    item.visibility === "public"
                      ? "Public"
                      : item.visibility === "protected" || item.visibility === "approved"
                        ? "Protected"
                        : "Private"
                  return (
                    <div
                      key={i}
                      data-testid={`modal-artifact-${i}`}
                      style={{
                        border: "1px solid #e5e7eb", borderRadius: 8,
                        padding: "10px 12px", display: "flex", flexDirection: "column", gap: 5,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{
                          fontSize: 10, fontWeight: 700, color: "#475569",
                          textTransform: "uppercase", letterSpacing: "0.05em",
                        }}>
                          {SOURCE_TYPE_LABEL[item.sourceType] ?? item.sourceType}
                        </span>
                        <span style={{ fontSize: 11, fontWeight: 600, color: "#111827" }}>
                          {item.sourceTitle}
                        </span>
                        <span style={{
                          fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                          background: conf.bg, color: conf.color, border: `1px solid ${conf.border}`,
                        }}>
                          {item.confidence}
                        </span>
                        <span style={{
                          fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                          background: sc.bg, color: sc.color, border: `1px solid ${sc.border}`,
                        }}>
                          {item.artifactStatus}
                        </span>
                      </div>
                      <div style={{ fontSize: 10, color: "#374151", lineHeight: 1.4 }}>
                        {item.proofReason}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span
                          data-testid={`artifact-visibility-label-${i}`}
                          style={{
                            fontSize: 9, padding: "2px 7px", borderRadius: 4,
                            border: "1px solid #bfdbfe", background: "#eff6ff",
                            color: "#1d4ed8", fontWeight: 600,
                          }}
                        >
                          {visLabel}
                        </span>
                        <span style={{ fontSize: 10, color: "#6b7280" }}>{item.projectName}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Strongest / weakest */}
          <div style={{ display: "grid", gap: 5 }}>
            {pipeline.strongestProof && (
              <div style={{
                fontSize: 10, color: "#065f46", background: "#f0fdf4",
                border: "1px solid #bbf7d0", borderRadius: 6, padding: "6px 9px", lineHeight: 1.4,
              }}>
                <strong>Strongest proof:</strong> {pipeline.strongestProof}
              </div>
            )}
            {pipeline.weakestProof && (
              <div style={{
                fontSize: 10, color: "#92400e", background: "#fffbeb",
                border: "1px solid #fde68a", borderRadius: 6, padding: "6px 9px", lineHeight: 1.4,
              }}>
                <strong>Weakest proof:</strong> {pipeline.weakestProof}
              </div>
            )}
            {pipeline.stillNeedsReview.length > 0 && (
              <div style={{
                fontSize: 10, color: "#6b7280", background: "#f9fafb",
                border: "1px solid #e5e7eb", borderRadius: 6, padding: "6px 9px", lineHeight: 1.4,
              }}>
                <strong>Still needs review:</strong>{" "}
                {pipeline.stillNeedsReview.join(" · ")}
              </div>
            )}
          </div>

          {/* Recruiter visibility */}
          <div>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.06em", color: "#6b7280", marginBottom: 8,
            }}>
              What recruiters can see
            </div>
            <div style={{
              border: `1px solid ${visC.border}`, borderRadius: 8,
              padding: "10px 12px", background: visC.bg,
              display: "flex", flexDirection: "column", gap: 8,
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: visC.color }}>
                Current setting:{" "}
                {visibility === "public"
                  ? "Public summary"
                  : visibility === "protected"
                    ? "Protected evidence"
                    : "Private only"}
              </div>
              <div style={{ fontSize: 11, color: "#374151" }}>
                {visibility === "public" &&
                  "Recruiter can see: skill name, confidence level, and public evidence summary."}
                {visibility === "protected" &&
                  "Recruiter can see skill name and request access to protected evidence artifacts."}
                {visibility === "private" &&
                  "Recruiter cannot see this skill. It will not appear in the public passport."}
              </div>
              <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
                {(["public", "protected", "private"] as VisibilityMode[]).map((v) => {
                  const vc = visibilityColors(v)
                  const active = visibility === v
                  return (
                    <button
                      key={v}
                      type="button"
                      data-testid={`modal-visibility-${v}`}
                      onClick={() => onVisibilityChange(v)}
                      style={{
                        fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 6,
                        cursor: "pointer",
                        background: active ? vc.bg : "#f9fafb",
                        color: active ? vc.color : "#6b7280",
                        border: active ? `1px solid ${vc.border}` : "1px solid #e5e7eb",
                      }}
                    >
                      {v === "public" ? "Public" : v === "protected" ? "Protected" : "Private"}
                    </button>
                  )
                })}
                {savingState === "saving" && (
                  <span
                    data-testid={`modal-visibility-saving-${pipeline.id}`}
                    style={{ fontSize: 10, color: "#6b7280" }}
                  >
                    Saving…
                  </span>
                )}
                {savingState === "saved" && (
                  <span
                    data-testid={`modal-visibility-saved-${pipeline.id}`}
                    style={{ fontSize: 10, color: "#059669", fontWeight: 600 }}
                  >
                    Saved
                  </span>
                )}
                {savingState === "error" && (
                  <span
                    data-testid={`modal-visibility-error-${pipeline.id}`}
                    style={{ fontSize: 10, color: "#dc2626" }}
                  >
                    Error saving
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Suggested improvement */}
          <div>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.06em", color: "#6b7280", marginBottom: 6,
            }}>
              Suggested improvement
            </div>
            <div
              data-testid="modal-next-action"
              style={{
                fontSize: 11, color: "#1d4ed8", background: "#eff6ff",
                border: "1px solid #bfdbfe", borderRadius: 8,
                padding: "10px 12px", lineHeight: 1.5,
              }}
            >
              {pipeline.nextAction}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
  return typeof document !== "undefined" ? createPortal(modal, document.body) : modal
}

// ── Main export ───────────────────────────────────────────────────────────────

export function StudentSkillEvidencePipelines() {
  const [pipelines, setPipelines] = useState<DisplayPipeline[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [seeding, setSeeding] = useState(false)
  const [seedError, setSeedError] = useState<string | null>(null)
  const [usingFallback, setUsingFallback] = useState(false)
  const [managingId, setManagingId] = useState<string | null>(null)
  const [visibilities, setVisibilities] = useState<Record<string, VisibilityMode>>({})
  const [savingStates, setSavingStates] = useState<Record<string, VisibilitySaveState>>({})

  async function loadFromBackend() {
    setLoading(true)
    try {
      const data = await listSkillEvidencePipelines()
      if (data && data.length > 0) {
        const displayed = data.map(backendToDisplay)
        setPipelines(displayed)
        setUsingFallback(false)
        // Always sync visibility from backend (overrides any stale local state)
        setVisibilities(
          Object.fromEntries(data.map((p) => [p.skill_name, p.visibility_status]))
        )
        setSavingStates({})
      } else if (data && data.length === 0) {
        // Backend is reachable but empty
        setPipelines([])
        setUsingFallback(false)
      } else {
        // Backend unavailable — use mock fallback
        const mock = SKILL_NAMES.map(getSkillPipeline).map(mockToDisplay)
        setPipelines(mock)
        setUsingFallback(true)
        setVisibilities(Object.fromEntries(SKILL_NAMES.map((s) => [s, "public" as VisibilityMode])))
        setSavingStates({})
      }
    } catch {
      const mock = SKILL_NAMES.map(getSkillPipeline).map(mockToDisplay)
      setPipelines(mock)
      setUsingFallback(true)
      setVisibilities(Object.fromEntries(SKILL_NAMES.map((s) => [s, "public" as VisibilityMode])))
      setSavingStates({})
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadFromBackend()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleSeed() {
    setSeeding(true)
    setSeedError(null)
    try {
      await seedMockSkillEvidencePipelines()
      await loadFromBackend()
    } catch (err) {
      setSeedError(
        err instanceof Error
          ? err.message
          : "Unexpected error while seeding pipelines.",
      )
    } finally {
      setSeeding(false)
    }
  }

  async function handleVisibilityChange(
    skillName: string,
    backendId: string | undefined,
    v: VisibilityMode,
  ) {
    // Optimistic UI update
    setVisibilities((prev) => ({ ...prev, [skillName]: v }))

    if (!backendId || usingFallback) {
      // Fallback mode: local UI state only, no backend call
      if (usingFallback && process.env.NODE_ENV !== "production") {
        console.warn("[VeriBridge] Visibility change not persisted: backend unavailable (fallback mode).")
      }
      return
    }

    setSavingStates((prev) => ({ ...prev, [skillName]: "saving" }))

    try {
      const result = await updateSkillPipelineVisibility(backendId, v)
      if (result) {
        setSavingStates((prev) => ({ ...prev, [skillName]: "saved" }))
        setTimeout(() => {
          setSavingStates((prev) => ({ ...prev, [skillName]: "idle" }))
        }, 2000)
      } else {
        setSavingStates((prev) => ({ ...prev, [skillName]: "error" }))
      }
    } catch {
      setSavingStates((prev) => ({ ...prev, [skillName]: "error" }))
    }
  }

  const managingPipeline = managingId
    ? (pipelines ?? []).find((p) => p.id === managingId) ?? null
    : null

  return (
    <div data-testid="skill-evidence-pipelines">
      {/* Section header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
          <div
            data-testid="skill-pipelines-heading"
            style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}
          >
            Skill Evidence Pipelines
          </div>
          {usingFallback && (
            <span
              data-testid="fallback-badge"
              style={{
                fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
                background: "#fef3c7", color: "#92400e", border: "1px solid #fde68a",
              }}
            >
              Demo data
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          VeriBridge groups your evidence by skill so recruiters can inspect proof in one place.
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div
          data-testid="pipelines-loading"
          style={{
            padding: "32px 0", textAlign: "center", color: "#6b7280", fontSize: 13,
          }}
        >
          Loading skill pipelines&hellip;
        </div>
      )}

      {/* Empty state */}
      {!loading && pipelines !== null && pipelines.length === 0 && (
        <div
          data-testid="pipelines-empty"
          style={{
            padding: "32px 20px", textAlign: "center",
            border: "1px dashed #e5e7eb", borderRadius: 12, background: "#f9fafb",
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: "#374151", marginBottom: 8 }}>
            No skill pipelines yet
          </div>
          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 16 }}>
            Seed demo pipelines to see how your skill evidence will be presented to recruiters.
          </div>
          <button
            type="button"
            data-testid="seed-demo-btn"
            onClick={handleSeed}
            disabled={seeding}
            style={{
              fontSize: 12, fontWeight: 700, padding: "10px 20px", borderRadius: 8,
              background: "#1e40af", color: "#fff", border: "none",
              cursor: seeding ? "not-allowed" : "pointer",
              opacity: seeding ? 0.7 : 1,
            }}
          >
            {seeding ? "Seeding…" : "Seed demo skill pipelines"}
          </button>
          {seedError && (
            <div
              data-testid="seed-error-msg"
              style={{ fontSize: 11, color: "#dc2626", marginTop: 8 }}
            >
              {seedError}
            </div>
          )}
        </div>
      )}

      {/* Pipeline grid */}
      {!loading && pipelines !== null && pipelines.length > 0 && (
        <>
          {/* Seed button shown when using fallback (no backend data yet) */}
          {usingFallback && (
            <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 10 }}>
              <button
                type="button"
                data-testid="seed-demo-btn"
                onClick={handleSeed}
                disabled={seeding}
                style={{
                  fontSize: 11, fontWeight: 700, padding: "7px 14px", borderRadius: 7,
                  background: "#f0fdf4", color: "#065f46", border: "1px solid #bbf7d0",
                  cursor: seeding ? "not-allowed" : "pointer",
                  opacity: seeding ? 0.7 : 1,
                }}
              >
                {seeding ? "Seeding…" : "Seed demo skill pipelines"}
              </button>
              <span style={{ fontSize: 11, color: "#6b7280" }}>
                Showing demo data. Click to persist to backend.
              </span>
              {seedError && (
                <span
                  data-testid="seed-error-msg"
                  style={{ fontSize: 11, color: "#dc2626" }}
                >
                  {seedError}
                </span>
              )}
            </div>
          )}

          <div
            data-testid="skill-pipelines-grid"
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}
          >
            {pipelines.map((pipeline) => (
              <SkillPipelineCard
                key={pipeline.id}
                pipeline={pipeline}
                visibility={visibilities[pipeline.skillName] ?? "public"}
                savingState={savingStates[pipeline.skillName] ?? "idle"}
                onVisibilityChange={(v) =>
                  handleVisibilityChange(pipeline.skillName, pipeline.backendId, v)
                }
                onManage={() => setManagingId(pipeline.id)}
              />
            ))}
          </div>
        </>
      )}

      {/* Manage modal */}
      {managingPipeline && (
        <ManageSkillModal
          pipeline={managingPipeline}
          visibility={visibilities[managingPipeline.skillName] ?? "public"}
          savingState={savingStates[managingPipeline.skillName] ?? "idle"}
          onVisibilityChange={(v) =>
            handleVisibilityChange(managingPipeline.skillName, managingPipeline.backendId, v)
          }
          onClose={() => setManagingId(null)}
        />
      )}
    </div>
  )
}
