"use client"

import { useEffect, useState } from "react"
import {
  getPublicVBRProjectReport,
  isSafePublicUrl,
  matrixTraceLabel,
  type EvidenceTrace,
  type PublicVBRProjectReport,
  type PublicVideoEvidenceChip,
  type VBRReportSkillEvidenceRow,
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
} from "../../../../../components/passport/shared"
import { EvidenceTraceList } from "../../../../../components/passport/EvidenceTrace"
import { ProjectDefenseInspectionSection } from "../../../../../components/passport/ProjectDefenseInspectionCard"

// Keeps an in-page anchor target clear of the sticky top chrome when a
// skill-matrix trace link scrolls to it.
const ANCHOR_OFFSET = { scrollMarginTop: 96 }

const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Supporting evidence": "sky",
  "Evidence observed": "emerald",
  "Needs review": "rose",
  "Not assessed": "slate",
}

const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

function PublicVideoChip({ chip }: { chip: PublicVideoEvidenceChip }) {
  return (
    <div
      data-testid="public-video-chip"
      style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.4 }}
    >
      <Mono style={{ fontSize: 11, color: TOKEN.ink, whiteSpace: "nowrap" }}>{chip.label}</Mono>
      <span>— {chip.short_summary}</span>
      {chip.related_skill && <Badge tone="slate">{chip.related_skill}</Badge>}
    </div>
  )
}

