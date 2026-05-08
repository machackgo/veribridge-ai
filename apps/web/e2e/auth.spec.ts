/**
 * Auth flow tests — login page UI and .edu validation.
 *
 * Network calls to Supabase are intercepted with page.route() so these
 * tests are fully deterministic and require no real Supabase credentials.
 *
 * What is tested:
 *  - Login page renders with required UI elements
 *  - Non-.edu email shows a validation error (no network call needed)
 *  - .edu email + mocked OTP send → transitions to OTP screen
 *  - OTP screen has correct UI elements
 *  - Invalid OTP + mocked verify error → shows error message
 *  - "Change email" returns to email step
 *  - "Back to home" navigates to landing page
 */

import { expect, test } from "@playwright/test"

// ── Helpers ───────────────────────────────────────────────────────────────────

const EDU_EMAIL = "maya.reyes@wpi.edu"
const NON_EDU_EMAIL = "user@gmail.com"
const VALID_OTP = "123456"

/** Intercept Supabase OTP-send and return a success stub. */
async function mockOtpSend(page: Parameters<typeof page.route>[0]) {
  await page.route("**/auth/v1/otp**", async route => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ message_id: "test-msg" }),
    })
  })
}

/** Intercept Supabase OTP-verify and return a session stub. */
async function mockOtpVerifySuccess(page: Parameters<typeof page.route>[0]) {
  await page.route("**/auth/v1/verify**", async route => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "fake-access-token",
        token_type: "bearer",
        expires_in: 3600,
        refresh_token: "fake-refresh-token",
        user: {
          id: "test-uuid-1234",
          email: EDU_EMAIL,
          aud: "authenticated",
          role: "authenticated",
        },
      }),
    })
  })
}

/** Intercept Supabase OTP-verify and return an error stub. */
async function mockOtpVerifyFailure(page: Parameters<typeof page.route>[0]) {
  await page.route("**/auth/v1/verify**", async route => {
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        code: "otp_expired",
        message: "Invalid or expired OTP",
      }),
    })
  })
}

// ── Login page renders ─────────────────────────────────────────────────────────

test.describe("Login page — renders", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login")
  })

  test("shows the VeriBridge AI brand", async ({ page }) => {
    await expect(page.getByText("VeriBridge AI")).toBeVisible()
  })

  test("shows the sign-in headline", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /sign in with your \.edu email/i })
    ).toBeVisible()
  })

  test("has an email input", async ({ page }) => {
    await expect(page.getByTestId("email-input")).toBeVisible()
  })

  test("has a Send verification code button", async ({ page }) => {
    await expect(
      page.getByRole("button", { name: /send verification code/i })
    ).toBeVisible()
  })

  test("shows the .edu-only note", async ({ page }) => {
    await expect(
      page.getByText(/currently available for verified \.edu students/i)
    ).toBeVisible()
  })

  test("has a Back to home link", async ({ page }) => {
    await expect(page.getByRole("link", { name: /back to home/i })).toBeVisible()
  })

  test("Back to home navigates to landing page", async ({ page }) => {
    await page.getByRole("link", { name: /back to home/i }).click()
    await expect(page).toHaveURL("/")
  })
})

// ── Email validation ───────────────────────────────────────────────────────────

test.describe("Login page — .edu validation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login")
  })

  test("shows error for non-.edu email", async ({ page }) => {
    await page.getByTestId("email-input").fill(NON_EDU_EMAIL)
    await page.getByRole("button", { name: /send verification code/i }).click()
    await expect(page.getByTestId("error-banner")).toContainText(/\.edu students/)
  })

  test("shows error for Gmail address", async ({ page }) => {
    await page.getByTestId("email-input").fill("student@gmail.com")
    await page.getByRole("button", { name: /send verification code/i }).click()
    await expect(page.getByTestId("error-banner")).toBeVisible()
  })

  test("shows error for empty submission", async ({ page }) => {
    await page.getByRole("button", { name: /send verification code/i }).click()
    await expect(page.getByTestId("error-banner")).toBeVisible()
  })

  test("does NOT show error for valid .edu email (before network)", async ({
    page,
  }) => {
    // The error should not appear until after the network call resolves.
    // With mocked OTP send, we check that the page transitions normally.
    await mockOtpSend(page)
    await page.getByTestId("email-input").fill(EDU_EMAIL)
    await page.getByRole("button", { name: /send verification code/i }).click()
    // Should NOT see the .edu error
    await expect(page.getByTestId("error-banner")).not.toBeVisible()
  })
})

