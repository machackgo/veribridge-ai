"use client"

import { useCallback, useState } from "react"
import type { CSSProperties } from "react"
import {
  importSelectedGitHubPortfolioProofs,
  scanGitHubPortfolio,
  type GitHubPortfolioImportResponse,
  type GitHubPortfolioScanCandidate,
  type GitHubPortfolioScanResponse,
} from "@/lib/api"

type ScanStep = "form" | "scanning" | "review" | "importing" | "done"

type ScanFormState = {
  profileUrl: string
  maxRepos: string
  includeForks: boolean
  includeArchived: boolean
}

const initialForm = (): ScanFormState => ({
  profileUrl: "",
  maxRepos: "10",
  includeForks: false,
  includeArchived: false,
})

function isGitHubProfileUrl(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return false
  // Accept full URL or bare username
  return (
    /^https?:\/\/github\.com\/[a-zA-Z0-9_-]+\/?$/.test(trimmed) ||
    /^[a-zA-Z0-9_-]+$/.test(trimmed)
  )
}

function confidenceBadgeStyle(label: string): CSSProperties {
  if (label === "high")
    return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (label === "medium")
    return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
}

function statusBadgeStyle(status: string): CSSProperties {
  if (status === "suggested")
    return { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }
  return { background: "#fff7ed", color: "#9a3412", border: "1px solid #fed7aa" }
}

