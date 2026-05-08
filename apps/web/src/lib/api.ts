"use client"

import { createSupabaseBrowserClient } from "@/lib/supabase/client"

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"

/**
 * Authenticated fetch wrapper for the VeriBridge backend API.
 * Reads the current Supabase session and injects the access token
 * as an Authorization: Bearer header when present.
 */
export async function fetchAPI(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const supabase = createSupabaseBrowserClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string> | undefined) ?? {}),
  }

  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`
  }

  return fetch(`${API_BASE}${path}`, { ...options, headers })
}

export async function getStudentProfile(): Promise<unknown | null> {
  const res = await fetchAPI("/api/v1/student/profile")
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}
