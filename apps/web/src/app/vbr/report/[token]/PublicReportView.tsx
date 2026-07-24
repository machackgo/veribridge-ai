"use client"

/**
 * Public Verified Build Report — the recruiter-facing rendering of the ONE
 * canonical report.
 *
 * This view renders the SAME canonical sections, in the same order and design
 * language, as the student report at /student/vbr/projects/[id]/report (via the
 * shared `CanonicalReportSections` module):
 *
 *   1. Project overview (title, role, evidence summary grid)
 *   2. Jump navigation
 *   3. Direct links (truth-gated public repo + live site)
 *   4. Skills Demonstrated in This Project — skill-first evidence cards
 *   5. Candidate explanation (Project Defense narrative)
 *   6. Limitations
 *   7. Evidence by source + traceability (collapsed — progressive disclosure)
 *
 * The only differences from the student view are authentication-safe public
 * ones: no publish controls, no owner-only original-file access or replay, and
 * the deep audit detail is collapsed by default for recruiters. GitHub truth:
 * a repository is linked only when a GitHub Proof is attached AND the repo is
 * public; a private-but-scanned repo is labelled honestly; no GitHub Proof
 * means no repository identity is implied anywhere.
 */

import { useEffect, useState } from "react"
import {
  getPublicVBRProjectReport,
  isSafePublicUrl,
  type EvidenceTrace,
  type PublicMediaView,
  type PublicVBRProjectReport,
  type PublicVideoEvidenceChip,
} from "@/lib/vbr-api"
import { PUBLIC_API_BASE } from "@/lib/api-base"
import { recordPublicReportView } from "@/lib/report-view-beacon"
import {
  Badge,
  Card,
  CardHeader,
  ErrorState,
  LoadingState,
  Mono,
  TOKEN,
} from "../../../../../components/passport/shared"
import {
  CanonicalSkillEvidenceCard,
  DirectLinksBody,
  EvidenceSummaryGrid,
  GithubProofBlock,
  PUBLIC_SKILL_CARD_TEST_IDS,
  QUALITATIVE_LABEL_TONE,
  ReportJumpNav,
  safeDirectLinks,
} from "../../../../../components/passport/CanonicalReportSections"
import { EvidenceTraceList } from "../../../../../components/passport/EvidenceTrace"
import { ProjectDefenseInspectionSection } from "../../../../../components/passport/ProjectDefenseInspectionCard"
import styles from "./public-report.module.css"

// Keeps an in-page anchor target clear of the sticky top chrome when a
// trace link scrolls to it.
const ANCHOR_OFFSET = { scrollMarginTop: 96 }

/** Absolute API URL for a disclosure-gated media/document view path. */
const apiViewUrl = (path: string) => `${PUBLIC_API_BASE}${path}`

/** Candidate-shared captured screenshots — a small lazy horizontal strip. */
function WebsiteFrameStrip({ frames }: { frames: PublicMediaView[] }) {
  if (frames.length === 0) return null
  return (
    <div
      data-testid="public-website-frames"
      style={{ display: "flex", gap: 8, overflowX: "auto", padding: "6px 0", maxWidth: "100%" }}
    >
      {frames.map((frame, i) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={`${frame.view_path}-${i}`}
          data-testid="public-website-frame"
          src={apiViewUrl(frame.view_path)}
          alt={`Candidate-shared workflow screenshot ${i + 1}`}
          loading="lazy"
          style={{ maxHeight: 140, borderRadius: 8, border: `1px solid ${TOKEN.line}`, flexShrink: 0 }}
        />
      ))}
    </div>
  )
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

function Assessment({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{label}</Mono>
      <Badge tone={QUALITATIVE_LABEL_TONE[value] ?? "slate"}>{value}</Badge>
    </div>
  )
}

