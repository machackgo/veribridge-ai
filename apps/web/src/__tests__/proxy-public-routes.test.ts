/**
 * Regression tests for the auth proxy public-route allowlist (Gate 14).
 *
 * Gate 13 found that anonymous recruiters hitting the app's own published
 * share links were redirected to /login, because the proxy allowlist did not
 * include the current tokenized public routes:
 *   • /vbr/report/<token>  — published Verified Build Report
 *   • /p/<slug>[/skills/…] — published public Work Passport + Skill Report
 * (The bug was masked locally by NEXT_PUBLIC_DEMO_MODE=true, which bypasses
 *  the proxy entirely, so it only surfaced in production.)
 *
 * These tests pin the contract with the DEMO_MODE bypass OFF:
 *   • published report / passport open anonymously (no redirect);
 *   • protected app routes still redirect an anonymous user to /login;
 *   • an authenticated user is allowed through protected routes.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"

const getSession = vi.fn()

vi.mock("@supabase/ssr", () => ({
  createServerClient: () => ({
    auth: { getSession },
  }),
}))

import { proxy } from "@/proxy"

const ORIGIN = "https://veribridgeai.com"

function req(pathname: string): NextRequest {
  return new NextRequest(new URL(pathname, ORIGIN))
}

function locationOf(res: Response): string | null {
  return res.headers.get("location")
}

beforeEach(() => {
  // Ensure the DEMO_MODE bypass is OFF for every test (production behaviour).
  delete process.env.NEXT_PUBLIC_DEMO_MODE
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co"
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key"
  getSession.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("proxy public-route allowlist — anonymous", () => {
  beforeEach(() => {
    getSession.mockResolvedValue({ data: { session: null } })
  })

  it("lets an anonymous user open a published Verified Build Report", async () => {
    const res = await proxy(req("/vbr/report/zHVHUqVsg_-gwUV_B_aEPpfyhE93VnqR"))
    expect(res.status).not.toBe(307)
    expect(locationOf(res)).toBeNull()
  })

  it("lets an anonymous user open a published public Work Passport", async () => {
    const res = await proxy(req("/p/EJZb5dKMQuU"))
    expect(res.status).not.toBe(307)
    expect(locationOf(res)).toBeNull()
  })

  it("lets an anonymous user open a public Skill Report under a passport", async () => {
    const res = await proxy(req("/p/EJZb5dKMQuU/skills/api-development"))
    expect(locationOf(res)).toBeNull()
  })

  it("keeps the legacy public report route open", async () => {
    const res = await proxy(req("/r/sometoken"))
    expect(locationOf(res)).toBeNull()
  })

  it("lets an anonymous recruiter open a public Passport Card", async () => {
    const res = await proxy(req("/card/EJZb5dKMQuU"))
    expect(res.status).not.toBe(307)
    expect(locationOf(res)).toBeNull()
  })

  it("lets an anonymous recruiter open a Beam short link", async () => {
    const res = await proxy(req("/b/AbCdEf123456AbCd"))
    expect(res.status).not.toBe(307)
    expect(locationOf(res)).toBeNull()
  })

  it("keeps the owner-only /beam surface protected despite the /b/ prefix", async () => {
    const res = await proxy(req("/beam"))
    expect(res.status).toBe(307)
    expect(locationOf(res)).toContain("/login")
  })

  it("keeps the recruiter opener open", async () => {
    const res = await proxy(req("/recruiters/open"))
    expect(locationOf(res)).toBeNull()
  })

  it("does NOT expose the private dashboard to an anonymous user", async () => {
    const res = await proxy(req("/dashboard"))
    expect(res.status).toBe(307)
    expect(locationOf(res)).toBe(`${ORIGIN}/login?next=%2Fdashboard`)
  })

  it("does NOT expose the private student workspace to an anonymous user", async () => {
    const res = await proxy(req("/student/vbr"))
    expect(res.status).toBe(307)
    expect(locationOf(res)).toContain("/login?next=%2Fstudent%2Fvbr")
  })

  it("keeps the owner-only passport dashboard protected", async () => {
    // /dashboard/passport is the owner's private surface — must stay gated
    // even though /p/ (the published, slug-gated projection) is public.
    const res = await proxy(req("/dashboard/passport"))
    expect(res.status).toBe(307)
    expect(locationOf(res)).toContain("/login")
  })

  it("does not treat /privacy or /passport as public via the /p/ prefix", async () => {
    // /p/ must match the published-passport route only, not sibling paths.
    const privacy = await proxy(req("/dashboard/privacy"))
    expect(privacy.status).toBe(307)
    const passportSlug = await proxy(req("/passport/EJZb5dKMQuU"))
    // /passport/<slug> is a separate route and is NOT in the allowlist.
    expect(passportSlug.status).toBe(307)
  })
})

describe("proxy — authenticated", () => {
  beforeEach(() => {
    getSession.mockResolvedValue({
      data: { session: { access_token: "jwt", user: { id: "u1" } } },
    })
  })

  it("allows an authenticated user through a protected route", async () => {
    const res = await proxy(req("/student/vbr"))
    expect(locationOf(res)).toBeNull()
  })
})
