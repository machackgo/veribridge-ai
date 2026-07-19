import { normalizeWebsiteProofApiBase } from "../../../../packages/shared/websiteProofRecorderContract"

/** The single browser-side API base resolution path. */
export function resolvePublicApiBase(): string {
  const configured =
    process.env.NEXT_PUBLIC_API_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8128"
  const normalized = normalizeWebsiteProofApiBase(configured)
  if (!normalized) {
    throw new Error("NEXT_PUBLIC_API_URL must be an absolute HTTPS origin or a loopback HTTP origin.")
  }
  return normalized
}

export const PUBLIC_API_BASE = resolvePublicApiBase()
