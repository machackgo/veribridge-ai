"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

/**
 * Shared sign-out control for the Student Shell menu and the Account/Settings
 * pages — one implementation so session teardown can never drift per surface.
 *
 * Scope is "local": the chunked sb-* auth cookies for THIS browser are cleared
 * and this session's refresh token is revoked, without force-logging the user
 * out of their other devices. The Google account chooser on the next login is
 * handled separately (prompt=select_account on signInWithOAuth) — Google's own
 * session is intentionally left alone.
 */
export function SignOutButton({
  onDone,
  testId,
  appearance = "menu",
}: {
  onDone?: () => void
  testId: string
  appearance?: "menu" | "solid"
}) {
  const router = useRouter()
  const [signingOut, setSigningOut] = useState(false)

  const handleSignOut = async () => {
    if (signingOut) return
    setSigningOut(true)
    try {
      await createSupabaseBrowserClient().auth.signOut({ scope: "local" })
    } catch {
      // Even if revocation fails, proceed to /login — the proxy re-gates from there.
    }
    onDone?.()
    router.push("/login")
    router.refresh()
  }

  const base = {
    display: "block" as const,
    textAlign: "left" as const,
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 600,
    color: "var(--rose)",
    cursor: signingOut ? ("default" as const) : ("pointer" as const),
    opacity: signingOut ? 0.6 : 1,
  }

  const style =
    appearance === "menu"
      ? { ...base, width: "100%", padding: "8px 10px", border: "none", background: "transparent" }
      : {
          ...base,
          display: "inline-block" as const,
          padding: "9px 16px",
          border: "1px solid var(--line)",
          background: "var(--paper)",
          borderRadius: 10,
        }

  return (
    <button
      type="button"
      data-testid={testId}
      onClick={handleSignOut}
      disabled={signingOut}
      className="dash-nav-hover"
      style={style}
    >
      {signingOut ? "Signing out…" : "Sign out"}
    </button>
  )
}
