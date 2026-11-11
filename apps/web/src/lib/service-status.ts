/**
 * Hosted-service status for the public website.
 *
 * NEXT_PUBLIC_SERVICE_STATUS=paused is set on the Vercel production project
 * while the hosted API is offline. It is inlined at build time, so clearing the
 * variable and redeploying restores normal wording; the API client code paths
 * are unchanged either way (nothing is mocked, nothing is bypassed).
 */
export const SERVICE_PAUSED = process.env.NEXT_PUBLIC_SERVICE_STATUS === "paused"

export const NETWORK_UNREACHABLE_MESSAGE =
  "We couldn't reach the VeriBridge server. Check your connection and try again."

export const SERVICE_PAUSED_MESSAGE =
  "VeriBridge's hosted service is paused right now, so this can't be loaded. " +
  "The public pages and the product demonstration on the home page still work."

/** The message to show when no HTTP response came back at all. */
export function unreachableMessage(): string {
  return SERVICE_PAUSED ? SERVICE_PAUSED_MESSAGE : NETWORK_UNREACHABLE_MESSAGE
}

/**
 * fetch() for public (unauthenticated) API reads. A transport failure (no HTTP
 * response: DNS, CORS-blocked 5xx, offline) becomes a stable, honest message
 * instead of the browser's raw "Failed to fetch". HTTP responses pass through
 * unchanged so callers keep their 404/410/5xx handling.
 */
export async function publicApiFetch(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch (err) {
    throw new Error(unreachableMessage(), { cause: err })
  }
}
