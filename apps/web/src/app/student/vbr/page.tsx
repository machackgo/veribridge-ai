"use client"

import Link from "next/link"
import { useEffect, useState, type CSSProperties } from "react"
import {
  getVBRProjectQuestions,
  listVBRProjects,
  type VBRProjectResponse,
} from "@/lib/vbr-api"

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

export default function StudentVBRPage() {
  const [rows, setRows] = useState<ProjectRow[] | null>(null)
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
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "48px 24px" }}>
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
      <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginBottom: 32, opacity: 0.85 }}>
        Create a verified proof-of-skill report from your project, repo, and walkthrough.
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

      {rows === null && !error && (
        <p style={{ fontSize: 14, color: "var(--ink-2)", opacity: 0.7 }}>Loading your projects…</p>
      )}

      {rows && rows.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 32 }}>
          {rows.map(({ project, sessionId }) => (
            <div key={project.id} style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                <div>
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
        </div>
      )}

      {rows && rows.length === 0 && (
        <div style={{ ...cardStyle, marginBottom: 32 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", marginBottom: 8 }}>
            No projects yet
          </h2>
          <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, opacity: 0.85, marginBottom: 0 }}>
            Verified Build Report creation walks you through linking a GitHub repo, confirming what you
            built, and recording a short walkthrough that becomes your shareable proof report. Project
            creation is rolling out — check back soon to start your first report.
          </p>
        </div>
      )}

      <div style={{ display: "flex", gap: 12 }}>
        <Link href="/dashboard" style={primaryLinkStyle}>
          Go to dashboard
        </Link>
      </div>
    </div>
  )
}
