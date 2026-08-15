/**
 * Public app URL helper for recruiter-facing links (public Passport, Passport
 * Card, QR codes). Prefers the configured `NEXT_PUBLIC_APP_URL` (the same var
 * the domain integration uses — `https://veribridgeai.com` in production) and
 * falls back to the browser origin so links still work in local/dev where the
 * env var may be unset. Returns "" on the server when neither is available so
 * callers can render a relative fallback rather than a broken absolute URL.
 */
export function publicAppUrl(): string {
  const configured = process.env.NEXT_PUBLIC_APP_URL?.trim()
  if (configured) return configured.replace(/\/+$/, "")
  if (typeof window !== "undefined" && window.location?.origin) return window.location.origin
  return ""
}

/** Absolute public Work Passport URL for a slug (`{app}/p/{slug}`). */
export function publicPassportUrl(slug: string): string {
  const base = publicAppUrl()
  const path = `/p/${encodeURIComponent(slug)}`
  return base ? `${base}${path}` : path
}

/**
 * Absolute public Passport Card URL for a slug (`{app}/card/{slug}`).
 * The Card is the compact, QR-friendly recruiter entry point; the full public
 * Passport lives at `/p/{slug}`.
 */
export function publicPassportCardUrl(slug: string): string {
  const base = publicAppUrl()
  const path = `/card/${encodeURIComponent(slug)}`
  return base ? `${base}${path}` : path
}

/**
 * Absolute Beam short URL for a minted code (`{app}/b/{code}`) — the ONE value
 * the Beam Card QR / copy / share carry (Phase 2). The `/b/{code}` route asks
 * the backend resolver where to go at scan time, which is what makes every
 * handed-out QR revocable and rotatable after the fact. Same origin rules as
 * every public link: configured `NEXT_PUBLIC_APP_URL` in production, browser
 * origin in local dev — never a hardcoded host.
 */
export function beamShortUrl(code: string): string {
  const base = publicAppUrl()
  const path = `/b/${encodeURIComponent(code)}`
  return base ? `${base}${path}` : path
}

/**
 * Stamp a passport/beam URL as a QR scan surface (`?src=qr`).
 *
 * Applied ONLY to the value encoded into QR codes — copy/share buttons keep
 * the clean URL — so the public passport can honestly attribute a visit as a
 * QR scan (view analytics + Save Candidate acquisition source). The marker
 * is a plain query param: stripping it changes nothing about where the link
 * goes or what it shows.
 */
export function withQrSource(url: string): string
export function withQrSource(url: string | null): string | null
export function withQrSource(url: string | null | undefined): string | null | undefined
export function withQrSource(url: string | null | undefined): string | null | undefined {
  if (!url) return url
  return url.includes("?") ? `${url}&src=qr` : `${url}?src=qr`
}
