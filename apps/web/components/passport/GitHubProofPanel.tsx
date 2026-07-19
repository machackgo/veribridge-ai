"use client"

import { useEffect, useState } from "react"
import {
  listGitHubProofs,
  submitGitHubProof,
  analyzeGitHubProof,
  archiveGitHubProof,
  syncGitHubProofToSkillGraph,
  type GitHubProofResponse,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  ProgressBar,
  StatusBadge,
  TOKEN,
} from "./shared"
import { ProofProjectAttachPanel } from "./ProofProjectAttachPanel"

function EvidenceStrengthBar({ strength }: { strength: string | null | undefined }) {
  const map: Record<string, { pct: number; color: string }> = {
    strong: { pct: 90, color: TOKEN.emerald },
    substantial: { pct: 75, color: TOKEN.emerald },
    moderate: { pct: 55, color: TOKEN.amber },
    partial: { pct: 40, color: TOKEN.amber },
    weak: { pct: 20, color: TOKEN.rose },
    minimal: { pct: 15, color: TOKEN.rose },
  }
  if (!strength) return null
  const { pct, color } = map[strength.toLowerCase()] ?? { pct: 50, color: TOKEN.indigo }
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase" }}>Evidence Strength</Mono>
        <Mono style={{ fontSize: 10, color, fontWeight: 700 }}>{strength}</Mono>
      </div>
      <ProgressBar value={pct} color={color} height={5} />
    </div>
  )
}

type SyncStatus = "syncing" | "saved" | "error"

// Proof statuses whose analysis is complete enough to attach to a project.
const ATTACHABLE_STATUSES = new Set(["analyzed", "needs_more_evidence"])

function GitHubProofCard({
  proof,
  onAnalyze,
  onArchive,
  onRetrySync,
  onAttached,
  loading,
  syncStatus,
}: {
  proof: GitHubProofResponse
  onAnalyze: (id: string) => void
  onArchive: (id: string) => void
  onRetrySync: (id: string) => void
  onAttached: () => void
  loading: Record<string, boolean>
  syncStatus?: SyncStatus
}) {
  const isAnalyzing = loading[`analyze-${proof.id}`]
  const isArchiving = loading[`archive-${proof.id}`]
  const isArchived = proof.status === "archived"

  return (
    <Card style={{ padding: "16px 18px" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <div style={{ fontSize: 22, flexShrink: 0 }}>🐙</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>
              {proof.repo_owner}/{proof.repo_name}
            </span>
            <StatusBadge status={proof.status} />
            {proof.visibility && (
              <Badge tone={proof.visibility === "public" ? "sky" : "slate"}>{proof.visibility}</Badge>
            )}
            {/* Canonical relationship state — the SAME rows the Passport and
                reports read; a display title can never fake attachment. */}
            {!isArchived && (
              <span
                data-testid="github-relationship-state"
                data-state={proof.project_relationship_state ?? "vault_only"}
              >
                {proof.project_relationship_state === "directly_linked" && proof.project_title ? (
                  <Badge tone="emerald">Attached to {proof.project_title}</Badge>
                ) : (
                  <Badge tone="amber">Needs project attachment — not counted in project reports</Badge>
                )}
              </span>
            )}
          </div>

          <a
            href={proof.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 12, color: TOKEN.indigo }}
          >
            {proof.repo_url}
          </a>

          {/* Submitted claims */}
          {proof.submitted_skill_claims.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Claimed Skills
              </Mono>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
                {proof.submitted_skill_claims.map((s: string) => (
                  <Badge key={s} tone="indigo">{s}</Badge>
                ))}
              </div>
            </div>
          )}

          {/* Detected skills */}
          {proof.detected_skills.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.emerald, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Detected Skills
              </Mono>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
                {proof.detected_skills.map((s: string) => (
                  <Badge key={s} tone="emerald">{s}</Badge>
                ))}
              </div>
            </div>
          )}

          {/* Confidence */}
          {proof.confidence_score != null && (
            <div style={{ marginTop: 8 }}>
              <EvidenceStrengthBar strength={proof.evidence_strength} />
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6 }}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted }}>Confidence:</Mono>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color:
                      proof.confidence_score >= 70
                        ? TOKEN.emerald
                        : proof.confidence_score >= 40
                        ? TOKEN.amber
                        : TOKEN.rose,
                  }}
                >
                  {proof.confidence_score}%
                </span>
              </div>
            </div>
          )}

          {/* Analysis summary */}
          {proof.analysis_summary && (
            <div
              style={{
                marginTop: 10,
                padding: "8px 10px",
                background: TOKEN.bg,
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
              }}
            >
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase" }}>Analysis</Mono>
              <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: "4px 0 0", lineHeight: 1.5 }}>
                {proof.analysis_summary}
              </p>
            </div>
          )}

          {/* Public safe summary */}
          {proof.public_safe_summary && proof.analysis_summary !== proof.public_safe_summary && (
            <div
              style={{
                marginTop: 8,
                padding: "8px 10px",
                background: TOKEN.indigoSoft,
                border: `1px solid #c7d2fe`,
                borderRadius: 8,
              }}
            >
              <Mono style={{ fontSize: 10, color: TOKEN.indigo, textTransform: "uppercase" }}>Public summary</Mono>
              <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: "4px 0 0" }}>{proof.public_safe_summary}</p>
            </div>
          )}

          {/* Missing evidence */}
          {proof.missing_evidence.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.rose, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Missing Evidence
              </Mono>
              <ul style={{ margin: "4px 0 0", padding: "0 0 0 14px" }}>
                {proof.missing_evidence.map((m: string, i: number) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.muted }}>{m}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Actions */}
          {!isArchived && (
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Btn
                size="sm"
                variant="primary"
                onClick={() => onAnalyze(proof.id)}
                disabled={isAnalyzing || proof.status === "analyzing"}
              >
                {isAnalyzing || proof.status === "analyzing" ? "Analyzing…" : "Analyze Repo"}
              </Btn>
              <Btn
                size="sm"
                variant="ghost"
                onClick={() => onArchive(proof.id)}
                disabled={isArchiving}
              >
                Archive
              </Btn>
            </div>
          )}

          {/* Explicit project attachment — the shared canonical finalization
              flow (existing project / create new / keep vault-only). Shown for
              analyzed proofs so a GitHub-only project can appear in the Work
              Passport without any Website Proof. */}
          {!isArchived && ATTACHABLE_STATUSES.has(proof.status) && (
            <ProofProjectAttachPanel
              proofType="github"
              proofId={proof.id}
              relationshipState={proof.project_relationship_state}
              attachedProjectTitle={proof.project_title}
              defaultProjectTitle={proof.repo_name ? `${proof.repo_name}` : ""}
              defaultRepoUrl={proof.repo_url}
              onAttached={onAttached}
            />
          )}

          {/* Skill Graph sync status */}
          {syncStatus === "syncing" && (
            <Mono style={{ fontSize: 11, color: TOKEN.muted, marginTop: 8, display: "block" }}>
              Saving to Skill Graph…
            </Mono>
          )}
          {syncStatus === "saved" && (
            <Mono style={{ fontSize: 11, color: TOKEN.emerald, marginTop: 8, display: "block" }}>
              ✓ Saved to Skill Graph
            </Mono>
          )}
          {syncStatus === "error" && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
              <Mono style={{ fontSize: 11, color: TOKEN.rose }}>
                Couldn&apos;t save to Skill Graph.
              </Mono>
              <Btn size="sm" variant="ghost" onClick={() => onRetrySync(proof.id)}>
                Retry
              </Btn>
            </div>
          )}

          {proof.last_analyzed_at && (
            <Mono style={{ fontSize: 10, color: TOKEN.muted, marginTop: 8, display: "block" }}>
              Last analyzed: {new Date(proof.last_analyzed_at).toLocaleDateString()}
            </Mono>
          )}
        </div>
      </div>
    </Card>
  )
}

