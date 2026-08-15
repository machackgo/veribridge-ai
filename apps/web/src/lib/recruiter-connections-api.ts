/**
 * Typed client for the recruiter ↔ candidate connection API
 * (`/api/v1/recruiter/connections`, migration 065).
 *
 * All calls require a Supabase session — the recruiter is a real
 * authenticated user, not the legacy email-token requester. `fetchAPI`
 * attaches the bearer token and fails fast locally when no session exists.
 */

import { fetchAPI } from "@/lib/api"

export type ConnectionSource =
  | "qr_scan"
  | "shared_link"
  | "search"
  | "role_match"
  | "direct"

export interface ConnectionCandidate {
  display_name: string | null
  headline: string | null
  summary: string | null
  availability_label: string | null
  location: string | null
  role_areas: string[]
  public_slug: string | null
  is_published: boolean
}

export interface RecruiterConnection {
  id: string
  source: ConnectionSource
  created_at: string | null
  candidate: ConnectionCandidate
}

export interface SaveCandidateResult extends RecruiterConnection {
  saved: boolean
  already_saved: boolean
}

export interface ConnectionStatus {
  saved: boolean
  connection_id: string | null
}

async function parseErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: { message?: string } | string }
    const detail = body?.detail
    if (detail && typeof detail === "object" && typeof detail.message === "string") {
      return detail.message
    }
    if (typeof detail === "string") return detail
  } catch {
    // response body was not JSON — fall back to generic message
  }
  return fallback
}

/** Raised when the caller has no session — the UI routes to login instead. */
export class AuthRequiredError extends Error {
  constructor() {
    super("Sign in to save candidates.")
    this.name = "AuthRequiredError"
  }
}

function throwIfAuthRequired(res: Response): void {
  if (res.status === 401) throw new AuthRequiredError()
}

/**
 * Idempotently save the owner of a published public passport. Repeat saves
 * return `already_saved: true` — never a duplicate, never an error.
 */
export async function saveCandidate(
  passportSlug: string,
  source: ConnectionSource,
  sourceContext?: Record<string, unknown>,
): Promise<SaveCandidateResult> {
  const res = await fetchAPI("/api/v1/recruiter/connections", {
    method: "POST",
    body: JSON.stringify({
      passport_slug: passportSlug,
      source,
      ...(sourceContext ? { source_context: sourceContext } : {}),
    }),
  })
  throwIfAuthRequired(res)
  if (!res.ok) {
    throw new Error(
      await parseErrorMessage(res, `Failed to save candidate (HTTP ${res.status}).`),
    )
  }
  return res.json()
}

/** Whether the signed-in recruiter has already saved this passport's owner. */
export async function getConnectionStatus(
  passportSlug: string,
): Promise<ConnectionStatus> {
  const res = await fetchAPI(
    `/api/v1/recruiter/connections/status?passport_slug=${encodeURIComponent(passportSlug)}`,
  )
  throwIfAuthRequired(res)
  if (!res.ok) {
    throw new Error(
      await parseErrorMessage(res, `Failed to check saved state (HTTP ${res.status}).`),
    )
  }
  return res.json()
}

/** The recruiter's saved candidates, newest first. */
export async function listConnections(): Promise<RecruiterConnection[]> {
  const res = await fetchAPI("/api/v1/recruiter/connections")
  throwIfAuthRequired(res)
  if (!res.ok) {
    throw new Error(
      await parseErrorMessage(
        res,
        `Failed to load saved candidates (HTTP ${res.status}).`,
      ),
    )
  }
  const body = (await res.json()) as { connections?: RecruiterConnection[] }
  return body.connections ?? []
}

/** Remove one of the caller's own saved candidates. */
export async function deleteConnection(connectionId: string): Promise<void> {
  const res = await fetchAPI(
    `/api/v1/recruiter/connections/${encodeURIComponent(connectionId)}`,
    { method: "DELETE" },
  )
  throwIfAuthRequired(res)
  if (!res.ok && res.status !== 404) {
    throw new Error(
      await parseErrorMessage(
        res,
        `Failed to remove saved candidate (HTTP ${res.status}).`,
      ),
    )
  }
}

/**
 * Acquisition source for the current passport visit. Student QR surfaces
 * encode `/p/{slug}?src=qr`, so a QR arrival is attributable; every other
 * arrival at a passport URL is, by product reality, a shared link.
 */
export function passportArrivalSource(
  srcParam: string | null | undefined,
): ConnectionSource {
  return srcParam === "qr" ? "qr_scan" : "shared_link"
}
