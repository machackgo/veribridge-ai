// Canonical production metadata for the VeriBridge Website Proof Recorder
// Chrome extension.
//
// THIS FILE IS THE ONE SOURCE OF TRUTH for the store item ID and listing URL.
// Every install/discovery surface (student dashboard card, Website Proof
// install gate, connection-recovery panel, /extension help page) reads from
// here — never inline a store URL at a call site.
//
// The listing is published and permanent, so the canonical URL is built in
// rather than deployment-configured: an unset env var must never regress a
// live listing back to a "coming soon" state. NEXT_PUBLIC_RECORDER_EXTENSION_
// STORE_URL remains an override for pre-release/staging channels only, and is
// rejected unless it is a real Chrome Web Store URL.

/** Published Chrome Web Store item ID for the recorder extension. */
export const VERIBRIDGE_CHROME_EXTENSION_ID = "gdogdgnaioldjldljniffcmkcdpdjlme"

/** Canonical public Chrome Web Store listing for the recorder extension. */
export const VERIBRIDGE_CHROME_EXTENSION_URL =
  `https://chromewebstore.google.com/detail/veribridge-website-proof/${VERIBRIDGE_CHROME_EXTENSION_ID}` as const

/** True only for a real Chrome Web Store listing URL. */
export function isChromeWebStoreUrl(url: string): boolean {
  return (
    url.startsWith("https://chromewebstore.google.com/") ||
    url.startsWith("https://chrome.google.com/webstore/")
  )
}

const envOverride = process.env.NEXT_PUBLIC_RECORDER_EXTENSION_STORE_URL ?? ""

/**
 * The store URL every install surface links to. An env override is honored
 * only when it is a genuine Chrome Web Store URL, so a typo or a stray value
 * can never point students at an arbitrary origin.
 */
export const RECORDER_EXTENSION_STORE_URL: string = isChromeWebStoreUrl(envOverride)
  ? envOverride
  : VERIBRIDGE_CHROME_EXTENSION_URL

/**
 * Whether a real listing is available to link to. Kept as a function (rather
 * than inlining `true`) so the install surfaces retain their safe
 * no-broken-link fallback if the canonical URL is ever unpublished.
 */
export function isRecorderStoreListingLive(): boolean {
  return isChromeWebStoreUrl(RECORDER_EXTENSION_STORE_URL)
}

export type RecorderBrowserSupport = "supported" | "unsupported" | "unknown"

/**
 * Chromium desktop browsers can install from the Chrome Web Store (Chrome,
 * Edge, Brave, Opera…). Firefox/Safari and mobile browsers cannot run the
 * recorder today.
 */
export function detectRecorderBrowserSupport(userAgent?: string): RecorderBrowserSupport {
  const ua = userAgent ?? (typeof navigator === "undefined" ? "" : navigator.userAgent)
  if (!ua) return "unknown"
  if (/Mobi|Android|iPhone|iPad/i.test(ua)) return "unsupported"
  if (/Firefox\//i.test(ua)) return "unsupported"
  // Safari: has Safari/ but no Chrome/Chromium/Edg token.
  if (/Safari\//i.test(ua) && !/Chrome|Chromium|Edg/i.test(ua)) return "unsupported"
  if (/Chrome|Chromium|Edg/i.test(ua)) return "supported"
  return "unknown"
}
