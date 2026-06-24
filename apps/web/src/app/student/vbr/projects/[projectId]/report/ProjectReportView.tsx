"use client"

import { useEffect, useRef, useState, type CSSProperties } from "react"
import Link from "next/link"
import {
  getVBRProjectReport,
  getVBRProjectReportPublishStatus,
  isSafePublicUrl,
  matrixTraceLabel,
  publishVBRProjectReport,
  unpublishVBRProjectReport,
  type EvidenceTrace,
  type ProjectReportPublishStatus,
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
import { EvidenceTraceList } from "../../../../../../../components/passport/EvidenceTrace"

// Keeps an in-page anchor target clear of the sticky top chrome when the jump
// nav or a skill-matrix link scrolls to it.
const ANCHOR_OFFSET: CSSProperties = { scrollMarginTop: 96 }

const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Supporting evidence": "sky",
  "Evidence observed": "emerald",
  "Needs review": "rose",
  "Not assessed": "slate",
}

const SKILL_STATUS_TONE = QUALITATIVE_LABEL_TONE

const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

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

function SkillEvidenceRow({ row, tracesById }: { row: VBRReportSkillEvidenceRow; tracesById: Map<string, EvidenceTrace> }) {
  const sources = row.supporting_sources ?? []
  const limitations = row.limitations ?? []
  const traceRefs = (row.evidence_traces ?? [])
    .map((id) => tracesById.get(id))
    .filter((t): t is EvidenceTrace => Boolean(t))
  return (
    <tr data-testid="skill-evidence-row">
      <td style={{ padding: "8px 10px", fontSize: 13, fontWeight: 600, color: TOKEN.ink, verticalAlign: "top" }}>{row.skill}</td>
      <td style={{ padding: "8px 10px", verticalAlign: "top" }}>
        <Badge tone={SKILL_STATUS_TONE[row.status] ?? "slate"}>{row.status}</Badge>
      </td>
      <td style={{ padding: "8px 10px", verticalAlign: "top" }}>
        {sources.length > 0 ? (
          <div data-testid="skill-supporting-sources" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {sources.map((src) => (
              <Badge key={src} tone={SOURCE_TONE[src] ?? "slate"}>
                {src}
              </Badge>
            ))}
          </div>
        ) : (
          <span style={{ fontSize: 12, color: TOKEN.muted }}>—</span>
        )}
        {traceRefs.length > 0 && (
          <div data-testid="skill-trace-links" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            {traceRefs.map((t) => (
              <a key={t.trace_id} href={`#${t.evidence_anchor}`} style={{ fontSize: 11, color: TOKEN.indigo, textDecoration: "none" }}>
                {matrixTraceLabel(t)} →
              </a>
            ))}
          </div>
        )}
      </td>
      <td style={{ padding: "8px 10px", fontSize: 12, color: TOKEN.muted, textAlign: "center", verticalAlign: "top" }}>
        {row.evidence_chip_count}
      </td>
      <td style={{ padding: "8px 10px", fontSize: 12, color: TOKEN.muted, verticalAlign: "top" }}>
        {row.why_this_status ? <span data-testid="skill-why">{row.why_this_status}</span> : row.notes}
        {row.recruiter_can_verify && (
          <div data-testid="skill-verify" style={{ marginTop: 4, fontStyle: "italic" }}>
            {row.recruiter_can_verify}
          </div>
        )}
        {limitations.length > 0 && (
          <ul data-testid="skill-limitations" style={{ margin: "4px 0 0", paddingLeft: 16 }}>
            {limitations.map((line, i) => (
              <li key={i} style={{ fontSize: 11, color: TOKEN.muted }}>
                {line}
              </li>
            ))}
          </ul>
        )}
      </td>
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

function PublishControls({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState<ProjectReportPublishStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  // Once a publish/unpublish action runs, ignore any still-in-flight initial
  // status fetch so it cannot clobber the newer result.
  const actedRef = useRef(false)

  useEffect(() => {
    getVBRProjectReportPublishStatus(projectId)
      .then((s) => {
        if (!actedRef.current) setStatus(s)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load publish status."))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const isPublic = Boolean(status?.is_public && status?.public_token)
  const publicUrl =
    isPublic && status?.public_token
      ? `${typeof window !== "undefined" ? window.location.origin : ""}/vbr/report/${status.public_token}`
      : ""

  const run = (action: () => Promise<ProjectReportPublishStatus>) => {
    actedRef.current = true
    setBusy(true)
    setError(null)
    setCopied(false)
    action()
      .then(setStatus)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Action failed."))
      .finally(() => setBusy(false))
  }

  const copyLink = () => {
    if (!publicUrl) return
    void navigator.clipboard?.writeText(publicUrl)
    setCopied(true)
  }

  return (
    <Card>
      <div data-testid="publish-controls" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <CardHeader title="Recruiter-Safe Public Link" eyebrow="Share with recruiters" icon="🔗" />
          {isPublic ? (
            <span data-testid="public-link-active-badge">
              <Badge tone="emerald">Public link active</Badge>
            </span>
          ) : (
            <span data-testid="student-preview-badge">
              <Badge tone="slate">Student preview</Badge>
            </span>
          )}
        </div>

        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          Publishing creates a read-only link recruiters can open without logging in. It shows only recruiter-safe
          evidence summaries — never your raw evidence, private files, or numeric scores. You can unpublish at any time.
        </p>

        {error && (
          <p data-testid="publish-error" style={{ fontSize: 12, color: TOKEN.rose ?? "#be123c", margin: 0 }}>
            {error}
          </p>
        )}

        {isPublic ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div
              data-testid="public-link-url"
              style={{
                fontFamily: '"JetBrains Mono", monospace',
                fontSize: 12,
                color: TOKEN.ink,
                padding: "8px 10px",
                background: TOKEN.bg,
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
                wordBreak: "break-all",
              }}
            >
              {publicUrl}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                data-testid="copy-link-button"
                onClick={copyLink}
                style={primaryBtnStyle}
              >
                {copied ? "Copied!" : "Copy public link"}
              </button>
              <button
                type="button"
                data-testid="unpublish-link-button"
                disabled={busy}
                onClick={() => run(() => unpublishVBRProjectReport(projectId))}
                style={secondaryBtnStyle}
              >
                {busy ? "Working…" : "Unpublish link"}
              </button>
            </div>
          </div>
        ) : (
          <div>
            <button
              type="button"
              data-testid="publish-link-button"
              disabled={busy}
              onClick={() => run(() => publishVBRProjectReport(projectId))}
              style={primaryBtnStyle}
            >
              {busy ? "Publishing…" : "Publish recruiter-safe link"}
            </button>
          </div>
        )}
      </div>
    </Card>
  )
}

const primaryBtnStyle: CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: "none",
  background: TOKEN.indigo,
  color: "#fff",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
}

const secondaryBtnStyle: CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.inkSoft,
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
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
  const evidenceTraces = report.evidence_traces ?? []
  const tracesById = new Map(evidenceTraces.map((t) => [t.trace_id, t]))

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

      {/* Recruiter-safe public link controls */}
      <PublishControls projectId={projectId} />

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

      {/* In-page navigation to evidence sections */}
      <nav data-testid="report-jump-nav" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {[
          { href: "#github-proof", label: "GitHub Proof" },
          { href: "#documents", label: "Documents" },
          { href: "#website-proof", label: "Website Proof" },
          { href: "#project-defense", label: "Project Defense" },
          { href: "#skill-evidence", label: "Skill Evidence" },
          { href: "#limitations", label: "Limitations" },
        ].map((item) => (
          <a
            key={item.href}
            href={item.href}
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: TOKEN.indigo,
              textDecoration: "none",
              padding: "4px 10px",
              borderRadius: 999,
              border: `1px solid ${TOKEN.line}`,
              background: "#fff",
            }}
          >
            {item.label}
          </a>
        ))}
      </nav>

      {/* Direct safe links */}
      <SafeLinksCard report={report} />

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
      <Card id="evidence-by-source" style={ANCHOR_OFFSET}>
        <CardHeader title="Evidence by Source" eyebrow="Attached proof" icon="📎" />
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div id="github-proof" style={ANCHOR_OFFSET}>
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

          <div id="documents" style={ANCHOR_OFFSET}>
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

          <div id="website-proof" style={ANCHOR_OFFSET}>
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

          <div id="project-defense" style={ANCHOR_OFFSET}>
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
      <Card id="skill-evidence" style={ANCHOR_OFFSET}>
        <CardHeader title="Skill Evidence Matrix" eyebrow="Claimed skills → evidence" icon="🧩" />
        {report.skill_evidence.length === 0 ? (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>No claimed skills recorded for this project.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${TOKEN.line}`, textAlign: "left" }}>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Skill</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Status</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Supporting evidence</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em", textAlign: "center" }}>Chips</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Notes</th>
              </tr>
            </thead>
            <tbody>
              {report.skill_evidence.map((row) => (
                <SkillEvidenceRow key={row.skill} row={row} tracesById={tracesById} />
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Evidence Traceability — concrete claim → evidence audit trail */}
      {evidenceTraces.length > 0 && (
        <Card id="evidence-traceability" style={ANCHOR_OFFSET}>
          <CardHeader title="Evidence Traceability" eyebrow="Claim → evidence → source" icon="🔍" />
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px", lineHeight: 1.5 }}>
            Each item is a concrete evidence source behind your claimed skills. Public sources link directly; private
            evidence is summarized and never exposed as raw files.
          </p>
          <EvidenceTraceList traces={evidenceTraces} />
        </Card>
      )}

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
      <Card id="limitations" style={ANCHOR_OFFSET}>
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

const safeLinkStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "8px 12px",
  borderRadius: 8,
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.indigo,
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
}

/**
 * Direct, recruiter-safe outbound links: a public GitHub repo (only when known
 * public), a public deployed app URL, and live website-proof targets. Never
 * links raw private docs, transcripts, signed URLs, or storage paths.
 */
function SafeLinksCard({ report }: { report: VBRStudentProjectReportResponse }) {
  // Defence in depth: only ever render links whose target is public-safe.
  const repoUrl =
    report.github_proof?.repo_is_public && isSafePublicUrl(report.github_proof.repo_url)
      ? report.github_proof.repo_url
      : null
  const websiteTargets = report.website_proofs.map((w) => w.target_website).filter(isSafePublicUrl)
  const liveLinks = Array.from(new Set([report.deployed_url, ...websiteTargets].filter(isSafePublicUrl) as string[]))

  if (!repoUrl && liveLinks.length === 0) return null

  return (
    <Card>
      <CardHeader title="Direct Links" eyebrow="Verify it yourself" icon="🔗" />
      <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px", lineHeight: 1.5 }}>
        Public sources you can open directly. Private evidence (raw documents, transcripts, and recordings) is never linked.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {repoUrl && (
          <a data-testid="safe-repo-link" href={repoUrl} target="_blank" rel="noreferrer" style={safeLinkStyle}>
            🐙 View public repository
          </a>
        )}
        {liveLinks.map((url) => (
          <a key={url} data-testid="safe-live-link" href={url} target="_blank" rel="noreferrer" style={safeLinkStyle}>
            🌐 Open live site
          </a>
        ))}
      </div>
    </Card>
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
