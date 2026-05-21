"use client"

/**
 * multi-source-proof-form.tsx — Phase J4B
 * Source type selector grid and adaptive form for all non-GitHub/Website
 * evidence sources (LinkedIn, YouTube, Google Drive, PDF, Certificate,
 * Portfolio, Manual, Other).
 *
 * The parent panel handles actual submission; this component only builds
 * the payload and calls onSubmit().
 */

import { useState } from "react"
import type { CSSProperties } from "react"
import type { SkillEvidencePayload } from "@/lib/api"
import {
  type EvidenceSourceType,
  sourceTypeToDescription,
  sourceTypeToEvidenceType,
  sourceTypeToIcon,
  sourceTypeToBadgeLabel,
  getExtractionStatus,
  parseTimestampToSeconds,
  formatSecondsAsTimestamp,
  buildYouTubeTimestampUrl,
  extractYouTubeVideoId,
} from "@/lib/evidence-sources"

// ── Source types shown in the selector (excludes github/website — handled by parent) ──

const NEW_SOURCE_TYPES: EvidenceSourceType[] = [
  "linkedin_post",
  "youtube_demo",
  "google_drive_document",
  "pdf_report",
  "certificate",
  "portfolio",
  "manual_entry",
  "other_link",
]

// ── Form state ────────────────────────────────────────────────────────────────

type GenericFormState = {
  skillName: string
  proofTitle: string
  sourceUrl: string
  description: string
  projectName: string
  // LinkedIn
  postSummary: string
  // YouTube
  videoStartTimestamp: string
  videoEndTimestamp: string
  transcriptSnippet: string
  // Google Drive / PDF
  pageNumber: string
  sectionName: string
  documentSnippet: string
  // Certificate
  issuer: string
  credentialId: string
  // Portfolio
  projectSection: string
}

const initialForm = (): GenericFormState => ({
  skillName: "",
  proofTitle: "",
  sourceUrl: "",
  description: "",
  projectName: "",
  postSummary: "",
  videoStartTimestamp: "",
  videoEndTimestamp: "",
  transcriptSnippet: "",
  pageNumber: "",
  sectionName: "",
  documentSnippet: "",
  issuer: "",
  credentialId: "",
  projectSection: "",
})

// ── Shared input styles ───────────────────────────────────────────────────────

const inp: CSSProperties = {
  width: "100%",
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "#fff",
  color: "var(--ink)",
  padding: "9px 12px",
  fontSize: 13,
  outline: "none",
  boxSizing: "border-box",
}

const textArea: CSSProperties = {
  ...inp,
  minHeight: 72,
  resize: "vertical",
  fontFamily: "inherit",
  lineHeight: 1.5,
}

const labelText: CSSProperties = { fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }
const hintText: CSSProperties = { fontSize: 11, color: "var(--muted)" }
const sectionLabel: CSSProperties = {
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--muted)",
  marginBottom: 10,
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <span style={labelText}>{label}</span>
      {children}
      {hint && <span style={hintText}>{hint}</span>}
    </div>
  )
}

// ── Payload builder ───────────────────────────────────────────────────────────

