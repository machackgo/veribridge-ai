"use client"

/**
 * website-ai-analyzer-panel.tsx — Phase J4D / J4E / J4F / J4G
 * Website AI Analyzer with optional GitHub repo, functional verification,
 * and high-level grouped skill review.
 * Flow: form → analyzing → review (grouped) → saving → done.
 */

import { Fragment, useMemo, useState } from "react"
import type { CSSProperties } from "react"
import {
  analyzeWebsite,
  createSkillEvidence,
  generateEvidenceAccessLinks,
  type FunctionalVerificationCandidate,
  type FunctionalTestPlan,
  type GroupedWebsiteSkill,
  type WebsiteAnalysisCandidate,
  type WebsiteAnalyzeResponse,
  type WebsiteEvidenceSource,
} from "@/lib/api"
import {
  appendWorkLogEntry,
  completeStep,
  failStep,
  initialProgress,
  makeStep,
  startStep,
  updateStep,
  type ProofProcessingProgress,
} from "@/lib/proof-processing"
import { ProofProcessingProgressPanel } from "./proof-processing-progress-panel"

// ── Step presets ──────────────────────────────────────────────────────────────

function createWebsiteAnalyzeProgressSteps(hasRepo: boolean) {
  return [
    makeStep("connect",  "Reading website URL",          "Connecting to the public URL.",                             "Reading your website URL..."),
    makeStep("fetch",    "Fetching website content",      "Downloading page content, metadata, and API spec.",         "Fetching website content and metadata..."),
    makeStep("routes",   "Checking API routes",           "Inspecting /docs, /openapi.json, /health.",                 "Checking /docs, /openapi.json, and /health..."),
    ...(hasRepo ? [makeStep("repo", "Scanning GitHub repo", "Fetching file tree and scanning code files.", "Scanning connected GitHub repository...")] : []),
    makeStep("verify",   "Running functional tests",      "Safely calling inference endpoints to verify live output.", "Testing safe API endpoints with example data..."),
    makeStep("extract",  "Extracting evidence",           "Mapping all evidence to skill categories.",                  hasRepo ? "Merging website, repo, and functional evidence..." : "Extracting skill evidence..."),
    makeStep("group",    "Grouping into skill cards",     "Organizing evidence into high-level skill groups.",          "Building grouped skill review..."),
    makeStep("prepare",  "Preparing review screen",       "Rendering skill system graphs and evidence cards.",          "Preparing your grouped review screen..."),
  ]
}

function createWebsiteSaveProgressSteps() {
  return [
    makeStep("prepare",  "Preparing evidence",         "Reading selected candidates.",          "Preparing selected evidence..."),
    makeStep("save",     "Saving proof",               "Creating evidence records.",            "Saving proof..."),
    makeStep("links",    "Generating access links",    "Creating recruiter-accessible links.",  "Generating access links..."),
    makeStep("refresh",  "Updating Skill Proof Center","Reloading saved evidence.",             "Updating your Skill Proof Center..."),
    makeStep("complete", "Complete",                   "All done.",                             "Done."),
  ]
}

// ── Badge / style helpers ─────────────────────────────────────────────────────

const badgeBase: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
  textTransform: "uppercase", padding: "3px 8px", borderRadius: 999,
  display: "inline-block",
}

function confidenceStyle(c: string): CSSProperties {
  if (c === "high")   return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (c === "medium") return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
}

function sourceBadgeStyle(src: WebsiteEvidenceSource): CSSProperties {
  if (src === "combined")    return { background: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe" }
  if (src === "functional")  return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (src === "github_repo") return { background: "#f1f5f9", color: "#1e293b", border: "1px solid #e2e8f0" }
  return                            { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }
}

function sourceLabel(src: WebsiteEvidenceSource): string {
  if (src === "combined")    return "Combined"
  if (src === "functional")  return "Verified Workflow"
  if (src === "github_repo") return "GitHub"
  return "Website"
}

const inp: CSSProperties = {
  width: "100%", border: "1px solid var(--line)", borderRadius: 10,
  background: "#fff", color: "var(--ink)", padding: "9px 12px",
  fontSize: 13, outline: "none", boxSizing: "border-box",
}

// ── Validation helpers ────────────────────────────────────────────────────────

function isPublicHttpUrl(v: string): boolean {
  const t = v.trim()
  return t.startsWith("http://") || t.startsWith("https://")
}

function parseGitHubRepoUrl(url: string): { owner: string; repo: string } | null {
  const m = url.trim().match(/^(?:https?:\/\/)?github\.com\/([a-zA-Z0-9_-]+)\/([a-zA-Z0-9_.\-]+?)\/?$/)
  return m ? { owner: m[1], repo: m[2].replace(/\.git$/, "") } : null
}

// ── System graph component ────────────────────────────────────────────────────

function SystemGraph({ nodes }: { nodes: string[] }) {
  return (
    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 6, padding: "8px 0" }}>
      {nodes.map((node, i) => (
        <span key={`sgn-${i}`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            background: "#f8fafc", border: "1px solid #cbd5e1", borderRadius: 8,
            padding: "4px 10px", fontSize: 11, fontWeight: 600, color: "#334155",
            whiteSpace: "nowrap",
          }}>
            {node}
          </span>
          {i < nodes.length - 1 && (
            <span style={{ color: "#94a3b8", fontSize: 13, fontWeight: 700 }}>→</span>
          )}
        </span>
      ))}
    </div>
  )
}

// ── Functional verification row ───────────────────────────────────────────────

