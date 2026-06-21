"use client"

import { useParams } from "next/navigation"
import { PublicPassportView } from "./PublicPassportView"

export default function Page() {
  const params = useParams<{ slug: string }>()
  const slug = Array.isArray(params.slug) ? params.slug[0] : params.slug

  if (!slug) return null

  return <PublicPassportView slug={slug} />
}
