"use client"

import { useEffect, useState } from "react"

import { QrCode } from "./QrCode"

/**
 * Optional QR access, moved OFF the card face into a dismissible modal.
 *
 * Used for both the public Work Passport link and a project's public Verified
 * Build Report link (via `title`/`subtitle`). The encoded `value` is always a
 * canonical public URL (`{app}/p/{slug}` or `{app}/vbr/report/{token}`) —
 * never a private route, auth/session token, raw evidence, or a signed
 * storage URL. Renders nothing until opened / when there is no published URL.
 *
 * The URL itself is shown as selectable text with a copy action so the QR is
 * never the only way to reach the link (accessible text fallback).
 */
export function QrModal({
  value,
  qrValue,
  open,
  onClose,
  title = "Scan to open the Work Passport",
  subtitle = "Point a phone camera at the code to open the verified Work Passport.",
}: {
  value: string | null | undefined
  /**
   * Optional QR-only override (e.g. the passport URL stamped with the
   * `src=qr` scan marker). The visible/copyable link always stays `value`.
   */
  qrValue?: string | null
  open: boolean
  onClose: () => void
  title?: string
  subtitle?: string
}) {
  const [copied, setCopied] = useState(false)

  // Close on Escape; restore body scroll when unmounted.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) setCopied(false)
  }, [open])

  if (!open || !value) return null

  const copy = () => {
    void navigator.clipboard?.writeText(value)
    setCopied(true)
  }

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
          <span style={{ fontSize: 12, color: "#6b7280", lineHeight: 1.5 }}>{subtitle}</span>
        </div>

        <QrCode value={qrValue ?? value} size={208} data-testid="passport-modal-qr" />

        {/* Accessible text fallback: the QR is never the only way to the link. */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, width: "100%" }}>
          <span
            data-testid="passport-qr-modal-url"
            style={{
              fontSize: 11,
              color: "#3f4657",
              fontFamily: "'JetBrains Mono', monospace",
              wordBreak: "break-all",
              textAlign: "center",
              lineHeight: 1.5,
              userSelect: "all",
            }}
          >
            {value}
          </span>
          <button
            type="button"
            data-testid="passport-qr-modal-copy"
            onClick={copy}
            style={{
              padding: "7px 14px",
              borderRadius: 8,
              border: "1px solid #e6e8ef",
              background: "#ffffff",
              color: "#0a0e1a",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {copied ? "Link copied!" : "Copy link"}
          </button>
        </div>

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
