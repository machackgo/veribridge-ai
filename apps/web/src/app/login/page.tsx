"use client"

import { Suspense, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

type Step = "email" | "otp"

const RESEND_DELAY = 60
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const SMTP_DELIVERY_ERROR_MESSAGE =
  "Verification email could not be sent. For local development, enable demo mode. For production, configure a verified SMTP sender domain."

// ── Helpers ───────────────────────────────────────────────────────────────────

function isValidEmail(v: string) {
  return EMAIL_PATTERN.test(v.trim())
}

function maskEmail(email: string) {
  const [local, domain] = email.split("@")
  if (!local || !domain) return email
  const visible = local.slice(0, 3)
  return `${visible}${"•".repeat(Math.max(0, local.length - 3))}@${domain}`
}

function getOtpSendErrorMessage(err: unknown) {
  const fallback = "Failed to send code. Please try again."
  const message = err instanceof Error ? err.message : ""
  const normalized = message.toLowerCase()

  if (
    normalized.includes("error sending magic link email") ||
    normalized.includes("failed to send") ||
    normalized.includes("email delivery") ||
    normalized.includes("smtp") ||
    normalized.includes("resend")
  ) {
    return SMTP_DELIVERY_ERROR_MESSAGE
  }

  return message || fallback
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Logo() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 32 }}>
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: "50%",
          background: "linear-gradient(135deg, #4361ee 0%, #3730a3 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontWeight: 700,
          fontSize: 14,
          color: "#fff",
          letterSpacing: "-0.5px",
          flexShrink: 0,
        }}
      >
        vb
      </div>
      <span
        style={{
          fontWeight: 700,
          fontSize: 18,
          color: "var(--ink, #0a0e1a)",
          letterSpacing: "-0.4px",
        }}
      >
        VeriBridge AI
      </span>
    </div>
  )
}

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <div
      role="alert"
      data-testid="error-banner"
      style={{
        background: "#fff1f1",
        border: "1px solid #fca5a5",
        borderRadius: 10,
        padding: "12px 16px",
        fontSize: 14,
        color: "#b91c1c",
        marginBottom: 16,
        lineHeight: 1.5,
      }}
    >
      {msg}
    </div>
  )
}

function PrimaryButton({
  children,
  loading,
  disabled,
  type = "submit",
}: {
  children: React.ReactNode
  loading?: boolean
  disabled?: boolean
  type?: "submit" | "button"
}) {
  return (
    <button
      type={type}
      disabled={loading || disabled}
      style={{
        width: "100%",
        padding: "13px 24px",
        background:
          loading || disabled
            ? "#a5b4fc"
            : "linear-gradient(135deg, #4361ee 0%, #3730a3 100%)",
        color: "#fff",
        border: "none",
        borderRadius: 12,
        fontSize: 15,
        fontWeight: 600,
        cursor: loading || disabled ? "not-allowed" : "pointer",
        transition: "opacity 150ms ease, transform 150ms ease",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        letterSpacing: "-0.2px",
      }}
    >
      {loading ? (
        <>
          <span
            style={{
              width: 16,
              height: 16,
              borderRadius: "50%",
              border: "2px solid rgba(255,255,255,0.4)",
              borderTopColor: "#fff",
              display: "inline-block",
              animation: "vb-spin 0.7s linear infinite",
            }}
          />
          {children}
        </>
      ) : (
        children
      )}
    </button>
  )
}

// ── Google sign-in ────────────────────────────────────────────────────────────

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84c-.21 1.13-.85 2.09-1.81 2.73v2.27h2.92c1.71-1.57 2.69-3.88 2.69-6.64z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.27c-.81.54-1.85.86-3.04.86-2.34 0-4.32-1.58-5.03-3.71H.96v2.33A8.997 8.997 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.7A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.17.29-1.7V4.97H.96A8.997 8.997 0 0 0 0 9c0 1.45.35 2.83.96 4.03l3.01-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0 5.48 0 2.44 2.02.96 4.97l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  )
}