function buildPayload(sourceType: EvidenceSourceType, form: GenericFormState): SkillEvidencePayload | string {
  const skillName = form.skillName.trim()
  if (!skillName) return "Enter the skill this evidence proves."

  const title = form.proofTitle.trim() || skillName
  const desc = form.description.trim()

  // For manual_entry, description is required (no URL path)
  if (sourceType === "manual_entry" && !desc) {
    return "Add a description explaining what this evidence proves."
  }

  // For URL-based sources (not manual_entry), require a URL
  const url = form.sourceUrl.trim()
  if (sourceType !== "manual_entry" && !url) {
    return "Enter the source URL."
  }

  const metadata: Record<string, unknown> = {
    evidence_title: title,
    submission_source: "student_manual_multi_source",
    proof_kind: sourceType,
    project_name: form.projectName.trim() || null,
  }

  let evidenceUrl: string | null = url || null

  if (sourceType === "youtube_demo") {
    const startSec = parseTimestampToSeconds(form.videoStartTimestamp)
    const endSec = parseTimestampToSeconds(form.videoEndTimestamp)
    metadata.video_url = url
    metadata.video_id = extractYouTubeVideoId(url) || null
    if (startSec !== null) {
      metadata.timestamp_start_seconds = startSec
      metadata.timestamp_start_formatted = formatSecondsAsTimestamp(startSec)
      evidenceUrl = buildYouTubeTimestampUrl(url, startSec)
    }
    if (endSec !== null) {
      metadata.timestamp_end_seconds = endSec
      metadata.timestamp_end_formatted = formatSecondsAsTimestamp(endSec)
    }
    if (form.transcriptSnippet.trim()) {
      metadata.transcript_snippet = form.transcriptSnippet.trim()
    }
  }

  if (sourceType === "linkedin_post" && form.postSummary.trim()) {
    metadata.post_summary = form.postSummary.trim()
  }

  if (sourceType === "google_drive_document" || sourceType === "pdf_report") {
    if (form.pageNumber.trim()) metadata.page_number = form.pageNumber.trim()
    if (form.sectionName.trim()) metadata.section_name = form.sectionName.trim()
    if (form.documentSnippet.trim()) metadata.document_snippet = form.documentSnippet.trim()
  }

  if (sourceType === "certificate") {
    if (form.issuer.trim()) metadata.issuer = form.issuer.trim()
    if (form.credentialId.trim()) metadata.credential_id = form.credentialId.trim()
  }

  if (sourceType === "portfolio" && form.projectSection.trim()) {
    metadata.project_section = form.projectSection.trim()
  }

  return {
    skill_name: skillName,
    evidence_type: sourceTypeToEvidenceType(sourceType),
    evidence_url: evidenceUrl,
    evidence_description: desc || `${title} — ${sourceTypeToBadgeLabel(sourceType)} proof for ${skillName}`,
    proof_visibility: "public",
    metadata,
  }
}

// ── Adaptive form fields ──────────────────────────────────────────────────────

