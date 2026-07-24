"use client"

/**
 * Passport visibility — the first-class 🔒 Private / 🌍 Public control.
 *
 * One canonical server-side state (`vbr_work_passports.is_published`) drives
 * everything: the public Passport page, Passport Beam, QR codes, public report
 * links, and public skill-report links. This control is the student's master
 * privacy switch over all of those surfaces at once.
 *
 * Contract with the parent:
 * - `isPublished` is the SERVER-CONFIRMED state; this component never renders
 *   an optimistic state. `changeVisibility(target)` must resolve only after
 *   the backend confirmed the change (and reject on failure).
 * - Every change goes through an explicit confirmation dialog; Cancel never
 *   calls the server. Double submission is blocked while a change is in flight.
 *
 * Accessibility: the two state buttons are toggle buttons (`aria-pressed`),
 * the dialog is `role="dialog" aria-modal` with a labelled title, Escape
 * cancels, and errors/success are announced via `role="alert"`/`role="status"`.
 * State is always conveyed by text ("Private Passport"), never color alone.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react"

type VisibilityTarget = "public" | "private"

const TXT = {
  ink: "#0f172a",
  inkSoft: "#334155",
  muted: "#64748b",
  line: "#e2e8f0",
  indigo: "#4f46e5",
  emerald: "#047857",
  emeraldBg: "#ecfdf5",
  emeraldLine: "#a7f3d0",
  slateBg: "#f1f5f9",
  rose: "#be123c",
  roseBg: "#fff1f2",
}

export function PassportVisibilityControl({
  isPublished,
  changeVisibility,
}: {
  /** Server-confirmed visibility: true → 🌍 Public, false → 🔒 Private. */
  isPublished: boolean
  /**
   * Perform the server-side change. Must resolve AFTER the backend confirms
   * (the parent updates `isPublished` from the response) and reject on failure.
   */
  changeVisibility: (target: VisibilityTarget) => Promise<void>
}) {
  const [confirmTarget, setConfirmTarget] = useState<VisibilityTarget | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successNote, setSuccessNote] = useState<string | null>(null)
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null)

  // Move focus into the dialog when it opens (basic focus management).
  useEffect(() => {
    if (confirmTarget) confirmButtonRef.current?.focus()
  }, [confirmTarget])

  // Escape cancels the dialog (never mid-request — a server call in flight
  // will still settle and the parent state stays server-truthful).
  useEffect(() => {
    if (!confirmTarget) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) setConfirmTarget(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [confirmTarget, busy])

  const requestChange = (target: VisibilityTarget) => {
    if (busy) return
    setSuccessNote(null)
    setError(null)
    if ((target === "public") === isPublished) return // already in that state
    setConfirmTarget(target)
  }

  const confirm = () => {
    if (!confirmTarget || busy) return // busy-guard prevents double submission
    setBusy(true)
    setError(null)
    changeVisibility(confirmTarget)
      .then(() => {
        setSuccessNote(
          confirmTarget === "private"
            ? "Your Passport is now private. Your public link, Beam, and QR code now show a private-state page."
            : "Your Passport is now live. Anyone with your link or QR code can view your recruiter-safe Passport.",
        )
        setConfirmTarget(null)
      })
      .catch((err: unknown) => {
        setError(
          err instanceof Error && err.message
            ? err.message
            : "The change didn't go through. Your Passport visibility is unchanged — please try again.",
        )
      })
      .finally(() => setBusy(false))
  }

  const stateBtn = (active: boolean): CSSProperties => ({
    flex: 1,
    minWidth: 120,
    padding: "9px 14px",
    fontSize: 13,
    fontWeight: 700,
    borderRadius: 9,
    cursor: busy ? "wait" : "pointer",
    border: `2px solid ${active ? TXT.indigo : TXT.line}`,
    background: active ? "#eef2ff" : "#fff",
    color: active ? TXT.indigo : TXT.inkSoft,
    opacity: busy ? 0.6 : 1,
  })

  return (
    <div
      data-testid="passport-visibility-control"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 14,
        borderRadius: 12,
        border: `1px solid ${TXT.line}`,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: TXT.ink }}>Passport visibility</span>
        {isPublished ? (
          <span
            data-testid="passport-public-badge"
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: TXT.emerald,
              background: TXT.emeraldBg,
              border: `1px solid ${TXT.emeraldLine}`,
              borderRadius: 999,
              padding: "4px 11px",
            }}
          >
            🌍 Public Passport Live
          </span>
        ) : (
          <span
            data-testid="passport-private-badge"
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: TXT.inkSoft,
              background: TXT.slateBg,
              border: `1px solid ${TXT.line}`,
              borderRadius: 999,
              padding: "4px 11px",
            }}
          >
            🔒 Private Passport
          </span>
        )}
      </div>

      <div role="group" aria-label="Passport visibility" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          data-testid="visibility-private-option"
          aria-pressed={!isPublished}
          disabled={busy}
          onClick={() => requestChange("private")}
          style={stateBtn(!isPublished)}
        >
          🔒 Private
        </button>
        <button
          type="button"
          data-testid="visibility-public-option"
          aria-pressed={isPublished}
          disabled={busy}
          onClick={() => requestChange("public")}
          style={stateBtn(isPublished)}
        >
          🌍 Public
        </button>
      </div>

      <p data-testid="visibility-state-description" style={{ fontSize: 11.5, color: TXT.muted, margin: 0, lineHeight: 1.6 }}>
        {isPublished
          ? "Anyone with your Passport link or QR code can view your recruiter-safe published Passport."
          : "Only you can view your full Work Passport. Public links and QR access show a private-state page."}{" "}
        Your raw evidence remains private in both modes.
      </p>

      {successNote && (
        <p data-testid="visibility-success-note" role="status" style={{ fontSize: 12, color: TXT.emerald, margin: 0, lineHeight: 1.5 }}>
          {successNote}
        </p>
      )}
      {error && !confirmTarget && (
        <p data-testid="visibility-error" role="alert" style={{ fontSize: 12, color: TXT.rose, margin: 0, lineHeight: 1.5 }}>
          {error}
        </p>
      )}

      {confirmTarget && (
        <div
          data-testid="visibility-confirm-backdrop"
          onClick={() => {
            if (!busy) setConfirmTarget(null)
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15,23,42,0.45)",
            zIndex: 90,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="visibility-confirm-title"
            data-testid="visibility-confirm-dialog"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff",
              borderRadius: 14,
              border: `1px solid ${TXT.line}`,
              boxShadow: "0 18px 50px rgba(15,23,42,0.25)",
              padding: 20,
              width: "100%",
              maxWidth: 420,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <h3 id="visibility-confirm-title" style={{ margin: 0, fontSize: 16, fontWeight: 700, color: TXT.ink }}>
              {confirmTarget === "private" ? "Make your Passport private?" : "Publish your Passport publicly?"}
            </h3>
            <p style={{ margin: 0, fontSize: 12.5, color: TXT.inkSoft, lineHeight: 1.6 }}>
              {confirmTarget === "private"
                ? "This will immediately block public access through your Passport link, Beam, QR code, public reports, and public skill-report links. You can make it public again later."
                : "Anyone with the link or QR code will be able to view your recruiter-safe profile, published projects, skills, and reports. Raw evidence will remain private."}
            </p>
            {error && (
              <p data-testid="visibility-confirm-error" role="alert" style={{ fontSize: 12, color: TXT.rose, background: TXT.roseBg, borderRadius: 8, padding: "8px 10px", margin: 0, lineHeight: 1.5 }}>
                {error}
              </p>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap", marginTop: 4 }}>
              <button
                type="button"
                data-testid="visibility-confirm-cancel"
                disabled={busy}
                onClick={() => setConfirmTarget(null)}
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  padding: "9px 14px",
                  borderRadius: 9,
                  cursor: busy ? "wait" : "pointer",
                  border: `1px solid ${TXT.line}`,
                  background: "#fff",
                  color: TXT.inkSoft,
                  opacity: busy ? 0.6 : 1,
                }}
              >
                Cancel
              </button>
              <button
                ref={confirmButtonRef}
                type="button"
                data-testid="visibility-confirm-submit"
                disabled={busy}
                onClick={confirm}
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  padding: "9px 14px",
                  borderRadius: 9,
                  cursor: busy ? "wait" : "pointer",
                  border: "none",
                  background: confirmTarget === "private" ? TXT.ink : TXT.indigo,
                  color: "#fff",
                  opacity: busy ? 0.7 : 1,
                }}
              >
                {busy
                  ? confirmTarget === "private"
                    ? "Making private…"
                    : "Publishing…"
                  : confirmTarget === "private"
                    ? "Make Passport Private"
                    : "Make Passport Public"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