function FunctionalRow({ fc }: { fc: FunctionalVerificationCandidate }) {
  const [showRaw, setShowRaw] = useState(false)
  const {
    verified, status_code, evidence_title, verification_message,
    response_fields_found, method, endpoint_url,
    verification_label, test_input_source, is_user_guided,
    request_body_summary, what_to_test, expected_output_description,
    response_preview, response_summary, raw_response_json, response_truncated,
  } = fc

  const bg     = verified ? "#f0fdf4" : status_code && status_code < 500 ? "#fef9c3" : "#fff7ed"
  const border = verified ? "#bbf7d0" : status_code && status_code < 500 ? "#fef08a" : "#fed7aa"

  const resultBadge = verified
    ? { label: "API ENDPOINT VERIFIED", bg: "#dcfce7", color: "#166534", border: "#bbf7d0" }
    : status_code
    ? { label: `HTTP ${status_code}`, bg: "#fef9c3", color: "#854d0e", border: "#fef08a" }
    : { label: "VERIFICATION UNAVAILABLE", bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" }

  const typeBadge = is_user_guided
    ? { label: verification_label || "User-guided API test", bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" }
    : { label: verification_label || "Auto-detected API test", bg: "#f8fafc", color: "#475569", border: "#cbd5e1" }

  const inputSourceNote = test_input_source === "user_provided"
    ? "Test input provided by user"
    : "Test input auto-generated from OpenAPI schema / default values"

  // Format a preview value for display
  function formatVal(v: unknown): string {
    if (v === null || v === undefined) return "—"
    if (typeof v === "object") return JSON.stringify(v).slice(0, 80)
    const s = String(v)
    return s.length > 80 ? s.slice(0, 80) + "…" : s
  }

  const hasPreview = response_preview && Object.keys(response_preview).length > 0

  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 8, padding: "11px 13px", marginBottom: 6 }}>

      {/* Type + result + endpoint badges */}
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 7 }}>
        <span style={{ ...badgeBase, fontSize: 9, background: typeBadge.bg, color: typeBadge.color, border: `1px solid ${typeBadge.border}` }}>
          {typeBadge.label}
        </span>
        <span style={{ ...badgeBase, fontSize: 9, background: resultBadge.bg, color: resultBadge.color, border: `1px solid ${resultBadge.border}` }}>
          {resultBadge.label}
        </span>
        <span style={{ ...badgeBase, fontSize: 9, background: "#f8fafc", color: "#64748b", border: "1px solid #e2e8f0", fontFamily: "monospace" }}>
          {method} {(() => { try { return new URL(endpoint_url).pathname } catch { return endpoint_url } })()}
        </span>
        {status_code && (
          <span style={{ ...badgeBase, fontSize: 9, background: "#f8fafc", color: "#64748b", border: "1px solid #e2e8f0" }}>
            HTTP {status_code}
          </span>
        )}
      </div>

      {/* Title */}
      <div style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)", marginBottom: 5 }}>{evidence_title}</div>

      {/* What to test */}
      {what_to_test && (
        <div style={{ fontSize: 11, color: "var(--ink-2)", marginBottom: 4 }}>
          <strong>What to test:</strong> {what_to_test}
        </div>
      )}

      {/* Test input */}
      {request_body_summary && (
        <div style={{ fontSize: 11, color: "var(--ink-2)", marginBottom: 3 }}>
          <strong>Test input:</strong>{" "}
          <span style={{ fontFamily: "monospace", wordBreak: "break-all" }}>{request_body_summary}</span>
        </div>
      )}
      <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 5, fontStyle: "italic" }}>
        {inputSourceNote}
      </div>

      {/* Expected output */}
      {expected_output_description && (
        <div style={{ fontSize: 11, color: "var(--ink-2)", marginBottom: 5 }}>
          <strong>Expected output:</strong> {expected_output_description}
        </div>
      )}

      {/* ── Actual output returned ── */}
      {verified && (
        <div style={{ borderTop: "1px solid rgba(0,0,0,0.08)", paddingTop: 8, marginTop: 5 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#166534", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 5 }}>
            Actual output returned
          </div>

          {hasPreview ? (
            <>
              {/* Key-value preview table */}
              <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 12px", marginBottom: 6 }}>
                {Object.entries(response_preview!).slice(0, 10).map(([k, v]) => (
                  <Fragment key={`preview-${k}`}>
                    <span style={{ fontSize: 11, color: "#475569", fontFamily: "monospace", whiteSpace: "nowrap" }}>{k}:</span>
                    <span style={{ fontSize: 11, color: "#166534", fontWeight: 600, wordBreak: "break-all" }}>{formatVal(v)}</span>
                  </Fragment>
                ))}
              </div>
              {response_summary && (
                <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 5 }}>
                  Summary: {response_summary}
                </div>
              )}
            </>
          ) : response_fields_found.length > 0 ? (
            <div style={{ fontSize: 11, color: "#475569", marginBottom: 5 }}>
              Output values were not captured, but expected response fields were detected:{" "}
              <span style={{ fontFamily: "monospace" }}>{response_fields_found.slice(0, 10).join(", ")}</span>
            </div>
          ) : (
            <div style={{ fontSize: 11, color: "#475569", marginBottom: 5 }}>
              Output values were not captured, but the endpoint returned HTTP 200.
            </div>
          )}

          {/* Raw response accordion */}
          {raw_response_json && (
            <div style={{ marginTop: 4 }}>
              <button
                type="button"
                onClick={() => setShowRaw((v) => !v)}
                style={{ fontSize: 10, color: "var(--indigo)", fontWeight: 600, background: "none", border: "none", cursor: "pointer", padding: 0, textDecoration: "underline" }}
              >
                {showRaw ? "Hide raw response" : "Show raw response"}
              </button>
              {showRaw && (
                <div style={{ marginTop: 5 }}>
                  <pre style={{
                    fontSize: 10, fontFamily: "monospace", background: "#f8fafc",
                    border: "1px solid #e2e8f0", borderRadius: 6, padding: 8,
                    overflowX: "auto", maxHeight: 220, overflowY: "auto",
                    whiteSpace: "pre-wrap", wordBreak: "break-all", color: "#334155", margin: 0,
                  }}>
                    {raw_response_json}
                  </pre>
                  {response_truncated && (
                    <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 3, fontStyle: "italic" }}>
                      Raw response truncated for readability.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Non-verified: show fields detected */}
      {!verified && response_fields_found.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--ink-2)", marginBottom: 4 }}>
          <strong>Response fields found:</strong>{" "}
          <span style={{ fontFamily: "monospace" }}>{response_fields_found.slice(0, 10).join(", ")}</span>
        </div>
      )}

      {/* Scope + browser disclaimer */}
      <div style={{ fontSize: 10, color: "#64748b", marginTop: 6 }}>
        {verified ? "✓ Verifies: API endpoint responded with expected output" : "⚠ API endpoint could not be fully verified"}
        {" · "}
        <span style={{ color: "#6366f1", fontStyle: "italic" }}>Browser UI workflow verification — coming soon</span>
      </div>

      <div style={{ marginTop: 6 }}>
        <a href={endpoint_url} target="_blank" rel="noopener noreferrer"
          style={{ fontSize: 10, color: "var(--indigo)", fontWeight: 600, textDecoration: "none" }}>
          Open endpoint →
        </a>
      </div>
    </div>
  )
}

// ── Atomic evidence row ───────────────────────────────────────────────────────

function AtomicRow({ c }: { c: WebsiteAnalysisCandidate }) {
  return (
    <div style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid #f1f5f9", background: "#fafafa", marginBottom: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>{c.evidence_title}</div>
          <div style={{ fontSize: 11, color: "var(--ink-2)", marginTop: 2, lineHeight: 1.4 }}>
            {c.evidence_summary.slice(0, 140)}{c.evidence_summary.length > 140 ? "…" : ""}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 3, fontFamily: "monospace" }}>
            {c.route_path}
          </div>
        </div>
        <a href={c.source_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "var(--indigo)", fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap", flexShrink: 0 }}>
          {c.action_label} →
        </a>
      </div>
    </div>
  )
}

// ── Grouped skill card ────────────────────────────────────────────────────────

