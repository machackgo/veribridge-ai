"use client"

import Link from "next/link"
import { useEffect, useState, type CSSProperties, type ReactNode } from "react"
import {
  getVBRProjectQuestions,
  listVBRProjects,
  type VBRProjectResponse,
} from "@/lib/vbr-api"
import { listGitHubProofs, type GitHubProofResponse } from "@/lib/passport-api"

type ProjectRow = {
  project: VBRProjectResponse
  sessionId: string | null
}

const cardStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--paper)",
  padding: 20,
}

const sourceCardStyle: CSSProperties = {
  ...cardStyle,
  display: "flex",
  flexDirection: "column",
  gap: 10,
}

const statusChipStyle: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink-2)",
  fontSize: 12,
  fontFamily: "var(--font-mono)",
}

const primaryLinkStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "10px 18px",
  borderRadius: 10,
  border: "1px solid var(--indigo)",
  background: "var(--indigo)",
  color: "#fff",
  fontSize: 14,
  fontWeight: 600,
  textDecoration: "none",
}

const secondaryLinkStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "10px 18px",
  borderRadius: 10,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink)",
  fontSize: 14,
  fontWeight: 600,
  textDecoration: "none",
}

const comingSoonBadgeStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "6px 12px",
  borderRadius: 8,
  border: "1px dashed var(--line-strong)",
  background: "var(--bg-2)",
  color: "var(--ink-2)",
  fontSize: 13,
  fontWeight: 600,
  opacity: 0.8,
}

function ProofSourceCard({
  icon,
  title,
  description,
  action,
}: {
  icon: string
  title: string
  description: string
  action: ReactNode
}) {
  return (
    <div style={sourceCardStyle}>
      <div style={{ fontSize: 22 }}>{icon}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>{title}</div>
      <p style={{ fontSize: 13, color: "var(--ink-2)", lineHeight: 1.5, opacity: 0.85, margin: 0, flex: 1 }}>
        {description}
      </p>
      <div>{action}</div>
    </div>
  )
}

