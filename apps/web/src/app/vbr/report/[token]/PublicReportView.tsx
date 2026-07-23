"use client"

/**
 * Public Verified Build Report — the canonical recruiter-facing report.
 *
 * Information architecture (narrative first, audit second):
 *   1. Project overview — what was built, the candidate's role
 *   2. Strongest evidence-backed skills — stacked cards (no matrix table)
 *   3. Evidence coverage — one compact chip row
 *   4. Public sources — links the recruiter can open directly
 *   5. Candidate explanation — Project Defense summary
 *   6. Limitations — honest gaps
 *   7. Full evidence detail — traceability + per-source audit, collapsed
 *
 * Mobile-first: primary content never scrolls sideways; skill evidence renders
 * as stacked cards; deep traceability lives behind an explicit expand.
 */

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
import { recordPublicReportView } from "@/lib/report-view-beacon"
import {
  Badge,
  Card,
  ErrorState,
  LoadingState,
  Mono,
  TOKEN,
  type BadgeTone,
} from "../../../../../components/passport/shared"
import { EvidenceTraceList } from "../../../../../components/passport/EvidenceTrace"
import { ProjectDefenseInspectionSection } from "../../../../../components/passport/ProjectDefenseInspectionCard"
import styles from "./public-report.module.css"

// Keeps an in-page anchor target clear of the sticky top chrome when a
// trace link scrolls to it.
const ANCHOR_OFFSET = { scrollMarginTop: 96 }

const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Supporting evidence": "sky",
  "Evidence observed": "emerald",
  "Needs review": "rose",
  "Not assessed": "slate",
}

/** Compact display label for an evidence source. */
const SOURCE_SHORT: Record<string, string> = {
  "GitHub Proof": "GitHub",
  "Document Proof": "Documents",
  "Website Proof": "Website",
  "Project Defense": "Project Defense",
  "Video Evidence": "Video",
  "VBR Report": "Verified Build Report",
}

function shortSource(label: string): string {
  return SOURCE_SHORT[label] ?? label
}

function PublicVideoChip({ chip }: { chip: PublicVideoEvidenceChip }) {
  return (
    <div data-testid="public-video-chip" className={styles.mutedText}>
      <strong style={{ color: TOKEN.inkSoft }}>{chip.label}</strong> — {chip.short_summary}
      {chip.related_skill && (
        <>
          {" "}
          <Badge tone="slate">{chip.related_skill}</Badge>
        </>
      )}
    </div>
  )
}

/**
 * One skill's evidence as a stacked card — replaces the old desktop matrix
 * table row so the report reads cleanly on any viewport.
 */
