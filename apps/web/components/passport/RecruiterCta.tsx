"use client"

import { Card, TOKEN } from "./shared"

/**
 * The public recruiter CTA — shared by the public Passport and the public
 * Skill Report. Static, link-only (no form, no data capture): the primary
 * action goes to the public `/recruiters/request-vbr` explainer and the
 * secondary to the `/recruiters` overview. Safe on any public surface.
 */
export function RecruiterCta() {
  return (
    <Card>
      <div
        data-testid="recruiter-cta"
        style={{
          textAlign: "center",
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: "8px 0",
        }}
      >
        <h2 style={{ fontSize: 16, color: TOKEN.ink, margin: 0 }}>
          Want candidates to send proof-backed reports?
        </h2>
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
          Ask applicants to generate a VeriBridge Verified Build Report for one project.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
          <a
            data-testid="recruiter-cta-request-vbr"
            href="/recruiters/request-vbr"
            style={{
              padding: "8px 14px",
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
          <a
            data-testid="recruiter-cta-how-it-works"
            href="/recruiters"
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: `1px solid ${TOKEN.line}`,
              background: "#fff",
              color: TOKEN.inkSoft,
              fontSize: 13,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            See how VeriBridge works
          </a>
        </div>
      </div>
    </Card>
  )
}
