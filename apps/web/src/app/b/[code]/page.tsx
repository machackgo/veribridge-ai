import type { CSSProperties } from "react"
import { redirect } from "next/navigation"

import { resolveBeamCode } from "@/lib/beam-link"

/**
 * `/b/{code}` — the scan target of every Beam Card QR (Phase 2).
 *
 * Server component on purpose: the backend resolver is consulted during the
 * HTTP request itself, so a valid code turns into a real server-side redirect
 * to the live public Passport (`/p/{slug}`) — instant for any QR scanner, no
 * client JS required — and the backend stays the ONLY authority on where a
 * code goes.
 *
 * Invalid / revoked / expired / unpublished-target codes all render the same
 * safe notice IN PLACE (the URL stays on `/b/{code}` so a refresh simply
 * retries): no holder name, no slug, no proof data, no reason detail. A
 * resolver outage renders a distinct retryable message instead — a network
 * blip must never tell a recruiter the candidate killed the link.
 */

// The target can be revoked/rotated at any moment — never cache a resolution.
export const dynamic = "force-dynamic"

export default async function BeamShortLinkPage({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>
  searchParams?: Promise<{ src?: string }>
}) {
  const { code } = await params
  const resolution = await resolveBeamCode(code)

  if (resolution.kind === "active") {
    // Carry the QR scan marker through to the passport so the arrival keeps
    // its honest `qr_scan` attribution across the short-link redirect.
    const src = (await searchParams)?.src
    const suffix = src === "qr" ? "?src=qr" : ""
    redirect(`${resolution.publicPassportPath}${suffix}`)
  }

  return <BeamLinkNotice unavailable={resolution.kind === "unavailable"} />
}

/** Safe, anonymous notice — shared copy for every non-active outcome. */
function BeamLinkNotice({ unavailable }: { unavailable: boolean }) {
  return (
    <div
      data-testid="beam-link-notice"
      style={{
        minHeight: "100vh",
        background: "#eef1f7",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "28px 16px",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: 430,
          width: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 10,
          padding: "40px 26px",
          borderRadius: 24,
          background: "#ffffff",
          border: "1px solid #e6e8ef",
          boxShadow: "0 1px 2px rgba(10,14,26,0.05), 0 28px 64px -32px rgba(30,27,75,0.25)",
          textAlign: "center",
        }}
      >
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9.5,
            letterSpacing: "0.22em",
            color: "#4f46e5",
          }}
        >
          VERIBRIDGE AI
        </span>
        <span aria-hidden style={{ fontSize: 26 }}>
          {unavailable ? "📡" : "🔗"}
        </span>
        {unavailable ? (
          <>
            <h1 data-testid="beam-link-unavailable" style={headlineStyle}>
              We couldn’t check this link right now
            </h1>
            <p style={bodyStyle}>
              The link service didn’t respond. This is usually temporary — please try again in a
              moment.
            </p>
          </>
        ) : (
          <>
            <h1 data-testid="beam-link-inactive" style={headlineStyle}>
              This Passport is currently private
            </h1>
            <p style={bodyStyle}>
              The holder has not made their Work Passport available for public viewing, or this
              link is no longer active. Ask them for an updated link.
            </p>
          </>
        )}
        <a data-testid="beam-link-learn-more" href="/" style={ctaStyle}>
          Learn about VeriBridge
        </a>
      </div>
    </div>
  )
}

const headlineStyle: CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
  color: "#0a0e1a",
  margin: 0,
  letterSpacing: "-0.01em",
}

const bodyStyle: CSSProperties = {
  fontSize: 12.5,
  color: "#6b7280",
  margin: 0,
  lineHeight: 1.6,
  maxWidth: 320,
}

const ctaStyle: CSSProperties = {
  marginTop: 8,
  fontSize: 12.5,
  fontWeight: 600,
  padding: "9px 16px",
  borderRadius: 10,
  border: "1px solid #e6e8ef",
  background: "#fff",
  color: "#1f2a44",
  textDecoration: "none",
}
