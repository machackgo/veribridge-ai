"use client"

import { useState } from "react"

import { Card, CardHeader, TOKEN } from "../../../../components/passport/shared"

/**
 * Public "Request a VBR from your candidates" page (`/recruiters/request-vbr`).
 *
 * Deliberately simple for the link-review MVP: it explains what a Verified
 * Build Report is and gives recruiters a copyable message to send their
 * candidates. No auth, no email capture, no CRM — the only interaction is a
 * local clipboard copy.
 */

const CANDIDATE_MESSAGE = `Hi! As part of our process, we'd like to see verified evidence of a project you've built.

Please create a free VeriBridge Verified Build Report (VBR) for one project — it walks you through attaching your GitHub repo, a live demo or website walkthrough, supporting documents, and a short recorded project defense. Then publish your Verified Work Passport and send us the public link.

It usually takes under an hour, and it lets us review real evidence instead of just a résumé.`

const steps = [
  {
    icon: "🧾",
    title: "What is a Verified Build Report?",
    body: "A VBR is an evidence package for ONE project a candidate actually built: their code, a recorded walkthrough of the running product, supporting documents, and a recorded project defense where they explain their own work. Every claim is described qualitatively and linked to inspectable evidence — never a score.",
  },
  {
    icon: "✉️",
    title: "Ask your candidates",
    body: "Send applicants the message below. Candidates sign up free, build a VBR for one project, and share their public Verified Work Passport link with you.",
  },
  {
    icon: "🔍",
    title: "Review the evidence",
    body: "Open the passport link they send back — no account or login needed on your side. Check the GitHub evidence, runtime walkthroughs, project defense, and the honest limitations before you decide.",
  },
]

export default function RequestVbrPage() {
  const [copied, setCopied] = useState(false)

  const copyMessage = () => {
    navigator.clipboard
      ?.writeText(CANDIDATE_MESSAGE)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2500)
      })
      .catch(() => setCopied(false))
  }

  return (
    <div
      data-testid="request-vbr-page"
      style={{ maxWidth: 720, margin: "0 auto", padding: "56px 24px", display: "flex", flexDirection: "column", gap: 20 }}
    >
      <div style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 10 }}>
        <h1 style={{ fontSize: 28, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px" }}>
          Request a VBR from your candidates
        </h1>
        <p style={{ fontSize: 14, color: TOKEN.muted, margin: "0 auto", maxWidth: 560, lineHeight: 1.6 }}>
          Ask applicants to generate a VeriBridge Verified Build Report for one project — and screen on
          evidence of what they actually built.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {steps.map((step) => (
          <Card key={step.title}>
            <CardHeader title={step.title} eyebrow="How it works" icon={step.icon} />
            <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}>{step.body}</p>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader title="Message to send your candidates" eyebrow="Copy & paste" icon="📋" />
        <pre
          data-testid="request-vbr-message"
          style={{
            whiteSpace: "pre-wrap",
            fontFamily: "inherit",
            fontSize: 12.5,
            color: TOKEN.inkSoft,
            lineHeight: 1.6,
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 8,
            padding: "12px 14px",
            margin: "0 0 10px",
          }}
        >
          {CANDIDATE_MESSAGE}
        </pre>
        <button
          type="button"
          data-testid="request-vbr-copy"
          onClick={copyMessage}
          style={{
            alignSelf: "flex-start",
            padding: "8px 14px",
            borderRadius: 8,
            background: TOKEN.indigo,
            color: "#fff",
            fontSize: 13,
            fontWeight: 600,
            border: "none",
            cursor: "pointer",
          }}
        >
          {copied ? "Copied ✓" : "Copy message"}
        </button>
      </Card>

      <p style={{ fontSize: 12, color: TOKEN.muted, textAlign: "center", margin: 0 }}>
        A VBR is never an employment certification or background check — it is inspectable evidence.{" "}
        <a href="/recruiters" style={{ color: TOKEN.indigo, textDecoration: "none" }}>
          See how VeriBridge works →
        </a>
      </p>
    </div>
  )
}
