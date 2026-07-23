/**
 * Account/Settings consolidation + Google account-chooser regression guards.
 *
 * Covers:
 *  - /dashboard/profile and /dashboard/settings never render the legacy UI
 *    again — they redirect to the canonical /student/account and
 *    /student/settings routes.
 *  - The new Account page renders only real session data (name/email/id/
 *    provider), shows a neutral "Not provided" state for absent fields, and
 *    contains none of the legacy sample-persona content.
 *  - The new Settings page exposes only implemented controls (sign out,
 *    links to real sharing surfaces) — no inert toggles, no sample data.
 *  - "Continue with Google" calls signInWithOAuth with
 *    queryParams.prompt=select_account so Google shows its account chooser
 *    after a VeriBridge sign-out, and OAuth is never auto-triggered on load.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"

const redirectMock = vi.fn((path: string) => {
  // Mirror Next.js semantics: redirect() throws and never returns.
  throw new Error(`NEXT_REDIRECT:${path}`)
})

const routerPush = vi.fn()
const routerRefresh = vi.fn()

vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirectMock(path),
  useRouter: () => ({ push: routerPush, refresh: routerRefresh }),
  useSearchParams: () => ({ get: (_k: string) => null }),
}))

const getUserMock = vi.fn()

vi.mock("../lib/supabase/server", () => ({
  createSupabaseServerClient: async () => ({ auth: { getUser: getUserMock } }),
}))

const signInWithOtp = vi.fn()
const verifyOtp = vi.fn()
const signInWithOAuth = vi.fn()
const signOutMock = vi.fn()

vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: () => ({
    auth: { signInWithOtp, verifyOtp, signInWithOAuth, signOut: signOutMock },
  }),
}))

import LegacyProfilePage from "../app/dashboard/profile/page"
import LegacySettingsPage from "../app/dashboard/settings/page"
import AccountPage from "../app/student/account/page"
import SettingsPage from "../app/student/settings/page"
import LoginPage from "../app/login/page"

const REAL_USER = {
  id: "11111111-2222-3333-4444-555555555555",
  email: "student@example.edu",
  created_at: "2026-07-01T10:00:00Z",
  last_sign_in_at: "2026-07-22T08:30:00Z",
  user_metadata: { full_name: "Real Student" },
  app_metadata: { provider: "email", providers: ["email", "google"] },
}

const LEGACY_SAMPLE_MARKERS = [/maya reyes/i, /gpa/i, /visa/i, /sample data/i, /job match/i]

beforeEach(() => {
  redirectMock.mockClear()
  getUserMock.mockReset().mockResolvedValue({ data: { user: REAL_USER }, error: null })
  signInWithOtp.mockReset()
  verifyOtp.mockReset()
  signInWithOAuth.mockReset()
  signOutMock.mockReset().mockResolvedValue({ error: null })
  routerPush.mockReset()
  routerRefresh.mockReset()
})

describe("legacy route redirects", () => {
  it("/dashboard/profile redirects to /student/account without rendering legacy UI", () => {
    expect(() => LegacyProfilePage()).toThrowError("NEXT_REDIRECT:/student/account")
    expect(redirectMock).toHaveBeenCalledWith("/student/account")
  })

  it("/dashboard/settings redirects to /student/settings without rendering legacy UI", () => {
    expect(() => LegacySettingsPage()).toThrowError("NEXT_REDIRECT:/student/settings")
    expect(redirectMock).toHaveBeenCalledWith("/student/settings")
  })
})

describe("/student/account page", () => {
  it("renders only real session identity and the sign-out action", async () => {
    render(await AccountPage())
    const page = screen.getByTestId("student-account-page")
    expect(page).toHaveTextContent("Real Student")
    expect(page).toHaveTextContent("student@example.edu")
    expect(page).toHaveTextContent(REAL_USER.id)
    expect(page).toHaveTextContent(/google/i)
    expect(screen.getByTestId("account-signout")).toBeInTheDocument()
    for (const marker of LEGACY_SAMPLE_MARKERS) {
      expect(page.textContent).not.toMatch(marker)
    }
  })

  it("shows neutral 'Not provided' states instead of inventing missing fields", async () => {
    getUserMock.mockResolvedValue({
      data: {
        user: {
          ...REAL_USER,
          user_metadata: {},
          app_metadata: {},
          last_sign_in_at: null,
        },
      },
      error: null,
    })
    render(await AccountPage())
    const page = screen.getByTestId("student-account-page")
    expect(page.textContent).toContain("Not provided")
    expect(page.textContent).not.toMatch(/maya reyes/i)
  })

  it("sign-out from the Account page clears the local session and lands on /login", async () => {
    render(await AccountPage())
    fireEvent.click(screen.getByTestId("account-signout"))
    await waitFor(() => expect(signOutMock).toHaveBeenCalledWith({ scope: "local" }))
    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/login"))
    expect(routerRefresh).toHaveBeenCalled()
  })
})

describe("/student/settings page", () => {
  it("exposes only implemented controls: sign out and links to real sharing surfaces", async () => {
    render(await SettingsPage())
    const page = screen.getByTestId("student-settings-page")
    expect(page).toHaveTextContent("student@example.edu")
    expect(screen.getByTestId("settings-signout")).toBeInTheDocument()

    const hrefs = Array.from(page.querySelectorAll("a")).map((a) => a.getAttribute("href"))
    expect(hrefs).toContain("/student/vbr/passport")
    expect(hrefs).toContain("/student/vbr/passport/vault")
    // No link may lead back into the legacy dashboard shell.
    expect(hrefs.some((h) => h?.startsWith("/dashboard"))).toBe(false)

    // No inert form controls: every element that looks interactive must be real.
    const checkboxes = page.querySelectorAll("input[type=checkbox], input[type=radio], select")
    expect(checkboxes.length).toBe(0)

    for (const marker of LEGACY_SAMPLE_MARKERS) {
      expect(page.textContent).not.toMatch(marker)
    }
  })
})

describe("Google OAuth account chooser", () => {
  it("never auto-triggers OAuth on /login load", () => {
    render(<LoginPage />)
    expect(signInWithOAuth).not.toHaveBeenCalled()
  })

  it("requests Google's account chooser via prompt=select_account on click", async () => {
    signInWithOAuth.mockResolvedValue({ error: null })
    render(<LoginPage />)
    fireEvent.click(screen.getByTestId("google-signin-btn"))

    await waitFor(() => expect(signInWithOAuth).toHaveBeenCalledTimes(1))
    const call = signInWithOAuth.mock.calls[0][0]
    expect(call.provider).toBe("google")
    expect(call.options.queryParams).toEqual({ prompt: "select_account" })
    expect(call.options.redirectTo).toContain("/auth/callback")
  })
})