function GoogleButton({
  onClick,
  loading,
  disabled,
}: {
  onClick: () => void
  loading: boolean
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading || disabled}
      data-testid="google-signin-btn"
      style={{
        width: "100%",
        padding: "12px 24px",
        background: "#fff",
        color: "var(--ink, #0a0e1a)",
        border: "1.5px solid #d1d5db",
        borderRadius: 12,
        fontSize: 15,
        fontWeight: 600,
        cursor: loading || disabled ? "not-allowed" : "pointer",
        opacity: loading || disabled ? 0.6 : 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        letterSpacing: "-0.2px",
        fontFamily: "inherit",
      }}
    >
      {loading ? (
        <span
          style={{
            width: 16,
            height: 16,
            borderRadius: "50%",
            border: "2px solid rgba(67,97,238,0.25)",
            borderTopColor: "#4361ee",
            display: "inline-block",
            animation: "vb-spin 0.7s linear infinite",
          }}
        />
      ) : (
        <GoogleIcon />
      )}
      Continue with Google
    </button>
  )
}

function Divider() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "20px 0" }}>
      <div style={{ flex: 1, height: 1, background: "#e5e7eb" }} />
      <span style={{ fontSize: 12, color: "#9ca3af" }}>or</span>
      <div style={{ flex: 1, height: 1, background: "#e5e7eb" }} />
    </div>
  )
}

// ── Email step ────────────────────────────────────────────────────────────────

function EmailStep({
  email,
  setEmail,
  onSubmit,
  loading,
  error,
  onGoogleSignIn,
  googleLoading,
}: {
  email: string
  setEmail: (v: string) => void
  onSubmit: (e: React.FormEvent) => void
  loading: boolean
  error: string | null
  onGoogleSignIn: () => void
  googleLoading: boolean
}) {
  return (
    <div>
      <h1
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: "var(--ink, #0a0e1a)",
          letterSpacing: "-0.6px",
          marginBottom: 8,
        }}
      >
        Sign in to VeriBridge
      </h1>
      <p
        style={{
          fontSize: 14,
          color: "var(--ink-2, #1f2a44)",
          marginBottom: 28,
          lineHeight: 1.6,
          opacity: 0.7,
        }}
      >
        We&apos;ll send a one-time verification code to your email.
      </p>

      {error && <ErrorBanner msg={error} />}

      <GoogleButton onClick={onGoogleSignIn} loading={googleLoading} disabled={loading} />

      <Divider />

      <form onSubmit={onSubmit} noValidate>
        <label
          htmlFor="email"
          style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--ink, #0a0e1a)", marginBottom: 6 }}
        >
          Email address
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          data-testid="email-input"
          style={{
            width: "100%",
            padding: "12px 16px",
            border: "1.5px solid #d1d5db",
            borderRadius: 10,
            fontSize: 15,
            color: "var(--ink, #0a0e1a)",
            background: "#fff",
            marginBottom: 20,
            outline: "none",
            boxSizing: "border-box",
            transition: "border-color 150ms ease",
            fontFamily: "inherit",
          }}
          onFocus={e => { e.currentTarget.style.borderColor = "#4361ee" }}
          onBlur={e => { e.currentTarget.style.borderColor = "#d1d5db" }}
        />

        <PrimaryButton loading={loading} disabled={googleLoading}>
          Send verification code
        </PrimaryButton>
      </form>
    </div>
  )
}

// ── OTP step ──────────────────────────────────────────────────────────────────

