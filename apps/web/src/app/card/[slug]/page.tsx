"use client"

import { useParams } from "next/navigation"
import { PublicPassportCardView } from "./PublicPassportCardView"

/**
 * Public Verified Passport Card route: `/card/[slug]`.
 *
 * A short, top-level URL is intentional — it keeps QR codes low-density and the
 * printed/shared link easy to type at a career fair. The full public Passport
 * stays at `/p/[slug]`; this card is the compact entry point into it.
 */
export default function Page() {
  const params = useParams<{ slug: string }>()
  const slug = Array.isArray(params.slug) ? params.slug[0] : params.slug

  if (!slug) return null

  return <PublicPassportCardView slug={slug} />
}
