"use client"

import { useEffect, useMemo, useState } from "react"

import { getPublicWorkPassportBySlug, fallbackSkillSlug, type PublicWorkPassport } from "@/lib/vbr-api"
import { buildPublicCardModel, type PassportCardCapability } from "@/lib/passport-card"
import { ErrorState, LoadingState, TOKEN } from "../../../../components/passport/shared"
import { PassportCard } from "../../../../components/passport/PassportCard"

/**
 * Public, mobile-first Verified Passport Card — the career-fair / QR entry point
 * to a candidate's evidence-backed profile. It reuses the recruiter-safe public
 * passport payload (`getPublicWorkPassportBySlug`), so it can only ever show
 * published, recruiter-safe fields: never raw evidence, private/unpublished
 * reports, internal ids, or numeric scores. From here a recruiter opens the full
 * Work Passport or a published project report.
 */
export function PublicPassportCardView({ slug }: { slug: string }) {
  const [passport, setPassport] = useState<PublicWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  if (loading) return <LoadingState label="Loading Verified Passport Card…" />

  if (notFound) {
    return (
      <div
        data-testid="public-card-not-found"
        style={{ maxWidth: 460, margin: "0 auto", padding: "64px 24px", textAlign: "center" }}
      >
        <h1 style={{ fontSize: 20, color: TOKEN.ink, marginBottom: 10 }}>This passport card is not available</h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, lineHeight: 1.6 }}>
          The link may have been unpublished by the candidate, or it may be incorrect. Ask the candidate for an
          up-to-date Verified Work Passport link.
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
              background: "rgba(255,255,255,0.14)",
              color: "#fff",
              fontSize: 14,
              fontWeight: 600,
              textDecoration: "none",
              border: "1px solid rgba(255,255,255,0.22)",
            }}
          >
            View full Work Passport →
          </a>
        }
      />

      <p data-testid="public-card-footer-note" style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", margin: 0, lineHeight: 1.6, maxWidth: 420 }}>
        Scan the profile area to verify the full Work Passport. Recruiter-safe summaries only — no raw files, private
        evidence, or numeric scores.
      </p>
    </div>
  )
}