/** Public skill-report href behind a skill card, when the passport is published. */
function publicSkillHref(passportPath: string | null | undefined, skill: string): string | null {
  if (!passportPath || !/^\/p\/[A-Za-z0-9_-]+$/.test(passportPath)) return null
  const slug = skill
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
  return slug ? `${passportPath}/skills/${slug}` : null
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
              <CardHeader title="Evidence Traceability" eyebrow="Claim → evidence → source" icon="🔍" />
              <p className={styles.mutedText} style={{ marginBottom: 10 }}>
                Each item is a concrete evidence source behind the skills above. Public sources link
                directly; private evidence is summarized, never exposed.
              </p>
              <EvidenceTraceList traces={evidenceTraces} />
            </Card>
          )}

          {/* Per-source audit detail — canonical section order. */}
          <Card id="evidence-by-source" style={ANCHOR_OFFSET}>
            <CardHeader title="Evidence by Source" eyebrow="Supporting detail" icon="📎" />
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div id="github-proof" style={ANCHOR_OFFSET}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>GitHub Proof</Mono>
                <GithubProofBlock githubProof={report.github_proof} linkTestId="public-github-proof-repo-link" />
              </div>

              <div id="documents" style={ANCHOR_OFFSET}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Document Proof</Mono>
                {report.documents.length > 0 ? (
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                    {report.documents.map((doc, i) => {
                      const sharedView = doc.disclosure === "viewable" ? doc.shared_view : null
                      return (
                        <li key={i} className={styles.bodyText}>
                          {doc.title}
                          {doc.status ? ` — ${doc.status}` : ""}
                          {sharedView && (
                            <span style={{ display: "inline-flex", gap: 10, marginLeft: 8, flexWrap: "wrap" }}>
                              <a
                                data-testid="public-doc-view-link"
                                href={apiViewUrl(sharedView.open_path)}
                                target="_blank"
                                rel="noreferrer"
                                style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
                              >
                                View document ↗
                              </a>
                              {sharedView.can_download && sharedView.download_path && (
                                <a
                                  data-testid="public-doc-download-link"
                                  href={apiViewUrl(sharedView.download_path)}
                                  style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
                                >
                                  Download
                                </a>
                              )}
                            </span>
                          )}
                        </li>
                      )
                    })}
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
                      const frames = wp.frame_views ?? []
                      return (
                        <li key={i} className={styles.bodyText} style={{ overflowWrap: "anywhere" }}>
                          {safeTarget ?? <em style={{ color: TOKEN.muted }}>Private/internal link omitted</em>} —{" "}
                          {wp.workflow_confidence} confidence
                          {wp.supported_skills.length > 0 ? ` (${wp.supported_skills.join(", ")})` : ""}{" "}
                          <Badge tone={QUALITATIVE_LABEL_TONE[wp.evidence_strength] ?? "slate"}>{wp.evidence_strength}</Badge>
                          {/* Candidate-shared runtime evidence (disclosure-gated). */}
                          <WebsiteFrameStrip frames={frames} />
                          {wp.replay_path && (
                            <div style={{ marginTop: 6 }}>
                              <p className={styles.mutedText} style={{ margin: "0 0 4px" }}>
                                Candidate shared the recorded walkthrough of this workflow.
                              </p>
                              <video
                                data-testid="public-website-replay"
                                src={apiViewUrl(wp.replay_path)}
                                controls
                                preload="metadata"
                                aria-label="Watch walkthrough recording"
                                style={{ width: "100%", maxWidth: 520, borderRadius: 10, border: `1px solid ${TOKEN.line}`, background: "#000" }}
                              />
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <p className={styles.mutedText} style={{ marginTop: 4 }}>Website proof not attached.</p>
                )}
              </div>

              <div id="project-defense" style={ANCHOR_OFFSET}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>Manual / Video Project Defense</Mono>
                {analysis ? (
                  <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 10 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                      <Assessment label="Overall" value={analysis.overall_assessment} />
                      <Assessment label="Clarity" value={analysis.explanation_clarity} />
                      <Assessment label="Ownership signal" value={analysis.ownership_signal} />
                      <Assessment label="Technical depth" value={analysis.technical_depth} />
                      <Assessment label="Consistency with evidence" value={analysis.consistency_with_evidence} />
                    </div>
                  </div>
                ) : (
                  <p className={styles.mutedText} style={{ marginTop: 4 }}>Project Defense has not been analyzed.</p>
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
        <span aria-hidden style={{ fontSize: 30, display: "block", marginBottom: 10 }}>🔒</span>
        <h1 style={{ fontSize: 20, color: TOKEN.ink, marginBottom: 10 }}>This report is not available</h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, lineHeight: 1.6 }}>
          The candidate’s Work Passport is currently private, the report was unpublished, or the link may be
          incorrect. Ask the candidate for an up-to-date Verified Build Report link.
        </p>
      </div>
    )
  }

  if (error || !report) return <ErrorState message={error ?? "Report not found."} onRetry={load} />

  const analysis = report.project_defense_analysis
  const evidenceTraces = report.evidence_traces ?? []
  const tracesById = new Map(evidenceTraces.map((t) => [t.trace_id, t]))
  const { repoUrl, liveLinks } = safeDirectLinks(report)

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
        <CardHeader title={report.project_title} eyebrow="Project summary" icon="📁" />
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
        {/* Repository identity appears ONLY when a GitHub Proof backs it — a
            public repo renders as a link; a scanned private repo is labelled;
            no proof → no implied repository (the GitHub truth model). A
            summary-only candidate disclosure never shows repo identity. */}
        {report.github_proof && report.github_proof.disclosure !== "summary" && report.repo_full_name && (
          <div style={{ marginBottom: 10 }}>
            {repoUrl ? (
              <a
                data-testid="public-report-repo-identity"
                href={repoUrl}
                target="_blank"
                rel="noreferrer"
                style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 11, color: TOKEN.indigo, textDecoration: "none", overflowWrap: "anywhere" }}
              >
                {report.repo_full_name} ↗
              </a>
            ) : (
              <Mono style={{ fontSize: 11, color: TOKEN.muted, display: "block", overflowWrap: "anywhere" }}>
                {report.repo_full_name} · private repository (scanner-verified, not publicly openable)
              </Mono>
            )}
          </div>
        )}
        {/* The canonical Project Evidence Summary grid. */}
        <EvidenceSummaryGrid pkg={report.evidence_package} testId="public-report-evidence-coverage" />
      </Card>

      {/* 2 — In-page navigation (canonical jump nav) */}
      <ReportJumpNav
        testId="public-report-jump-nav"
        items={[
          { href: "#skill-evidence", label: "Skills Demonstrated" },
          { href: "#github-proof", label: "GitHub Proof" },
          { href: "#documents", label: "Documents" },
          { href: "#website-proof", label: "Website Proof" },
          { href: "#project-defense", label: "Project Defense" },
          { href: "#limitations", label: "Limitations" },
        ]}
      />

      {/* 3 — Direct safe links the recruiter can verify directly */}
      {(repoUrl || liveLinks.length > 0) && (
        <Card>
          <CardHeader title="Direct Links" eyebrow="Verify it yourself" icon="🔗" />
          <p className={styles.mutedText} style={{ marginBottom: 10 }}>
            Public sources you can open directly. Private evidence (raw documents, transcripts, and
            recordings) is never linked.
          </p>
          <DirectLinksBody
            repoUrl={repoUrl}
            liveLinks={liveLinks}
            repoTestId="public-safe-repo-link"
            liveTestId="public-safe-live-link"
          />
        </Card>
      )}

      {/* 4 — Skills Demonstrated in This Project (canonical skill-first cards) */}
      <Card id="skill-evidence" style={ANCHOR_OFFSET}>
        <CardHeader
          title="Skills Demonstrated in This Project"
          eyebrow="Skill → proof types → evidence"
          icon="🧩"
        />
        <p className={styles.mutedText} style={{ marginBottom: 12 }}>
          Each card shows one skill, the proof sources that support it in this project, the evidence
          grouped by source, and what that evidence does not prove.
        </p>
        {report.skill_evidence.length === 0 ? (
          <p className={styles.mutedText}>No claimed skills recorded for this project.</p>
        ) : (
          <div data-testid="public-skill-cards" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {report.skill_evidence.map((row) => (
              <CanonicalSkillEvidenceCard
                key={row.skill}
                row={row}
                tracesById={tracesById}
                testIds={PUBLIC_SKILL_CARD_TEST_IDS}
                skillHref={publicSkillHref(report.public_passport_path, row.skill)}
                skillCtaLabel="Open the full public skill report →"
              />
            ))}
          </div>
        )}
      </Card>

      {/* 5 — Candidate explanation (Project Defense narrative) */}
      {analysis && (
        <Card>
          <CardHeader title="Candidate Explanation" eyebrow="Project Defense narrative" icon="🗣️" />
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

      {/* 5b — Candidate-shared Project Defense media (disclosure-gated). Only
          rendered when the candidate explicitly shared it — never an empty
          shell, never error-like wording when absent. */}
      {(report.defense_transcript_view || report.defense_video_view) && (
        <Card>
          <CardHeader title="Candidate-Shared Defense Recording" eyebrow="Shared by the candidate" icon="🎙️" />
          <p className={styles.mutedText} style={{ marginBottom: 10 }}>
            The candidate chose to share this Project Defense material with recruiters.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {report.defense_transcript_view && (
              <a
                data-testid="public-defense-transcript-link"
                href={apiViewUrl(report.defense_transcript_view.view_path)}
                target="_blank"
                rel="noreferrer"
                style={{
                  alignSelf: "flex-start",
                  fontSize: 13,
                  fontWeight: 600,
                  color: TOKEN.indigo,
                  textDecoration: "none",
                  padding: "8px 12px",
                  borderRadius: 8,
                  border: `1px solid ${TOKEN.line}`,
                  background: "#fff",
                }}
              >
                📄 View transcript ↗
              </a>
            )}
            {report.defense_video_view && (
              <video
                data-testid="public-defense-video"
                src={apiViewUrl(report.defense_video_view.view_path)}
                controls
                preload="metadata"
                aria-label="Candidate-shared defense recording"
                style={{ width: "100%", maxWidth: 640, borderRadius: 10, border: `1px solid ${TOKEN.line}`, background: "#000" }}
              />
            )}
          </div>
        </Card>
      )}

      {/* 6 — Limitations / not assessed */}
      <Card id="limitations" style={ANCHOR_OFFSET}>
        <CardHeader title="Limitations / Not Assessed" eyebrow="Honest gaps" icon="⚠️" />
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {report.limitations.map((line, i) => (
            <li key={i} className={styles.mutedText}>
              {line}
            </li>
          ))}
        </ul>
      </Card>

      {/* 7 — Deep evidence & traceability (collapsed by default) */}
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
