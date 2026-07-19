/**
 * Login email-verification (OTP) flow — code-length correctness.
 *
 * Regression guard for the manual-QA bug where Supabase was configured to email
 * an 8-digit verification code but the login input hard-capped at 6 digits, so
 * the full code could never be typed and email-code login was blocked.
 *
 * The code is generated and verified by Supabase; these tests only assert that
 * the UI accepts the real length and forwards the complete code to
 * `verifyOtp` — they never weaken or bypass verification.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import LoginPage from "../app/login/page"

const signInWithOtp = vi.fn()
const verifyOtp = vi.fn()
const signInWithOAuth = vi.fn()

vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: () => ({
    auth: { signInWithOtp, verifyOtp, signInWithOAuth },
  }),
}))

const routerPush = vi.fn()
const routerRefresh = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, refresh: routerRefresh }),
  useSearchParams: () => ({ get: (_k: string) => "/dashboard" }),
}))

const EMAIL = "maya.reyes@wpi.edu"
const CODE_8 = "48210573"

async function goToOtpStep() {
  render(<LoginPage />)
  signInWithOtp.mockResolvedValue({ error: null })
  fireEvent.change(screen.getByTestId("email-input"), { target: { value: EMAIL } })
  fireEvent.click(screen.getByRole("button", { name: /send verification code/i }))
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /enter your verification code/i })).toBeInTheDocument()
  )
  return screen.getByTestId("otp-input") as HTMLInputElement
}

beforeEach(() => {
  signInWithOtp.mockReset()
  verifyOtp.mockReset()
  signInWithOAuth.mockReset()
  routerPush.mockReset()
  routerRefresh.mockReset()
})

describe("login OTP code length", () => {
  it("accepts a full 8-digit code without truncating it", async () => {
    const input = await goToOtpStep()
    fireEvent.change(input, { target: { value: CODE_8 } })
    expect(input.value).toBe(CODE_8)
    expect(input.maxLength).toBe(8)
  })

  it("does not truncate the code below the configured length (strips overflow only)", async () => {
    const input = await goToOtpStep()
    fireEvent.change(input, { target: { value: "482105739999" } })
    // First 8 digits preserved; only the overflow beyond the code length is dropped.
    expect(input.value).toBe(CODE_8)
  })

  it("sends the complete 8-digit code to Supabase verifyOtp", async () => {
    verifyOtp.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null })
    const input = await goToOtpStep()
    fireEvent.change(input, { target: { value: CODE_8 } })
    fireEvent.click(screen.getByRole("button", { name: /verify and continue/i }))

    await waitFor(() => expect(verifyOtp).toHaveBeenCalledTimes(1))
    expect(verifyOtp).toHaveBeenCalledWith({ email: EMAIL, token: CODE_8, type: "email" })
  })

  it("blocks submission and shows a clear 8-digit error for a short code", async () => {
    const input = await goToOtpStep()
    fireEvent.change(input, { target: { value: "123456" } })
    fireEvent.click(screen.getByRole("button", { name: /verify and continue/i }))

    await waitFor(() =>
      expect(screen.getByTestId("error-banner")).toHaveTextContent(/8-digit code/i)
    )
    expect(verifyOtp).not.toHaveBeenCalled()
  })

  it("surfaces a clear error when Supabase rejects an invalid/expired code", async () => {
    verifyOtp.mockResolvedValue({ data: { session: null }, error: new Error("Invalid or expired OTP") })
    const input = await goToOtpStep()
    fireEvent.change(input, { target: { value: CODE_8 } })
    fireEvent.click(screen.getByRole("button", { name: /verify and continue/i }))

    await waitFor(() =>
      expect(screen.getByTestId("error-banner")).toHaveTextContent(/incorrect or expired code/i)
    )
    expect(routerPush).not.toHaveBeenCalled()
  })

  it("redirects to the next destination after a successful verification", async () => {
    verifyOtp.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null })
    const input = await goToOtpStep()
    fireEvent.change(input, { target: { value: CODE_8 } })
    fireEvent.click(screen.getByRole("button", { name: /verify and continue/i }))

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/dashboard"))
  })
})
