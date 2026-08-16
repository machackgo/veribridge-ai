"use client"

/**
 * Recruiter entry experience for signed-out visitors (`/recruiters`).
 *
 * Everything here routes into the one real Recruiter V1 surface — the
 * Saved Candidates workspace — through the existing `/login?next=…` flow
 * (OTP or Google; the same flow creates the account on first sign-in).
 * No sample candidates, scores, or invented metrics appear anywhere.
 */

import { Card, CardHeader, TOKEN } from "../../../components/passport/shared"

const LOGIN_HREF = `/login?next=${encodeURIComponent("/recruiters/workspace")}`

const steps = [
  {
    icon: "🪪",
    title: "1. A candidate shares their Work Passport — or you find them",
    body: "Candidates hand you a QR code or a public link to their Verified Work Passport — an evidence-backed index of the projects they've actually built and defended. You can also search every published passport by skill, technology, or project, with each result explained by real evidence.",
  },
  {
    icon: "📌",
    title: "2. You save the candidates worth keeping",
    body: "Press “Save Candidate” on any passport or search result — from a QR scan at a career fair, a shared link, or search — and they land in your workspace with the date and source recorded. Saves are private to you.",
  },
  {
    icon: "🔍",
    title: "3. You review real evidence, any time",
    body: "Reopen a saved candidate's passport and their Verified Build Reports: what they built, the skills demonstrated, and evidence from their code, deployed app, documents, and recorded project defense — described qualitatively, never as a score.",
  },
]

export function RecruitersEntryView() {
  return (
    <div
      style={{
        maxWidth: 860,
        margin: "0 auto",
        padding: "56px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 22,
      }}
    >
      <div
        data-testid="recruiters-hero"
        style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 12 }}
      >
        <p
          style={{
            fontSize: 11.5,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: TOKEN.muted,
            margin: 0,
            fontWeight: 700,
          }}
        >
          For recruiters
        </p>
        <h1 style={{ fontSize: 32, color: TOKEN.ink, margin: 0, letterSpacing: "-0.6px" }}>
          Recruiter Workspace
        </h1>
        <p
          style={{
            fontSize: 15,
            color: TOKEN.muted,
            margin: "0 auto",
            maxWidth: 560,
            lineHeight: 1.6,
          }}
        >
          Search candidates who published a Verified Work Passport, and access
          candidates you have saved from VeriBridge Passports — real people, real
          evidence, saved by you from a QR scan, a shared link, or search.
        </p>
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            gap: 10,
            flexWrap: "wrap",
            marginTop: 6,
          }}
        >
          <a
            data-testid="recruiters-signin-link"
            href={LOGIN_HREF}
            style={{
              padding: "11px 22px",
              borderRadius: 9,
              background: TOKEN.indigo,
              color: "#fff",
              fontSize: 13.5,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            Sign in
          </a>
          <a
            data-testid="recruiters-create-account-link"
            href={LOGIN_HREF}
            style={{
              padding: "11px 22px",
              borderRadius: 9,
              border: `1px solid ${TOKEN.line}`,
              background: "#fff",
              color: TOKEN.ink,
              fontSize: 13.5,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            Create recruiter account
          </a>
        </div>
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
          One account, one flow — signing in for the first time creates your recruiter
          account automatically.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {steps.map((step) => (
          <Card key={step.title}>
            <CardHeader title={step.title} eyebrow="How it works" icon={step.icon} />
            <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}>
              {step.body}
            </p>
          </Card>
        ))}
      </div>

      <Card>
        <div data-testid="recruiters-promise" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <CardHeader title="An honest signal" eyebrow="What we never do" icon="🤝" />
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
            Evidence is always described qualitatively — observed, supporting, or process
            evidence. We never reduce a person to a number, a percentage, or a ranking, and
            a report is never a guarantee of employment, skill mastery, or identity.
            Candidates choose exactly what they make public.
          </p>
        </div>
      </Card>

      <div style={{ display: "flex", justifyContent: "center", gap: 8, flexWrap: "wrap" }}>
        <a
          data-testid="recruiters-open-report-link"
          href="/recruiters/open"
          style={{
            padding: "10px 18px",
            borderRadius: 8,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
            color: TOKEN.ink,
            fontSize: 13,
            fontWeight: 600,
            textDecoration: "none",
          }}
        >
          Open a report link or QR
        </a>
        <a
          data-testid="recruiters-request-vbr-link"
          href="/recruiters/request-vbr"
          style={{
            padding: "10px 18px",
            borderRadius: 8,
            border: `1px solid ${TOKEN.line}`,
            background: "#fff",
            color: TOKEN.ink,
            fontSize: 13,
            fontWeight: 600,
            textDecoration: "none",
          }}
        >
          Request a VBR from your candidates
        </a>
      </div>

      <p style={{ fontSize: 12, color: TOKEN.muted, textAlign: "center", margin: 0 }}>
        Have a candidate&apos;s passport link? Open it to see their Verified Build Reports.
      </p>
    </div>
  )
}