function OtpStep({
  email,
  otp,
  setOtp,
  onSubmit,
  onResend,
  onChangeEmail,
  loading,
  error,
  countdown,
  inputRef,
}: {
  email: string
  otp: string
  setOtp: (v: string) => void
  onSubmit: (e: React.FormEvent) => void
  onResend: () => void
  onChangeEmail: () => void
  loading: boolean
  error: string | null
  countdown: number
  inputRef: React.RefObject<HTMLInputElement | null>
}) {
  return (
    <form onSubmit={onSubmit} noValidate>
      <div style={{ marginBottom: 8 }}>
        <div
          data-testid="code-sent-badge"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 12px",
            background: "#eef2ff",
            borderRadius: 20,
            fontSize: 12,
            color: "#4361ee",
            fontWeight: 600,
            marginBottom: 16,
          }}
        >
          <span>✉</span> Code sent
        </div>
      </div>

      <h1
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: "var(--ink, #0a0e1a)",
          letterSpacing: "-0.6px",
          marginBottom: 8,
        }}
      >
        Enter your verification code
      </h1>
      <p
        style={{
          fontSize: 14,
          color: "var(--ink-2, #1f2a44)",
          marginBottom: 28,
          lineHeight: 1.6,
          opacity: 0.7,
        }}
      >
        Enter the verification code sent to your university email{" "}
        <span style={{ fontWeight: 600, color: "var(--ink, #0a0e1a)" }}>
          {maskEmail(email)}
        </span>
        . The code expires in 10 minutes.
      </p>

      {error && <ErrorBanner msg={error} />}

      <label
        htmlFor="otp-code"
        style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--ink, #0a0e1a)", marginBottom: 6 }}
      >
        Verification code
      </label>
      <input
        id="otp-code"
        ref={inputRef}
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        placeholder="000000"
        maxLength={6}
        value={otp}
        onChange={e => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
        required
        data-testid="otp-input"
        style={{
          width: "100%",
          padding: "14px 16px",
          border: "1.5px solid #d1d5db",
          borderRadius: 10,
          fontSize: 28,
          fontFamily: "JetBrains Mono, monospace",
          fontWeight: 600,
          letterSpacing: "0.35em",
          color: "var(--ink, #0a0e1a)",
          background: "#fff",
          marginBottom: 20,
          outline: "none",
          boxSizing: "border-box",
          textAlign: "center",
          transition: "border-color 150ms ease",
        }}
        onFocus={e => { e.currentTarget.style.borderColor = "#4361ee" }}
        onBlur={e => { e.currentTarget.style.borderColor = "#d1d5db" }}
      />

      <PrimaryButton loading={loading}>
        Verify and continue
      </PrimaryButton>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
          marginTop: 20,
          fontSize: 13,
        }}
      >
        <button
          type="button"
          onClick={onResend}
          disabled={countdown > 0 || loading}
          data-testid="resend-btn"
          style={{
            background: "none",
            border: "none",
            color: countdown > 0 ? "#9ca3af" : "#4361ee",
            cursor: countdown > 0 ? "default" : "pointer",
            padding: 0,
            fontSize: 13,
            fontWeight: 500,
            fontFamily: "inherit",
          }}
        >
          {countdown > 0 ? `Resend in ${countdown}s` : "Resend code"}
        </button>
        <span style={{ color: "#d1d5db" }}>|</span>
        <button
          type="button"
          onClick={onChangeEmail}
          data-testid="change-email-btn"
          style={{
            background: "none",
            border: "none",
            color: "#6b7280",
            cursor: "pointer",
            padding: 0,
            fontSize: 13,
            fontFamily: "inherit",
          }}
        >
          Change email
        </button>
      </div>
    </form>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

// useSearchParams() requires a Suspense boundary in Next.js static generation.
// LoginInner holds all logic; LoginPage is the Suspense shell.

function LoginInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const redirectTo = searchParams.get("next") ?? "/student/vbr"

  const [step, setStep] = useState<Step>("email")
  const [email, setEmail] = useState("")
  const [otp, setOtp] = useState("")
  const [loading, setLoading] = useState(false)
  const [googleLoading, setGoogleLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [countdown, setCountdown] = useState(0)

  const otpInputRef = useRef<HTMLInputElement | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const supabase = createSupabaseBrowserClient()

  useEffect(() => {
    if (step === "otp") {
      const t = setTimeout(() => otpInputRef.current?.focus(), 80)
      return () => clearTimeout(t)
    }
  }, [step])

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  function startCountdown() {
    setCountdown(RESEND_DELAY)
    timerRef.current = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(timerRef.current!)
          timerRef.current = null
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }

  async function sendOtp(addr: string) {
    const { error } = await supabase.auth.signInWithOtp({
      email: addr,
      options: { shouldCreateUser: true },
    })
    if (error) throw error
  }

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const addr = email.trim().toLowerCase()

    if (!addr) {
      setError("Please enter your email address.")
      return
    }
    if (!isValidEmail(addr)) {
      setError("Please enter a valid email address.")
      return
    }

    setLoading(true)
    try {
      await sendOtp(addr)
      setEmail(addr)
      setStep("otp")
      startCountdown()
    } catch (err: unknown) {
      setError(getOtpSendErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleOtpSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const code = otp.trim()

    if (code.length !== 6) {
      setError("Please enter the 6-digit code from your email.")
      return
    }

    setLoading(true)
    try {
      const { data, error } = await supabase.auth.verifyOtp({
        email,
        token: code,
        type: "email",
      })
      if (error) throw error
      if (data.session) {
        const destination = redirectTo.startsWith("/") ? redirectTo : "/student/vbr"
        router.push(destination)
        router.refresh()
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : ""
      setError(
        msg.toLowerCase().includes("invalid") || msg.toLowerCase().includes("expired")
          ? "Incorrect or expired code. Please check your email and try again."
          : msg || "Verification failed. Please try again."
      )
    } finally {
      setLoading(false)
    }
  }

  async function handleResend() {
    if (countdown > 0 || loading) return
    setError(null)
    setLoading(true)
    try {
      await sendOtp(email)
      startCountdown()
    } catch (err: unknown) {
      setError(getOtpSendErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleGoogleSignIn() {
    setError(null)
    setGoogleLoading(true)
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(redirectTo || "/student/vbr")}`,
        },
      })
      if (error) throw error
      // On success the browser navigates away to Google; no further action needed here.
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start Google sign-in. Please try again.")
      setGoogleLoading(false)
    }
  }

  function handleChangeEmail() {
    setStep("email")
    setOtp("")
    setError(null)
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setCountdown(0)
  }

  return (
    <>
      <style>{`
        @keyframes vb-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>

      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background:
            "radial-gradient(ellipse 80% 60% at 50% -10%, #e0e7ff 0%, #fafbfd 60%)",
          padding: "24px 16px",
        }}
      >
        {/* Card */}
        <div
          style={{
            width: "100%",
            maxWidth: 420,
            background: "#fff",
            borderRadius: 20,
            boxShadow:
              "0 1px 3px rgba(10,14,26,0.06), 0 8px 32px rgba(10,14,26,0.08)",
            padding: "40px 40px 36px",
            border: "1px solid rgba(209,213,219,0.6)",
          }}
        >
          <Logo />

          {step === "email" ? (
            <EmailStep
              email={email}
              setEmail={setEmail}
              onSubmit={handleEmailSubmit}
              loading={loading}
              error={error}
              onGoogleSignIn={handleGoogleSignIn}
              googleLoading={googleLoading}
            />
          ) : (
            <OtpStep
              email={email}
              otp={otp}
              setOtp={setOtp}
              onSubmit={handleOtpSubmit}
              onResend={handleResend}
              onChangeEmail={handleChangeEmail}
              loading={loading}
              error={error}
              countdown={countdown}
              inputRef={otpInputRef}
            />
          )}
        </div>

        {/* Footer link */}
        <Link
          href="/"
          style={{
            marginTop: 24,
            fontSize: 13,
            color: "#6b7280",
            textDecoration: "none",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          ← Back to home
        </Link>
      </div>
    </>
  )
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  )
}
