"use client"

import { useEffect, useRef, useState, type CSSProperties } from "react"
import Link from "next/link"
import {
  fallbackSkillSlug,
  getVBRProjectReport,
  getVBRProjectReportPublishStatus,
  publishVBRProjectReport,
  skillReportPath,
  unpublishVBRProjectReport,
  type ProjectReportPublishStatus,
  type RealUnmappedProofContext,
  type VBRStudentProjectReportResponse,
  type VideoEvidenceChip,
} from "@/lib/vbr-api"
import { buildPublicAppUrl } from "@/lib/api"

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
import {
  CanonicalSkillEvidenceCard,
  DirectLinksBody,
  EvidenceSummaryGrid,
  GithubProofBlock,
  OWNER_SKILL_CARD_TEST_IDS,
  ReportJumpNav,
  safeDirectLinks,
} from "../../../../../../../components/passport/CanonicalReportSections"
import { useAuthorizedMediaUrl } from "../../../../../../../components/passport/AuthorizedReplayVideo"
import { ClaimEvidenceMapSection } from "../../../../../../../components/passport/ClaimEvidenceMapSection"
import { DocumentOriginalAccessActions } from "../../../../../../../components/passport/OriginalProofAccess"
import { EvidenceTraceList } from "../../../../../../../components/passport/EvidenceTrace"
import { VaultSkillLinkList } from "../../../../../../../components/passport/VaultProofs"
import { ProjectDefenseInspectionSection } from "../../../../../../../components/passport/ProjectDefenseInspectionCard"
import { QrModal } from "../../../../../../../components/passport/QrModal"

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

/**
 * Retained website walkthrough replay inside the Website Behavior Evidence
 * card. The replay path is the owner-gated canonical API route from the report
 * payload — it is streamed with the caller's session (the backend re-checks
 * access per request; strangers get 404) and played from a local object URL.
 */
function WebsiteReplayBlock({ replayPath, analysisPath }: { replayPath?: string | null; analysisPath?: string | null }) {
  const src = useAuthorizedMediaUrl(replayPath ?? null)
  if (!replayPath && !analysisPath) return null
  return (
    <div data-testid="website-replay" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {replayPath && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <Badge tone="emerald">Recording retained</Badge>
            <span style={{ fontSize: 11, color: TOKEN.muted }}>
              Owner-only replay of the recorded walkthrough — access is re-checked on every request.
            </span>
          </div>
          <video
            data-testid="website-replay-video"
            controls
            preload="none"
            src={src ?? undefined}
            style={{ width: "100%", maxHeight: 280, borderRadius: 8, background: "#000" }}
          />
        </>
      )}
      {analysisPath && (
        <Link
          data-testid="website-analysis-link"
          href={analysisPath}
          style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none", alignSelf: "flex-start" }}
        >
          Open full Website analysis →
        </Link>
      )}
    </div>
  )
}

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

// The skill-first evidence card now comes from the shared canonical report
// module (`CanonicalSkillEvidenceCard`) so the student preview and the public
// recruiter report render the identical card design.

/**
 * "Attached proof not yet skill-mapped" strip — REAL analyzed proof attached to
 * THIS project that no exact claimed skill row consumed. Secondary context, not
 * part of the skill evidence cards above: it never counts as skill evidence and
 * never appears on the public report. Each entry jumps to the existing proof
 * section (GitHub Proof / Website Proof / Documents / Project Defense) instead
 * of duplicating those cards.
 */
