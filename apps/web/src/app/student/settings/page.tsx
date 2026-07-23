import Link from "next/link"
import type { CSSProperties, ReactNode } from "react"
import { createSupabaseServerClient } from "../../../lib/supabase/server"
import { SignOutButton } from "../../../../components/student/SignOutButton"

/**
 * /student/settings — the canonical Settings page (dashboard consolidation).
 *
 * Deliberately honest: it exposes only controls that actually work today.
 * Sharing/publishing is managed inside the surfaces that own it (Work
 * Passport, per-project reports), so this page links there instead of
 * duplicating half-wired toggles. No sample data, no inert controls.
 */

export const metadata = { title: "Settings · VeriBridge AI" }

const cardStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--paper)",
  padding: 18,
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={cardStyle}>
      <h2 style={{ margin: "0 0 10px", fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>{title}</h2>
      <div style={{ display: "grid", gap: 12 }}>{children}</div>
    </section>
  )
}

const settingLinkStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "8px 14px",
  borderRadius: 10,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink)",
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
}

export default async function SettingsPage() {
  let email = ""
  try {
    const supabase = await createSupabaseServerClient()
    const {
      data: { user },
    } = await supabase.auth.getUser()
    email = user?.email ?? ""
  } catch {
    // Proxy-gated route; fall through to generic copy if the session can't be read.
  }

  return (
    <div data-testid="student-settings-page" style={{ maxWidth: 900, margin: "0 auto", padding: "24px 24px 48px" }}>
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--ink)" }}>
          Settings
        </h1>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--muted)" }}>
          Controls for your session and where to manage sharing.
        </p>
      </header>

      <div style={{ display: "grid", gap: 16 }}>
        <Section title="Session">
          <p style={{ margin: 0, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6 }}>
            {email ? (
              <>
                You are signed in as <strong style={{ color: "var(--ink)" }}>{email}</strong>.
              </>
            ) : (
              "You are signed in."
            )}{" "}
            Signing out ends this browser&apos;s session; your data stays intact.
          </p>
          <div>
            <SignOutButton testId="settings-signout" appearance="solid" />
          </div>
        </Section>

        <Section title="Sharing &amp; publishing">
          <p style={{ margin: 0, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6 }}>
            Publishing controls live where they act, next to the thing being shared:
          </p>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.8 }}>
            <li>Work Passport publishing and public link — on the Work Passport page.</li>
            <li>Verified Build Report publishing — on each project&apos;s report page.</li>
          </ul>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link href="/student/vbr/passport" style={settingLinkStyle}>
              Open Work Passport
            </Link>
            <Link href="/student/vbr/passport/vault" style={settingLinkStyle}>
              Open Proof Vault
            </Link>
          </div>
        </Section>

        <Section title="Preferences">
          <p style={{ margin: 0, fontSize: 13, color: "var(--muted)", lineHeight: 1.6 }}>
            No other preferences are configurable yet. New settings will appear here when they ship.
          </p>
        </Section>
      </div>
    </div>
  )
}
