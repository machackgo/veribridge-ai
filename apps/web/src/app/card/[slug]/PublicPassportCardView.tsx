"use client"

import { useEffect, useMemo, useState, type CSSProperties } from "react"

import { getPublicWorkPassportBySlug, fallbackSkillSlug, type PublicWorkPassport } from "@/lib/vbr-api"
import { buildPublicCardModel, type PassportCardCapability } from "@/lib/passport-card"
import { ErrorState, LoadingState, TOKEN } from "../../../../components/passport/shared"
import { PassportCard } from "../../../../components/passport/PassportCard"
import { QrModal } from "../../../../components/passport/QrModal"
import { downloadPassportCardImage } from "@/lib/card-image"

/**
 * Public, mobile-first Verified Passport Card — the career-fair entry point to a
 * candidate's evidence-backed profile. It reuses the recruiter-safe public
 * passport payload (`getPublicWorkPassportBySlug`), so it can only ever show
 * published, recruiter-safe fields: never raw evidence, private/unpublished
 * reports, internal ids, or numeric scores. The card face carries no QR/barcode;
 * a recruiter opens the full Work Passport, shares/copies the link, saves the card
 * as an image, or opens an optional QR modal — all from clean controls below it.
 */
export function PublicPassportCardView({ slug }: { slug: string }) {
  const [passport, setPassport] = useState<PublicWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [qrOpen, setQrOpen] = useState(false)
  const [actionNote, setActionNote] = useState<string | null>(null)
  const [downloadFallback, setDownloadFallback] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    getPublicWorkPassportBySlug(slug)
      .then((data) => {
        if (!data) {
          setNotFound(true)
          return
        }
        setPassport(data)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load passport card."))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const model = useMemo(() => (passport ? buildPublicCardModel(passport, slug) : null), [passport, slug])

  const copyLink = async () => {
    const url = model?.publicPassportUrl
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setActionNote(null)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* Clipboard blocked — the CTA below still opens the Passport. */
    }
  }

  // Web Share API (mobile share sheet) with a copy-link fallback. Only ever
  // shares the public Passport URL — never a private route or raw evidence.
  const onShare = async () => {
    const url = model?.publicPassportUrl
    if (!url) return
    setActionNote(null)
    const nav = navigator as Navigator & { share?: (data: ShareData) => Promise<void> }
    if (typeof nav.share === "function") {
      try {
        await nav.share({ title: "Verified Work Passport", text: "Verified Work Passport", url })
        return
      } catch {
        /* Cancelled or unsupported — fall through to copy. */
      }
    }
    await copyLink()
    setActionNote("Sharing isn’t available here — link copied instead.")
  }

  // Save the card as a PNG rebuilt from the safe model; manual save-as fallback
  // on any browser limitation.
  const onDownload = async () => {
    if (!model) return
    setDownloadFallback(false)
    try {
      await downloadPassportCardImage(model)
      setActionNote("Saved veribridge-passport-card.png")
    } catch {
      setDownloadFallback(true)
    }
  }

  if (loading) return <LoadingState label="Loading Verified Passport Card…" />

  if (notFound) {
    return (
      <div
        data-testid="public-card-not-found"
        style={{ maxWidth: 460, margin: "0 auto", padding: "64px 24px", textAlign: "center" }}
      >
        <span aria-hidden style={{ fontSize: 30, display: "block", marginBottom: 10 }}>🔒</span>
        <h1 style={{ fontSize: 20, color: TOKEN.ink, marginBottom: 10 }}>This Work Passport is currently private</h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, lineHeight: 1.6 }}>
          The candidate has not made this Passport available for public viewing, or the link may be incorrect. Ask
          the candidate for an up-to-date Verified Work Passport link.
        </p>
      </div>
    )
  }

  if (error || !model) return <ErrorState message={error ?? "Passport card not found."} onRetry={load} />

  // Role-area chips deep-link into the full public Passport's skill evidence anchor.
  const capabilityHref = (cap: PassportCardCapability) =>
    `/p/${encodeURIComponent(slug)}#public-skill-${fallbackSkillSlug(cap.skill)}`

  return (
    <div
      data-testid="public-passport-card"
      style={{ maxWidth: 480, margin: "0 auto", padding: "32px 16px", display: "flex", flexDirection: "column", gap: 16, alignItems: "center" }}
    >
      <div style={{ textAlign: "center" }}>
        <h1 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Verified Work Passport Card</h1>
      </div>

      <PassportCard
        model={model}
        variant="public"
        capabilityHref={capabilityHref}
        footer={
          <a
            data-testid="public-card-full-passport-cta"
            href={`/p/${encodeURIComponent(slug)}`}
            style={{
              marginTop: 2,
              textAlign: "center",
              padding: "11px 16px",
              borderRadius: 10,
              background: TOKEN.indigo,
              color: "#fff",
              fontSize: 14,
              fontWeight: 600,
              textDecoration: "none",
              border: `1px solid ${TOKEN.indigo}`,
            }}
          >
            View Verified Passport →
          </a>
        }
      />

      {/* Share / save controls — off the card face so the card stays clean. */}
      <div data-testid="public-card-actions" style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
        <button type="button" data-testid="public-card-copy-link" onClick={copyLink} style={publicActionBtn}>
          {copied ? "✓ Copied" : "Copy Passport link"}
        </button>
        <button type="button" data-testid="public-card-share" onClick={onShare} style={publicActionBtn}>
          Share Passport
        </button>
        <button type="button" data-testid="public-card-download" onClick={onDownload} style={publicActionBtn}>
          ⬇ Download card
        </button>
        <button type="button" data-testid="public-card-show-qr" onClick={() => setQrOpen(true)} style={publicActionBtn}>
          Show QR
        </button>
      </div>

      {actionNote && (
        <p data-testid="public-card-action-note" style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", margin: 0 }}>
          {actionNote}
        </p>
      )}
      {downloadFallback && (
        <p data-testid="public-card-download-fallback" style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", margin: 0, lineHeight: 1.5, maxWidth: 420 }}>
          Image download isn’t available in this browser. Long-press (or right-click) the card above and choose “Save
          image”.
        </p>
      )}

      <p data-testid="public-card-footer-note" style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", margin: 0, lineHeight: 1.6, maxWidth: 420 }}>
        Recruiter-safe summaries only — no raw files, private evidence, or numeric scores.
      </p>

      <QrModal value={model.publicPassportUrl} open={qrOpen} onClose={() => setQrOpen(false)} />
    </div>
  )
}

const publicActionBtn: CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  padding: "8px 14px",
  borderRadius: 9,
  cursor: "pointer",
  border: `1px solid ${TOKEN.line}`,
  background: "#fff",
  color: TOKEN.inkSoft,
}