function SkillEvidenceCard({
  row,
  tracesById,
}: {
  row: VBRReportSkillEvidenceRow
  tracesById: Map<string, EvidenceTrace>
}) {
  const sources = row.supporting_sources ?? []
  const limitations = row.limitations ?? []
  const traceRefs = (row.evidence_traces ?? [])
    .map((id) => tracesById.get(id))
    .filter((t): t is EvidenceTrace => Boolean(t))
  return (
    <div data-testid="public-skill-row" className={styles.skillCard}>
      <div className={styles.skillCardHeader}>
        <span className={styles.skillName}>{row.skill}</span>
        <Badge tone={QUALITATIVE_LABEL_TONE[row.status] ?? "slate"}>{row.status}</Badge>
      </div>
      {sources.length > 0 && (
        <div data-testid="public-skill-supporting-sources" className={styles.chipRow}>
          {sources.map((src) => (
            <Badge key={src} tone="slate">
              {shortSource(src)}
            </Badge>
          ))}
        </div>
      )}
      {(row.why_this_status || row.notes) && (
        <p className={styles.mutedText}>
          {row.why_this_status ? (
            <span data-testid="public-skill-why">{row.why_this_status}</span>
          ) : (
            row.notes
          )}
        </p>
      )}
      {row.recruiter_can_verify && (
        <p data-testid="public-skill-verify" className={styles.mutedText} style={{ fontStyle: "italic" }}>
          {row.recruiter_can_verify}
        </p>
      )}
      {limitations.length > 0 && (
        <ul data-testid="public-skill-limitations" style={{ margin: 0, paddingLeft: 16 }}>
          {limitations.map((line, i) => (
            <li key={i} className={styles.mutedText}>
              {line}
            </li>
          ))}
        </ul>
      )}
      {traceRefs.length > 0 && (
        <div data-testid="public-skill-trace-links" className={styles.chipRow}>
          {traceRefs.map((t) => (
            <a
              key={t.trace_id}
              href={`#${t.evidence_anchor}`}
              style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "none" }}
            >
              {matrixTraceLabel(t)} →
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function Assessment({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <span className={styles.mutedText} style={{ minWidth: 0 }}>
        {label}
      </span>
      <Badge tone={QUALITATIVE_LABEL_TONE[value] ?? "slate"}>{value}</Badge>
    </div>
  )
}

/**
 * Public sources the recruiter can open directly: a public GitHub repo and
 * live website targets. Never links private evidence.
 */
function PublicSourcesCard({ report }: { report: PublicVBRProjectReport }) {
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
      <h2 className={styles.sectionTitle} style={{ marginBottom: 8 }}>
        Public sources
      </h2>
      <p className={styles.mutedText} style={{ marginBottom: 10 }}>
        Open these directly to verify. Private evidence (raw documents, transcripts, recordings) is
        never linked.
      </p>
      <div className={styles.chipRow} style={{ gap: 8 }}>
        {repoUrl && (
          <a data-testid="public-safe-repo-link" href={repoUrl} target="_blank" rel="noreferrer" className={styles.safeLink}>
            View public repository ↗
          </a>
        )}
        {liveLinks.map((url) => (
          <a key={url} data-testid="public-safe-live-link" href={url} target="_blank" rel="noreferrer" className={styles.safeLink}>
            Open live site ↗
          </a>
        ))}
      </div>
    </Card>
  )
}

/** Compact evidence-coverage chips (replaces the old six-tile grid). */
function EvidenceCoverage({ report }: { report: PublicVBRProjectReport }) {
  const pkg = report.evidence_package
  const items: { label: string; present: boolean; detail?: string }[] = [
    { label: "GitHub", present: pkg.github_proof_attached },
    {
      label: "Documents",
      present: pkg.documents_count > 0,
      detail: pkg.documents_count > 0 ? `${pkg.documents_count}` : undefined,
    },
    {
      label: "Website",
      present: pkg.website_proofs_count > 0,
      detail: pkg.website_proofs_count > 0 ? `${pkg.website_proofs_count}` : undefined,
    },
    { label: "Project Defense", present: pkg.project_defense_completed },
    { label: "Video", present: pkg.video_defense_recorded },
  ]
  return (
    <div data-testid="public-report-evidence-coverage" className={styles.chipRow}>
      {items.map((item) => (
        <Badge key={item.label} tone={item.present ? "emerald" : "slate"}>
          {item.present ? "✓ " : "– "}
          {item.label}
          {item.detail ? ` · ${item.detail}` : ""}
        </Badge>
      ))}
    </div>
  )
}

/** Deep, audit-level evidence — collapsed by default (progressive disclosure). */
function DeepEvidenceSection({
  report,
  evidenceTraces,
}: {
  report: PublicVBRProjectReport
  evidenceTraces: EvidenceTrace[]
}) {
  const [open, setOpen] = useState(false)
  const analysis = report.project_defense_analysis
  const pkg = report.evidence_package

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <button
        type="button"
        className={styles.disclosureButton}
        data-testid="public-report-deep-evidence-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide full evidence detail ▴" : "Full evidence detail & traceability ▾"}
      </button>

      {open && (
        <div data-testid="public-report-deep-evidence" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Claim → evidence → source audit trail */}
          {evidenceTraces.length > 0 && (
            <Card id="evidence-traceability" style={ANCHOR_OFFSET}>
              <h2 className={styles.sectionTitle} style={{ marginBottom: 8 }}>
                Evidence traceability
              </h2>
              <p className={styles.mutedText} style={{ marginBottom: 10 }}>
                Each item is a concrete evidence source behind the skills above. Public sources link
                directly; private evidence is summarized, never exposed.
              </p>
              <EvidenceTraceList traces={evidenceTraces} />
            </Card>
          )}

          {/* Per-source audit detail */}
          <Card id="evidence-by-source" style={ANCHOR_OFFSET}>
            <h2 className={styles.sectionTitle} style={{ marginBottom: 10 }}>
              Evidence by source
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div id="github-proof" style={ANCHOR_OFFSET}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>GitHub Proof</Mono>
                {report.github_proof ? (
                  <div style={{ marginTop: 4 }}>
                    <p className={styles.bodyText} style={{ marginBottom: 4 }}>
                      {report.github_proof.repo_owner && report.github_proof.repo_name
                        ? `${report.github_proof.repo_owner}/${report.github_proof.repo_name}`
                        : report.github_proof.repo_url}
                    </p>
                    {report.github_proof.public_safe_summary && (
                      <p className={styles.mutedText} style={{ marginBottom: 6 }}>{report.github_proof.public_safe_summary}</p>
                    )}
                    <div className={styles.chipRow}>
                      {report.github_proof.detected_skills.map((skill) => (
                        <Badge key={skill} tone="slate">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className={styles.mutedText} style={{ marginTop: 4 }}>GitHub proof not attached.</p>
                )}
              </div>

              <div id="documents" style={ANCHOR_OFFSET}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Document Proof</Mono>
                {report.documents.length > 0 ? (
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                    {report.documents.map((doc, i) => (
                      <li key={i} className={styles.bodyText}>
                        {doc.title}
                        {doc.status ? ` — ${doc.status}` : ""}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.mutedText} style={{ marginTop: 4 }}>No document proof attached.</p>
                )}
              </div>

              <div id="website-proof" style={ANCHOR_OFFSET}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Website Proof</Mono>
                {report.website_proofs.length > 0 ? (
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                    {report.website_proofs.map((wp, i) => {
                      const safeTarget = isSafePublicUrl(wp.target_website) ? wp.target_website : null
                      return (
                        <li key={i} className={styles.bodyText} style={{ overflowWrap: "anywhere" }}>
                          {safeTarget ?? <em style={{ color: TOKEN.muted }}>Private/internal link omitted</em>} —{" "}
                          {wp.workflow_confidence} confidence
                          {wp.supported_skills.length > 0 ? ` (${wp.supported_skills.join(", ")})` : ""}{" "}
                          <Badge tone={QUALITATIVE_LABEL_TONE[wp.evidence_strength] ?? "slate"}>{wp.evidence_strength}</Badge>
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <p className={styles.mutedText} style={{ marginTop: 4 }}>Website proof not attached.</p>
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
                  <p className={styles.mutedText} style={{ marginTop: 4 }}>Transcript evidence not available.</p>
                ) : (
                  <p className={styles.mutedText} style={{ marginTop: 4 }}>Video defense not recorded.</p>
                )}
              </div>

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

              {analysis && (
                <div>
                  <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Defense Assessment Detail</Mono>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                    <Assessment label="Overall" value={analysis.overall_assessment} />
                    <Assessment label="Clarity" value={analysis.explanation_clarity} />
                    <Assessment label="Ownership signal" value={analysis.ownership_signal} />
                    <Assessment label="Technical depth" value={analysis.technical_depth} />
                    <Assessment label="Consistency with evidence" value={analysis.consistency_with_evidence} />
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>
      )}
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
        // Fire-and-forget, session-deduped view event. Never awaited and never
        // able to fail loudly — analytics must not block or break the report.
        void recordPublicReportView(token)
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
  const evidenceTraces = report.evidence_traces ?? []
  const tracesById = new Map(evidenceTraces.map((t) => [t.trace_id, t]))

  return (
    <div data-testid="public-report" className={styles.page}>
      {/* Header */}
      <div style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 6 }}>
        <Mono style={{ fontSize: 11, letterSpacing: "0.16em", color: TOKEN.indigo, textTransform: "uppercase" }}>
          VeriBridge AI · Verified Build Report
        </Mono>
        <h1 className={styles.reportTitle}>{report.report_title}</h1>
        {report.candidate_display_name && (
          <p style={{ fontSize: 14.5, color: TOKEN.inkSoft, margin: 0, fontWeight: 600 }}>
            {report.public_passport_path ? (
              <a
                data-testid="public-report-candidate-link"
                href={report.public_passport_path}
                style={{ color: TOKEN.inkSoft, textDecoration: "none" }}
              >
                {report.candidate_display_name}
              </a>
            ) : (
              report.candidate_display_name
            )}
          </p>
        )}
        {report.published_at && (
          <p className={styles.mutedText} style={{ fontSize: 12 }}>
            Published {new Date(report.published_at).toLocaleDateString()}
          </p>
        )}
      </div>

      {/* 1 — Project overview: what was built + the candidate's role */}
      <Card>
        <h2 className={styles.sectionTitle} style={{ marginBottom: 8 }}>
          {report.project_title}
        </h2>
        {report.project_summary && (
          <p className={styles.bodyText} style={{ marginBottom: 10 }}>
            {report.project_summary}
          </p>
        )}
        {report.student_role && (
          <p className={styles.mutedText} style={{ marginBottom: 10 }}>
            <strong style={{ color: TOKEN.inkSoft }}>Candidate role: </strong>
            {report.student_role}
          </p>
        )}
        {report.repo_full_name && (
          <Mono style={{ fontSize: 11, color: TOKEN.muted, display: "block", marginBottom: 10, overflowWrap: "anywhere" }}>
            {report.repo_full_name}
          </Mono>
        )}
        {/* Compact evidence coverage inside the overview so the recruiter sees
            what backs this report immediately — without a stats wall. */}
        <EvidenceCoverage report={report} />
      </Card>

      {/* 2 — Strongest evidence-backed skills (stacked cards, no table) */}
      <section id="skill-evidence" style={{ ...ANCHOR_OFFSET, display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 className={styles.sectionTitle}>Evidence-backed skills</h2>
        {report.skill_evidence.length === 0 ? (
          <Card>
            <p className={styles.mutedText}>No claimed skills recorded for this project.</p>
          </Card>
        ) : (
          <div data-testid="public-skill-cards" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {report.skill_evidence.map((row) => (
              <SkillEvidenceCard key={row.skill} row={row} tracesById={tracesById} />
            ))}
          </div>
        )}
      </section>

      {/* 3 — Public sources the recruiter can verify directly */}
      <PublicSourcesCard report={report} />

      {/* 4 — Candidate explanation (Project Defense narrative) */}
      {analysis && (
        <Card id="project-defense" style={ANCHOR_OFFSET}>
          <h2 className={styles.sectionTitle} style={{ marginBottom: 8 }}>
            Candidate explanation
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <p className={styles.bodyText}>{analysis.transcript_summary}</p>
            <p className={styles.mutedText} style={{ fontStyle: "italic" }}>
              {analysis.recruiter_summary}
            </p>
            <div className={styles.chipRow}>
              <Badge tone={QUALITATIVE_LABEL_TONE[analysis.overall_assessment] ?? "slate"}>
                Overall: {analysis.overall_assessment}
              </Badge>
              <Badge tone={QUALITATIVE_LABEL_TONE[analysis.ownership_signal] ?? "slate"}>
                Ownership: {analysis.ownership_signal}
              </Badge>
            </div>
          </div>
        </Card>
      )}

      {/* 5 — Limitations / not assessed */}
      <Card id="limitations" style={ANCHOR_OFFSET}>
        <h2 className={styles.sectionTitle} style={{ marginBottom: 8 }}>
          Limitations & not assessed
        </h2>
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {report.limitations.map((line, i) => (
            <li key={i} className={styles.mutedText}>
              {line}
            </li>
          ))}
        </ul>
      </Card>

      {/* 6 — Deep evidence & traceability (collapsed by default) */}
      <DeepEvidenceSection report={report} evidenceTraces={evidenceTraces} />

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
        <p className={styles.mutedText} style={{ fontSize: 11.5, textAlign: "center" }}>
          {report.verification_note}
        </p>
      )}

      {/* CTA */}
      <Card>
        <div data-testid="public-report-cta" style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 10, padding: "8px 0" }}>
          <h2 style={{ fontSize: 16, color: TOKEN.ink, margin: 0 }}>Hiring? Verify what candidates actually built.</h2>
          <p className={styles.mutedText}>
            Request an evidence-backed Verified Build Report from your candidates, or learn how VeriBridge works.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
            <a
              href="/recruiters"
              style={{ padding: "10px 16px", borderRadius: 10, background: TOKEN.indigo, color: "#fff", fontSize: 13, fontWeight: 600, textDecoration: "none" }}
            >
              Request a VBR from your candidates
            </a>
            <a
              href="/recruiters"
              style={{ padding: "10px 16px", borderRadius: 10, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.inkSoft, fontSize: 13, fontWeight: 600, textDecoration: "none" }}
            >
              See how VeriBridge works
            </a>
          </div>
        </div>
      </Card>
    </div>
  )
}
