"use client"

import { Card, CardHeader, TOKEN } from "../../../components/passport/shared"

const sections = [
  {
    icon: "🪪",
    title: "1. Candidates share a Verified Work Passport",
    body: "A candidate sends you a single public link — their Verified Work Passport. It's an evidence-backed index of the projects they've actually built and defended. No login required to view it.",
  },
  {
    icon: "🔍",
    title: "2. You open a Verified Build Report",
    body: "Each featured project links to a recruiter-safe Verified Build Report: what they built, the skills demonstrated, and evidence drawn from their code, deployed app, documents, and a recorded project defense — described qualitatively, never as a score or ranking.",
  },
  {
    icon: "✅",
    title: "3. You request a VBR from your own candidates",
    body: "Ask the candidates in your pipeline to share their Verified Work Passport. It's a fast, honest signal of what someone can really do — grounded in evidence, not self-reported claims.",
  },
]

export default function RecruitersPage() {
  return (
    <div style={{ maxWidth: 820, margin: "0 auto", padding: "56px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
      <div data-testid="recruiters-hero" style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 10 }}>
        <h1 style={{ fontSize: 30, color: TOKEN.ink, margin: 0, letterSpacing: "-0.5px" }}>
          Verify what candidates actually built.
        </h1>
        <p style={{ fontSize: 15, color: TOKEN.muted, margin: "0 auto", maxWidth: 600, lineHeight: 1.6 }}>
          VeriBridge turns a candidate&apos;s real projects into recruiter-safe, evidence-backed reports — so you can
          screen for genuine, demonstrated skill instead of polished résumés.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {sections.map((section) => (
          <Card key={section.title}>
            <CardHeader title={section.title} eyebrow="How it works" icon={section.icon} />
            <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}>{section.body}</p>
          </Card>
        ))}
      </div>

      <Card>
        <div data-testid="recruiters-promise" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <CardHeader title="An honest signal" eyebrow="What we never do" icon="🤝" />
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
            Evidence is always described qualitatively — observed, supporting, or process evidence. We never reduce a
            person to a number, a percentage, or a ranking, and a report is never a guarantee of employment, skill
            mastery, or identity. Candidates choose exactly what they make public.
          </p>
        </div>
      </Card>

      <div style={{ display: "flex", justifyContent: "center" }}>
        <a
          data-testid="recruiters-request-vbr-link"
          href="/recruiters/request-vbr"
          style={{
            padding: "10px 18px",
            borderRadius: 8,
            background: TOKEN.indigo,
            color: "#fff",
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