type SubmitForm = {
  repo_url: string
  submitted_skill_claims: string
}

// Proof statuses for which a Skill Graph sync is attempted after analysis.
const SYNCABLE_STATUSES = new Set(["analyzed", "needs_more_evidence"])

export function GitHubProofPanel({ sessionId }: { sessionId?: string }) {
  const [proofs, setProofs] = useState<GitHubProofResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})
  const [syncState, setSyncState] = useState<Record<string, SyncStatus>>({})
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<SubmitForm>({ repo_url: "", submitted_skill_claims: "" })
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    listGitHubProofs(sessionId)
      .then(setProofs)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [sessionId])

  const handleSubmit = async () => {
    if (!form.repo_url.trim()) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const claims = form.submitted_skill_claims
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
      const proof = await submitGitHubProof({
        repo_url: form.repo_url.trim(),
        proof_session_id: sessionId ?? null,
        submitted_skill_claims: claims,
      })
      setProofs((prev) => [proof, ...prev])
      setForm({ repo_url: "", submitted_skill_claims: "" })
      setShowForm(false)
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Submission failed")
    } finally {
      setSubmitting(false)
    }
  }

  const runSync = async (id: string) => {
    setSyncState((prev) => ({ ...prev, [id]: "syncing" }))
    try {
      const result = await syncGitHubProofToSkillGraph(id)
      const didSave =
        result.ok &&
        (result.already_synced || result.artifacts_created > 0) &&
        result.errors.length === 0
      setSyncState((prev) => ({ ...prev, [id]: didSave ? "saved" : "error" }))
    } catch {
      setSyncState((prev) => ({ ...prev, [id]: "error" }))
    }
  }

  const handleAnalyze = async (id: string) => {
    setActionLoading((prev) => ({ ...prev, [`analyze-${id}`]: true }))
    try {
      const updated = await analyzeGitHubProof(id)
      setProofs((prev) => prev.map((p) => (p.id === id ? updated : p)))
      if (SYNCABLE_STATUSES.has(updated.status)) {
        void runSync(id)
      }
    } catch {
      // silently fail — user can retry
    } finally {
      setActionLoading((prev) => ({ ...prev, [`analyze-${id}`]: false }))
    }
  }

  const handleArchive = async (id: string) => {
    setActionLoading((prev) => ({ ...prev, [`archive-${id}`]: true }))
    try {
      const updated = await archiveGitHubProof(id)
      setProofs((prev) => prev.map((p) => (p.id === id ? updated : p)))
    } catch {
      // silently fail
    } finally {
      setActionLoading((prev) => ({ ...prev, [`archive-${id}`]: false }))
    }
  }

  const active = proofs.filter((p) => p.status !== "archived")
  const archived = proofs.filter((p) => p.status === "archived")

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>GitHub Proof Submissions</h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Submit public GitHub repositories as verifiable evidence of your technical skills.
          </p>
        </div>
        <Btn variant="primary" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ Add Repository"}
        </Btn>
      </div>

      {/* Submit form */}
      {showForm && (
        <Card style={{ border: `1px solid ${TOKEN.indigo}40`, background: TOKEN.indigoSoft }}>
          <CardHeader title="Submit GitHub Repository" eyebrow="New proof" icon="🐙" />
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Repository URL *
              </label>
              <input
                type="url"
                placeholder="https://github.com/username/repo"
                value={form.repo_url}
                onChange={(e) => setForm((f) => ({ ...f, repo_url: e.target.value }))}
                style={{
                  width: "100%",
                  padding: "9px 12px",
                  border: `1px solid ${TOKEN.line}`,
                  borderRadius: 8,
                  fontSize: 13,
                  background: TOKEN.paper,
                  boxSizing: "border-box",
                }}
              />
            </div>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Skill Claims (comma-separated, optional)
              </label>
              <input
                type="text"
                placeholder="React, TypeScript, GraphQL"
                value={form.submitted_skill_claims}
                onChange={(e) => setForm((f) => ({ ...f, submitted_skill_claims: e.target.value }))}
                style={{
                  width: "100%",
                  padding: "9px 12px",
                  border: `1px solid ${TOKEN.line}`,
                  borderRadius: 8,
                  fontSize: 13,
                  background: TOKEN.paper,
                  boxSizing: "border-box",
                }}
              />
              <p style={{ fontSize: 11, color: TOKEN.muted, marginTop: 4 }}>
                Skills you claim to demonstrate in this repository. Will be compared against detected skills.
              </p>
            </div>
            {submitError && (
              <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6 }}>
                {submitError}
              </p>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <Btn variant="primary" onClick={handleSubmit} disabled={submitting || !form.repo_url.trim()}>
                {submitting ? "Submitting…" : "Submit Repository"}
              </Btn>
              <Btn variant="secondary" onClick={() => setShowForm(false)}>Cancel</Btn>
            </div>
          </div>
        </Card>
      )}

      {/* Loading / error */}
      {loading && <LoadingState label="Loading GitHub proofs…" />}
      {error && <ErrorState message={error} onRetry={load} />}

      {/* Active proofs */}
      {!loading && !error && active.length === 0 && archived.length === 0 && (
        <EmptyState
          icon="🐙"
          title="No GitHub proofs yet"
          description="Submit a public GitHub repository to demonstrate your technical skills with real code evidence."
          action={<Btn variant="primary" onClick={() => setShowForm(true)}>Submit your first repo</Btn>}
        />
      )}

      {active.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {active.map((p) => (
            <GitHubProofCard
              key={p.id}
              proof={p}
              onAnalyze={handleAnalyze}
              onArchive={handleArchive}
              onRetrySync={runSync}
              onAttached={load}
              loading={actionLoading}
              syncStatus={syncState[p.id]}
            />
          ))}
        </div>
      )}

      {/* Archived proofs */}
      {archived.length > 0 && (
        <details>
          <summary
            style={{ fontSize: 12, color: TOKEN.muted, cursor: "pointer", padding: "8px 0", fontWeight: 600 }}
          >
            {archived.length} archived proof{archived.length !== 1 ? "s" : ""}
          </summary>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
            {archived.map((p) => (
              <GitHubProofCard
                key={p.id}
                proof={p}
                onAnalyze={handleAnalyze}
                onArchive={handleArchive}
                onRetrySync={runSync}
                onAttached={load}
                loading={actionLoading}
                syncStatus={syncState[p.id]}
              />
            ))}
          </div>
        </details>
      )}

      {/* Disclaimer */}
      <p style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", marginTop: 4 }}>
        Only public repositories are analyzed. Repository content is read-only and not stored.
      </p>
    </div>
  )
}
