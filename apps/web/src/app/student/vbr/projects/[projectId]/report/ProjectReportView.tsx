"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import {
  getVBRProjectReport,
  type VBRReportSkillEvidenceRow,
  type VBRStudentProjectReportResponse,
  type VideoEvidenceChip,
} from "@/lib/vbr-api"
import {
  Badge,
  Card,
  CardHeader,
  ErrorState,
  LoadingState,
  Mono,
  TOKEN,
  type BadgeTone,
} from "../../../../../../../components/passport/shared"

const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Supporting evidence": "sky",
  "Evidence observed": "emerald",
  "Needs review": "rose",
  "Not assessed": "slate",
}

const SKILL_STATUS_TONE = QUALITATIVE_LABEL_TONE

function VideoChip({ chip }: { chip: VideoEvidenceChip }) {
  return (
    <div
      data-testid="report-video-evidence-chip"
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        fontSize: 12,
        color: TOKEN.inkSoft,
        lineHeight: 1.4,
      }}
    >
      <Mono style={{ fontSize: 11, color: TOKEN.ink, whiteSpace: "nowrap" }}>{chip.label}</Mono>
      <span>— {chip.short_summary}</span>
      {chip.related_skill && <Badge tone="slate">{chip.related_skill}</Badge>}
    </div>
  )
}