function RealUnmappedProofStrip({ entries }: { entries: RealUnmappedProofContext[] }) {
  if (entries.length === 0) return null
  return (
    <Card id="real-unmapped-proof" style={ANCHOR_OFFSET}>
      <div data-testid="report-real-unmapped-strip" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <CardHeader
          title="Attached proof not yet skill-mapped"
          eyebrow="Real proof exists, not skill-mapped yet"
          icon="🧭"
        />
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>
          These proof sources are attached to this project but are not yet mapped to a specific skill claim. They are
          real, analyzed evidence — kept separate from the skill cards above so exact skill evidence stays exact.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {entries.map((ctx, i) => (
            <div
              key={`${ctx.proof_type}:${ctx.evidence_label ?? ""}:${i}`}
              data-testid="report-real-unmapped-entry"
              data-proof-type={ctx.proof_type}
              style={{
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
                padding: 10,
                display: "flex",
                flexDirection: "column",
                gap: 4,
                background: TOKEN.bg,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <Badge tone={SOURCE_TONE[ctx.proof_type] ?? "slate"}>{ctx.proof_type}</Badge>
                {ctx.evidence_label && (
                  <span style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted }}>{ctx.evidence_label}</span>
                )}
              </div>
              {ctx.safe_summary && (
                <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{ctx.safe_summary}</p>
              )}
              <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>{ctx.reason}</p>
              {ctx.inspection_anchor && (
                <a
                  href={`#${ctx.inspection_anchor}`}
                  data-testid="report-real-unmapped-jump"
                  style={{ fontSize: 12, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
                >
                  Inspect this proof section →
                </a>
              )}
            </div>
          ))}
        </div>
      </div>
    </Card>
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
  const [qrOpen, setQrOpen] = useState(false)
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
      ? buildPublicAppUrl(`/vbr/report/${status.public_token}`)
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
                data-testid="show-report-qr-button"
                onClick={() => setQrOpen(true)}
                style={secondaryBtnStyle}
              >
                Show QR code
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
            {/* Report QR: encodes exactly the canonical public report URL (the
                same value Copy uses) — never an auth token or private route. */}
            <QrModal
              value={publicUrl || null}
              open={qrOpen}
              onClose={() => setQrOpen(false)}
              title="Scan to open the Verified Build Report"
              subtitle="Point a phone camera at the code to open this project’s public report."
            />
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

      {/* In-page navigation to evidence sections (canonical jump nav) */}
      <ReportJumpNav
        items={[
          { href: "#skills-demonstrated", label: "Skills Demonstrated" },
          { href: "#github-proof", label: "GitHub Proof" },
          { href: "#documents", label: "Documents" },
          { href: "#website-proof", label: "Website Proof" },
          { href: "#project-defense", label: "Project Defense" },
          { href: "#limitations", label: "Limitations" },
        ]}
      />

      {/* Direct safe links */}
      <SafeLinksCard report={report} />

      {/* Project Evidence Summary — a compact proof-source overview. Kept
          deliberately secondary: the skill-first cards below are the main body. */}
      <Card>
        <CardHeader title="Project Evidence Summary" eyebrow="Proof sources attached" icon="🗂️" />
        <EvidenceSummaryGrid pkg={pkg} />
      </Card>

      {/* ── MAIN BODY: Skills Demonstrated in This Project ─────────────────────
          The report's primary lens. For each claimed skill, a skill-first
          evidence card answers "which skills are demonstrated in THIS project,
          and what exact proof types support each skill?" — replacing the old,
          spreadsheet-like Skill Evidence Matrix. */}
      <Card id="skills-demonstrated" style={ANCHOR_OFFSET}>
        <CardHeader
          title="Skills Demonstrated in This Project"
          eyebrow="Skill → proof types → evidence"
          icon="🧩"
        />
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 12px", lineHeight: 1.5 }}>
          Each card shows one skill, the proof sources that support it in this project, the evidence grouped by
          source, and what that evidence does not prove. Skills with no attached proof are marked{" "}
          <strong>Not assessed</strong>.
        </p>
        {report.skill_evidence.length === 0 ? (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>No claimed skills recorded for this project.</p>
        ) : (
          <div data-testid="skill-evidence-cards" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {report.skill_evidence.map((row) => (
              <CanonicalSkillEvidenceCard
                key={row.skill}
                row={row}
                tracesById={tracesById}
                testIds={OWNER_SKILL_CARD_TEST_IDS}
                skillHref={skillReportPath(fallbackSkillSlug(row.skill))}
              />
            ))}
          </div>
        )}
      </Card>

      {/* Canonical claim→evidence map — the backend-synthesized argument for
          each skill claim (citations, identity checks, corroboration, mismatch
          and pending states). Rendered verbatim; absent on legacy payloads. */}
      {report.claim_evidence_map && report.claim_evidence_map.claims.length > 0 && (
        <Card id="claim-evidence-map" style={ANCHOR_OFFSET}>
          <CardHeader title="Claim-to-Evidence Map" eyebrow="What exactly proves each claim" icon="🧭" />
          <ClaimEvidenceMapSection map={report.claim_evidence_map} />
        </Card>
      )}

      {/* Attached proof not yet skill-mapped — real analyzed proof with no exact
          skill row. Secondary strip; jumps into the proof sections below. */}
      <RealUnmappedProofStrip entries={report.real_unmapped_proof_context ?? []} />

      {/* Evidence by source — secondary supporting detail beneath the skill
          cards (the per-source proof breakdown + Website Behavior Evidence). */}
      <Card id="evidence-by-source" style={ANCHOR_OFFSET}>
        <CardHeader title="Evidence by Source" eyebrow="Supporting detail" icon="📎" />
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div id="github-proof" style={ANCHOR_OFFSET}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              GitHub Proof
            </Mono>
            {/* Canonical GitHub truth block. Owner-only nuance: the private
                preview may still show the raw repository reference in the
                not-attached note (the student registered it themselves). */}
            <GithubProofBlock
              githubProof={report.github_proof}
              notAttachedNote={`GitHub Proof not attached — repository reference only (${report.repo_full_name || report.repo_url}).`}
            />
          </div>

          <div id="documents" style={ANCHOR_OFFSET}>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
              Document Proof
            </Mono>
            {report.documents.length > 0 ? (
              <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                {report.documents.map((doc, i) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                    {doc.title}
                    {doc.source_type ? ` (${doc.source_type})` : ""}
                    {doc.status ? ` — ${doc.status}` : ""}
                    {/* Owner-only retained-original access: Open/Download when the
                        original file is retained, the honest not-retained note
                        otherwise. Absent on public surfaces (backend strips it). */}
                    {doc.original_document && (
                      <div style={{ marginTop: 4 }}>
                        <DocumentOriginalAccessActions access={doc.original_document} />
                      </div>
                    )}
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

            {(report.website_skill_evidence ?? []).length > 0 && (
              <div
                data-testid="website-skill-evidence"
                style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}
              >
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                  Website Behavior Evidence
                </Mono>
                {(report.website_skill_evidence ?? []).map((ev, i) => (
                  <div
                    key={i}
                    data-testid="website-behavior-card"
                    style={{ border: `1px solid ${TOKEN.line}`, borderRadius: 8, padding: 10, display: "flex", flexDirection: "column", gap: 6 }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <Mono style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.14em" }}>
                        Website Runtime Inspection
                      </Mono>
                      <Badge tone="slate">{ev.website_purpose_label}</Badge>
                      {ev.verification_mode_label ? (
                        <span
                          data-testid="website-verification-mode"
                          data-mode={ev.verification_mode === "directly_verifiable_live" ? "live" : "recorded"}
                        >
                          <Badge tone={ev.verification_mode === "directly_verifiable_live" ? "emerald" : "amber"}>
                            {ev.verification_mode_label}
                          </Badge>
                        </span>
                      ) : null}
                    </div>
                    {(ev.target_domain || ev.app_context || ev.target_website) && (
                      <p data-testid="website-target-site" style={{ fontSize: 11, color: TOKEN.inkSoft, margin: 0 }}>
                        <strong>Target site: </strong>
                        {ev.target_domain || ev.target_website}
                        {ev.app_context && ev.app_context !== ev.target_domain ? ` · ${ev.app_context}` : ""}
                      </p>
                    )}
                    {ev.runtime_claim_observed ? (
                      <p data-testid="website-runtime-claim" style={{ fontSize: 12, color: TOKEN.ink, margin: 0, fontWeight: 600 }}>
                        {ev.runtime_claim_observed}
                      </p>
                    ) : null}
                    <p data-testid="website-behavior-claim" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>
                      {ev.behavior_claim}
                    </p>
                    {ev.user_action_observed ? (
                      <p data-testid="website-user-action" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                        <strong>User action: </strong>
                        {ev.user_action_observed}
                      </p>
                    ) : null}
                    {ev.output_observed ? (
                      <p data-testid="website-output-observed" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                        <strong>Output: </strong>
                        {ev.output_observed}
                      </p>
                    ) : null}
                    {(ev.recruiter_checklist ?? []).length > 0 && (
                      <ul
                        data-testid="website-recruiter-checklist"
                        style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}
                      >
                        {(ev.recruiter_checklist ?? []).map((step, si) => (
                          <li key={si} data-testid="website-checklist-item" style={{ fontSize: 11, color: TOKEN.inkSoft }}>
                            {step}
                          </li>
                        ))}
                      </ul>
                    )}
                    {ev.website_replay_available && (
                      <WebsiteReplayBlock replayPath={ev.website_replay_path} analysisPath={ev.website_analysis_path} />
                    )}
                    {!ev.website_replay_available && ev.website_analysis_path && (
                      <WebsiteReplayBlock analysisPath={ev.website_analysis_path} />
                    )}
                    {ev.skill_mapping_available ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {ev.skills.map((sk) => (
                          <div
                            key={sk.skill_name}
                            data-testid="website-skill-relevance"
                            data-skill={sk.skill_name}
                            style={{ display: "flex", flexDirection: "column", gap: 2 }}
                          >
                            <span style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: 12, color: TOKEN.inkSoft }}>
                              <Badge tone={sk.is_direct_evidence ? "emerald" : "amber"}>
                                {sk.is_direct_evidence ? "Direct" : "Supporting context"}
                              </Badge>
                              {sk.relevance_label}
                            </span>
                            <span style={{ fontSize: 11, color: TOKEN.muted }}>{sk.limitation}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p data-testid="website-skill-mapping-empty" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
                        Website Proof captured; skill-specific mapping not available yet.
                      </p>
                    )}
                  </div>
                ))}
              </div>
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

          {/* First-class Project Defense inspection — per-question explanation /
              corroboration evidence. Never framed as implementation proof. */}
          {(report.project_defense_inspection?.length ?? 0) > 0 && (
            <div>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Project Defense Inspection
              </Mono>
              <div style={{ marginTop: 6 }}>
                <ProjectDefenseInspectionSection
                  cards={report.project_defense_inspection}
                  testId="report-project-defense-inspection"
                />
              </div>
            </div>
          )}
        </div>
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

      {/* Other student proofs for related skills — cross-proof vault matches.
          These are NOT attached to this project; they are shown separately from
          the attached skill matrix above so the report stays project-honest. */}
      {(report.other_student_proofs?.length ?? 0) > 0 && (
        <Card id="other-student-proofs" style={ANCHOR_OFFSET}>
          <div data-testid="other-student-proofs">
            <CardHeader
              title="Other Student Proofs for Related Skills"
              eyebrow="From your wider proof vault — not attached to this project"
              icon="🗂️"
            />
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px", lineHeight: 1.5 }}>
              These are other safe proofs you own that match this project&apos;s claimed skills but are{" "}
              <strong>not attached to this project</strong>. They are summarised here as cross-proof / vault evidence —
              open the full <strong>Skill Report</strong> to inspect the connected evidence. They are never counted as
              this project&apos;s attached evidence.
            </p>
            <VaultSkillLinkList groups={report.other_student_proofs} />
          </div>
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

/**
 * Direct, recruiter-safe outbound links: a public GitHub repo (only when known
 * public), a public deployed app URL, and live website-proof targets. Never
 * links raw private docs, transcripts, signed URLs, or storage paths. Uses the
 * shared canonical truth gate + body so student and public reports agree.
 */
function SafeLinksCard({ report }: { report: VBRStudentProjectReportResponse }) {
  const { repoUrl, liveLinks } = safeDirectLinks(report)

  if (!repoUrl && liveLinks.length === 0) return null

  return (
    <Card>
      <CardHeader title="Direct Links" eyebrow="Verify it yourself" icon="🔗" />
      <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px", lineHeight: 1.5 }}>
        Public sources you can open directly. Private evidence (raw documents, transcripts, and recordings) is never linked.
      </p>
      <DirectLinksBody repoUrl={repoUrl} liveLinks={liveLinks} repoTestId="safe-repo-link" liveTestId="safe-live-link" />
    </Card>
  )
}