function SkillRow({ row, tracesById }: { row: VBRReportSkillEvidenceRow; tracesById: Map<string, EvidenceTrace> }) {
  const sources = row.supporting_sources ?? []
  const limitations = row.limitations ?? []
  const traceRefs = (row.evidence_traces ?? [])
    .map((id) => tracesById.get(id))
    .filter((t): t is EvidenceTrace => Boolean(t))
  return (
    <tr data-testid="public-skill-row">
      <td style={{ padding: "8px 10px", fontSize: 13, fontWeight: 600, color: TOKEN.ink, verticalAlign: "top" }}>{row.skill}</td>
      <td style={{ padding: "8px 10px", verticalAlign: "top" }}>
        <Badge tone={QUALITATIVE_LABEL_TONE[row.status] ?? "slate"}>{row.status}</Badge>
      </td>
      <td style={{ padding: "8px 10px", verticalAlign: "top" }}>
        {sources.length > 0 ? (
          <div data-testid="public-skill-supporting-sources" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
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
          <div data-testid="public-skill-trace-links" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            {traceRefs.map((t) => (
              <a
                key={t.trace_id}
                href={`#${t.evidence_anchor}`}
                style={{ fontSize: 11, color: TOKEN.indigo, textDecoration: "none" }}
              >
                {matrixTraceLabel(t)} →
              </a>
            ))}
          </div>
        )}
      </td>
      <td style={{ padding: "8px 10px", fontSize: 12, color: TOKEN.muted, verticalAlign: "top" }}>
        {row.why_this_status ? (
          <span data-testid="public-skill-why">{row.why_this_status}</span>
        ) : (
          row.notes
        )}
        {row.recruiter_can_verify && (
          <div data-testid="public-skill-verify" style={{ marginTop: 4, fontStyle: "italic" }}>
            {row.recruiter_can_verify}
          </div>
        )}
        {limitations.length > 0 && (
          <ul data-testid="public-skill-limitations" style={{ margin: "4px 0 0", paddingLeft: 16 }}>
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

function Assessment({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{label}</Mono>
      <Badge tone={QUALITATIVE_LABEL_TONE[value] ?? "slate"}>{value}</Badge>
    </div>
  )
}

const safeLinkStyle = {
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
} as const

/**
 * Recruiter-safe outbound links: a public GitHub repo (only when known public)
 * and live website-proof / deployed targets. Never links private evidence.
 */
function SafeLinksCard({ report }: { report: PublicVBRProjectReport }) {
  // Defence in depth: only ever render links whose target is public-safe, even
  // though the backend already filters unsafe links out of the projection.
  const repoUrl =
    report.github_proof?.repo_is_public && isSafePublicUrl(report.github_proof.repo_url)
      ? report.github_proof.repo_url
      : null
  const websiteTargets = report.website_proofs.map((w) => w.target_website).filter(isSafePublicUrl)
  const liveLinks = Array.from(
    new Set([report.deployed_url, ...websiteTargets].filter(isSafePublicUrl) as string[]),
  )

  if (!repoUrl && liveLinks.length === 0) return null

  return (
    <Card>
      <CardHeader title="Direct Links" eyebrow="Verify it yourself" icon="🔗" />
      <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px", lineHeight: 1.5 }}>
        Public sources you can open directly. Private evidence (raw documents, transcripts, and recordings) is never linked.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {repoUrl && (
          <a data-testid="public-safe-repo-link" href={repoUrl} target="_blank" rel="noreferrer" style={safeLinkStyle}>
            🐙 View public repository
          </a>
        )}
        {liveLinks.map((url) => (
          <a key={url} data-testid="public-safe-live-link" href={url} target="_blank" rel="noreferrer" style={safeLinkStyle}>
            🌐 Open live site
          </a>
        ))}
      </div>
    </Card>
  )
}

function EvidenceStat({ label, value, tone }: { label: string; value: string; tone: BadgeTone }) {
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

export function PublicReportView({ token }: { token: string }) {
  const [report, setReport] = useState<PublicVBRProjectReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    getPublicVBRProjectReport(token)
      .then((data) => {
        if (!data) {
          setNotFound(true)
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
  }, [token])

  if (loading) return <LoadingState label="Loading Verified Build Report…" />

  if (notFound) {
    return (
      <div data-testid="public-report-not-found" style={{ maxWidth: 560, margin: "0 auto", padding: "64px 24px", textAlign: "center" }}>
        <h1 style={{ fontSize: 20, color: TOKEN.ink, marginBottom: 10 }}>This report is no longer available</h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, lineHeight: 1.6 }}>
          The link may have been unpublished by the candidate, or it may be incorrect. Ask the candidate for an
          up-to-date Verified Build Report link.
        </p>
      </div>
    )
  }

  if (error || !report) return <ErrorState message={error ?? "Report not found."} onRetry={load} />

  const analysis = report.project_defense_analysis
  const pkg = report.evidence_package
  const evidenceTraces = report.evidence_traces ?? []
  const tracesById = new Map(evidenceTraces.map((t) => [t.trace_id, t]))

  return (
    <div data-testid="public-report" style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 6 }}>
        <Mono style={{ fontSize: 11, letterSpacing: "0.16em", color: TOKEN.indigo, textTransform: "uppercase" }}>
          VeriBridge AI
        </Mono>
        <h1 style={{ fontSize: 26, color: TOKEN.ink, margin: 0 }}>{report.report_title}</h1>
        {report.candidate_display_name && (
          <p style={{ fontSize: 14, color: TOKEN.inkSoft, margin: 0 }}>{report.candidate_display_name}</p>
        )}
        {report.published_at && (
          <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
            Published {new Date(report.published_at).toLocaleDateString()}
          </Mono>
        )}
      </div>

      {/* Project summary */}
      <Card>
        <CardHeader title={report.project_title} eyebrow="Project" icon="📁" />
        {report.project_summary && (
          <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "0 0 10px", lineHeight: 1.5 }}>
            {report.project_summary}
          </p>
        )}
        {report.student_role && (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px" }}>
            <strong style={{ color: TOKEN.inkSoft }}>Candidate role: </strong>
            {report.student_role}
          </p>
        )}
        {report.repo_full_name && (
          <Mono style={{ fontSize: 11, color: TOKEN.muted, display: "block", marginBottom: 8 }}>
            {report.repo_full_name}
          </Mono>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {report.claimed_skills.map((skill) => (
            <Badge key={skill} tone="indigo">
              {skill}
            </Badge>
          ))}
        </div>
      </Card>

      {/* Direct safe links */}
      <SafeLinksCard report={report} />

      {/* Evidence package summary */}
      <Card>
        <CardHeader title="Evidence Package" eyebrow="Overview" icon="🗂️" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
          <EvidenceStat label="GitHub Proof" value={pkg.github_proof_attached ? "Attached" : "Not attached"} tone={pkg.github_proof_attached ? "emerald" : "slate"} />
          <EvidenceStat label="Documents" value={pkg.documents_count > 0 ? `${pkg.documents_count} attached` : "None"} tone={pkg.documents_count > 0 ? "emerald" : "slate"} />
          <EvidenceStat label="Website Proof" value={pkg.website_proofs_count > 0 ? `${pkg.website_proofs_count} attached` : "Not attached"} tone={pkg.website_proofs_count > 0 ? "emerald" : "slate"} />
          <EvidenceStat label="Project Defense" value={pkg.project_defense_completed ? "Completed" : "Not completed"} tone={pkg.project_defense_completed ? "emerald" : "slate"} />
          <EvidenceStat label="Video Defense" value={pkg.video_defense_recorded ? "Recorded" : "Not recorded"} tone={pkg.video_defense_recorded ? "emerald" : "slate"} />
          <EvidenceStat label="Evidence Chips" value={`${pkg.video_evidence_chip_count}`} tone={pkg.video_evidence_chip_count > 0 ? "emerald" : "slate"} />
        </div>
      </Card>

      {/* Skills demonstrated */}
      <Card id="skill-evidence" style={ANCHOR_OFFSET}>
        <CardHeader title="Skill Evidence Matrix" eyebrow="Evidence-backed" icon="🧩" />
        {report.skill_evidence.length === 0 ? (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>No claimed skills recorded for this project.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${TOKEN.line}`, textAlign: "left" }}>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Skill</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Evidence</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Supporting evidence</th>
                <th style={{ padding: "6px 10px", fontSize: 11, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Notes</th>
              </tr>
            </thead>
            <tbody>
              {report.skill_evidence.map((row) => (
                <SkillRow key={row.skill} row={row} tracesById={tracesById} />
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
            Each item below is a concrete evidence source behind the skills above. Public sources link directly;
            private evidence (raw documents, transcripts, and recordings) is summarized, never exposed.
          </p>
          <EvidenceTraceList traces={evidenceTraces} />
        </Card>
      )}

      {/* Evidence by source */}
      <Card id="evidence-by-source" style={ANCHOR_OFFSET}>
        <CardHeader title="Evidence by Source" eyebrow="Supporting evidence" icon="📎" />
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div id="github-proof" style={ANCHOR_OFFSET}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>GitHub Proof</Mono>
            {report.github_proof ? (
              <div style={{ marginTop: 4 }}>
                <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: "0 0 4px" }}>
                  {report.github_proof.repo_owner && report.github_proof.repo_name
                    ? `${report.github_proof.repo_owner}/${report.github_proof.repo_name}`
                    : report.github_proof.repo_url}
                </p>
                {report.github_proof.public_safe_summary && (
                  <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 6px" }}>{report.github_proof.public_safe_summary}</p>
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
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>GitHub proof not attached.</p>
            )}
          </div>

          <div id="documents" style={ANCHOR_OFFSET}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Document Proof</Mono>
            {report.documents.length > 0 ? (
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {report.documents.map((doc, i) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                    {doc.title}
                    {doc.status ? ` — ${doc.status}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>No document proof attached.</p>
            )}
          </div>

          <div id="website-proof" style={ANCHOR_OFFSET}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Website Proof</Mono>
            {report.website_proofs.length > 0 ? (
              <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                {report.website_proofs.map((wp, i) => {
                  // Never render a raw private/internal target URL; show a
                  // generic note instead (the backend blanks unsafe targets).
                  const safeTarget = isSafePublicUrl(wp.target_website) ? wp.target_website : null
                  return (
                    <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span>
                        {safeTarget ?? <em style={{ color: TOKEN.muted }}>Private/internal link omitted</em>} — {wp.workflow_confidence} confidence
                        {wp.supported_skills.length > 0 ? ` (${wp.supported_skills.join(", ")})` : ""}
                      </span>
                      <Badge tone={QUALITATIVE_LABEL_TONE[wp.evidence_strength] ?? "slate"}>{wp.evidence_strength}</Badge>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>Website proof not attached.</p>
            )}
          </div>

          <div id="project-defense" style={ANCHOR_OFFSET}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Project Defense</Mono>
            {analysis ? (
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 10 }}>
                <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{analysis.transcript_summary}</p>
                <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>{analysis.recruiter_summary}</p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                  <Assessment label="Overall" value={analysis.overall_assessment} />
                  <Assessment label="Clarity" value={analysis.explanation_clarity} />
                  <Assessment label="Ownership signal" value={analysis.ownership_signal} />
                  <Assessment label="Technical depth" value={analysis.technical_depth} />
                  <Assessment label="Consistency with evidence" value={analysis.consistency_with_evidence} />
                </div>
              </div>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>Project Defense not recorded.</p>
            )}
          </div>

          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Timestamped Video Evidence</Mono>
            {report.video_evidence_chips.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                {report.video_evidence_chips.map((chip, i) => (
                  <PublicVideoChip key={`${chip.label}-${i}`} chip={chip} />
                ))}
              </div>
            ) : pkg.video_defense_recorded ? (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>Transcript evidence not available.</p>
            ) : (
              <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>Video defense not recorded.</p>
            )}
          </div>

          {/* Recruiter-safe Project Defense inspection. Fail-closed cards render
              a withheld placeholder when the session is not public-safe. */}
          {(report.project_defense_inspection?.length ?? 0) > 0 && (
            <div>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Project Defense Inspection</Mono>
              <div style={{ marginTop: 6 }}>
                <ProjectDefenseInspectionSection
                  cards={report.project_defense_inspection}
                  testId="public-project-defense-inspection"
                />
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Limitations */}
      <Card id="limitations" style={ANCHOR_OFFSET}>
        <CardHeader title="Limitations / Not Assessed" eyebrow="In good faith" icon="⚠️" />
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {report.limitations.map((line, i) => (
            <li key={i} style={{ fontSize: 12, color: TOKEN.muted }}>
              {line}
            </li>
          ))}
        </ul>
      </Card>

      {/* Back to the candidate's public Work Passport (only when published) */}
      {report.public_passport_path && (
        <p style={{ textAlign: "center", margin: 0 }}>
          <a
            data-testid="public-report-passport-link"
            href={report.public_passport_path}
            style={{ fontSize: 13, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
          >
            ← View this candidate&apos;s full Verified Work Passport
          </a>
        </p>
      )}

      {/* Verification note */}
      {report.verification_note && (
        <p style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.6, textAlign: "center", margin: 0 }}>
          {report.verification_note}
        </p>
      )}

      {/* CTA */}
      <Card>
        <div data-testid="public-report-cta" style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 10, padding: "8px 0" }}>
          <h2 style={{ fontSize: 16, color: TOKEN.ink, margin: 0 }}>Hiring? Verify what candidates actually built.</h2>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
            Request an evidence-backed Verified Build Report from your candidates, or learn how VeriBridge works.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
            <a
              href="/recruiters"
              style={{ padding: "8px 14px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 13, fontWeight: 600, textDecoration: "none" }}
            >
              Request a VBR from your candidates
            </a>
            <a
              href="/recruiters"
              style={{ padding: "8px 14px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.inkSoft, fontSize: 13, fontWeight: 600, textDecoration: "none" }}
            >
              See how VeriBridge works
            </a>
          </div>
        </div>
      </Card>
    </div>
  )
}