function AdaptiveFormFields({
  sourceType,
  form,
  onChange,
}: {
  sourceType: EvidenceSourceType
  form: GenericFormState
  onChange: (patch: Partial<GenericFormState>) => void
}) {
  const isManual = sourceType === "manual_entry"

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {/* Always: skill name */}
      <Field label="Skill this proves *" hint="E.g. Machine Learning, React, Docker">
        <input
          value={form.skillName}
          onChange={(e) => onChange({ skillName: e.target.value })}
          placeholder="e.g. Machine Learning"
          style={inp}
        />
      </Field>

      {/* Always: proof title */}
      <Field label="Proof title *" hint="Give this piece of evidence a name">
        <input
          value={form.proofTitle}
          onChange={(e) => onChange({ proofTitle: e.target.value })}
          placeholder={
            sourceType === "youtube_demo" ? "e.g. ML model training demo at 5:12"
            : sourceType === "linkedin_post" ? "e.g. LinkedIn post about FastAPI project"
            : sourceType === "certificate" ? "e.g. AWS Cloud Practitioner Certificate"
            : "e.g. Data Engineering capstone report"
          }
          style={inp}
        />
      </Field>

      {/* Source URL (except manual entry) */}
      {!isManual && (
        <Field
          label="Source URL *"
          hint={
            sourceType === "youtube_demo" ? "Paste the YouTube video URL"
            : sourceType === "linkedin_post" ? "Paste the public LinkedIn post URL — only links you have permission to share"
            : sourceType === "google_drive_document" ? "Paste a shareable Google Drive link"
            : sourceType === "pdf_report" ? "Paste the public PDF or document URL"
            : sourceType === "certificate" ? "Paste the certificate verification URL"
            : sourceType === "portfolio" ? "Paste the portfolio page or project URL"
            : "Paste the public resource URL"
          }
        >
          <input
            value={form.sourceUrl}
            onChange={(e) => onChange({ sourceUrl: e.target.value })}
            placeholder={
              sourceType === "youtube_demo" ? "https://youtube.com/watch?v=..."
              : sourceType === "linkedin_post" ? "https://linkedin.com/posts/..."
              : sourceType === "certificate" ? "https://coursera.org/verify/..."
              : "https://..."
            }
            style={inp}
          />
        </Field>
      )}

      {/* YouTube: timestamp fields */}
      {sourceType === "youtube_demo" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Field label="Start timestamp" hint="e.g. 05:12 or 312">
              <input
                value={form.videoStartTimestamp}
                onChange={(e) => onChange({ videoStartTimestamp: e.target.value })}
                placeholder="05:12"
                style={inp}
              />
            </Field>
            <Field label="End timestamp" hint="Optional — e.g. 06:40">
              <input
                value={form.videoEndTimestamp}
                onChange={(e) => onChange({ videoEndTimestamp: e.target.value })}
                placeholder="06:40"
                style={inp}
              />
            </Field>
          </div>
          <Field label="Transcript snippet" hint="Paste the part of the transcript that demonstrates this skill — optional, helps future AI analysis">
            <textarea
              value={form.transcriptSnippet}
              onChange={(e) => onChange({ transcriptSnippet: e.target.value })}
              placeholder="e.g. Here I explain how RandomForest handles feature importance..."
              style={textArea}
            />
          </Field>
        </>
      )}

      {/* LinkedIn: post summary */}
      {sourceType === "linkedin_post" && (
        <Field label="Post summary" hint="Brief description of what the post is about — optional">
          <textarea
            value={form.postSummary}
            onChange={(e) => onChange({ postSummary: e.target.value })}
            placeholder="e.g. I shared an overview of my FastAPI + Docker project..."
            style={textArea}
          />
        </Field>
      )}

      {/* Google Drive / PDF: page and section */}
      {(sourceType === "google_drive_document" || sourceType === "pdf_report") && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Page or slide number" hint="Optional">
            <input
              value={form.pageNumber}
              onChange={(e) => onChange({ pageNumber: e.target.value })}
              placeholder="e.g. 5"
              style={inp}
            />
          </Field>
          <Field label="Section or chapter" hint="Optional">
            <input
              value={form.sectionName}
              onChange={(e) => onChange({ sectionName: e.target.value })}
              placeholder="e.g. Section 2.1"
              style={inp}
            />
          </Field>
        </div>
      )}

      {/* Certificate: issuer + credential ID */}
      {sourceType === "certificate" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Issuer" hint="e.g. Coursera, AWS, Udemy">
            <input
              value={form.issuer}
              onChange={(e) => onChange({ issuer: e.target.value })}
              placeholder="e.g. Coursera"
              style={inp}
            />
          </Field>
          <Field label="Credential ID" hint="Optional">
            <input
              value={form.credentialId}
              onChange={(e) => onChange({ credentialId: e.target.value })}
              placeholder="e.g. ABC123XYZ"
              style={inp}
            />
          </Field>
        </div>
      )}

      {/* Portfolio: project section */}
      {sourceType === "portfolio" && (
        <Field label="Project section or name" hint="Optional — which project on the portfolio this refers to">
          <input
            value={form.projectSection}
            onChange={(e) => onChange({ projectSection: e.target.value })}
            placeholder="e.g. ML Projects → Boston Accident Prediction"
            style={inp}
          />
        </Field>
      )}

      {/* Description */}
      <Field
        label={isManual ? "Proof details *" : "What does this prove?"}
        hint={isManual ? "Explain what you did and why it demonstrates this skill" : "Describe what skill is demonstrated — optional but recommended"}
      >
        <textarea
          value={form.description}
          onChange={(e) => onChange({ description: e.target.value })}
          placeholder={
            isManual
              ? "e.g. I designed and implemented a RandomForest classifier that achieved 87% accuracy on test data..."
              : "e.g. This post describes my experience building a full MLOps pipeline with Docker and Prometheus."
          }
          style={{ ...textArea, minHeight: isManual ? 96 : 72 }}
        />
      </Field>

      {/* Optional: project name */}
      <Field label="Project name" hint="Optional — helps group this evidence with other proof from the same project">
        <input
          value={form.projectName}
          onChange={(e) => onChange({ projectName: e.target.value })}
          placeholder="e.g. Boston Accident Risk Prediction"
          style={inp}
        />
      </Field>

      {/* Privacy notice */}
      <div
        style={{
          fontSize: 11,
          color: "var(--muted)",
          background: "var(--bg-2)",
          border: "1px solid var(--line)",
          borderRadius: 8,
          padding: "8px 10px",
          lineHeight: 1.6,
        }}
      >
        Only add evidence you own or have permission to share. Do not include private credentials,
        passwords, or non-public links.
      </div>
    </div>
  )
}

// ── Source type selector grid ─────────────────────────────────────────────────

const SOURCE_TYPES_ALL: EvidenceSourceType[] = [
  "github_repository",
  "deployed_website",
  ...NEW_SOURCE_TYPES,
]

