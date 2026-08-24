import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { PoolComparisonView } from "./PoolComparisonView"

/**
 * Evidence comparison for 2–5 members of one Talent Pool
 * (`/recruiters/pools/{id}/compare?ids=…`).
 *
 * A route rather than a modal so the comparison is deep-linkable, survives a
 * reload, and participates in browser back/forward. Server-side auth gate
 * identical to the other recruiter pages; the API additionally isolates
 * pools per recruiter AND refuses any candidate that is not a member of the
 * pool being compared.
 */
export default async function RecruiterPoolComparePage({
  params,
}: {
  params: Promise<{ poolId: string }>
}) {
  const { poolId } = await params
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(
      `/login?next=${encodeURIComponent(`/recruiters/pools/${poolId}/compare`)}`,
    )
  }

  return <PoolComparisonView poolId={poolId} />
}
