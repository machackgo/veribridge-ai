// Window↔background recorder message bridge for the content script.
//
// Extracted into a dependency-injected factory so the bridge's trust gating,
// ping handling, and failure NACKs are unit-testable without a DOM or a real
// chrome runtime. content.ts wires this with the real window/chrome deps.

import {
  RECORDER_AUTH_REFRESH_REQUEST,
  RECORDER_AUTH_REFRESH_ACK,
  RECORDER_BRIDGE_PING,
  RECORDER_BRIDGE_PONG,
  RECORDER_INIT_ACK,
  RECORDER_INIT_NACK,
  RECORDER_INIT_REQUEST,
  RECORDER_START_ACK,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_ACK,
  RECORDER_TARGET_OPEN_REQUEST,
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  isTrustedVeriBridgeAppLocation,
} from "../../../packages/shared/websiteProofRecorderContract"

export interface RecorderBridgeResponse {
  ok?: boolean
  error_code?: string
  [key: string]: unknown
}

export interface RecorderBridgeEvent {
  origin: string
  data: unknown
  /** True when event.source === window (same-window postMessage). */
  same_window: boolean
}

export interface RecorderBridgeDeps {
  /** Current page location — read per message, never cached (SPA navigation). */
  getLocation: () => { hostname: string; pathname: string; origin: string }
  /** True once the extension has been reloaded and this script is orphaned. */
  isContextInvalidated: () => boolean
  /** Relay to the background service worker; resolves null when unreachable. */
  sendToBackground: (message: { type: string; payload: unknown }) => Promise<RecorderBridgeResponse | null>
  /** Post a message back to the page (origin-pinned by the caller). */
  postToPage: (message: { source: "veribridge-extension"; type: string; payload: unknown }) => void
  /** Trust localhost app routes (dev-channel builds). Default true. */
  allowLocalDevOrigins?: boolean
  /** Installed build version (manifest). Defaults to the contract constant. */
  getBuildVersion?: () => string
}

const RELAYED_REQUEST_TYPES: ReadonlySet<string> = new Set([
  RECORDER_INIT_REQUEST,
  RECORDER_AUTH_REFRESH_REQUEST,
  RECORDER_TARGET_OPEN_REQUEST,
  RECORDER_START_REQUEST,
])

function ackTypeFor(requestType: string, ok: boolean): string {
  if (!ok) return RECORDER_INIT_NACK
  switch (requestType) {
    case RECORDER_INIT_REQUEST: return RECORDER_INIT_ACK
    case RECORDER_TARGET_OPEN_REQUEST: return RECORDER_TARGET_OPEN_ACK
    case RECORDER_START_REQUEST: return RECORDER_START_ACK
    default: return RECORDER_AUTH_REFRESH_ACK
  }
}

/**
 * Returns the message handler for the recorder bridge. The handler is attached
 * on every page; each message is gated on the trusted-app-location check AT
 * MESSAGE TIME. The gate must not run at script-load time because the app is a
 * single-page application: a tab that first loaded on "/" keeps this same
 * content script after client-side navigation to /student/proofs/website, and
 * load-time gating silently dropped every recorder request on such tabs.
 */
export function createRecorderBridgeHandler(deps: RecorderBridgeDeps) {
  const allowLocalDev = deps.allowLocalDevOrigins ?? true
  const buildVersion = (): string =>
    deps.getBuildVersion?.() ?? WEBSITE_PROOF_RECORDER_BUILD_VERSION
  return (event: RecorderBridgeEvent): void => {
    if (!event.same_window) return
    const location = deps.getLocation()
    if (event.origin !== location.origin) return
    if (!isTrustedVeriBridgeAppLocation(location, allowLocalDev)) return
    const data = event.data as
      | { source?: string; type?: string; payload?: Record<string, unknown> }
      | null
    if (!data || data.source !== "veribridge-app") return

    if (data.type === RECORDER_BRIDGE_PING) {
      // Answered synchronously without the background so the page can tell
      // "bridge present" apart from "worker unreachable" and detect stale
      // builds immediately instead of waiting for the initialization deadline.
      deps.postToPage({
        source: "veribridge-extension",
        type: RECORDER_BRIDGE_PONG,
        payload: {
          request_id: String(data.payload?.request_id ?? ""),
          schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
          build_version: buildVersion(),
          context_valid: !deps.isContextInvalidated(),
          bridge_trusted: true,
        },
      })
      return
    }

    if (!data.type || !RELAYED_REQUEST_TYPES.has(data.type)) return
    const requestType = data.type
    void deps.sendToBackground({ type: requestType, payload: data.payload ?? {} }).then((response) => {
      if (!response) {
        // The background never answered (extension reloaded, or an MV3 worker
        // restart race). Fail loudly with a retryable NACK instead of leaving
        // the page to diagnose a silent timeout.
        const contextInvalidated = deps.isContextInvalidated()
        deps.postToPage({
          source: "veribridge-extension",
          type: RECORDER_INIT_NACK,
          payload: {
            ok: false,
            request_id: String(data.payload?.request_id ?? ""),
            session_id: null,
            config_revision: null,
            schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
            build_version: buildVersion(),
            ready: false,
            error_code: contextInvalidated
              ? "extension_context_invalidated"
              : "extension_worker_unreachable",
            message: contextInvalidated
              ? "The extension was reloaded. Refresh this proof page and retry."
              : "The recorder service worker did not answer. Retry initialization.",
          },
        })
        return
      }
      // The background response is an allowlisted safe ACK/NACK and never
      // includes the auth credential from the request config.
      deps.postToPage({
        source: "veribridge-extension",
        type: ackTypeFor(requestType, response.ok === true),
        payload: response,
      })
    })
  }
}