function GroupedSkillCard({
  group,
  isSelected,
  onToggle,
  atomicById,
  functionalById,
}: {
  group: GroupedWebsiteSkill
  isSelected: boolean
  onToggle: () => void
  atomicById: Map<string, WebsiteAnalysisCandidate>
  functionalById: Map<string, FunctionalVerificationCandidate>
}) {
  const [expanded, setExpanded] = useState(false)

  const allAtomicInGroup = group.candidate_ids
    .filter((id) => atomicById.has(id))
    .map((id) => atomicById.get(id)!)

  const websiteItems = allAtomicInGroup.filter((c) => c.evidence_source === "website")
  const repoItems    = allAtomicInGroup.filter((c) => c.evidence_source === "github_repo")
  const combinedItems = allAtomicInGroup.filter((c) => c.evidence_source === "combined")
  const functionalItems = group.functional_candidate_ids
    .filter((id) => functionalById.has(id))
    .map((id) => functionalById.get(id)!)

  const hasFunctionalPassed = functionalItems.some((fc) => fc.verified)
  const isPartial = group.is_partial
  const border = isSelected ? "#6366f1" : hasFunctionalPassed ? "#bbf7d0" : isPartial ? "#fcd34d" : "var(--line)"
  const bgHeader = isSelected ? "#f5f3ff" : "#fff"

  return (
    <div style={{
      border: `1px solid ${border}`,
      borderRadius: 14,
      overflow: "hidden",
      transition: "border-color 0.15s",
    }}>
      {/* ── Card header ── */}
      <div style={{
        display: "grid", gridTemplateColumns: "auto 1fr auto",
        gap: 12, padding: "14px 16px", background: bgHeader,
        cursor: "pointer",
      }} onClick={onToggle}>
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          style={{ marginTop: 3, width: 15, height: 15, cursor: "pointer", flexShrink: 0 }}
        />

        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)" }}>{group.skill_name}</div>

          {/* Source badges */}
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 5 }}>
            {group.sources.map((src) => (
              <span key={src} style={{ ...badgeBase, ...sourceBadgeStyle(src), fontSize: 9 }}>
                {sourceLabel(src)}
              </span>
            ))}
            <span style={{ ...badgeBase, ...confidenceStyle(group.confidence), fontSize: 9 }}>
              {group.confidence}
            </span>
            {hasFunctionalPassed && (
              <span style={{ ...badgeBase, fontSize: 9, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                Live Test Passed
              </span>
            )}
            {isPartial && (
              <span style={{ ...badgeBase, fontSize: 9, background: "#fef9c3", color: "#92400e", border: "1px solid #fcd34d" }}>
                Partial Evidence
              </span>
            )}
            {group.inferred_cloud_platform && (
              <span style={{ ...badgeBase, fontSize: 9, background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
                {group.inferred_cloud_platform} (inferred)
              </span>
            )}
          </div>

          {/* Subskill chips */}
          {group.subskills.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 7 }}>
              {group.subskills.slice(0, 6).map((sk) => (
                <span key={sk} style={{
                  fontSize: 10, background: "#f1f5f9", color: "#475569",
                  border: "1px solid #e2e8f0", borderRadius: 999, padding: "2px 8px",
                }}>
                  {sk}
                </span>
              ))}
              {group.subskills.length > 6 && (
                <span style={{ fontSize: 10, color: "var(--muted)", padding: "2px 4px" }}>
                  +{group.subskills.length - 6} more
                </span>
              )}
            </div>
          )}

          {/* Evidence count summary */}
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6, display: "flex", gap: 10 }}>
            {group.website_count > 0 && <span>{group.website_count} website</span>}
            {group.repo_count > 0 && <span>{group.repo_count} GitHub</span>}
            {group.combined_count > 0 && <span style={{ color: "#5b21b6" }}>{group.combined_count} combined</span>}
            {group.functional_count > 0 && <span style={{ color: "#166534" }}>{group.functional_count} functional</span>}
          </div>
        </div>

        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v) }}
          style={{
            border: "1px solid var(--line-2)", background: "transparent",
            color: "var(--ink-2)", borderRadius: 8, padding: "5px 10px",
            fontWeight: 600, fontSize: 11, cursor: "pointer", alignSelf: "flex-start", whiteSpace: "nowrap",
          }}
        >
          {expanded ? "Collapse ↑" : "Expand ↓"}
        </button>
      </div>

      {/* ── Expanded content ── */}
      {expanded && (
        <div style={{ borderTop: "1px solid #f1f5f9", padding: "14px 16px", background: "#fafafa" }}>

          {/* System graph */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--muted)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
              Skill System Graph
            </div>
            <SystemGraph nodes={group.system_graph_nodes} />
          </div>

          {/* Cloud platform inferred signal (AI Product Deployment / Cloud Deployment) */}
          {group.inferred_cloud_platform && (
            <div style={{
              background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 10,
              padding: "11px 13px", marginBottom: 14,
            }}>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 7 }}>
                <span style={{ ...badgeBase, fontSize: 9, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                  GCP Cloud Run inferred
                </span>
                <span style={{ ...badgeBase, fontSize: 9, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }}>
                  Needs supporting docs for full proof
                </span>
              </div>

              {/* Deployment pipeline visualization */}
              <div style={{ fontSize: 10, fontWeight: 700, color: "#166534", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>
                Detected deployment pipeline
              </div>
              <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 5, marginBottom: 8 }}>
                {(["Live URL", "API docs / OpenAPI", "Functional endpoint response"] as const).map((node, i, arr) => (
                  <span key={`dp-${i}`} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <span style={{ fontSize: 11, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0", borderRadius: 7, padding: "3px 9px", fontWeight: 600 }}>
                      {node}
                    </span>
                    {i < arr.length - 1 && <span style={{ color: "#94a3b8", fontWeight: 700 }}>→</span>}
                  </span>
                ))}
              </div>

              <div style={{ fontSize: 11, color: "#166534", lineHeight: 1.5 }}>
                <strong>{group.inferred_cloud_platform}</strong> inferred from the public URL domain (<code style={{ fontSize: 10 }}>run.app</code>).
                The live URL confirms a cloud-hosted API with publicly accessible endpoints.
              </div>
              <div style={{ fontSize: 10, color: "#166534", marginTop: 5, fontStyle: "italic" }}>
                Add Cloud Run service YAML, deployment screenshots, or architecture docs for verified GCP deployment proof.
              </div>
            </div>
          )}

          {/* Partial proof honesty box */}
          {isPartial && group.partial_proof_message && (
            <div style={{
              background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 10,
              padding: "12px 14px", marginBottom: 14,
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Partial Pipeline Evidence
              </div>
              <div style={{ fontSize: 12, color: "#78350f", lineHeight: 1.6, marginBottom: group.missing_proof_suggestions.length > 0 ? 10 : 0 }}>
                {group.partial_proof_message}
              </div>
              {group.missing_proof_suggestions.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 4 }}>
                    To strengthen this skill:
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
                    {group.missing_proof_suggestions.map((s, i) => {
                      const isComingSoon = s.startsWith("📄")
                      return (
                        <li key={`ms-${i}`} style={{
                          fontSize: 11,
                          color: isComingSoon ? "#6366f1" : "#78350f",
                          fontStyle: isComingSoon ? "italic" : "normal",
                          listStyle: isComingSoon ? "none" : "disc",
                          marginLeft: isComingSoon ? -16 : 0,
                        }}>
                          {s}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Functional verification */}
          {functionalItems.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#166534", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                Functional Verification
              </div>
              {functionalItems.map((fc) => (
                <FunctionalRow key={fc.candidate_id} fc={fc} />
              ))}
            </div>
          )}

          {/* Combined evidence */}
          {combinedItems.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#5b21b6", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                Combined Evidence (Website + GitHub)
              </div>
              {combinedItems.map((c) => <AtomicRow key={c.candidate_id} c={c} />)}
            </div>
          )}

          {/* Website evidence */}
          {websiteItems.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#1d4ed8", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                Website Evidence
              </div>
              {websiteItems.map((c) => <AtomicRow key={c.candidate_id} c={c} />)}
            </div>
          )}

          {/* GitHub evidence */}
          {repoItems.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#1e293b", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                GitHub Evidence
              </div>
              {repoItems.map((c) => <AtomicRow key={c.candidate_id} c={c} />)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

type PanelStep = "form" | "analyzing" | "review" | "saving" | "done"

type FunctionalTestPlanState = {
  whatToTest: string
  testInput: string
  expectedOutput: string
  testMode: "auto" | "api_endpoint" | "plan_only"
}

export function WebsiteAIAnalyzerPanel({
  url,
  onUrlChange,
  skillFocus,
  onSkillFocusChange,
  githubRepoUrl,
  onGithubRepoUrlChange,
  functionalTestPlan,
  onFunctionalTestPlanChange,
  onSaveComplete,
  onBack,
}: {
  url: string
  onUrlChange: (v: string) => void
  skillFocus: string
  onSkillFocusChange: (v: string) => void
  githubRepoUrl: string
  onGithubRepoUrlChange: (v: string) => void
  functionalTestPlan: FunctionalTestPlanState
  onFunctionalTestPlanChange: (plan: FunctionalTestPlanState) => void
  onSaveComplete?: () => void
  onBack: () => void
}) {
  const [showTestPlan, setShowTestPlan] = useState(false)
  const [panelStep, setPanelStep] = useState<PanelStep>("form")
  const [analyzeResult, setAnalyzeResult] = useState<WebsiteAnalyzeResponse | null>(null)
  const [selectedGroupIds, setSelectedGroupIds] = useState<Set<string>>(new Set())
  const [showAtomicAccordion, setShowAtomicAccordion] = useState(false)
  const [analyzeProgress, setAnalyzeProgress] = useState<ProofProcessingProgress | null>(null)
  const [saveProgress, setSaveProgress] = useState<ProofProcessingProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

  // Quick-lookup maps by candidate_id
  const atomicById = useMemo(
    () => new Map((analyzeResult?.candidates ?? []).map((c) => [c.candidate_id, c])),
    [analyzeResult]
  )
  const functionalById = useMemo(
    () => new Map((analyzeResult?.functional_candidates ?? []).map((c) => [c.candidate_id, c])),
    [analyzeResult]
  )

  function toggleGroup(groupId: string) {
    setSelectedGroupIds((prev) => {
      const next = new Set(prev)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
  }

  // Total unique candidate IDs across selected groups
  const totalSelectedCandidateIds = useMemo(() => {
    const ids = new Set<string>()
    for (const gid of selectedGroupIds) {
      const group = analyzeResult?.grouped_skills.find((g) => g.group_id === gid)
      if (group) group.candidate_ids.forEach((id) => ids.add(id))
    }
    return ids
  }, [selectedGroupIds, analyzeResult])

  // ── Analyze ────────────────────────────────────────────────────────────────

  async function handleAnalyze() {
    setError(null)
    const trimmedUrl = url.trim()
    if (!trimmedUrl) { setError("Website URL is required."); return }
    if (!isPublicHttpUrl(trimmedUrl)) {
      setError("Enter a valid public http/https URL (e.g. https://your-app.run.app)."); return
    }
    const trimmedRepo = githubRepoUrl.trim()
    if (trimmedRepo && !parseGitHubRepoUrl(trimmedRepo)) {
      setError("GitHub repo URL must be: https://github.com/owner/repo"); return
    }

    const hasRepo = Boolean(trimmedRepo)
    let steps = createWebsiteAnalyzeProgressSteps(hasRepo)
    steps = completeStep(steps, "connect", { agentCopy: `Connecting to ${trimmedUrl}...` })
    steps = startStep(steps, "fetch")

    let prog = initialProgress(steps)
    prog = appendWorkLogEntry(prog, `Reading ${trimmedUrl}...`)
    if (hasRepo) prog = appendWorkLogEntry(prog, `Connected GitHub repo: ${trimmedRepo}`)
    setAnalyzeProgress({ ...prog })
    setPanelStep("analyzing")

    // Staged work log messages timed to approximate server phases
    const staged = [
      { ms: 0,    msg: "Downloading homepage content and metadata..." },
      { ms: 2000, msg: "Checking /docs for FastAPI/Swagger documentation..." },
      { ms: 4000, msg: "Checking /openapi.json for API specification..." },
      { ms: 6000, msg: "Checking /health endpoint..." },
      ...(hasRepo ? [
        { ms: 8000,  msg: "Fetching connected GitHub repository file tree..." },
        { ms: 12000, msg: "Scanning code files (Dockerfile, API routes, ML models, cloud config)..." },
        { ms: 18000, msg: "Merging website and GitHub repo evidence..." },
      ] : []),
      { ms: hasRepo ? 22000 : 8000,  msg: "Parsing OpenAPI spec to find safe testable endpoints..." },
      { ms: hasRepo ? 25000 : 11000, msg: "Preparing safe test request for /predict endpoint..." },
      { ms: hasRepo ? 27000 : 13000, msg: "Calling /predict with example data (safe inference test)..." },
      { ms: hasRepo ? 29000 : 15000, msg: "Verifying response — checking status code and expected fields..." },
      { ms: hasRepo ? 31000 : 17000, msg: "Grouping evidence into high-level skill categories..." },
      { ms: hasRepo ? 33000 : 19000, msg: "Building skill system graphs for each group..." },
      { ms: hasRepo ? 35000 : 21000, msg: "Preparing grouped review screen..." },
    ]

    const maxTime = hasRepo ? 50_000 : 35_000
    const t0 = Date.now()
    let si = 0
    const interval = setInterval(() => {
      const elapsed = Date.now() - t0
      let changed = false
      while (si < staged.length && elapsed >= staged[si].ms) {
        prog = appendWorkLogEntry(prog, staged[si].msg)
        si++
        changed = true
      }
      const pct = Math.min(78, 15 + ((elapsed / maxTime) * 63))
      prog = { ...prog, syntheticPercent: Math.round(pct) }
      if (changed) setAnalyzeProgress({ ...prog })
      else setAnalyzeProgress((p) => p ? { ...p, syntheticPercent: Math.round(pct) } : p)
    }, 500)

    try {
      const hasTestPlan = !!(
        functionalTestPlan.whatToTest.trim() ||
        functionalTestPlan.testInput.trim() ||
        functionalTestPlan.expectedOutput.trim()
      )
      const testPlanPayload: FunctionalTestPlan | null = hasTestPlan || functionalTestPlan.testMode !== "auto"
        ? {
            what_to_test: functionalTestPlan.whatToTest.trim() || null,
            test_input: functionalTestPlan.testInput.trim() || null,
            expected_output: functionalTestPlan.expectedOutput.trim() || null,
            test_mode: functionalTestPlan.testMode,
          }
        : null

      const result = await analyzeWebsite({
        url: trimmedUrl,
        skill_focus: skillFocus.trim() || null,
        github_repo_url: trimmedRepo || null,
        run_safe_tests: true,
        functional_test_plan: testPlanPayload,
      })
      clearInterval(interval)

      // Complete all analysis steps
      steps = completeStep(steps, "fetch")
      steps = completeStep(steps, "routes", {
        description: `Checked: ${result.checked_urls.map((u) => { try { return new URL(u).pathname || "/" } catch { return u } }).join(", ")}`,
      })
      if (hasRepo) {
        steps = completeStep(steps, "repo", {
          description: result.repo_candidate_count > 0
            ? `Found ${result.repo_candidate_count} GitHub evidence item${result.repo_candidate_count !== 1 ? "s" : ""}.`
            : "Repo scanned — see warnings if any.",
        })
      }
      steps = completeStep(steps, "verify", {
        description: result.functional_verification_available
          ? `${result.functional_candidate_count} functional verification result${result.functional_candidate_count !== 1 ? "s" : ""}.`
          : "Functional verification completed — see warnings.",
      })
      steps = completeStep(steps, "extract", {
        description: `Found ${result.candidate_count} evidence item${result.candidate_count !== 1 ? "s" : ""}.`,
        agentCopy: `Found ${result.candidate_count} evidence item${result.candidate_count !== 1 ? "s" : ""}.`,
      })
      steps = completeStep(steps, "group", {
        description: `Grouped into ${result.grouped_skills.length} high-level skill${result.grouped_skills.length !== 1 ? "s" : ""}.`,
        agentCopy: `${result.grouped_skills.length} grouped skill${result.grouped_skills.length !== 1 ? "s" : ""} ready for review.`,
      })
      steps = completeStep(steps, "prepare")

      let finalMsg = `Analysis complete — ${result.grouped_skills.length} grouped skill${result.grouped_skills.length !== 1 ? "s" : ""}, ${result.candidate_count} evidence item${result.candidate_count !== 1 ? "s" : ""}.`
      if (result.functional_verification_available) {
        const passed = result.functional_candidates.filter((fc) => fc.verified).length
        finalMsg += passed > 0
          ? ` ${passed} functional test${passed !== 1 ? "s" : ""} passed.`
          : ` Functional verification completed.`
      }
      if (result.combined_candidate_count > 0) {
        finalMsg += ` ${result.combined_candidate_count} skill${result.combined_candidate_count !== 1 ? "s" : ""} have combined website + GitHub evidence.`
      }
      prog = appendWorkLogEntry(prog, finalMsg, "completed")
      for (const w of result.warnings) {
        prog = appendWorkLogEntry(prog, w, "warning")
      }

      setAnalyzeProgress({
        ...prog, steps, overallStatus: "completed",
        savedCount: result.candidate_count, syntheticPercent: undefined,
      })
      setAnalyzeResult(result)

      // Auto-select all groups with suggested status
      const autoSelect = new Set(
        result.grouped_skills.filter((g) => g.suggested_status === "suggested").map((g) => g.group_id)
      )
      setSelectedGroupIds(autoSelect)
      setPanelStep("review")
    } catch (err) {
      clearInterval(interval)
      const msg = err instanceof Error ? err.message : "Analysis failed."
      steps = failStep(steps, "fetch", msg)
      prog = appendWorkLogEntry(prog, msg, "error")
      setAnalyzeProgress({ ...prog, steps, overallStatus: "failed", errorMessages: [msg], syntheticPercent: undefined })
      setError(msg)
      setPanelStep("form")
    }
  }

  // ── Save ────────────────────────────────────────────────────────────────────

  async function handleSave() {
    if (selectedGroupIds.size === 0) {
      setError("Select at least one skill group to save."); return
    }
    setError(null)

    // Collect all unique candidates from selected groups
    const seenIds = new Set<string>()
    const atomicToSave: WebsiteAnalysisCandidate[] = []
    const functionalToSave: FunctionalVerificationCandidate[] = []

    for (const gid of selectedGroupIds) {
      const group = analyzeResult?.grouped_skills.find((g) => g.group_id === gid)
      if (!group) continue
      for (const cid of group.candidate_ids) {
        if (seenIds.has(cid)) continue
        seenIds.add(cid)
        const atomic = atomicById.get(cid)
        if (atomic) { atomicToSave.push(atomic); continue }
        const functional = functionalById.get(cid)
        if (functional) functionalToSave.push(functional)
      }
    }

    const total = atomicToSave.length + functionalToSave.length
    if (total === 0) { setError("No evidence items found in selected groups."); return }

    let steps = createWebsiteSaveProgressSteps()
    steps = completeStep(steps, "prepare", {
      description: `${selectedGroupIds.size} group${selectedGroupIds.size !== 1 ? "s" : ""} selected — ${total} evidence item${total !== 1 ? "s" : ""}.`
    })
    steps = startStep(steps, "save")

    let prog = initialProgress(steps)
    prog = appendWorkLogEntry(prog, `Preparing ${total} evidence item${total !== 1 ? "s" : ""} from ${selectedGroupIds.size} skill group${selectedGroupIds.size !== 1 ? "s" : ""}...`)
    setSaveProgress({ ...prog })
    setPanelStep("saving")

    let savedCount = 0, failedCount = 0
    const errMessages: string[] = []
    let itemIndex = 0

    // Save atomic candidates
    for (const candidate of atomicToSave) {
      itemIndex++
      const label = `${candidate.skill_name} — ${sourceLabel(candidate.evidence_source)}`
      steps = updateStep(steps, "save", {
        countCurrent: itemIndex, countTotal: total,
        agentCopy: `Saving ${label} (${itemIndex} of ${total})...`,
      })
      prog = appendWorkLogEntry(
        { ...prog, steps, syntheticPercent: Math.round(10 + (itemIndex / total) * 60) },
        `Saving ${itemIndex} of ${total} — ${label}`
      )
      setSaveProgress({ ...prog })
      await tick()

      try {
        const evidenceType = candidate.evidence_source === "github_repo" ? "github repository" : "deployed_website"
        const ev = await createSkillEvidence({
          skill_name: candidate.skill_name,
          evidence_type: evidenceType,
          evidence_url: candidate.source_url,
          evidence_description: candidate.evidence_summary,
          proof_visibility: "public",
          metadata: {
            evidence_title: candidate.evidence_title,
            submission_source: "website_ai_analyzer",
            proof_kind: "website_ai_analysis",
            skill_category: candidate.skill_category,
            route_path: candidate.route_path,
            evidence_type_detail: candidate.evidence_type,
            action_label: candidate.action_label,
            evidence_snippet: candidate.evidence_snippet,
            evidence_source: candidate.evidence_source,
            is_combined: candidate.is_combined,
            related_source_url: candidate.related_source_url ?? null,
            base_url: analyzeResult?.base_url ?? candidate.source_url,
            github_repo_url: analyzeResult?.github_repo_url ?? null,
          },
        })
        try { await generateEvidenceAccessLinks(ev.id) } catch { /* best-effort */ }
        savedCount++
        prog = appendWorkLogEntry({ ...prog, steps }, `Saved — ${label}`, "completed")
      } catch (err) {
        failedCount++
        const msg = err instanceof Error ? err.message : "Unknown error"
        errMessages.push(`${label}: ${msg}`)
        prog = appendWorkLogEntry({ ...prog, steps }, `Failed — ${label}`, "error")
      }
      setSaveProgress({ ...prog })
    }

    // Save functional verification candidates
    for (const fc of functionalToSave) {
      itemIndex++
      const label = `${fc.skill_name} — Functional Verification`
      steps = updateStep(steps, "save", {
        countCurrent: itemIndex, countTotal: total,
        agentCopy: `Saving ${label} (${itemIndex} of ${total})...`,
      })
      prog = appendWorkLogEntry(
        { ...prog, steps, syntheticPercent: Math.round(10 + (itemIndex / total) * 60) },
        `Saving ${itemIndex} of ${total} — ${label}`
      )
      setSaveProgress({ ...prog })
      await tick()

      try {
        const ev = await createSkillEvidence({
          skill_name: fc.skill_name,
          evidence_type: "deployed_website",
          evidence_url: fc.endpoint_url,
          evidence_description: fc.verification_message,
          proof_visibility: "public",
          metadata: {
            evidence_title: fc.evidence_title,
            submission_source: "website_ai_analyzer_functional",
            proof_kind: "functional_verification",
            skill_category: fc.skill_category,
            endpoint_url: fc.endpoint_url,
            method: fc.method,
            request_summary: fc.request_summary,
            request_body_summary: fc.request_body_summary,
            response_fields_found: fc.response_fields_found,
            response_preview: fc.response_preview ?? null,
            response_summary: fc.response_summary ?? null,
            status_code: fc.status_code,
            verified: fc.verified,
            verification_label: fc.verification_label,
            is_user_guided: fc.is_user_guided,
            test_input_source: fc.test_input_source,
            what_to_test: fc.what_to_test ?? null,
            expected_output_description: fc.expected_output_description ?? null,
            verification_badge: fc.verified ? "Live Test Passed" : "Endpoint Detected",
            base_url: analyzeResult?.base_url ?? fc.endpoint_url,
            github_repo_url: analyzeResult?.github_repo_url ?? null,
          },
        })
        try { await generateEvidenceAccessLinks(ev.id) } catch { /* best-effort */ }
        savedCount++
        prog = appendWorkLogEntry({ ...prog, steps }, `Saved — ${label}`, "completed")
      } catch (err) {
        failedCount++
        const msg = err instanceof Error ? err.message : "Unknown error"
        errMessages.push(`${label}: ${msg}`)
        prog = appendWorkLogEntry({ ...prog, steps }, `Failed — ${label}`, "error")
      }
      setSaveProgress({ ...prog })
    }

    const finalMsg = `Done — saved ${savedCount} · failed ${failedCount}`
    steps = completeStep(steps, "save", { description: `Saved ${savedCount} · Failed ${failedCount}`, agentCopy: `Saved ${savedCount} evidence item${savedCount !== 1 ? "s" : ""}.` })
    steps = completeStep(steps, "links")
    prog = appendWorkLogEntry({ ...prog, steps }, "Updating your Skill Proof Center...")
    onSaveComplete?.()
    steps = completeStep(steps, "refresh")
    steps = completeStep(steps, "complete", { description: finalMsg, agentCopy: finalMsg })
    prog = appendWorkLogEntry({ ...prog, steps }, finalMsg, "completed")

    setSaveProgress({
      ...prog, steps,
      overallStatus: failedCount === total && savedCount === 0 ? "failed" : "completed",
      savedCount, failedCount, errorMessages: errMessages, syntheticPercent: undefined,
    })
    setPanelStep("done")
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {error && (
        <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 10, padding: "8px 12px", fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* ── Form ── */}
      {panelStep === "form" && (
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)", marginBottom: 4 }}>
              🌐 Website / Portfolio AI Analysis
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
              Enter a live URL. VeriBridge fetches the page, checks /docs and /openapi.json, runs safe functional
              tests on inference endpoints, and groups all evidence into high-level skill cards.
              Optionally connect a GitHub repo to prove backend, ML, and deployment skills behind the site.
            </div>
          </div>

          {/* Website URL — controlled by parent state so it survives remounts */}
          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>Website URL *</span>
            <input
              type="url"
              autoFocus
              autoComplete="url"
              value={url}
              onChange={(e) => onUrlChange(e.target.value)}
              onBlur={(e) => {
                // Auto-prepend https:// if the user typed a bare domain
                const v = e.target.value.trim()
                if (v && !v.startsWith("http://") && !v.startsWith("https://")) {
                  onUrlChange("https://" + v)
                }
              }}
              placeholder="https://your-app.run.app or https://your-portfolio.vercel.app"
              style={{
                ...inp,
                borderColor: url.trim() && !isPublicHttpUrl(url) ? "#fca5a5" : "var(--line)",
              }}
            />
            {url.trim() && !isPublicHttpUrl(url) ? (
              <span style={{ fontSize: 11, color: "#991b1b" }}>Enter a valid public URL starting with https:// or http://</span>
            ) : (
              <span style={{ fontSize: 11, color: "var(--muted)" }}>Only public URLs. Private or localhost URLs are not supported.</span>
            )}
          </div>

          {/* Skill focus */}
          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Skill focus <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span>
            </span>
            <input
              value={skillFocus}
              onChange={(e) => onSkillFocusChange(e.target.value)}
              placeholder="e.g. FastAPI, Machine Learning, Cloud Deployment, Computer Vision"
              style={inp}
            />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Comma-separated skills to prioritize during analysis.</span>
          </div>

          {/* Related GitHub repo */}
          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Related GitHub repository <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional but recommended)</span>
            </span>
            <input
              type="url"
              autoComplete="url"
              value={githubRepoUrl}
              onChange={(e) => onGithubRepoUrlChange(e.target.value)}
              placeholder="https://github.com/your-username/your-repo"
              style={inp}
            />
            <span style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
              Connecting the repo helps VeriBridge prove backend, ML, deployment, and MLOps skills —
              Dockerfiles, GitHub Actions, model files, API routes, README architecture.
            </span>
          </div>

          {/* Optional: Functional Test Plan */}
          <div style={{ border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
            <button
              type="button"
              onClick={() => setShowTestPlan((v) => !v)}
              style={{
                width: "100%", textAlign: "left", padding: "10px 14px", border: "none",
                background: showTestPlan ? "#f0f9ff" : "#f8fafc", cursor: "pointer",
                fontSize: 12, fontWeight: 600, color: "var(--ink-2)",
                display: "flex", justifyContent: "space-between", alignItems: "center",
              }}
            >
              <span>
                Optional: Functional Test Plan
                {(functionalTestPlan.whatToTest || functionalTestPlan.testInput) && (
                  <span style={{ marginLeft: 8, fontSize: 10, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe", borderRadius: 999, padding: "1px 6px" }}>
                    configured
                  </span>
                )}
              </span>
              <span style={{ color: "var(--muted)" }}>{showTestPlan ? "▲" : "▼"}</span>
            </button>

            {showTestPlan && (
              <div style={{ padding: "12px 14px", display: "grid", gap: 10, background: "#f0f9ff" }}>
                <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                  Guide VeriBridge on what to test and what input to use. Without this, the system auto-detects
                  safe endpoints from the OpenAPI spec and uses default test values.
                </div>

                {/* What to test */}
                <div style={{ display: "grid", gap: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)" }}>What should VeriBridge test? <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span></span>
                  <input
                    value={functionalTestPlan.whatToTest}
                    onChange={(e) => onFunctionalTestPlanChange({ ...functionalTestPlan, whatToTest: e.target.value })}
                    placeholder="e.g. Verify accident risk prediction returns a risk class and confidence score"
                    style={inp}
                  />
                </div>

                {/* Test input */}
                <div style={{ display: "grid", gap: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)" }}>Test input <span style={{ fontWeight: 400, color: "var(--muted)" }}>(JSON or key=value; pairs)</span></span>
                  <textarea
                    value={functionalTestPlan.testInput}
                    onChange={(e) => onFunctionalTestPlanChange({ ...functionalTestPlan, testInput: e.target.value })}
                    placeholder={'origin=Fenway Park, Boston, MA; destination=Boston Logan International Airport, MA; num_segments=5\n\nor: {"origin": "Fenway Park, Boston, MA", "destination": "Boston Logan International Airport, MA"}'}
                    rows={3}
                    style={{ ...inp, fontFamily: "monospace", fontSize: 11, resize: "vertical" }}
                  />
                  <span style={{ fontSize: 10, color: "var(--muted)" }}>
                    Used for POST inference endpoints (/predict, /classify, /recommend).
                    If empty, auto-generated values are used.
                  </span>
                </div>

                {/* Expected output */}
                <div style={{ display: "grid", gap: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)" }}>Expected output <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span></span>
                  <input
                    value={functionalTestPlan.expectedOutput}
                    onChange={(e) => onFunctionalTestPlanChange({ ...functionalTestPlan, expectedOutput: e.target.value })}
                    placeholder="e.g. risk class, confidence score, route recommendation, segmented risk output"
                    style={inp}
                  />
                </div>

                {/* Test mode */}
                <div style={{ display: "grid", gap: 4 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)" }}>Test mode</span>
                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                    {([
                      { value: "auto", label: "Auto-detect from OpenAPI spec", desc: "VeriBridge finds safe endpoints automatically" },
                      { value: "api_endpoint", label: "API endpoint test (use my test input)", desc: "Use the input above for API endpoint tests" },
                      { value: "plan_only", label: "Save test plan only (no live test)", desc: "Record this plan without running any tests" },
                    ] as const).map(({ value, label, desc }) => (
                      <label key={value} style={{ display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer" }}>
                        <input
                          type="radio"
                          name="test-mode"
                          value={value}
                          checked={functionalTestPlan.testMode === value}
                          onChange={() => onFunctionalTestPlanChange({ ...functionalTestPlan, testMode: value })}
                          style={{ marginTop: 2 }}
                        />
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-2)" }}>{label}</div>
                          <div style={{ fontSize: 10, color: "var(--muted)" }}>{desc}</div>
                        </div>
                      </label>
                    ))}
                    {/* Browser UI — coming soon */}
                    <label style={{ display: "flex", alignItems: "flex-start", gap: 8, opacity: 0.5, cursor: "not-allowed" }}>
                      <input type="radio" disabled style={{ marginTop: 2 }} />
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-2)" }}>
                          Browser UI verification
                          <span style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, background: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe", borderRadius: 999, padding: "1px 6px" }}>
                            coming soon
                          </span>
                        </div>
                        <div style={{ fontSize: 10, color: "var(--muted)" }}>Full Playwright-based UI workflow test</div>
                      </div>
                    </label>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <button type="button" onClick={onBack} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
              ← Back
            </button>
            <button
              type="button"
              disabled={!url.trim() || !isPublicHttpUrl(url)}
              onClick={() => void handleAnalyze()}
              style={{
                border: "none",
                background: !url.trim() || !isPublicHttpUrl(url) ? "var(--bg-2)" : "var(--ink)",
                color: !url.trim() || !isPublicHttpUrl(url) ? "var(--muted)" : "#fff",
                borderRadius: 10, padding: "10px 18px", fontWeight: 700, fontSize: 14,
                cursor: !url.trim() || !isPublicHttpUrl(url) ? "not-allowed" : "pointer",
              }}
            >
              Analyze Website with AI
            </button>
          </div>
        </div>
      )}

      {/* ── Analyzing progress ── */}
      {panelStep === "analyzing" && analyzeProgress && (
        <ProofProcessingProgressPanel title="Website AI Analysis" progress={analyzeProgress} canClose={false} />
      )}

      {/* ── Review ── */}
      {panelStep === "review" && analyzeResult && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Header */}
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)", marginBottom: 4 }}>
              Review grouped skill evidence
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.7 }}>
              Found <strong style={{ color: "var(--ink-2)" }}>{analyzeResult.grouped_skills.length}</strong> grouped skill{analyzeResult.grouped_skills.length !== 1 ? "s" : ""} from {analyzeResult.candidate_count} evidence item{analyzeResult.candidate_count !== 1 ? "s" : ""}.
              {analyzeResult.functional_verification_available && (() => {
                const passed = analyzeResult.functional_candidates.filter((fc) => fc.verified).length
                return passed > 0
                  ? <span style={{ color: "#166534", fontWeight: 600 }}> {passed} functional test{passed !== 1 ? "s" : ""} passed.</span>
                  : <span style={{ color: "var(--muted)" }}> Functional verification ran.</span>
              })()}
              {analyzeResult.combined_candidate_count > 0 && (
                <span style={{ color: "#5b21b6", fontWeight: 600 }}> {analyzeResult.combined_candidate_count} skill{analyzeResult.combined_candidate_count !== 1 ? "s" : ""} have combined website + GitHub evidence.</span>
              )}
            </div>
          </div>

          {/* Source legend */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: "var(--muted)" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ ...badgeBase, ...sourceBadgeStyle("functional"), fontSize: 9 }}>Verified Workflow</span> live endpoint tested
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ ...badgeBase, ...sourceBadgeStyle("combined"), fontSize: 9 }}>Combined</span> website + GitHub
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ ...badgeBase, ...sourceBadgeStyle("website"), fontSize: 9 }}>Website</span> website only
            </span>
            {analyzeResult.github_repo_url && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ ...badgeBase, ...sourceBadgeStyle("github_repo"), fontSize: 9 }}>GitHub</span> repo only
              </span>
            )}
          </div>

          {/* Warnings */}
          {analyzeResult.warnings.length > 0 && (
            <div style={{ background: "#fef9c3", border: "1px solid #fef08a", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#854d0e", lineHeight: 1.5 }}>
              {analyzeResult.warnings.map((w, i) => <div key={`w-${i}`}>{w}</div>)}
            </div>
          )}

          {/* No groups fallback */}
          {analyzeResult.grouped_skills.length === 0 ? (
            <div style={{ border: "1px dashed var(--line-2)", borderRadius: 12, padding: 20, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No evidence candidates found.</div>
              <div style={{ marginBottom: 12 }}>The website responded but no strong skill signals were detected automatically.</div>
              <button
                type="button"
                onClick={() => void (async () => {
                  setError(null)
                  let steps = createWebsiteSaveProgressSteps()
                  steps = completeStep(steps, "prepare")
                  steps = startStep(steps, "save")
                  let prog = initialProgress(steps)
                  prog = appendWorkLogEntry(prog, "Saving website link as manual proof...")
                  setSaveProgress({ ...prog })
                  setPanelStep("saving")
                  try {
                    const ev = await createSkillEvidence({
                      skill_name: skillFocus.trim() || "Web Development",
                      evidence_type: "deployed_website",
                      evidence_url: analyzeResult.base_url,
                      evidence_description: `Live website at ${analyzeResult.base_url}. Skill focus: ${skillFocus || "general web development"}.`,
                      proof_visibility: "public",
                      metadata: {
                        evidence_title: `Live website — ${analyzeResult.base_url}`,
                        submission_source: "website_ai_analyzer_fallback",
                        proof_kind: "website_ai_analysis",
                      },
                    })
                    try { await generateEvidenceAccessLinks(ev.id) } catch { /* best-effort */ }
                    onSaveComplete?.()
                    steps = completeStep(steps, "save")
                    steps = completeStep(steps, "links")
                    steps = completeStep(steps, "refresh")
                    steps = completeStep(steps, "complete", { description: "Website link saved as manual proof." })
                    prog = appendWorkLogEntry({ ...prog, steps }, "Website link saved as manual proof.", "completed")
                    setSaveProgress({ ...prog, steps, overallStatus: "completed", savedCount: 1 })
                    setPanelStep("done")
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Save failed.")
                    setPanelStep("review")
                  }
                })()}
                style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
              >
                Save as manual website proof
              </button>
            </div>
          ) : (
            <>
              {/* Group selection controls */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                <span style={{ fontSize: 12, color: "var(--ink-2)", fontWeight: 600 }}>
                  {selectedGroupIds.size} of {analyzeResult.grouped_skills.length} skill group{analyzeResult.grouped_skills.length !== 1 ? "s" : ""} selected
                  {totalSelectedCandidateIds.size > 0 && (
                    <span style={{ fontWeight: 400, color: "var(--muted)" }}> ({totalSelectedCandidateIds.size} evidence item{totalSelectedCandidateIds.size !== 1 ? "s" : ""})</span>
                  )}
                </span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    onClick={() => setSelectedGroupIds(new Set(analyzeResult.grouped_skills.map((g) => g.group_id)))}
                    style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 8, padding: "6px 12px", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedGroupIds(new Set())}
                    style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 8, padding: "6px 12px", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
                  >
                    Deselect all
                  </button>
                </div>
              </div>

              {/* Grouped skill cards */}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {analyzeResult.grouped_skills.map((group) => (
                  <GroupedSkillCard
                    key={group.group_id}
                    group={group}
                    isSelected={selectedGroupIds.has(group.group_id)}
                    onToggle={() => toggleGroup(group.group_id)}
                    atomicById={atomicById}
                    functionalById={functionalById}
                  />
                ))}
              </div>

              {/* Atomic evidence accordion (debug) */}
              <div style={{ border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
                <button
                  type="button"
                  onClick={() => setShowAtomicAccordion((v) => !v)}
                  style={{
                    width: "100%", textAlign: "left", padding: "10px 14px",
                    border: "none", background: "#f8fafc", cursor: "pointer",
                    fontSize: 12, fontWeight: 600, color: "var(--ink-2)",
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                  }}
                >
                  <span>Show all raw evidence ({analyzeResult.candidates.length} atomic item{analyzeResult.candidates.length !== 1 ? "s" : ""})</span>
                  <span>{showAtomicAccordion ? "↑" : "↓"}</span>
                </button>
                {showAtomicAccordion && (
                  <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6, maxHeight: 360, overflowY: "auto" }}>
                    {analyzeResult.candidates.map((c) => (
                      <div key={c.candidate_id} style={{
                        padding: "8px 10px", borderRadius: 8,
                        border: `1px solid ${c.is_combined ? "#ddd6fe" : "var(--line)"}`,
                        background: c.is_combined ? "#faf5ff" : "#fff",
                        fontSize: 12,
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                          <span style={{ fontWeight: 600, color: "var(--ink)" }}>{c.skill_name}</span>
                          <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                            <span style={{ ...badgeBase, ...sourceBadgeStyle(c.evidence_source), fontSize: 9 }}>{sourceLabel(c.evidence_source)}</span>
                            <span style={{ ...badgeBase, ...confidenceStyle(c.confidence), fontSize: 9 }}>{c.confidence}</span>
                          </div>
                        </div>
                        <div style={{ color: "var(--muted)", marginTop: 2, fontFamily: "monospace", fontSize: 10 }}>{c.route_path}</div>
                      </div>
                    ))}
                    {analyzeResult.functional_candidates.length > 0 && (
                      <>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#166534", marginTop: 6 }}>Functional verification candidates</div>
                        {analyzeResult.functional_candidates.map((fc) => (
                          <div key={fc.candidate_id} style={{
                            padding: "8px 10px", borderRadius: 8,
                            border: "1px solid #bbf7d0", background: "#f0fdf4", fontSize: 12,
                          }}>
                            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                              <span style={{ fontWeight: 600, color: "var(--ink)" }}>{fc.skill_name}</span>
                              <span style={{ ...badgeBase, fontSize: 9, background: fc.verified ? "#dcfce7" : "#fef9c3", color: fc.verified ? "#166534" : "#854d0e", border: `1px solid ${fc.verified ? "#bbf7d0" : "#fef08a"}` }}>
                                {fc.verified ? "Live Test Passed" : fc.status_code ? `HTTP ${fc.status_code}` : "Unavailable"}
                              </span>
                            </div>
                            <div style={{ color: "var(--muted)", marginTop: 2, fontFamily: "monospace", fontSize: 10 }}>{fc.method} {fc.endpoint_url}</div>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <button type="button" onClick={() => setPanelStep("form")} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
                  ← Back
                </button>
                <button
                  type="button"
                  disabled={selectedGroupIds.size === 0}
                  onClick={() => void handleSave()}
                  style={{
                    border: "none",
                    background: selectedGroupIds.size === 0 ? "var(--bg-2)" : "var(--ink)",
                    color: selectedGroupIds.size === 0 ? "var(--muted)" : "#fff",
                    borderRadius: 10, padding: "10px 18px", fontWeight: 700, fontSize: 14,
                    cursor: selectedGroupIds.size === 0 ? "not-allowed" : "pointer",
                  }}
                >
                  {selectedGroupIds.size > 0
                    ? `Save ${selectedGroupIds.size} grouped skill${selectedGroupIds.size !== 1 ? "s" : ""} to profile`
                    : "Select skills to save"}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Saving progress ── */}
      {panelStep === "saving" && saveProgress && (
        <ProofProcessingProgressPanel title="Saving grouped skill evidence" progress={saveProgress} canClose={false} />
      )}

      {/* ── Done ── */}
      {panelStep === "done" && saveProgress && (
        <ProofProcessingProgressPanel title="Grouped skill evidence saved" progress={saveProgress} onClose={onBack} canClose />
      )}
    </div>
  )
}
