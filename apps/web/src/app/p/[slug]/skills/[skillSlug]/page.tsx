"use client"

import { useParams } from "next/navigation"
import { PublicSkillReportView } from "./PublicSkillReportView"

export default function Page() {
  const params = useParams<{ slug: string; skillSlug: string }>()
  const slug = Array.isArray(params.slug) ? params.slug[0] : params.slug
  const skillSlug = Array.isArray(params.skillSlug) ? params.skillSlug[0] : params.skillSlug

  if (!slug || !skillSlug) return null

  return <PublicSkillReportView slug={slug} skillSlug={skillSlug} />
}
