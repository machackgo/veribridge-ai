"use client"

import { Card, CardHeader, TOKEN } from "./shared"

/**
 * Recruiter-facing framing for the public Passport / public Skill Report:
 * what this surface is, what backs the claims, and — explicitly — what it is
 * NOT (an employment certification or background check). Static copy only;
 * safe on any public surface.
 */

const TRUST_STATEMENTS = [
  "This Passport summarizes public-safe proof submitted by the candidate.",
  "Claims are backed by evidence types such as GitHub, website walkthroughs, documents, project defense, and video proof where available.",
  "VeriBridge separates direct skill evidence from project context and vault-only/suggested evidence.",
  "This is not an employment certification or background check.",
  "Inspect the linked evidence before making hiring decisions.",
]

export function RecruiterTrustFraming() {
  return (
    <Card>
      <div data-testid="recruiter-trust-framing" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <CardHeader title="How to read this Passport" eyebrow="For recruiters" icon="🧭" />
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {TRUST_STATEMENTS.map((line) => (
            <li key={line} style={{ fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.6 }}>
              {line}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

const REVIEW_CHECKLIST = [
  "Check GitHub / code evidence — open the linked public repository or code lines.",
  "Check website / runtime evidence — open the live URL where one is available.",
  "Check the project defense explanation — does the candidate explain their own work?",
  "Check document / video support — treat these as corroboration, not primary proof.",
  "Review the limitations — every section states honestly what was not verified.",
  "Ask follow-up questions where evidence is partial or marked “Needs review”.",
]

export function RecruiterReviewChecklist() {
  return (
    <Card>
      <div data-testid="recruiter-review-checklist" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <CardHeader title="Recruiter review checklist" eyebrow="Before you decide" icon="✅" />
        <ol style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {REVIEW_CHECKLIST.map((line) => (
            <li key={line} style={{ fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.6 }}>
              {line}
            </li>
          ))}
        </ol>
      </div>
    </Card>
  )
}