export function SourceTypeSelector({
  onSelect,
}: {
  onSelect: (type: EvidenceSourceType) => void
}) {
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div style={sectionLabel}>Select evidence source</div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: 10,
        }}
      >
        {SOURCE_TYPES_ALL.map((st) => {
          const extractionStatus = getExtractionStatus(st)
          const isActive = extractionStatus.status === "active"
          return (
            <button
              key={`st-${st}`}
              type="button"
              onClick={() => onSelect(st)}
              style={{
                border: "1px solid var(--line)",
                borderRadius: 12,
                padding: "14px 12px",
                background: "#fff",
                cursor: "pointer",
                textAlign: "left",
                display: "flex",
                flexDirection: "column",
                gap: 6,
                transition: "border-color 0.1s, background 0.1s",
              }}
            >
              <span style={{ fontSize: 22 }}>{sourceTypeToIcon(st)}</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                {sourceTypeToBadgeLabel(st)}
              </span>
              <span style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.4 }}>
                {sourceTypeToDescription(st)}
              </span>
              {isActive && (
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: "#166534",
                    background: "#dcfce7",
                    border: "1px solid #bbf7d0",
                    borderRadius: 999,
                    padding: "2px 6px",
                    alignSelf: "flex-start",
                  }}
                >
                  Active
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Main export: generic form wrapper ─────────────────────────────────────────

export function MultiSourceProofForm({
  sourceType,
  submitting,
  error,
  onBack,
  onSubmit,
}: {
  sourceType: EvidenceSourceType
  submitting: boolean
  error: string | null
  onBack: () => void
  onSubmit: (payload: SkillEvidencePayload) => Promise<void>
}) {
  const [form, setForm] = useState<GenericFormState>(initialForm)
  const [localError, setLocalError] = useState<string | null>(null)

  function patch(p: Partial<GenericFormState>) {
    setForm((prev) => ({ ...prev, ...p }))
    setLocalError(null)
  }

  const displayedError = localError ?? error

  async function handleSubmit() {
    const result = buildPayload(sourceType, form)
    if (typeof result === "string") {
      setLocalError(result)
      return
    }
    setLocalError(null)
    await onSubmit(result)
  }

  const extractionStatus = getExtractionStatus(sourceType)

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Source header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 26 }}>{sourceTypeToIcon(sourceType)}</span>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>
            {sourceTypeToBadgeLabel(sourceType)} Proof
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            {sourceTypeToDescription(sourceType)}
          </div>
        </div>
        {extractionStatus.status !== "active" && (
          <span
            style={{
              marginLeft: "auto",
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "#854d0e",
              background: "#fef9c3",
              border: "1px solid #fef08a",
              borderRadius: 999,
              padding: "3px 8px",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
          >
            {extractionStatus.label}
          </span>
        )}
      </div>

      {/* AI extraction notice for queued/future sources */}
      {extractionStatus.status !== "active" && (
        <div
          style={{
            background: "#eff6ff",
            border: "1px solid #bfdbfe",
            borderRadius: 10,
            padding: "10px 12px",
            fontSize: 12,
            color: "#1d4ed8",
            lineHeight: 1.5,
          }}
        >
          {extractionStatus.message} GitHub scanning is active now. LinkedIn, YouTube, documents,
          certificates, and portfolio AI extraction will be added in upcoming phases.
        </div>
      )}

      {/* Error */}
      {displayedError && (
        <div
          role="alert"
          style={{
            border: "1px solid #fecaca",
            background: "#fef2f2",
            color: "#991b1b",
            borderRadius: 10,
            padding: "8px 12px",
            fontSize: 12,
          }}
        >
          {displayedError}
        </div>
      )}

      {/* Adaptive form fields */}
      <AdaptiveFormFields sourceType={sourceType} form={form} onChange={patch} />

      {/* Footer */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <button
          type="button"
          onClick={onBack}
          style={{
            border: "1px solid var(--line-2)",
            background: "transparent",
            color: "var(--ink-2)",
            borderRadius: 10,
            padding: "9px 14px",
            fontWeight: 600,
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          ← Back
        </button>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={submitting}
          style={{
            border: "1px solid transparent",
            background: submitting ? "var(--bg-2)" : "var(--ink)",
            color: submitting ? "var(--muted)" : "#fff",
            borderRadius: 10,
            padding: "10px 18px",
            fontWeight: 700,
            fontSize: 14,
            cursor: submitting ? "not-allowed" : "pointer",
          }}
        >
          {submitting ? "Saving…" : "Save proof evidence"}
        </button>
      </div>
    </div>
  )
}
