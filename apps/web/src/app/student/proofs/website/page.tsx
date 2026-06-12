"use client"

import Link from "next/link"
import { useState, type CSSProperties, type FormEvent } from "react"
import {
  createWebsiteProofSession,
  resumeWebsiteProofSession,
  getWebsiteProofSession,
  closeWebsiteProofSession,
  type WebsiteProofSessionResponse,
  type WebsiteProofSessionStatus,
} from "@/lib/api"

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

const secondaryButtonStyle: CSSProperties = {
  ...secondaryLinkStyle,
  cursor: "pointer",
}

const disabledSecondaryButtonStyle: CSSProperties = {
  ...secondaryButtonStyle,
  opacity: 0.5,
  cursor: "not-allowed",
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

const infoGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
  gap: 10,
  marginBottom: 16,
}

const infoCellStyle: CSSProperties = {
  fontSize: 13,
  color: "var(--ink-2)",
}

const sectionTitleStyle: CSSProperties = {
  fontSize: 14,
  fontWeight: 700,
  color: "var(--ink)",
  marginBottom: 8,
  marginTop: 20,
}

const previewBoxStyle: CSSProperties = {
  fontSize: 13,
  color: "var(--ink-2)",
  lineHeight: 1.6,
  background: "var(--bg-2)",
  border: "1px solid var(--line)",
  borderRadius: 8,
  padding: 12,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
}

const screenshotStyle: CSSProperties = {
  maxWidth: "100%",
  borderRadius: 8,
  border: "1px solid var(--line)",
  display: "block",
}

const actionRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10,
  marginTop: 16,
  marginBottom: 16,
}

type StatusTone = "info" | "success" | "warning" | "error"

const TONE_STYLES: Record<StatusTone, CSSProperties> = {
  info: { background: "var(--teal-soft)", border: "1px solid var(--teal)" },
  success: { background: "var(--emerald-soft)", border: "1px solid var(--emerald)" },
  warning: { background: "var(--amber-soft)", border: "1px solid var(--amber)" },
  error: { background: "var(--rose-soft)", border: "1px solid var(--rose)" },
}

const STATUS_INFO: Record<WebsiteProofSessionStatus, { label: string; description: string; tone: StatusTone }> = {
  created: {
    label: "Created",
    description: "Session created. VeriBridge is preparing to run the proof workflow.",
    tone: "info",
  },
  running: {
    label: "Running",
    description: "VeriBridge is running the proof workflow now. Refresh status for updates.",
    tone: "info",
  },
  waiting_for_manual_login: {
    label: "Action required",
    description:
      "This site needs you to sign in or complete setup. Open the login link, finish in the new tab, then come back and click \"Resume Proof\".",
    tone: "warning",
  },
  authenticated_ready: {
    label: "Ready to resume",
    description: "Login detected. Click \"Resume Proof\" to continue capturing evidence.",
    tone: "success",
  },
  resumed: {
    label: "Resumed",
    description: "The proof workflow was resumed and is running.",
    tone: "info",
  },
  completed: {
    label: "Completed",
    description: "The proof workflow completed. Review the results below.",
    tone: "success",
  },
  partial: {
    label: "Partially completed",
    description: "Some steps completed and some did not. Review the results below.",
    tone: "warning",
  },
  failed: {
    label: "Failed",
    description: "The proof workflow failed. See the error details below.",
    tone: "error",
  },
  expired: {
    label: "Expired",
    description: "This session has expired. Close it and start a new session.",
    tone: "error",
  },
}

const TERMINAL_STATUSES: WebsiteProofSessionStatus[] = ["completed", "failed", "expired"]

const FINAL_TEXT_PREVIEW_LENGTH = 600

function formatTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
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
  const [closedNotice, setClosedNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<"refresh" | "resume" | "close" | null>(null)
  const [showFullPageText, setShowFullPageText] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const trimmedUrl = websiteUrl.trim()
    if (!trimmedUrl || (!trimmedUrl.startsWith("http://") && !trimmedUrl.startsWith("https://"))) {
      setValidationError("Enter a valid website URL starting with http:// or https://")
      return
    }

    setValidationError(null)
    setSubmitError(null)
    setClosedNotice(null)
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
      setShowFullPageText(false)
      setActionError(null)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create website proof session.")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRefresh() {
    if (!session) return
    setActionError(null)
    setActionLoading("refresh")
    try {
      const result = await getWebsiteProofSession(session.session_id)
      setSession(result)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to refresh session status.")
    } finally {
      setActionLoading(null)
    }
  }

  async function handleResume() {
    if (!session) return
    setActionError(null)
    setActionLoading("resume")
    try {
      const result = await resumeWebsiteProofSession(session.session_id)
      setSession(result)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to resume proof session.")
    } finally {
      setActionLoading(null)
    }
  }

  async function handleClose() {
    if (!session) return
    setActionError(null)
    setActionLoading("close")
    try {
      await closeWebsiteProofSession(session.session_id)
      setSession(null)
      setShowFullPageText(false)
      setClosedNotice("Session closed. You can start a new Website Proof session below.")
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to close session.")
    } finally {
      setActionLoading(null)
    }
  }

  const statusInfo = session ? STATUS_INFO[session.status] : null
  const isTerminal = session ? TERMINAL_STATUSES.includes(session.status) : false
  const actionsDisabled = actionLoading !== null

  const finalPageText = session?.final_page_text ?? null
  const finalPageTextIsLong = (finalPageText?.length ?? 0) > FINAL_TEXT_PREVIEW_LENGTH
  const finalPageTextPreview =
    finalPageText && finalPageTextIsLong && !showFullPageText
      ? `${finalPageText.slice(0, FINAL_TEXT_PREVIEW_LENGTH)}…`
      : finalPageText

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

      {!session && closedNotice && (
        <div
          role="status"
          style={{
            ...TONE_STYLES.success,
            borderRadius: 10,
            padding: "12px 16px",
            fontSize: 14,
            color: "var(--ink)",
            marginBottom: 16,
          }}
        >
          {closedNotice}
        </div>
      )}

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
                ...TONE_STYLES.error,
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

      {session && statusInfo && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)", marginBottom: 8 }}>
            Website proof session
          </h2>

          <div
            role="status"
            style={{
              ...TONE_STYLES[statusInfo.tone],
              borderRadius: 10,
              padding: "12px 16px",
              fontSize: 14,
              color: "var(--ink)",
              lineHeight: 1.5,
              marginBottom: 16,
            }}
          >
            <strong>{statusInfo.label}.</strong> {statusInfo.description}
          </div>

          <div style={infoGridStyle}>
            <div style={infoCellStyle}>
              Session ID
              <br />
              <span style={statusChipStyle}>{session.session_id}</span>
            </div>
            <div style={infoCellStyle}>
              Status
              <br />
              <span style={statusChipStyle}>{session.status}</span>
            </div>
            <div style={infoCellStyle}>
              Auth mode
              <br />
              <span style={statusChipStyle}>{session.auth_mode}</span>
            </div>
            <div style={infoCellStyle}>
              Created
              <br />
              <span style={statusChipStyle}>{formatTimestamp(session.created_at)}</span>
            </div>
            <div style={infoCellStyle}>
              Expires
              <br />
              <span style={statusChipStyle}>{formatTimestamp(session.expires_at)}</span>
            </div>
            <div style={infoCellStyle}>
              Steps run
              <br />
              <span style={statusChipStyle}>{session.steps_run?.length ?? 0}</span>
            </div>
          </div>

          {session.error_message && (
            <div
              role="alert"
              style={{
                ...TONE_STYLES.error,
                borderRadius: 10,
                padding: "12px 16px",
                fontSize: 14,
                color: "var(--ink)",
                marginBottom: 16,
              }}
            >
              {session.error_message}
            </div>
          )}

          {session.login_url && (
            <div
              style={{
                ...TONE_STYLES.warning,
                borderRadius: 10,
                padding: "12px 16px",
                marginBottom: 16,
              }}
            >
              <p style={{ fontSize: 14, color: "var(--ink)", lineHeight: 1.6, marginBottom: 12 }}>
                Complete any required login or setup, then return here and click &quot;Resume Proof&quot;.
              </p>
              <a
                href={session.login_url}
                target="_blank"
                rel="noopener noreferrer"
                style={secondaryLinkStyle}
              >
                Open website login / app
              </a>
              {session.login_screenshot && (
                <div style={{ marginTop: 12 }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={session.login_screenshot} alt="Login page screenshot" style={screenshotStyle} />
                </div>
              )}
            </div>
          )}

          {actionError && (
            <div
              role="alert"
              style={{
                ...TONE_STYLES.error,
                borderRadius: 10,
                padding: "12px 16px",
                fontSize: 14,
                color: "var(--ink)",
                marginBottom: 16,
              }}
            >
              {actionError}
            </div>
          )}

          <div style={actionRowStyle}>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={actionsDisabled}
              style={actionsDisabled ? disabledSecondaryButtonStyle : secondaryButtonStyle}
            >
              {actionLoading === "refresh" ? "Refreshing…" : "Refresh status"}
            </button>
            <button
              type="button"
              onClick={handleResume}
              disabled={actionsDisabled || isTerminal}
              style={actionsDisabled || isTerminal ? disabledSecondaryButtonStyle : secondaryButtonStyle}
            >
              {actionLoading === "resume" ? "Resuming…" : "Resume Proof"}
            </button>
            <button
              type="button"
              onClick={handleClose}
              disabled={actionsDisabled}
              style={actionsDisabled ? disabledSecondaryButtonStyle : secondaryButtonStyle}
            >
              {actionLoading === "close" ? "Closing…" : "Close Session"}
            </button>
          </div>

          {(session.proof_summary || session.final_screenshot || finalPageText || session.steps_run?.length > 0) && (
            <>
              <h3 style={sectionTitleStyle}>Proof result</h3>

              {session.proof_summary && (
                <p style={{ fontSize: 14, color: "var(--ink)", lineHeight: 1.6, marginBottom: 12 }}>
                  {session.proof_summary}
                </p>
              )}

              {session.final_screenshot && (
                <div style={{ marginBottom: 12 }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={session.final_screenshot} alt="Final page screenshot" style={screenshotStyle} />
                </div>
              )}

              {finalPageTextPreview && (
                <div style={{ marginBottom: 12 }}>
                  <div style={previewBoxStyle}>{finalPageTextPreview}</div>
                  {finalPageTextIsLong && (
                    <button
                      type="button"
                      onClick={() => setShowFullPageText((prev) => !prev)}
                      style={{
                        marginTop: 8,
                        background: "none",
                        border: "none",
                        color: "var(--indigo)",
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                        padding: 0,
                      }}
                    >
                      {showFullPageText ? "Show less" : "Show more"}
                    </button>
                  )}
                </div>
              )}

              {session.steps_run?.length > 0 && (
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)", marginBottom: 6 }}>
                    Steps run
                  </div>
                  <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.7 }}>
                    {session.steps_run.map((step, idx) => (
                      <li key={idx}>{step}</li>
                    ))}
                  </ol>
                </div>
              )}
            </>
          )}

          <p style={{ fontSize: 14, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 20, marginBottom: 16, opacity: 0.85 }}>
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