export default function StudentVBRPage() {
  const [rows, setRows] = useState<ProjectRow[] | null>(null)
  const [githubProofs, setGithubProofs] = useState<GitHubProofResponse[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const projects = await listVBRProjects()
        const withSessions = await Promise.all(
          projects.map(async (project) => {
            try {
              const questions = await getVBRProjectQuestions(project.id)
              return { project, sessionId: questions.session_id }
            } catch {
              return { project, sessionId: null }
            }
          })
        )
        if (!cancelled) setRows(withSessions)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load your projects.")
        }
      }

      try {
        const proofs = await listGitHubProofs()
        if (!cancelled) setGithubProofs(proofs)
      } catch {
        if (!cancelled) setGithubProofs([])
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  const continueSession = rows?.find((row) => row.sessionId)?.sessionId ?? null
  const loaded = rows !== null && githubProofs !== null
  const hasProofSources = (rows?.length ?? 0) > 0 || (githubProofs?.length ?? 0) > 0

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", padding: "48px 24px" }}>
      <h1
        style={{
          fontSize: 28,
          fontWeight: 700,
          color: "var(--ink)",
          letterSpacing: "-0.6px",
          marginBottom: 12,
        }}
      >
        VeriBridge Proof Studio
      </h1>
      <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginBottom: 32, opacity: 0.85, maxWidth: 640 }}>
        Add your proof sources once. VeriBridge will use them to create project reports, skill evidence, and
        public proof links.
      </p>

      {error && (
        <div
          role="alert"
          style={{
            background: "var(--rose-soft)",
            border: "1px solid var(--rose)",
            borderRadius: 10,
            padding: "12px 16px",
            fontSize: 14,
            color: "var(--ink)",
            marginBottom: 24,
          }}
        >
          {error}
        </div>
      )}

      {/* Proof source cards */}
      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", marginBottom: 12 }}>
          Add a proof source
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 12,
          }}
        >
          <ProofSourceCard
            icon="🐙"
            title="GitHub Repository Proof"
            description="For code repositories and commits. Submit a public repo to detect skills from your code."
            action={
              <Link href="/dashboard/passport/github" style={secondaryLinkStyle}>
                Add GitHub proof
              </Link>
            }
          />

          <ProofSourceCard
            icon="🌐"
            title="Website / Live App Proof"
            description="For deployed apps and live demos. Link a live URL as evidence your project works end to end."
            action={
              <Link href="/student/proofs/website" style={secondaryLinkStyle}>
                Add website proof
              </Link>
            }
          />

          <ProofSourceCard
            icon="🎥"
            title="Walkthrough / Verified Build Report"
            description="Record a short walkthrough of your project and generate a shareable Verified Build Report."
            action={
              continueSession ? (
                <Link href={`/student/vbr/sessions/${continueSession}`} style={primaryLinkStyle}>
                  Continue recording
                </Link>
              ) : (
                <span style={comingSoonBadgeStyle}>Report generation ready; project creation UI coming next</span>
              )
            }
          />

          <ProofSourceCard
            icon="📄"
            title="Other Proofs"
            description="Documents, certificates, and coursework as supporting evidence."
            action={<span style={comingSoonBadgeStyle}>Coming soon</span>}
          />
        </div>
      </section>

      {/* Pipeline explainer */}
      <section style={{ ...cardStyle, marginBottom: 32 }}>
        <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)", marginBottom: 10 }}>
          What happens next
        </h2>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 8,
            fontSize: 13,
            color: "var(--ink-2)",
          }}
        >
          <span style={statusChipStyle}>Collect proofs</span>
          <span aria-hidden="true">→</span>
          <span style={statusChipStyle}>Detect projects &amp; skills</span>
          <span aria-hidden="true">→</span>
          <span style={statusChipStyle}>Generate reports</span>
          <span aria-hidden="true">→</span>
          <span style={statusChipStyle}>Publish profile</span>
        </div>
        <p style={{ fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6, opacity: 0.8, marginTop: 12, marginBottom: 0 }}>
          Add as many proof sources as you have — VeriBridge will use all of them together to build your
          project reports and skill evidence.
        </p>
      </section>

      {/* Your proof sources */}
      <section>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", marginBottom: 12 }}>
          Your proof sources
        </h2>

        {!loaded && !error && (
          <p style={{ fontSize: 14, color: "var(--ink-2)", opacity: 0.7 }}>Loading your proof sources…</p>
        )}

        {loaded && !hasProofSources && (
          <div style={cardStyle}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)", marginBottom: 8 }}>
              No proof sources added yet
            </h3>
            <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, opacity: 0.85, marginBottom: 0 }}>
              Add a GitHub repo, website, or record a project walkthrough above to get started. VeriBridge
              will use your proof sources to build project reports, skill evidence, and a shareable proof
              link.
            </p>
          </div>
        )}

        {loaded && hasProofSources && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {rows?.map(({ project, sessionId }) => (
              <div key={`vbr-${project.id}`} style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                  <div>
                    <div style={{ fontSize: 13, color: "var(--ink-2)", opacity: 0.7, marginBottom: 2 }}>
                      Walkthrough / Verified Build Report
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)", marginBottom: 4 }}>
                      {project.title}
                    </div>
                    {project.repo_full_name && (
                      <div style={{ fontSize: 13, color: "var(--ink-2)", opacity: 0.75 }}>
                        {project.repo_full_name}
                      </div>
                    )}
                  </div>
                  <span style={statusChipStyle}>{project.status}</span>
                </div>

                {sessionId && (
                  <div style={{ marginTop: 12 }}>
                    <Link href={`/student/vbr/sessions/${sessionId}`} style={secondaryLinkStyle}>
                      Continue recording
                    </Link>
                  </div>
                )}
              </div>
            ))}

            {githubProofs?.map((proof) => (
              <div key={`gh-${proof.id}`} style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                  <div>
                    <div style={{ fontSize: 13, color: "var(--ink-2)", opacity: 0.7, marginBottom: 2 }}>
                      GitHub Repository Proof
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)", marginBottom: 4 }}>
                      {proof.repo_name ?? proof.repo_url}
                    </div>
                    {proof.repo_owner && (
                      <div style={{ fontSize: 13, color: "var(--ink-2)", opacity: 0.75 }}>{proof.repo_owner}</div>
                    )}
                  </div>
                  <span style={statusChipStyle}>{proof.status}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
