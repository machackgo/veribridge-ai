"use client"

import { useEffect, useState, type CSSProperties } from "react"

import {
  getOrCreateBeamLink,
  getPrivateWorkPassport,
  getWorkPassportStatus,
} from "@/lib/vbr-api"
import {
  buildBeamCardModel,
  loadBeamCardCache,
  loadBeamLinkCache,
  saveBeamCardCache,
  saveBeamLinkCache,
  type BeamCardModel,
} from "@/lib/beam-card"
import { beamShortUrl } from "@/lib/app-url"
import { BeamCard } from "../../../components/passport/BeamCard"
import { LoadingState } from "../../../components/passport/shared"

/**
 * The `/beam` experience — load the owner's passport, build the public-safe
 * {@link BeamCardModel}, and present the premium full-screen Beam Card with the
 * share/copy/open actions underneath.
 *
 * Phase 2 — dynamic revocable short QR: for a PUBLISHED passport the view also
 * creates/reuses the owner's Beam short link and the QR / copy / share payload
 * becomes `{app}/b/{code}` instead of the direct public URL. The backend
 * resolver decides where the code goes at scan time, so every QR the student
 * has ever handed out can be rotated/revoked later. If the link service is
 * unavailable, the card falls back to the direct public Passport URL with a
 * visible note (honest, still public-safe) — the handoff moment never dies.
 *
 * Honesty rules, same as Passport Beam:
 *  - unpublished passport → an honest publish-first state (never a fabricated
 *    link, never a private/owner route in the QR);
 *  - the ONLY values shared/copied/encoded are the public short link or the
 *    public Passport URL;
 *  - no fake wallet passes, no NFC/proximity magic, no invented analytics.
 *
 * Offline fallback: the last successfully loaded PUBLISHED card + short link
 * are cached on this device — every cached field is public-safe by
 * construction, and a cached short link STILL resolves (and can still be
 * revoked) server-side at scan time. If the network load fails (career-fair
 * Wi-Fi), the cached card renders with a visible "offline copy" note instead
 * of an error dead-end.
 */