function SkillEvidenceRow({ row }: { row: VBRReportSkillEvidenceRow }) {
  return (
    <tr data-testid="skill-evidence-row">
      <td style={{ padding: "8px 10px", fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>{row.skill}</td>
      <td style={{ padding: "8px 10px" }}>
        <Badge tone={SKILL_STATUS_TONE[row.status] ?? "slate"}>{row.status}</Badge>
      </td>
      <td style={{ padding: "8px 10px", fontSize: 12, color: TOKEN.muted, textAlign: "center" }}>
        {row.evidence_chip_count}
      </td>
      <td style={{ padding: "8px 10px", fontSize: 12, color: TOKEN.muted }}>{row.notes}</td>
    </tr>
  )
}

function AnalysisAssessment({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{label}</Mono>
      <Badge tone={QUALITATIVE_LABEL_TONE[value] ?? "slate"}>{value}</Badge>
    </div>
  )
}

export function ProjectReportView({ projectId }: { projectId: string }) {
  const [report, setReport] = useState<VBRStudentProjectReportResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getVBRProjectReport(projectId)
      .then((data) => {
        if (!data) {
          setError("This VBR report could not be found, or you do not have access to it.")
          return
        }
        setReport(data)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load report."))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  if (loading) return <LoadingState label="Loading VBR report preview…" />
  if (error || !report) return <ErrorState message={error ?? "Report not found."} onRetry={load} />

  const analysis = report.project_defense_analysis
  const pkg = report.evidence_package

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Preview-only notice */}
      <div
        data-testid="report-preview-notice"
        style={{
          padding: "10px 14px",
          borderRadius: 8,
          background: TOKEN.indigoSoft,
          border: `1px solid #c7d2fe`,
          fontSize: 12,
          color: "#3730a3",
        }}
      >
        {report.note}
      </div>

      {/* Project summary */}
      <Card>
        <CardHeader title={report.project_title} eyebrow="Project summary" icon="📁" />
        {report.project_description && (
          <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "0 0 10px", lineHeight: 1.5 }}>
            {report.project_description}
          </p>
        )}
        {report.student_role && (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px" }}>
            <strong style={{ color: TOKEN.inkSoft }}>Student role: </strong>
            {report.student_role}
          </p>
        )}
        <Mono style={{ fontSize: 11, color: TOKEN.muted, display: "block", marginBottom: 8 }}>
          {report.repo_full_name || report.repo_url}
        </Mono>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {report.claimed_skills.map((skill) => (
            <Badge key={skill} tone="indigo">
              {skill}
            </Badge>
          ))}
        </div>
        <Badge tone="slate">Project status: {report.project_status.replace(/_/g, " ")}</Badge>
      </Card>

      {/* Evidence package summary */}
      <Card>
        <CardHeader title="Evidence Package Summary" eyebrow="Overview" icon="🗂️" />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: 10,
          }}
        >
          <EvidencePackageStat label="GitHub Proof" value={pkg.github_proof_attached ? "Attached" : "Not attached"} tone={pkg.github_proof_attached ? "emerald" : "slate"} />
          <EvidencePackageStat label="Documents" value={pkg.documents_count > 0 ? `${pkg.documents_count} attached` : "None"} tone={pkg.documents_count > 0 ? "emerald" : "slate"} />
          <EvidencePackageStat label="Website Proof" value={pkg.website_proofs_count > 0 ? `${pkg.website_proofs_count} attached` : "Not attached"} tone={pkg.website_proofs_count > 0 ? "emerald" : "slate"} />
          <EvidencePackageStat label="Project Defense" value={pkg.project_defense_completed ? "Completed" : "Not completed"} tone={pkg.project_defense_completed ? "emerald" : "slate"} />
          <EvidencePackageStat label="Video Defense" value={pkg.video_defense_recorded ? "Recorded" : "Not recorded"} tone={pkg.video_defense_recorded ? "emerald" : "slate"} />
          <EvidencePackageStat label="Video Evidence Chips" value={`${pkg.video_evidence_chip_count}`} tone={pkg.video_evidence_chip_count > 0 ? "emerald" : "slate"} />
        </div>
      </Card>

      {/* Evidence by source */}
      <Card>
        <CardHeader title="Evidence by Source" eyebrow="Attached proof" icon="📎" />
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              GitHub Proof
            </Mono>
            {report.github_proof ? (
              <div style={{ marginTop: 4 }}>
                <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "0 0 4px" }}>
                  {report.github_proof.repo_owner && report.github_proof.repo_name
                    ? `${report.github_proof.repo_owner}/${report.github_proof.repo_name}`
                    : report.github_proof.repo_url}
                  {report.github_proof.status ? ` — ${report.github_proof.status}` : ""}
                </p>
                {report.github_proof.public_safe_summary && (
                  <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 6px" }}>
                    {report.github_proof.public_safe_summary}
                  </p>
                )}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {report.github_proof.detected_skills.map((skill) => (
                    <Badge key={skill} tone="slate">
                      {skill}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>
                GitHub Proof not attached — repository reference only ({report.repo_full_name || report.repo_url}).
              </p>
            )}
          </div>

          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Document Proof
            </Mono>
            {report.documents.length > 0 ? (
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {report.documents.map((doc, i) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                    {doc.title}
                    {doc.source_type ? ` (${doc.source_type})` : ""}
                    {doc.status ? ` — ${doc.status}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>No document proof attached.</p>
            )}
          </div>

          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Website Proof
            </Mono>
            {report.website_proofs.length > 0 ? (
              <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                {report.website_proofs.map((wp, i) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span>
                      {wp.target_website} — {wp.workflow_confidence} confidence
                      {wp.supported_skills.length > 0 ? ` (${wp.supported_skills.join(", ")})` : ""}
                    </span>
                    <Badge tone={QUALITATIVE_LABEL_TONE[wp.evidence_strength] ?? "slate"}>{wp.evidence_strength}</Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>Website proof not attached.</p>
            )}
          </div>

          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Manual / Video Project Defense
            </Mono>
            {analysis ? (
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 10 }}>
                <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{analysis.transcript_summary}</p>
                <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
                  {analysis.recruiter_summary}
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                  <AnalysisAssessment label="Overall" value={analysis.overall_assessment} />
                  <AnalysisAssessment label="Clarity" value={analysis.explanation_clarity} />
                  <AnalysisAssessment label="Ownership signal" value={analysis.ownership_signal} />
                  <AnalysisAssessment label="Technical depth" value={analysis.technical_depth} />
                  <AnalysisAssessment label="Consistency with evidence" value={analysis.consistency_with_evidence} />
                </div>
                {analysis.risk_flags.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {analysis.risk_flags.map((flag) => (
                      <Badge key={flag} tone="amber">
                        {flag.replace(/_/g, " ")}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>
                Project Defense has not been analyzed yet.
              </p>
            )}
          </div>

          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Timestamped Video Evidence
            </Mono>
            {report.video_evidence_chips.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                {report.video_evidence_chips.map((chip, i) => (
                  <VideoChip key={`${chip.label}-${i}`} chip={chip} />
                ))}
              </div>
            ) : pkg.video_defense_recorded ? (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>
                No timestamped video evidence chips yet.
              </p>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>Video defense not recorded yet.</p>
            )}
          </div>
        </div>
      </Card>

      {/* Skill-level evidence table */}
      <Card>
        <CardHeader title="Skill-Level Evidence" eyebrow="Claimed skills" icon="🧩" />
        {report.skill_evidence.length === 0 ? (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>No claimed skills recorded for this project.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${TOKEN.line}`, textAlign: "left" }}>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Skill</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Status</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em", textAlign: "center" }}>Chips</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Notes</th>
              </tr>
            </thead>
            <tbody>
              {report.skill_evidence.map((row) => (
                <SkillEvidenceRow key={row.skill} row={row} />
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Defense questions */}
      {report.defense_questions.length > 0 && (
        <Card>
          <CardHeader title="Project Defense Questions" eyebrow="Process evidence" icon="❓" />
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
            {report.defense_questions.map((q) => (
              <li key={q.id} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                {q.question_text}{" "}
                <Badge tone={q.answered ? "emerald" : "slate"} style={{ marginLeft: 6 }}>
                  {q.answered ? "Answered" : "Not answered"}
                </Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Limitations */}
      <Card>
        <CardHeader title="Limitations / Not Assessed" eyebrow="Be honest" icon="⚠️" />
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {report.limitations.map((line, i) => (
            <li key={i} style={{ fontSize: 12, color: TOKEN.muted }}>
              {line}
            </li>
          ))}
        </ul>
      </Card>

      {/* Next actions */}
      {report.next_actions.length > 0 && (
        <Card>
          <CardHeader title="Safe Next Actions" eyebrow="Strengthen this report" icon="✅" />
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
            {report.next_actions.map((line, i) => (
              <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                {line}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <p style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center" }}>
        <Link href="/student/proofs/project-defense" style={{ color: TOKEN.indigo, textDecoration: "none" }}>
          ← Back to Project Defense workspace
        </Link>
      </p>
    </div>
  )
}

function EvidencePackageStat({ label, value, tone }: { label: string; value: string; tone: BadgeTone }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 8,
        background: TOKEN.bg,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
        {label}
      </Mono>
      <Badge tone={tone}>{value}</Badge>
    </div>
  )
}
