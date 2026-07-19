"use client"

import { useEffect, useState } from "react"

import { fetchAPI } from "@/lib/api"

/**
 * Resolve a canonical evidence playback URL into something a <video> element
 * can actually play.
 *
 * Backend-authorized replay routes (``/api/v1/…``) are Bearer-gated and live on
 * the API origin, so a raw ``<video src>`` can never authorize against them.
 * Those are streamed through `fetchAPI` (which attaches the caller's session)
 * and exposed as a local object URL — the backend re-checks access per request
 * and no storage path or signed URL ever reaches the DOM. Genuinely public
 * absolute URLs pass through unchanged. Returns null while loading or when the
 * caller is not authorized (the backend answers 404), so players stay honest
 * instead of broken.
 */
export function useAuthorizedMediaUrl(rawUrl: string | null | undefined): string | null {
  const isApiRoute = Boolean(rawUrl && rawUrl.startsWith("/api/"))
  const [resolved, setResolved] = useState<string | null>(!rawUrl || isApiRoute ? null : rawUrl)

  useEffect(() => {
    if (!rawUrl) {
      setResolved(null)
      return
    }
    if (!rawUrl.startsWith("/api/")) {
      setResolved(rawUrl)
      return
    }
    let cancelled = false
    let objectUrl: string | null = null
    ;(async () => {
      try {
        const res = await fetchAPI(rawUrl)
        if (!res.ok) return
        const blob = await res.blob()
        if (!blob || blob.size === 0) return
        objectUrl = URL.createObjectURL(blob)
        if (!cancelled) setResolved(objectUrl)
      } catch {
        // Leave unresolved — the player shows no source rather than a broken one.
      }
    })()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [rawUrl])

  return resolved
}