// ── OTP step ──────────────────────────────────────────────────────────────────

test.describe("Login page — OTP screen", () => {
  async function goToOtpStep(page: Parameters<typeof mockOtpSend>[0]) {
    await page.goto("/login")
    await mockOtpSend(page)
    await page.getByTestId("email-input").fill(EDU_EMAIL)
    await page.getByRole("button", { name: /send verification code/i }).click()
    await expect(
      page.getByRole("heading", { name: /check your inbox/i })
    ).toBeVisible()
  }

  test("shows Check your inbox headline", async ({ page }) => {
    await goToOtpStep(page)
    await expect(
      page.getByRole("heading", { name: /check your inbox/i })
    ).toBeVisible()
  })

  test("shows masked email address", async ({ page }) => {
    await goToOtpStep(page)
    // Masked email shows domain but obscures some local part
    await expect(page.getByText(/@wpi\.edu/)).toBeVisible()
  })

  test("shows a code sent badge", async ({ page }) => {
    await goToOtpStep(page)
    await expect(page.getByText(/code sent/i)).toBeVisible()
  })

  test("has an OTP input", async ({ page }) => {
    await goToOtpStep(page)
    await expect(page.getByTestId("otp-input")).toBeVisible()
  })

  test("has a Verify code button", async ({ page }) => {
    await goToOtpStep(page)
    await expect(
      page.getByRole("button", { name: /verify code/i })
    ).toBeVisible()
  })

  test("has a Resend code button (initially in cooldown)", async ({ page }) => {
    await goToOtpStep(page)
    const resend = page.getByTestId("resend-btn")
    await expect(resend).toBeVisible()
    // Should show cooldown immediately after OTP send
    await expect(resend).toContainText(/resend in/i)
  })

  test("has a Change email button", async ({ page }) => {
    await goToOtpStep(page)
    await expect(page.getByTestId("change-email-btn")).toBeVisible()
  })

  test("Change email returns to email step", async ({ page }) => {
    await goToOtpStep(page)
    await page.getByTestId("change-email-btn").click()
    await expect(
      page.getByRole("heading", { name: /sign in with your \.edu email/i })
    ).toBeVisible()
    await expect(page.getByTestId("email-input")).toBeVisible()
  })

  test("OTP input only accepts digits", async ({ page }) => {
    await goToOtpStep(page)
    const input = page.getByTestId("otp-input")
    await input.fill("12abc6")
    await expect(input).toHaveValue("126")
  })

  test("short OTP shows validation error", async ({ page }) => {
    await goToOtpStep(page)
    await page.getByTestId("otp-input").fill("123")
    await page.getByRole("button", { name: /verify code/i }).click()
    await expect(page.getByTestId("error-banner")).toContainText(/6-digit/i)
  })

  test("wrong OTP shows error from server", async ({ page }) => {
    await goToOtpStep(page)
    await mockOtpVerifyFailure(page)
    await page.getByTestId("otp-input").fill(VALID_OTP)
    await page.getByRole("button", { name: /verify code/i }).click()
    await expect(page.getByTestId("error-banner")).toBeVisible()
  })
})

// ── Dashboard redirect (DEMO_MODE is ON during tests) ─────────────────────────

test.describe("Auth guard — DEMO_MODE active in test suite", () => {
  test("dashboard is accessible without login in test mode", async ({ page }) => {
    // DEMO_MODE=true is set in playwright.config.ts webServer command.
    // This confirms existing dashboard tests are not broken.
    await page.goto("/dashboard")
    await expect(page).toHaveURL("/dashboard")
    await expect(page).not.toHaveURL("/login")
  })
})
