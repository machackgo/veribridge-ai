/** Extension-facing aliases for the one shared Website Proof recorder contract. */
export {
  normalizeWebsiteProofApiBase as normalizeRecorderApiUrl,
  normalizeWebsiteProofRecorderConfig as normalizeRecorderSessionConfig,
  refreshWebsiteProofRecorderAuth as refreshRecorderSessionAuth,
  selectWebsiteProofRecorderConfig as selectRecorderSessionConfig,
} from "../../../packages/shared/websiteProofRecorderContract"

export type {
  WebsiteProofRecorderConfig as RecorderSessionConfig,
  RecorderConfigSelection as RecorderSessionConfigSelection,
} from "../../../packages/shared/websiteProofRecorderContract"

import type { WebsiteProofRecorderConfig } from "../../../packages/shared/websiteProofRecorderContract"

/** Return a base only when it belongs to the exact session being operated on. */
export function recorderApiUrlForSession(
  config: WebsiteProofRecorderConfig | null,
  sessionId: string,
): string | null {
  return config?.session_id === sessionId ? config.api_base_url : null
}