export function GitHubPortfolioScanPanel({
  onImportSuccess,
  onClose,
}: {
  onImportSuccess?: () => void
  onClose: () => void
}) {
  const [step, setStep] = useState<ScanStep>("form")
  const [form, setForm] = useState<ScanFormState>(initialForm)
  const [scanResult, setScanResult] = useState<GitHubPortfolioScanResponse | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [importResult, setImportResult] = useState<GitHubPortfolioImportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  function close() {
    setStep("form")
    setForm(initialForm())
    setScanResult(null)
    setSelected(new Set())
    setImportResult(null)
    setError(null)
    onClose()
  }

  function toggleCandidate(candidateId: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(candidateId)) {
        next.delete(candidateId)
      } else {
        next.add(candidateId)
      }
      return next
    })
  }

  function selectAll() {
    if (!scanResult) return
    setSelected(new Set(scanResult.proof_candidates.map((c) => c.candidate_id)))
  }

  function deselectAll() {
    setSelected(new Set())
  }

  async function handleScan() {
    setError(null)
    const url = form.profileUrl.trim()
    if (!url) {
      setError("Enter your GitHub profile URL or username.")
      return
    }
    if (!isGitHubProfileUrl(url)) {
      setError(
        'Enter a valid GitHub profile URL (e.g. https://github.com/yourusername) or a plain username.'
      )
      return
    }

    const maxRepos = parseInt(form.maxRepos, 10)
    if (!Number.isFinite(maxRepos) || maxRepos < 1 || maxRepos > 50) {
      setError("Max repos must be between 1 and 50.")
      return
    }

    setStep("scanning")
    try {
      const result = await scanGitHubPortfolio({
        github_profile_url: url.includes("github.com") ? url : undefined,
        github_username: url.includes("github.com") ? undefined : url,
        max_repos: maxRepos,
        include_forks: form.includeForks,
        include_archived: form.includeArchived,
      })
      setScanResult(result)
      // Auto-select high-confidence / suggested candidates
      const autoSelect = new Set(
        result.proof_candidates
          .filter((c) => c.suggested_status === "suggested")
          .map((c) => c.candidate_id)
      )
      setSelected(autoSelect)
      setStep("review")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed. Please try again.")
      setStep("form")
    }
  }

  async function handleImport() {
    if (!scanResult) return
    const candidates = scanResult.proof_candidates.filter((c) => selected.has(c.candidate_id))
    if (candidates.length === 0) {
      setError("Select at least one proof candidate before saving.")
      return
    }

    setError(null)
    setStep("importing")
    try {
      const result = await importSelectedGitHubPortfolioProofs(candidates)
      setImportResult(result)
      setStep("done")
      onImportSuccess?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed. Please try again.")
      setStep("review")
    }
  }

  return (
    <div
      role="presentation"
      data-testid="github-scan-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) close()
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.52)",
        zIndex: 50,
        display: "grid",
        placeItems: "center",
        padding: 20,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="github-scan-title"
        data-testid="github-scan-modal"
        style={{
          width: "min(900px, 100%)",
          maxHeight: "min(92vh, 960px)",
          overflow: "auto",
          borderRadius: 18,
          background: "#fff",
          border: "1px solid var(--line)",
          boxShadow: "0 30px 80px rgba(15,23,42,.25)",
          padding: 24,
          display: "grid",
          gap: 20,
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 12,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 11,
                fontWeight: 800,
                letterSpacing: "0.14em",
                textTransform: "uppercase",
                color: "var(--muted)",
              }}
            >
              {step === "done" ? "Completed" : "GitHub Portfolio Scan"}
            </div>
            <h2
              id="github-scan-title"
              style={{ margin: "4px 0 0", fontSize: 22, fontWeight: 700, color: "var(--ink)" }}
            >
              {step === "form" && "Scan my GitHub profile"}
              {step === "scanning" && "Scanning public repositories…"}
              {step === "review" && "Review detected proof suggestions"}
              {step === "importing" && "Saving selected proof items…"}
              {step === "done" && "GitHub proof items imported"}
            </h2>
            {step === "form" && (
              <p
                style={{
                  margin: "6px 0 0",
                  color: "var(--muted)",
                  fontSize: 13,
                  lineHeight: 1.6,
                }}
              >
                Enter your GitHub profile URL. VeriBridge will scan your public repos and suggest
                proof candidates. You review and approve before anything is saved.
              </p>
            )}
            {step === "review" && scanResult && (
              <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13 }}>
                We found{" "}
                <strong>{scanResult.candidate_count} proof suggestion{scanResult.candidate_count === 1 ? "" : "s"}</strong>{" "}
                across{" "}
                <strong>{scanResult.repo_count_scanned} repo{scanResult.repo_count_scanned === 1 ? "" : "s"}</strong>{" "}
                and{" "}
                <strong>{scanResult.detected_skill_count} skill{scanResult.detected_skill_count === 1 ? "" : "s"}</strong>.{" "}
                Review and select the ones you want to add to your profile.
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={close}
            aria-label="Close GitHub scan modal"
            data-testid="github-scan-modal-close"
            style={{
              border: "1px solid var(--line)",
              background: "#fff",
              color: "var(--ink-2)",
              borderRadius: 10,
              width: 38,
              height: 38,
              fontSize: 18,
              fontWeight: 700,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            ×
          </button>
        </div>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            data-testid="github-scan-error"
            style={{
              border: "1px solid #fecaca",
              background: "#fef2f2",
              color: "#991b1b",
              borderRadius: 12,
              padding: "10px 12px",
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            {error}
          </div>
        )}

        {/* ── Form step ── */}
        {step === "form" && (
          <div style={{ display: "grid", gap: 16 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                GitHub profile URL or username
              </span>
              <input
                data-testid="github-scan-profile-url"
                value={form.profileUrl}
                onChange={(e) => setForm((prev) => ({ ...prev, profileUrl: e.target.value }))}
                placeholder="https://github.com/yourusername"
                style={inputStyle}
              />
              <span style={{ fontSize: 12, color: "var(--muted)" }}>
                Public repos only. Private repos require GitHub OAuth (future).
              </span>
            </label>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                  Max repos to scan
                </span>
                <input
                  data-testid="github-scan-max-repos"
                  type="number"
                  min={1}
                  max={50}
                  value={form.maxRepos}
                  onChange={(e) => setForm((prev) => ({ ...prev, maxRepos: e.target.value }))}
                  style={inputStyle}
                />
              </label>

              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  cursor: "pointer",
                  paddingTop: 24,
                }}
              >
                <input
                  data-testid="github-scan-include-forks"
                  type="checkbox"
                  checked={form.includeForks}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, includeForks: e.target.checked }))
                  }
                  style={{ width: 16, height: 16, cursor: "pointer" }}
                />
                <span style={{ fontSize: 13, color: "var(--ink)" }}>Include forks</span>
              </label>

              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  cursor: "pointer",
                  paddingTop: 24,
                }}
              >
                <input
                  data-testid="github-scan-include-archived"
                  type="checkbox"
                  checked={form.includeArchived}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, includeArchived: e.target.checked }))
                  }
                  style={{ width: 16, height: 16, cursor: "pointer" }}
                />
                <span style={{ fontSize: 13, color: "var(--ink)" }}>Include archived</span>
              </label>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                data-testid="github-scan-submit"
                onClick={() => void handleScan()}
                style={{
                  border: "1px solid transparent",
                  background: "var(--ink)",
                  color: "#fff",
                  borderRadius: 10,
                  padding: "10px 18px",
                  fontWeight: 700,
                  fontSize: 14,
                  cursor: "pointer",
                }}
              >
                Scan GitHub profile
              </button>
            </div>
          </div>
        )}

        {/* ── Scanning step ── */}
        {step === "scanning" && (
          <div
            style={{
              padding: "32px 0",
              textAlign: "center",
              color: "var(--muted)",
              fontSize: 14,
            }}
          >
            Scanning public repositories — this may take a few seconds…
          </div>
        )}

        {/* ── Review step ── */}
        {step === "review" && scanResult && (
          <div style={{ display: "grid", gap: 16 }}>
            {scanResult.proof_candidates.length === 0 ? (
              <div
                data-testid="github-scan-no-candidates"
                style={{
                  border: "1px dashed var(--line-2)",
                  borderRadius: 14,
                  padding: 24,
                  textAlign: "center",
                  color: "var(--muted)",
                  fontSize: 13,
                  lineHeight: 1.7,
                }}
              >
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>
                  No high-confidence proof candidates found.
                </div>
                We scanned {scanResult.repo_count_scanned} repo{scanResult.repo_count_scanned === 1 ? "" : "s"} but did not find high-confidence
                proof ranges yet. Try manual proof submission or adjust scan options (include
                forks, increase max repos).
              </div>
            ) : (
              <>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 8,
                  }}
                >
                  <div style={{ fontSize: 13, color: "var(--ink-2)", fontWeight: 600 }}>
                    {selected.size} of {scanResult.proof_candidates.length} selected
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      data-testid="github-scan-select-all"
                      onClick={selectAll}
                      style={ghostBtnStyle}
                    >
                      Select all
                    </button>
                    <button
                      type="button"
                      data-testid="github-scan-deselect-all"
                      onClick={deselectAll}
                      style={ghostBtnStyle}
                    >
                      Deselect all
                    </button>
                  </div>
                </div>

                <div
                  data-testid="github-scan-candidates-list"
                  style={{ display: "grid", gap: 10, maxHeight: 480, overflowY: "auto" }}
                >
                  {scanResult.proof_candidates.map((candidate) => {
                    const isSelected = selected.has(candidate.candidate_id)
                    return (
                      <label
                        key={candidate.candidate_id}
                        data-testid={`scan-candidate-${candidate.candidate_id}`}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "auto 1fr",
                          gap: 14,
                          padding: 14,
                          border: `1px solid ${isSelected ? "var(--indigo)" : "var(--line)"}`,
                          borderRadius: 12,
                          background: isSelected ? "var(--indigo-soft)" : "#fff",
                          cursor: "pointer",
                          transition: "border-color 0.12s, background 0.12s",
                        }}
                      >
                        <input
                          type="checkbox"
                          data-testid={`scan-candidate-checkbox-${candidate.candidate_id}`}
                          checked={isSelected}
                          onChange={() => toggleCandidate(candidate.candidate_id)}
                          style={{ marginTop: 2, width: 16, height: 16, cursor: "pointer" }}
                        />
                        <div style={{ display: "grid", gap: 8 }}>
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              gap: 8,
                              flexWrap: "wrap",
                            }}
                          >
                            <div>
                              <div
                                data-testid="scan-candidate-skill"
                                style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)" }}
                              >
                                {candidate.skill_label}
                              </div>
                              <div
                                data-testid="scan-candidate-project"
                                style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}
                              >
                                {candidate.project_title} · {candidate.repo_name}
                              </div>
                            </div>
                            <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                              <span
                                style={{
                                  ...confidenceBadgeStyle(candidate.confidence_label),
                                  fontSize: 10,
                                  fontWeight: 700,
                                  letterSpacing: "0.1em",
                                  textTransform: "uppercase",
                                  padding: "3px 8px",
                                  borderRadius: 999,
                                }}
                              >
                                {candidate.confidence_label}
                              </span>
                              <span
                                style={{
                                  ...statusBadgeStyle(candidate.suggested_status),
                                  fontSize: 10,
                                  fontWeight: 700,
                                  letterSpacing: "0.1em",
                                  textTransform: "uppercase",
                                  padding: "3px 8px",
                                  borderRadius: 999,
                                }}
                              >
                                {candidate.suggested_status === "suggested"
                                  ? "Auto-selected"
                                  : "Review"}
                              </span>
                            </div>
                          </div>

                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "1fr 1fr",
                              gap: 8,
                              fontSize: 12,
                              color: "var(--muted)",
                            }}
                          >
                            <div>
                              <span
                                data-testid="scan-candidate-filepath"
                                style={{ fontFamily: "'JetBrains Mono', monospace" }}
                              >
                                {candidate.file_path}
                              </span>
                              <span
                                data-testid="scan-candidate-linerange"
                                style={{
                                  marginLeft: 6,
                                  fontFamily: "'JetBrains Mono', monospace",
                                  fontWeight: 600,
                                }}
                              >
                                L{candidate.line_start}–L{candidate.line_end}
                              </span>
                            </div>
                            <div style={{ color: "var(--muted)" }}>{candidate.selection_reason}</div>
                          </div>

                          <div style={{ fontSize: 12, color: "var(--ink-2)", lineHeight: 1.5 }}>
                            {candidate.evidence_description}
                          </div>

                          <a
                            href={candidate.github_highlight_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid="scan-candidate-review-link"
                            onClick={(e) => e.stopPropagation()}
                            style={{
                              fontSize: 12,
                              fontWeight: 600,
                              color: "var(--indigo)",
                              textDecoration: "none",
                            }}
                          >
                            Review evidence on GitHub →
                          </a>
                        </div>
                      </label>
                    )
                  })}
                </div>
              </>
            )}

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <button
                type="button"
                data-testid="github-scan-back"
                onClick={() => {
                  setStep("form")
                  setError(null)
                }}
                style={ghostBtnStyle}
              >
                ← Back
              </button>
              <button
                type="button"
                data-testid="github-scan-save-selected"
                onClick={() => void handleImport()}
                disabled={selected.size === 0}
                style={{
                  border: "1px solid transparent",
                  background: selected.size === 0 ? "var(--bg-2)" : "var(--ink)",
                  color: selected.size === 0 ? "var(--muted)" : "#fff",
                  borderRadius: 10,
                  padding: "10px 18px",
                  fontWeight: 700,
                  fontSize: 14,
                  cursor: selected.size === 0 ? "not-allowed" : "pointer",
                }}
              >
                Save {selected.size > 0 ? `${selected.size} selected` : "selected"} to profile
              </button>
            </div>
          </div>
        )}

        {/* ── Importing step ── */}
        {step === "importing" && (
          <div
            style={{
              padding: "32px 0",
              textAlign: "center",
              color: "var(--muted)",
              fontSize: 14,
            }}
          >
            Saving selected proof items and running verification…
          </div>
        )}

        {/* ── Done step ── */}
        {step === "done" && importResult && (
          <div style={{ display: "grid", gap: 16 }}>
            <div
              data-testid="github-scan-import-success"
              style={{
                border: "1px solid #bbf7d0",
                background: "#f0fdf4",
                borderRadius: 14,
                padding: "16px 18px",
              }}
            >
              <div style={{ fontSize: 15, fontWeight: 700, color: "#166534", marginBottom: 4 }}>
                {importResult.imported_count > 0
                  ? `Imported ${importResult.imported_count} GitHub proof item${importResult.imported_count === 1 ? "" : "s"}.`
                  : "No new proof items were imported."}
              </div>
              {importResult.skipped_duplicate_count > 0 && (
                <div style={{ fontSize: 13, color: "#166534", marginTop: 4 }}>
                  {importResult.skipped_duplicate_count} duplicate{importResult.skipped_duplicate_count === 1 ? "" : "s"} skipped — already in your profile.
                </div>
              )}
              {importResult.failed_count > 0 && (
                <div style={{ fontSize: 13, color: "#991b1b", marginTop: 4 }}>
                  {importResult.failed_count} item{importResult.failed_count === 1 ? "" : "s"} failed to import.
                </div>
              )}
            </div>

            {importResult.per_candidate_results.length > 0 && (
              <div style={{ display: "grid", gap: 8 }}>
                {importResult.per_candidate_results.map((r) => (
                  <div
                    key={r.candidate_id}
                    style={{
                      padding: "10px 12px",
                      border: "1px solid var(--line)",
                      borderRadius: 10,
                      background: "var(--bg-2)",
                      fontSize: 12,
                      display: "grid",
                      gridTemplateColumns: "auto 1fr",
                      gap: 8,
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 700,
                        color:
                          r.status === "imported"
                            ? "var(--emerald)"
                            : r.status === "skipped_duplicate"
                              ? "var(--muted)"
                              : "var(--rose)",
                      }}
                    >
                      {r.status === "imported" ? "✓" : r.status === "skipped_duplicate" ? "−" : "✕"}
                    </span>
                    <span style={{ color: "var(--ink-2)" }}>
                      <strong>{r.skill_label}</strong> · {r.repo_name} · {r.message}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                data-testid="github-scan-done"
                onClick={close}
                style={{
                  border: "1px solid transparent",
                  background: "var(--ink)",
                  color: "#fff",
                  borderRadius: 10,
                  padding: "10px 18px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const inputStyle: CSSProperties = {
  width: "100%",
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "#fff",
  color: "var(--ink)",
  padding: "10px 12px",
  fontSize: 14,
  outline: "none",
  boxSizing: "border-box",
}

const ghostBtnStyle: CSSProperties = {
  border: "1px solid var(--line-2)",
  background: "transparent",
  color: "var(--ink-2)",
  borderRadius: 10,
  padding: "9px 14px",
  fontWeight: 600,
  fontSize: 13,
  cursor: "pointer",
}
