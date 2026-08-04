// Chrome Web Store listing for the VeriBridge Website Proof Recorder.
//
// The listing URL is env-driven because the store item ID only exists after
// Google approves the first submission. Until then the install screen shows a
// "release under review" state instead of a broken link — never expose a
// store button before the listing is live.

export const RECORDER_EXTENSION_STORE_URL: string =
  process.env.NEXT_PUBLIC_RECORDER_EXTENSION_STORE_URL ?? ""

export function isRecorderStoreListingLive(): boolean {
  return (
    RECORDER_EXTENSION_STORE_URL.startsWith("https://chromewebstore.google.com/") ||
    RECORDER_EXTENSION_STORE_URL.startsWith("https://chrome.google.com/webstore/")
  )
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
