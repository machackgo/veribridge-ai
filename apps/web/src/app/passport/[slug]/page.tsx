import { redirect } from "next/navigation"

/**
 * Legacy public passport route.
 *
 * The canonical public Work Passport now lives at /p/[slug], which renders the
 * recruiter-safe view (no numeric readiness scores, score bars, percentages, or
 * "fully verified" wording). This route is kept only so old links keep working —
 * it permanently redirects to /p/[slug] and renders nothing itself.
 */
export default async function LegacyPublicPassportPage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  redirect(`/p/${slug}`)
}
