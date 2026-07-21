"use client"

import { useId, useState } from "react"
import { useRouter } from "next/navigation"

import { ReportScanner } from "../../../../components/recruiter/ReportScanner"
import { RecruiterCta } from "../../../../components/passport/RecruiterCta"
import { Card, CardHeader, TOKEN } from "../../../../components/passport/shared"
import {
  parseReportLink,
  REPORT_LINK_REJECTION_MESSAGES,
  type ReportLinkParse,
} from "@/lib/report-link"
import { markReportOpenSource } from "@/lib/report-view-beacon"

/**
 * Recruiter open/scan page — the no-account entry point for a candidate's
 * Verified Build Report. A recruiter can paste the full public report URL,
 * paste just the public token, or (where the browser supports it) scan the
 * candidate's QR code with the device camera.
 *
 * Every path funnels through `parseReportLink`, which only ever yields an
 * internally constructed same-app route — pasted or scanned content is never
 * navigated to directly, so arbitrary/malicious URLs cannot redirect anyone.
 */
export default function RecruiterOpenPage() {
  const router = useRouter()
  const inputId = useId()
  const [value, setValue] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)
  const [scannerOpen, setScannerOpen] = useState(false)

  const openParsed = (parse: Extract<ReportLinkParse, { ok: true }>, scanned: boolean) => {
    setError(null)
    setOpening(true)
    markReportOpenSource(scanned ? "recruiter_scan" : "recruiter_open")
    router.push(parse.path)
  }

  const submit = () => {
    const parse = parseReportLink(value)
    if (!parse.ok) {
      setError(REPORT_LINK_REJECTION_MESSAGES[parse.reason])
      return
    }
    openParsed(parse, false)
  }

  return (
    <div
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "56px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}
    >
      <div data-testid="recruiter-open-hero" style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 8 }}>
        <h1 style={{ fontSize: 28, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px" }}>
          Open a Verified Build Report
        </h1>
        <p style={{ fontSize: 14, color: TOKEN.muted, margin: "0 auto", maxWidth: 540, lineHeight: 1.6 }}>
          Paste the report link a candidate shared with you — or scan their QR code.
          No account needed.
        </p>
      </div>

      <Card>
        <form
          data-testid="recruiter-open-form"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
          style={{ display: "flex", flexDirection: "column", gap: 10 }}
        >
          <CardHeader title="Paste a report link or token" eyebrow="Open a report" icon="🔗" />
          <label htmlFor={inputId} style={{ fontSize: 12.5, fontWeight: 600, color: TOKEN.inkSoft }}>
            Report link or public token
          </label>
          <input
            id={inputId}
            data-testid="recruiter-open-input"
            type="text"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            placeholder="https://…/vbr/report/… or the report token"
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              if (error) setError(null)
            }}
            style={{
              padding: "11px 12px",
              borderRadius: 10,
              border: `1px solid ${error ? "#e11d48" : TOKEN.line}`,
              fontSize: 13.5,
              color: TOKEN.ink,
              background: "#ffffff",
              outlineColor: TOKEN.indigo,
            }}
          />
          {error && (
            <p
              data-testid="recruiter-open-error"
              role="alert"
              style={{ fontSize: 12.5, color: "#be123c", margin: 0, lineHeight: 1.5 }}
            >
              {error}
            </p>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="submit"
              data-testid="recruiter-open-submit"
              disabled={opening}
              style={{
                padding: "10px 18px",
                borderRadius: 8,
                border: "none",
                background: TOKEN.indigo,
                color: "#fff",
                fontSize: 13,
                fontWeight: 600,
                cursor: opening ? "default" : "pointer",
                opacity: opening ? 0.7 : 1,
              }}
            >
              {opening ? "Opening…" : "Open report"}
            </button>
            {!scannerOpen && (
              <button
                type="button"
                data-testid="recruiter-open-scan-button"
                onClick={() => setScannerOpen(true)}
                style={{
                  padding: "10px 18px",
                  borderRadius: 8,
                  border: `1px solid ${TOKEN.line}`,
                  background: "#ffffff",
                  color: TOKEN.ink,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Scan a QR code
              </button>
            )}
          </div>
        </form>

        {scannerOpen && (
          <div style={{ marginTop: 12 }}>
            <ReportScanner
              onResult={(parse) => {
                setScannerOpen(false)
                openParsed(parse, true)
              }}
              onClose={() => setScannerOpen(false)}
            />
          </div>
        )}
      </Card>

      <Card>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <CardHeader title="What you'll see" eyebrow="Recruiter-safe" icon="🛡️" />
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
            A Verified Build Report only opens while the candidate keeps it published,
            and only shows recruiter-safe, qualitative evidence — never private files,
            recordings, scores, or rankings. Links that don&apos;t point to a VeriBridge
            report are rejected rather than opened.
          </p>
        </div>
      </Card>

      <RecruiterCta />
    </div>
  )
}
