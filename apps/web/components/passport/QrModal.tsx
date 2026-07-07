"use client"

import { useEffect } from "react"

import { QrCode } from "./QrCode"

/**
 * Optional QR access, moved OFF the card face into a dismissible modal.
 *
 * The Passport Card itself is now a clean, professional credential with no QR on
 * its face; scanning is still supported for recruiters who want it, but only when
 * the candidate explicitly opens this modal ("Show QR"). The encoded `value` is
 * always the public Work Passport URL (`{app}/p/{slug}`) — never a private route,
 * raw evidence, or a signed storage URL. Renders nothing until opened / when there
 * is no published URL yet.
 */
export function QrModal({
  value,
  open,
  onClose,
  title = "Scan to open the Work Passport",
}: {
  value: string | null | undefined
  open: boolean
  onClose: () => void
  title?: string
}) {
  // Close on Escape; restore body scroll when unmounted.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open || !value) return null

  return (
    <div
      data-testid="passport-qr-modal"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
        background: "rgba(10,14,26,0.62)",
        backdropFilter: "blur(4px)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          padding: "24px 24px 20px",
          borderRadius: 18,
          background: "#ffffff",
          boxShadow: "0 24px 60px -20px rgba(10,14,26,0.55)",
          maxWidth: 320,
          width: "100%",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, textAlign: "center" }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#0a0e1a" }}>{title}</span>
          <span style={{ fontSize: 12, color: "#6b7280", lineHeight: 1.5 }}>
            Point a phone camera at the code to open the verified Work Passport.
          </span>
        </div>

        <QrCode value={value} size={208} data-testid="passport-modal-qr" />

        <button
          type="button"
          data-testid="passport-qr-modal-close"
          onClick={onClose}
          style={{
            marginTop: 2,
            padding: "9px 18px",
            borderRadius: 10,
            border: "1px solid #e6e8ef",
            background: "#f7f8ff",
            color: "#312e81",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Done
        </button>
      </div>
    </div>
  )
}