export function BeamView() {
  const [model, setModel] = useState<BeamCardModel | null>(null)
  const [shortUrl, setShortUrl] = useState<string | null>(null)
  const [linkFallback, setLinkFallback] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [copied, setCopied] = useState(false)
  const [shareNote, setShareNote] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    setOffline(false)
    setLinkFallback(false)
    Promise.all([getPrivateWorkPassport(), getWorkPassportStatus()])
      .then(async ([passport, status]) => {
        const built = buildBeamCardModel(passport, status)
        let short: string | null = null
        if (built.isPublished) {
          try {
            // Create/reuse the revocable short link — the Phase 2 QR payload.
            const link = await getOrCreateBeamLink()
            short = beamShortUrl(link.code)
            saveBeamLinkCache(short)
          } catch {
            // Link service unavailable → this device's last saved short link
            // (still revocable server-side), else the direct public URL with
            // a visible note. Never a dead card at the career fair.
            short = loadBeamLinkCache()
            if (!short) setLinkFallback(true)
          }
        }
        setModel(built)
        setShortUrl(short)
        // Keep the device's last-card copy fresh (published cards only).
        saveBeamCardCache(built)
      })
      .catch((err: unknown) => {
        // Career-fair fallback: show the last saved public-safe card instead of
        // a dead error screen. The cache loader revalidates every field.
        const cached = loadBeamCardCache()
        if (cached) {
          setModel(cached)
          setShortUrl(loadBeamLinkCache())
          setOffline(true)
        } else {
          setError(err instanceof Error ? err.message : "Failed to load your Passport.")
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const publicUrl = model?.publicPassportUrl ?? null
  // The ONE QR / copy / share payload: revocable short link when available,
  // direct public Passport URL as the honest fallback. Both are public-safe.
  const shareUrl = shortUrl ?? publicUrl

  const copyLink = async () => {
    if (!shareUrl) return
    setShareNote(null)
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      setShareNote("Copy isn’t available here — select the link text on the card instead.")
    }
  }

  // Native share sheet when the browser has one; otherwise fall back to copy so
  // the button always does something useful. Only ever shares the public link.
  const sharePassport = async () => {
    if (!shareUrl) return
    setShareNote(null)
    const nav = navigator as Navigator & { share?: (data: ShareData) => Promise<void> }
    if (typeof nav.share === "function") {
      try {
        await nav.share({
          title: "Verified Work Passport",
          text: model?.name ? `${model.name} — Verified Work Passport` : "Verified Work Passport",
          url: shareUrl,
        })
        return
      } catch {
        /* Share sheet dismissed or unsupported — fall through to copy. */
      }
    }
    await copyLink()
    setShareNote("Sharing isn’t available here — link copied instead.")
  }

  return (
    <div
      data-testid="beam-view"
      style={{
        minHeight: "100vh",
        background: "#eef1f7",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 14,
        padding: "28px 16px 40px",
      }}
    >
      {/* Minimal chrome — the card is the screen. */}
      <div
        style={{
          width: "100%",
          maxWidth: 430,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
        }}
      >
        <a href="/student/vbr/passport" data-testid="beam-back-link" style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", textDecoration: "none" }}>
          ← Work Passport
        </a>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.18em", color: "#9aa3b2" }}>
          PASSPORT BEAM
        </span>
      </div>

      {loading ? (
        <LoadingState label="Loading your Beam Card…" />
      ) : error ? (
        <div data-testid="beam-error" style={{ maxWidth: 430, textAlign: "center", padding: "48px 16px" }}>
          <p style={{ fontSize: 14, fontWeight: 600, color: "#0a0e1a", marginBottom: 6 }}>
            Couldn’t load your Beam Card
          </p>
          <p style={{ fontSize: 12.5, color: "#6b7280", lineHeight: 1.6, marginBottom: 16 }}>{error}</p>
          <button type="button" data-testid="beam-retry" onClick={load} style={{ ...actionBtn, background: "#4f46e5", color: "#fff", borderColor: "#4f46e5" }}>
            Try again
          </button>
        </div>
      ) : model && model.isPublished && publicUrl ? (
        <>
          {offline && (
            <p
              data-testid="beam-offline-note"
              style={{
                margin: 0,
                fontSize: 11.5,
                fontWeight: 600,
                color: "#92400e",
                background: "#fef3c7",
                border: "1px solid #fde68a",
                borderRadius: 999,
                padding: "4px 12px",
              }}
            >
              Offline copy — showing your last saved card. The QR still opens the live Passport.
            </p>
          )}

          {linkFallback && !offline && (
            <p
              data-testid="beam-link-fallback-note"
              style={{
                margin: 0,
                fontSize: 11.5,
                fontWeight: 600,
                color: "#92400e",
                background: "#fef3c7",
                border: "1px solid #fde68a",
                borderRadius: 999,
                padding: "4px 12px",
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              Secure short link unavailable — sharing your direct public Passport link.
              <button
                type="button"
                data-testid="beam-link-retry"
                onClick={load}
                style={{
                  border: "none",
                  background: "transparent",
                  color: "#92400e",
                  fontSize: 11.5,
                  fontWeight: 700,
                  cursor: "pointer",
                  textDecoration: "underline",
                  padding: 0,
                }}
              >
                Retry
              </button>
            </p>
          )}

          <BeamCard model={model} shareUrl={shareUrl} />

          {/* Actions — off the card face so the credential stays clean. */}
          <div data-testid="beam-actions" style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", maxWidth: 430 }}>
            <button
              type="button"
              data-testid="beam-share"
              onClick={sharePassport}
              style={{ ...actionBtn, background: "#4f46e5", color: "#fff", borderColor: "#4f46e5" }}
            >
              Share Passport
            </button>
            <button type="button" data-testid="beam-copy" onClick={copyLink} style={actionBtn}>
              Copy link
            </button>
            <a data-testid="beam-open-public" href={publicUrl} target="_blank" rel="noreferrer" style={actionBtn}>
              Open public Passport ↗
            </a>
          </div>
          {copied && (
            <p data-testid="beam-copy-toast" role="status" style={noteStyle}>
              Link copied
            </p>
          )}
          {shareNote && (
            <p data-testid="beam-share-note" style={noteStyle}>
              {shareNote}
            </p>
          )}

          {/* Home-screen helper — honest instructions only (no fake wallet pass,
              no install prompt plumbing). Keeping /beam one tap away is the whole
              career-fair speed win. */}
          <details data-testid="beam-home-screen-tip" style={{ maxWidth: 430, width: "100%" }}>
            <summary style={{ fontSize: 11.5, fontWeight: 600, color: "#6b7280", cursor: "pointer", textAlign: "center", listStyle: "none" }}>
              Keep this card one tap away — add /beam to your home screen
            </summary>
            <div
              style={{
                marginTop: 8,
                fontSize: 11.5,
                color: "#6b7280",
                lineHeight: 1.7,
                background: "#ffffff",
                border: "1px solid #e6e8ef",
                borderRadius: 12,
                padding: "10px 14px",
              }}
            >
              <p style={{ margin: 0 }}>
                <strong style={{ color: "#1f2a44" }}>iPhone (Safari):</strong> Share → “Add to Home Screen”.
              </p>
              <p style={{ margin: 0 }}>
                <strong style={{ color: "#1f2a44" }}>Android (Chrome):</strong> ⋮ menu → “Add to Home screen”.
              </p>
              <p style={{ margin: "4px 0 0" }}>
                Your last loaded card also stays available on this device if the venue Wi-Fi drops.
              </p>
            </div>
          </details>
        </>
      ) : (
        /* Publish-first state — honest: no QR, no fabricated link, no private
           fallback. Publishing lives on the Work Passport page. */
        <div
          data-testid="beam-publish-first"
          style={{
            maxWidth: 430,
            width: "100%",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 10,
            padding: "36px 22px",
            borderRadius: 24,
            background: "#ffffff",
            border: "1px dashed #dfe4ff",
            textAlign: "center",
          }}
        >
          <span aria-hidden style={{ fontSize: 26 }}>🔒</span>
          <p style={{ fontSize: 14, fontWeight: 600, color: "#0a0e1a", margin: 0 }}>
            Publish your Passport to activate your Beam Card
          </p>
          <p style={{ fontSize: 12, color: "#6b7280", margin: 0, lineHeight: 1.6, maxWidth: 340 }}>
            Your Passport is currently private, so there is no public link to encode yet. Publishing creates a
            recruiter-safe public Passport — it links only to reports you have published, never raw evidence. You can
            unpublish any time.
          </p>
          <a
            data-testid="beam-open-passport"
            href="/student/vbr/passport"
            style={{ ...actionBtn, background: "#4f46e5", color: "#fff", borderColor: "#4f46e5", marginTop: 4 }}
          >
            Open your Work Passport
          </a>
        </div>
      )}
    </div>
  )
}

const actionBtn: CSSProperties = {
  fontSize: 12.5,
  fontWeight: 600,
  padding: "9px 16px",
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

const noteStyle: CSSProperties = {
  margin: 0,
  fontSize: 11.5,
  fontWeight: 600,
  color: "#059669",
  textAlign: "center",
}
