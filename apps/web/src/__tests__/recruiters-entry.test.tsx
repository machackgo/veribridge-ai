/**
 * Recruiter V1 entry (`/recruiters`) — signed-out entry experience and
 * routing hygiene.
 *
 * The entry page is the canonical "Recruiters" destination: signed-out
 * visitors get a sign-in/create-account experience that funnels into the
 * one real workspace; signed-in visitors are redirected server-side. The
 * old /recruiter/* prototype (fabricated sample candidates) must be
 * unreachable from normal navigation.
 */

import { readFileSync } from "node:fs"
import { join } from "node:path"
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { RecruitersEntryView } from "../app/recruiters/RecruitersEntryView"

const LOGIN_HREF = "/login?next=%2Frecruiters%2Fworkspace"

describe("RecruitersEntryView — signed-out entry", () => {
  it("presents the Recruiter Workspace hero with the saved-candidates promise", () => {
    render(<RecruitersEntryView />)
    expect(screen.getByTestId("recruiters-hero")).toBeInTheDocument()
    expect(screen.getByRole("heading", { level: 1, name: /recruiter workspace/i })).toBeInTheDocument()
    expect(screen.getByText(/candidates you have saved from VeriBridge AI Passports/i)).toBeInTheDocument()
  })

  it("routes Sign in and Create recruiter account through the existing login flow to the workspace", () => {
    render(<RecruitersEntryView />)
    expect(screen.getByTestId("recruiters-signin-link")).toHaveAttribute("href", LOGIN_HREF)
    expect(screen.getByTestId("recruiters-create-account-link")).toHaveAttribute("href", LOGIN_HREF)
  })

  it("keeps the open-report and request-VBR paths available", () => {
    render(<RecruitersEntryView />)
    expect(screen.getByTestId("recruiters-open-report-link")).toHaveAttribute("href", "/recruiters/open")
    expect(screen.getByTestId("recruiters-request-vbr-link")).toHaveAttribute("href", "/recruiters/request-vbr")
  })

  it("shows no fabricated candidates, scores, or pipeline metrics", () => {
    const { container } = render(<RecruitersEntryView />)
    const text = container.textContent ?? ""
    for (const banned of [
      "Maya Reyes",
      "Jordan Kim",
      "Arjun Singh",
      "Stripe Early Talent",
      "match",
      "Trust score",
      "Pipeline",
      "Job Posts",
    ]) {
      expect(text).not.toContain(banned)
    }
  })
})

describe("/recruiters page — auth-aware entry (source contract)", () => {
  const src = readFileSync(join(process.cwd(), "src/app/recruiters/page.tsx"), "utf8")

  it("checks the real Supabase session server-side", () => {
    expect(src).toContain("createSupabaseServerClient")
    expect(src).toContain("auth.getUser()")
  })

  it("sends signed-in recruiters straight to the real workspace", () => {
    expect(src).toContain('redirect("/recruiters/workspace")')
  })
})

describe("main navigation — no path into the removed prototype", () => {
  it("landing page links point at /recruiters, never the old /recruiter console", () => {
    const landing = readFileSync(
      join(process.cwd(), "components/landing-v2/LandingV2.tsx"),
      "utf8",
    )
    expect(landing).not.toContain('href="/recruiter"')
    expect(landing).toContain('"/recruiters"')
  })
})
