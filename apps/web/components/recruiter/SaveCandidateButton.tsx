"use client"

/**
 * "Save Candidate" CTA for the public Work Passport (`/p/{slug}`).
 *
 * Behavior:
 *   * Signed-out visitor → clicking routes to `/login?next=/p/{slug}?save=1…`
 *     (the existing validated `next` flow); after auth the visitor lands back
 *     on the SAME passport and the `save=1` marker completes the save
 *     automatically, so the recruiter never loses the candidate they were
 *     viewing.
 *   * Signed-in recruiter → saves immediately; repeat clicks are safe — the
 *     backend is idempotent and the button settles into a "Saved ✓" state
 *     that links to the workspace.
 *
 * Acquisition source: `?src=qr` (stamped on student QR surfaces) → qr_scan,
 * everything else → shared_link.
 *
 * Deliberately router-free: the public passport renders outside any student
 * shell, so this reads `window.location` directly and navigates with a full
 * page load (which also guarantees fresh session cookies on the login hop).
 */

import { useCallback, useEffect, useRef, useState } from "react"

import { TOKEN } from "../passport/shared"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"
import {
  AuthRequiredError,
  passportArrivalSource,
  getConnectionStatus,
  saveCandidate,
} from "@/lib/recruiter-connections-api"

type SaveState = "checking" | "idle" | "saving" | "saved" | "error"

const AUTO_SAVE_PARAM = "save"

function currentSearch(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams()
  return new URLSearchParams(window.location.search)
}

function currentPath(): string {
  if (typeof window === "undefined") return ""
  return window.location.pathname
}

export function SaveCandidateButton({
  slug,
  navigate,
}: {
  slug: string
  /** Test seam; defaults to a full-page navigation. */
  navigate?: (href: string) => void
}) {
  const [state, setState] = useState<SaveState>("checking")
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  // The auto-save marker must only fire once per mount, even if effects
  // re-run after the URL is cleaned below.
  const autoSaveHandled = useRef(false)

  const go = useCallback(
    (href: string) => {
      if (navigate) navigate(href)
      else window.location.assign(href)
    },
    [navigate],
  )

  const loginHref = () => {
    const params = new URLSearchParams()
    params.set(AUTO_SAVE_PARAM, "1")
    const src = currentSearch().get("src")
    if (src) params.set("src", src)
    return `/login?next=${encodeURIComponent(`${currentPath()}?${params.toString()}`)}`
  }

  const cleanUrl = useCallback(() => {
    // Drop the one-shot markers so refreshes don't re-trigger the save flow.
    try {
      window.history.replaceState(null, "", currentPath())
    } catch {
      // History unavailable (very old embeds) — the backend save is
      // idempotent anyway, so a re-trigger is harmless.
    }
  }, [])

  const doSave = useCallback(async () => {
    setState("saving")
    setErrorMessage(null)
    try {
      const source = passportArrivalSource(currentSearch().get("src"))
      await saveCandidate(slug, source, { passport_slug: slug })
      setState("saved")
    } catch (err) {
      if (err instanceof AuthRequiredError) {
        go(loginHref())
        return
      }
      setErrorMessage(err instanceof Error ? err.message : "Failed to save candidate.")
      setState("error")
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, go])

  useEffect(() => {
    let cancelled = false
    const init = async () => {
      let hasSession = false
      try {
        const supabase = createSupabaseBrowserClient()
        const { data } = await supabase.auth.getSession()
        hasSession = Boolean(data.session)
      } catch {
        hasSession = false
      }
      if (cancelled) return

      if (!hasSession) {
        setState("idle")
        return
      }

      // Returning from the login round-trip with the save marker → finish
      // the save the visitor started before authenticating.
      if (currentSearch().get(AUTO_SAVE_PARAM) === "1" && !autoSaveHandled.current) {
        autoSaveHandled.current = true
        await doSave()
        if (!cancelled) cleanUrl()
        return
      }

      try {
        const status = await getConnectionStatus(slug)
        if (!cancelled) setState(status.saved ? "saved" : "idle")
      } catch {
        // Status probe failure must not hide the CTA — fall back to idle;
        // a click still resolves idempotently server-side.
        if (!cancelled) setState("idle")
      }
    }
    void init()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const baseStyle: React.CSSProperties = {
    padding: "10px 18px",
    borderRadius: 10,
    fontSize: 13.5,
    fontWeight: 600,
    border: "none",
    cursor: "pointer",
    minWidth: 150,
  }

  if (state === "checking") {
    return (
      <div
        data-testid="save-candidate-checking"
        style={{ ...baseStyle, background: TOKEN.indigoSoft, color: TOKEN.muted, textAlign: "center", cursor: "default" }}
      >
        …
      </div>
    )
  }

  if (state === "saved") {
    return (
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
        <span
          data-testid="save-candidate-saved"
          style={{ ...baseStyle, background: TOKEN.emeraldSoft, color: TOKEN.emerald, cursor: "default", textAlign: "center" }}
        >
          Saved ✓
        </span>
        <a
          data-testid="save-candidate-workspace-link"
          href="/recruiters/workspace"
          style={{ fontSize: 12.5, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
        >
          View saved candidates →
        </a>
      </div>
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <button
        type="button"
        data-testid="save-candidate-button"
        onClick={() => void doSave()}
        disabled={state === "saving"}
        style={{
          ...baseStyle,
          background: state === "saving" ? TOKEN.indigoSoft : TOKEN.indigo,
          color: state === "saving" ? TOKEN.indigo : "#fff",
          cursor: state === "saving" ? "wait" : "pointer",
        }}
      >
        {state === "saving" ? "Saving…" : "Save Candidate"}
      </button>
      {state === "error" && (
        <p data-testid="save-candidate-error" role="alert" style={{ fontSize: 12, color: TOKEN.rose, margin: 0 }}>
          {errorMessage ?? "Failed to save candidate."}{" "}
          <button
            type="button"
            data-testid="save-candidate-retry"
            onClick={() => void doSave()}
            style={{ background: "none", border: "none", color: TOKEN.indigo, fontWeight: 600, cursor: "pointer", padding: 0, fontSize: 12 }}
          >
            Try again
          </button>
        </p>
      )}
    </div>
  )
}
