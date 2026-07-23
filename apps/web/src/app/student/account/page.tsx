import type { CSSProperties, ReactNode } from "react"
import { createSupabaseServerClient } from "../../../lib/supabase/server"
import { SignOutButton } from "../../../../components/student/SignOutButton"

/**
 * /student/account — the canonical Account page (dashboard consolidation).
 *
 * Renders ONLY real data from the authenticated Supabase session; there is no
 * editable profile store in the product today, so this page shows identity
 * facts and the sign-out action — nothing invented, no placeholder personas.
 * Absent fields render a neutral "Not provided" state.
 */

export const metadata = { title: "Account · VeriBridge AI" }

const cardStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--paper)",
  padding: 18,
}

function formatUtc(iso: string | undefined | null): string | null {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  // Fixed locale + UTC keeps server output deterministic.
  return `${new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(date)} UTC`
}

function Field({ label, value, mono = false }: { label: string; value: string | null; mono?: boolean }) {
  return (
    <div style={{ display: "grid", gap: 2 }}>
      <div className="vb-eyebrow" style={{ fontSize: 10 }}>
        {label}
      </div>
      {value ? (
        <div
          style={{
            fontSize: 14,
            color: "var(--ink)",
            fontFamily: mono ? "var(--font-mono)" : undefined,
            wordBreak: "break-all",
          }}
        >
          {value}
        </div>
      ) : (
        <div style={{ fontSize: 14, color: "var(--muted)", fontStyle: "italic" }}>Not provided</div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={cardStyle}>
      <h2 style={{ margin: "0 0 14px", fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>{title}</h2>
      <div style={{ display: "grid", gap: 14 }}>{children}</div>
    </section>
  )
}

export default async function AccountPage() {
  let email: string | null = null
  let name: string | null = null
  let userId: string | null = null
  let providers: string[] = []
  let createdAt: string | null = null
  let lastSignInAt: string | null = null

  try {
    const supabase = await createSupabaseServerClient()
    const {
      data: { user },
    } = await supabase.auth.getUser()
    if (user) {
      email = user.email ?? null
      const metadata = (user.user_metadata ?? {}) as Record<string, unknown>
      name =
        (typeof metadata.full_name === "string" && metadata.full_name) ||
        (typeof metadata.name === "string" && metadata.name) ||
        null
      userId = user.id
      const appMeta = (user.app_metadata ?? {}) as Record<string, unknown>
      if (Array.isArray(appMeta.providers)) {
        providers = appMeta.providers.filter((p): p is string => typeof p === "string")
      } else if (typeof appMeta.provider === "string") {
        providers = [appMeta.provider]
      }
      createdAt = formatUtc(user.created_at)
      lastSignInAt = formatUtc(user.last_sign_in_at)
    }
  } catch {
    // Route is proxy-gated; if the session still cannot be read, fall through
    // to the neutral empty states below rather than fabricating anything.
  }

  const providerLabel =
    providers.length > 0
      ? providers.map((p) => (p === "email" ? "Email verification code" : p === "google" ? "Google" : p)).join(", ")
      : null

  return (
    <div data-testid="student-account-page" style={{ maxWidth: 900, margin: "0 auto", padding: "24px 24px 48px" }}>
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--ink)" }}>
          Account
        </h1>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--muted)" }}>
          Identity for your authenticated VeriBridge session.
        </p>
      </header>

      <div style={{ display: "grid", gap: 16 }}>
        <Section title="Identity">
          <Field label="Name" value={name} />
          <Field label="Email" value={email} />
          <Field label="Sign-in method" value={providerLabel} />
        </Section>

        <Section title="Account details">
          <Field label="Account ID" value={userId} mono />
          <Field label="Account created" value={createdAt} />
          <Field label="Last sign-in" value={lastSignInAt} />
        </Section>

        <Section title="Session">
          <p style={{ margin: 0, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6 }}>
            Signing out ends this browser&apos;s session. Your proofs, passport, and reports are unaffected.
          </p>
          <div>
            <SignOutButton testId="account-signout" appearance="solid" />
          </div>
        </Section>
      </div>
    </div>
  )
}
