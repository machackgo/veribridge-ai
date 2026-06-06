"use client"

import React, { useState } from "react"
import {
  getSkillPipeline,
  type SkillEvidencePipeline,
} from "../recruiter-passport/RecruiterWorkPassportPreview"

// ── Skill list ─────────────────────────────────────────────────────────────────

const SKILL_NAMES = [
  "AI / Machine Learning",
  "JavaScript / Frontend",
  "Data & Visualization",
  "DevOps / Deployment",
]

// ── Skill-specific next actions (based on what is missing per skill) ───────────

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

// ── Visibility ─────────────────────────────────────────────────────────────────

type VisibilityMode = "public" | "protected" | "private"

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

function supportStatusText(s: string): string {
  if (s === "strongly supported") return "Strongly supported"
  if (s === "partially supported") return "Partially supported"
  return "Needs stronger proof"
}

function supportStatusColors(s: string) {
  if (s === "strongly supported") return sourceStatusColors("supported")
  if (s === "partially supported") return sourceStatusColors("partial")
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
  onVisibilityChange,
  onManage,
}: {
  pipeline: SkillEvidencePipeline
  visibility: VisibilityMode
  onVisibilityChange: (v: VisibilityMode) => void
  onManage: () => void
}) {
  const conf = confidenceColors(pipeline.confidence)
  const statusC = supportStatusColors(pipeline.supportStatus)
  const fa = pipeline.finalAnalysis
  const supportedCount = pipeline.evidenceSources.filter((s) => s.status === "supported").length
  const totalCount = pipeline.evidenceSources.length

  return (
    <div
      data-testid={`skill-pipeline-card-${pipeline.skillId}`}
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
          data-testid={`skill-confidence-${pipeline.skillId}`}
          style={{
            fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
            background: conf.bg, color: conf.color, border: `1px solid ${conf.border}`,
          }}
        >
          {pipeline.confidence} confidence
        </span>
        <span
          data-testid={`skill-status-${pipeline.skillId}`}
          style={{
            fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
            background: statusC.bg, color: statusC.color, border: `1px solid ${statusC.border}`,
          }}
        >
          {supportStatusText(pipeline.supportStatus)}
        </span>
      </div>

      {/* Skill name + student-safe explanation */}
      <div>
        <div
          data-testid={`skill-name-${pipeline.skillId}`}
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
        <div data-testid={`source-coverage-${pipeline.skillId}`} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {pipeline.evidenceSources.map((src) => {
            const sc = sourceStatusColors(src.status)
            return (
              <span
                key={src.key}
                data-testid={`source-chip-${pipeline.skillId}-${src.key}`}
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
      {fa && (
        <div style={{ display: "grid", gap: 5 }}>
          <div
            data-testid={`strongest-proof-${pipeline.skillId}`}
            style={{
              fontSize: 10, color: "#065f46", background: "#f0fdf4",
              border: "1px solid #bbf7d0", borderRadius: 6, padding: "5px 8px", lineHeight: 1.4,
            }}
          >
            <strong>Strongest:</strong> {fa.strongestProof}
          </div>
          <div
            data-testid={`weakest-proof-${pipeline.skillId}`}
            style={{
              fontSize: 10, color: "#92400e", background: "#fffbeb",
              border: "1px solid #fde68a", borderRadius: 6, padding: "5px 8px", lineHeight: 1.4,
            }}
          >
            <strong>Weakest:</strong> {fa.weakestProof}
          </div>
          {fa.stillNeedsReview.length > 0 && (
            <div
              data-testid={`missing-evidence-${pipeline.skillId}`}
              style={{
                fontSize: 10, color: "#991b1b", background: "#fef2f2",
                border: "1px solid #fecaca", borderRadius: 6, padding: "5px 8px", lineHeight: 1.4,
              }}
            >
              <strong>Missing:</strong> {fa.stillNeedsReview[0]}
            </div>
          )}
        </div>
      )}

      {/* Visibility controls */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: "#6b7280", marginBottom: 5 }}>
          Visibility
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {(["public", "protected", "private"] as VisibilityMode[]).map((v) => {
            const vc = visibilityColors(v)
            const active = visibility === v
            const label =
              v === "public" ? "Public summary" : v === "protected" ? "Protected evidence" : "Private only"
            return (
              <button
                key={v}
                type="button"
                data-testid={`visibility-btn-${pipeline.skillId}-${v}`}
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
        </div>
      </div>

      {/* Skill-specific next action */}
      <div
        data-testid={`next-action-${pipeline.skillId}`}
        style={{
          fontSize: 11, color: "#1d4ed8", background: "#eff6ff",
          border: "1px solid #bfdbfe", borderRadius: 6, padding: "7px 10px", lineHeight: 1.5,
        }}
      >
        <strong>Next action:</strong>{" "}
        {NEXT_ACTION[pipeline.skillName] ?? "Add more evidence to improve this skill's proof."}
      </div>

      {/* Manage button */}
      <button
        type="button"
        data-testid={`manage-btn-${pipeline.skillId}`}
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
  onVisibilityChange,
  onClose,
}: {
  pipeline: SkillEvidencePipeline
  visibility: VisibilityMode
  onVisibilityChange: (v: VisibilityMode) => void
  onClose: () => void
}) {
  const fa = pipeline.finalAnalysis
  const visC = visibilityColors(visibility)

  return (
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

          {/* Evidence artifacts */}
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

          {/* Strongest / weakest from finalAnalysis */}
          {fa && (
            <div style={{ display: "grid", gap: 5 }}>
              <div style={{
                fontSize: 10, color: "#065f46", background: "#f0fdf4",
                border: "1px solid #bbf7d0", borderRadius: 6, padding: "6px 9px", lineHeight: 1.4,
              }}>
                <strong>Strongest proof:</strong> {fa.strongestProof}
              </div>
              <div style={{
                fontSize: 10, color: "#92400e", background: "#fffbeb",
                border: "1px solid #fde68a", borderRadius: 6, padding: "6px 9px", lineHeight: 1.4,
              }}>
                <strong>Weakest proof:</strong> {fa.weakestProof}
              </div>
              {fa.stillNeedsReview.length > 0 && (
                <div style={{
                  fontSize: 10, color: "#6b7280", background: "#f9fafb",
                  border: "1px solid #e5e7eb", borderRadius: 6, padding: "6px 9px", lineHeight: 1.4,
                }}>
                  <strong>Still needs review:</strong>{" "}
                  {fa.stillNeedsReview.join(" · ")}
                </div>
              )}
            </div>
          )}

          {/* Recruiter visibility section */}
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
              <div style={{ display: "flex", gap: 4 }}>
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
              </div>
            </div>
          </div>

          {/* Skill-specific suggested improvement */}
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
              {NEXT_ACTION[pipeline.skillName] ??
                "Add more evidence to improve this skill's proof coverage."}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export function StudentSkillEvidencePipelines() {
  const pipelines = SKILL_NAMES.map(getSkillPipeline)
  const [managingSkill, setManagingSkill] = useState<string | null>(null)
  const [visibilities, setVisibilities] = useState<Record<string, VisibilityMode>>(
    () => Object.fromEntries(SKILL_NAMES.map((s) => [s, "public" as VisibilityMode])),
  )

  const managingPipeline = managingSkill
    ? pipelines.find((p) => p.skillName === managingSkill) ?? null
    : null

  function setVisibility(skillName: string, v: VisibilityMode) {
    setVisibilities((prev) => ({ ...prev, [skillName]: v }))
  }

  return (
    <div data-testid="skill-evidence-pipelines">
      {/* Section header */}
      <div style={{ marginBottom: 16 }}>
        <div
          data-testid="skill-pipelines-heading"
          style={{ fontSize: 18, fontWeight: 700, color: "#111827", marginBottom: 4 }}
        >
          Skill Evidence Pipelines
        </div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          VeriBridge groups your evidence by skill so recruiters can inspect proof in one place.
        </div>
      </div>

      {/* Skill card grid */}
      <div
        data-testid="skill-pipelines-grid"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}
      >
        {pipelines.map((pipeline) => (
          <SkillPipelineCard
            key={pipeline.skillId}
            pipeline={pipeline}
            visibility={visibilities[pipeline.skillName] ?? "public"}
            onVisibilityChange={(v) => setVisibility(pipeline.skillName, v)}
            onManage={() => setManagingSkill(pipeline.skillName)}
          />
        ))}
      </div>

      {/* Manage modal */}
      {managingPipeline && (
        <ManageSkillModal
          pipeline={managingPipeline}
          visibility={visibilities[managingPipeline.skillName] ?? "public"}
          onVisibilityChange={(v) => setVisibility(managingPipeline.skillName, v)}
          onClose={() => setManagingSkill(null)}
        />
      )}
    </div>
  )
}
