"use client"

import Link from "next/link"
import { useState, type CSSProperties, type FormEvent } from "react"
import { createWebsiteProofSession, type WebsiteProofSessionResponse } from "@/lib/api"

const cardStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--paper)",
  padding: 20,
}

const labelStyle: CSSProperties = {
  display: "block",
  fontSize: 13,
  fontWeight: 600,
  color: "var(--ink)",
  marginBottom: 6,
}

const inputStyle: CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: 8,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink)",
  fontSize: 14,
  boxSizing: "border-box",
}

const fieldWrapStyle: CSSProperties = {
  marginBottom: 16,
}

const primaryButtonStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "10px 18px",
  borderRadius: 10,
  border: "1px solid var(--indigo)",
  background: "var(--indigo)",
  color: "#fff",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
}

const disabledButtonStyle: CSSProperties = {
  ...primaryButtonStyle,
  opacity: 0.6,
  cursor: "not-allowed",
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

export default function WebsiteProofPage() {
  const [title, setTitle] = useState("")
  const [websiteUrl, setWebsiteUrl] = useState("")
  const [description, setDescription] = useState("")
  const [claimedSkills, setClaimedSkills] = useState("")
  const [validationError, setValidationError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [session, setSession] = useState<WebsiteProofSessionResponse | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const trimmedUrl = websiteUrl.trim()
    if (!trimmedUrl || (!trimmedUrl.startsWith("http://") && !trimmedUrl.startsWith("https://"))) {
      setValidationError("Enter a valid website URL starting with http:// or https://")
      return
    }

    setValidationError(null)
    setSubmitError(null)
    setSubmitting(true)

    const instructionParts = [
      title.trim() && `Project: ${title.trim()}`,
      description.trim() && `Description: ${description.trim()}`,
      claimedSkills.trim() && `Claimed skills: ${claimedSkills.trim()}`,
    ].filter(Boolean)

    try {
      const result = await createWebsiteProofSession({
        website_url: trimmedUrl,
        workflow_instructions: instructionParts.length > 0 ? instructionParts.join("\n\n") : null,
      })
      setSession(result)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create website proof session.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "48px 24px" }}>
      <h1
        style={{
          fontSize: 28,
          fontWeight: 700,
          color: "var(--ink)",
          letterSpacing: "-0.6px",
          marginBottom: 12,
        }}
      >
        Website / Live App Proof
      </h1>
      <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginBottom: 32, opacity: 0.85 }}>
        Capture evidence from a deployed app or live website so VeriBridge can verify real functionality,
        UI behavior, and workflow proof.
      </p>

      {!session && (
        <form onSubmit={handleSubmit} style={cardStyle}>
          <div style={fieldWrapStyle}>
            <label style={labelStyle} htmlFor="proof-title">
              Project / proof title
            </label>
            <input
              id="proof-title"
              type="text"
              style={inputStyle}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. My Recipe Finder App"
            />
          </div>

          <div style={fieldWrapStyle}>
            <label style={labelStyle} htmlFor="proof-url">
              Website URL / live app URL
            </label>
            <input
              id="proof-url"
              type="text"
              style={inputStyle}
              value={websiteUrl}
              onChange={(e) => setWebsiteUrl(e.target.value)}
              placeholder="https://your-app.example.com"
            />
          </div>

          <div style={fieldWrapStyle}>
            <label style={labelStyle} htmlFor="proof-description">
              Short description
            </label>
            <textarea
              id="proof-description"
              style={{ ...inputStyle, minHeight: 80, resize: "vertical" }}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this app do? What should VeriBridge check?"
            />
          </div>

          <div style={fieldWrapStyle}>
            <label style={labelStyle} htmlFor="proof-skills">
              Claimed skills (comma-separated, optional)
            </label>
            <input
              id="proof-skills"
              type="text"
              style={inputStyle}
              value={claimedSkills}
              onChange={(e) => setClaimedSkills(e.target.value)}
              placeholder="React, Node.js, PostgreSQL"
            />
          </div>

          {validationError && (
            <div role="alert" style={{ fontSize: 13, color: "var(--rose)", marginBottom: 16 }}>
              {validationError}
            </div>
          )}

          {submitError && (
            <div
              role="alert"
              style={{
                background: "var(--rose-soft)",
                border: "1px solid var(--rose)",
                borderRadius: 10,
                padding: "12px 16px",
                fontSize: 14,
                color: "var(--ink)",
                marginBottom: 16,
              }}
            >
              {submitError}
            </div>
          )}

          <button type="submit" style={submitting ? disabledButtonStyle : primaryButtonStyle} disabled={submitting}>
            {submitting ? "Creating session…" : "Create Website Proof Session"}
          </button>
        </form>
      )}

      {session && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", marginBottom: 8 }}>
            Website proof session created
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 16 }}>
            <div style={{ fontSize: 13, color: "var(--ink-2)" }}>
              Session ID: <span style={statusChipStyle}>{session.session_id}</span>
            </div>
            <div style={{ fontSize: 13, color: "var(--ink-2)" }}>
              Status: <span style={statusChipStyle}>{session.status}</span>
            </div>
          </div>
          {session.login_url && (
            <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, marginBottom: 16 }}>
              This site needs you to log in. Open the link below and sign in, then return here to continue.
              <br />
              <a href={session.login_url} target="_blank" rel="noreferrer">
                {session.login_url}
              </a>
            </p>
          )}
          <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, marginBottom: 16, opacity: 0.85 }}>
            VeriBridge will use this session to capture evidence from your live app. You can return to the
            Proof Studio to track progress alongside your other proof sources.
          </p>
          <Link href="/student/vbr" style={secondaryLinkStyle}>
            Back to Proof Studio
          </Link>
        </div>
      )}
    </div>
  )
}
