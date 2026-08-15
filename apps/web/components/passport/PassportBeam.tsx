"use client"

import { useEffect, useState, type CSSProperties } from "react"

import { withQrSource } from "@/lib/app-url"
import { firstNameFrom, realDisplayName } from "@/lib/passport-card"

import { QrCode } from "./QrCode"

/**
 * Passport Beam — the instant, in-person sharing surface for the Verified Work
 * Passport (career-fair mode). Inspired by the clarity of iPhone Hotspot /
 * NameDrop sharing, but honest for the web: a large scannable QR code, the
 * visible public-safe URL, copy-link, the native OS share sheet where the
 * browser supports it, and an "open public Passport" action. There is NO fake
 * proximity magic — no nearby-device scanning, no Bluetooth/AirDrop simulation,
 * no invented recruiter-view analytics.
 *
 * Safety: the ONLY value this panel ever encodes, displays, copies, or shares is
 * the already-public Passport URL (`{app}/p/{slug}`) produced by the existing
 * publish flow. When the passport is not published there is no public URL, so
 * the panel shows an honest publish-first state instead — it never fabricates a
 * link and never falls back to a private/owner route.
 */
export function PassportBeam({
  open,
  onClose,
  publicUrl,
  candidateName,
  onDownloadCard,
  onPublish,
  publishBusy = false,
}: {
  open: boolean
  onClose: () => void
  /** The recruiter-safe public Passport URL, or null while unpublished. */
  publicUrl: string | null
  /**
   * The candidate's display name, used for the personalized subtitle
   * ("Share Mohammed’s …") and the native share sheet's message text. Backend
   * placeholder copy ("Verified candidate profile") is normalized away here
   * too, so the panel can never present a placeholder as a real person.
   */
  candidateName?: string | null
  /** Existing "Download Passport Card" action, surfaced here when available. */
  onDownloadCard?: () => void
  /** Publish action for the publish-first state (owner surface only). */
  onPublish?: () => void
  publishBusy?: boolean
}) {
  const [copied, setCopied] = useState(false)
  const [shareNote, setShareNote] = useState<string | null>(null)
  // Web Share support is a client-only capability — resolve it on open so SSR
  // never guesses and the button truly appears only where `navigator.share` exists.
  const [canNativeShare, setCanNativeShare] = useState(false)

  useEffect(() => {
    if (!open) return
    setCopied(false)
    setShareNote(null)
    setCanNativeShare(typeof navigator !== "undefined" && typeof navigator.share === "function")
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  if (!open) return null

  const ready = Boolean(publicUrl)
  // Defense-in-depth: only a REAL name personalizes copy (never the backend's
  // "Verified candidate profile" placeholder, even if a caller passes it).
  const realName = realDisplayName(candidateName)
  const firstName = firstNameFrom(realName)

  const copyLink = async () => {
    if (!publicUrl) return
    try {
      await navigator.clipboard.writeText(publicUrl)
      setCopied(true)
      setShareNote(null)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      setShareNote("Copy isn’t available here — select the link text above instead.")
    }
  }

  // Native OS share sheet (AirDrop, Messages, WhatsApp, …) — only rendered when
  // the browser actually supports it, and only ever sharing the public URL.
  const nativeShare = async () => {
    if (!publicUrl) return
    setShareNote(null)
    try {
      await navigator.share({
        title: "Verified Work Passport",
        text: realName ? `${realName} — Verified Work Passport` : "Verified Work Passport",
        url: publicUrl,
      })
    } catch {
      /* Share sheet dismissed — nothing to do. */
    }
  }

  return (
    <div
      data-testid="passport-beam-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Passport Beam — share your recruiter-safe Passport"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        background: "rgba(10,14,26,0.66)",
        backdropFilter: "blur(6px)",
        overflowY: "auto",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          padding: "26px 26px 22px",
          borderRadius: 24,
          background: "#ffffff",
          border: "1px solid #e6e8ef",
          boxShadow: "0 32px 80px -24px rgba(10,14,26,0.55)",
          maxWidth: 460,
          width: "100%",
          margin: "auto 0",
          position: "relative",
        }}
      >
        <button
          type="button"
          data-testid="passport-beam-close"
          aria-label="Close Passport Beam"
          onClick={onClose}
          style={{
            position: "absolute",
            top: 14,
            right: 14,
            width: 32,
            height: 32,
            borderRadius: "50%",
            border: "1px solid #e6e8ef",
            background: "#f8fafc",
            color: "#6b7280",
            fontSize: 15,
            fontWeight: 600,
            cursor: "pointer",
            lineHeight: 1,
          }}
        >
          ✕
        </button>

        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: 5, paddingRight: 36 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <h2 style={{ fontSize: 19, fontWeight: 700, color: "#0a0e1a", margin: 0, letterSpacing: "-0.01em" }}>
              Passport Beam
            </h2>
            <span
              data-testid="passport-beam-status"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "3px 10px",
                borderRadius: 999,
                fontSize: 10.5,
                fontWeight: 600,
                whiteSpace: "nowrap",
                background: ready ? "#ecfdf5" : "#fef3c7",
                color: ready ? "#059669" : "#92400e",
                border: `1px solid ${ready ? "#a7f3d0" : "#fde68a"}`,
              }}
            >
              {ready ? "● Ready to share" : "🔒 Passport private"}
            </span>
          </div>
          <p data-testid="passport-beam-subtitle" style={{ fontSize: 12.5, color: "#6b7280", margin: 0, lineHeight: 1.55 }}>
            {firstName
              ? `Share ${firstName}’s recruiter-safe VeriBridge Passport in seconds.`
              : "Share your recruiter-safe VeriBridge Passport in seconds."}
          </p>
        </div>

        {ready && publicUrl ? (
          <>
            {/* The scan target — large, centred, career-fair readable. */}
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 10,
                padding: "18px 16px 14px",
                borderRadius: 18,
                background: "#f8fafc",
                border: "1px solid #eef0f6",
              }}
            >
              <QrCode value={withQrSource(publicUrl)} size={228} data-testid="passport-beam-qr" />
              <p
                data-testid="passport-beam-instruction"
                style={{ fontSize: 13, fontWeight: 600, color: "#1f2a44", margin: 0, textAlign: "center" }}
              >
                Ask the recruiter to scan this code.
              </p>
              <p style={{ fontSize: 11.5, color: "#6b7280", margin: 0, textAlign: "center", lineHeight: 1.5 }}>
                It opens your public Verified Work Passport — no app, no login.
              </p>
            </div>

            {/* The visible public-safe link. */}
            <div
              data-testid="passport-beam-url"
              style={{
                fontFamily: '"JetBrains Mono", monospace',
                fontSize: 12,
                color: "#0a0e1a",
                padding: "8px 11px",
                background: "#fafbfd",
                border: "1px solid #e6e8ef",
                borderRadius: 10,
                wordBreak: "break-all",
                textAlign: "center",
              }}
            >
              {publicUrl}
            </div>

            {/* Actions */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
              <button
                type="button"
                data-testid="passport-beam-copy"
                onClick={copyLink}
                style={{ ...beamBtn, background: "#4f46e5", color: "#fff", borderColor: "#4f46e5" }}
              >
                {copied ? "✓ Copied" : "Copy link"}
              </button>
              {canNativeShare && (
                <button type="button" data-testid="passport-beam-native-share" onClick={nativeShare} style={beamBtn}>
                  Share…
                </button>
              )}
              <a
                data-testid="passport-beam-open-public"
                href={publicUrl}
                target="_blank"
                rel="noreferrer"
                style={beamBtn}
              >
                Open public Passport ↗
              </a>
              {onDownloadCard && (
                <button type="button" data-testid="passport-beam-download" onClick={onDownloadCard} style={beamBtn}>
                  ⬇ Download Passport Card
                </button>
              )}
            </div>
            {shareNote && (
              <p data-testid="passport-beam-share-note" style={{ fontSize: 11, color: "#6b7280", margin: 0, textAlign: "center" }}>
                {shareNote}
              </p>
            )}
          </>
        ) : (
          /* Publish-first state — honest, no fake URL, no private fallback. */
          <div
            data-testid="passport-beam-publish-first"
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 10,
              padding: "26px 18px",
              borderRadius: 18,
              background: "#f8fafc",
              border: "1px dashed #dfe4ff",
              textAlign: "center",
            }}
          >
            <span aria-hidden style={{ fontSize: 26 }}>🔒</span>
            <p style={{ fontSize: 13.5, fontWeight: 600, color: "#0a0e1a", margin: 0 }}>
              Your Passport is currently private.
            </p>
            <p style={{ fontSize: 12, color: "#6b7280", margin: 0, lineHeight: 1.6, maxWidth: 340 }}>
              Anyone opening your link or QR code right now sees a private-state page. To enable sharing, set your
              Passport to Public in the Passport visibility control — it exposes only recruiter-safe published
              content, never raw evidence, and you can make it private again any time.
            </p>
            {onPublish && (
              <button
                type="button"
                data-testid="passport-beam-publish"
                disabled={publishBusy}
                onClick={onPublish}
                style={{
                  ...beamBtn,
                  background: "#4f46e5",
                  color: "#fff",
                  borderColor: "#4f46e5",
                  opacity: publishBusy ? 0.6 : 1,
                  marginTop: 4,
                }}
              >
                {publishBusy ? "Publishing…" : "Publish public Passport"}
              </button>
            )}
          </div>
        )}

        {/* Recruiter-safe trust notes — always visible, always honest. */}
        <ul
          data-testid="passport-beam-trust-notes"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 5,
            margin: 0,
            padding: "12px 14px",
            listStyle: "none",
            borderRadius: 12,
            background: "#fafbfd",
            border: "1px solid #eef0f6",
          }}
        >
          {["No recruiter login required", "Public-safe proof summary", "Private evidence stays protected"].map((note) => (
            <li key={note} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: "#1f2a44", fontWeight: 500 }}>
              <span aria-hidden style={{ color: "#059669", fontSize: 11, lineHeight: 1 }}>✓</span>
              {note}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

const beamBtn: CSSProperties = {
  fontSize: 12.5,
  fontWeight: 600,
  padding: "9px 14px",
  borderRadius: 10,
  cursor: "pointer",
  border: "1px solid #e6e8ef",
  background: "#fff",
  color: "#1f2a44",
  textDecoration: "none",
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
}
