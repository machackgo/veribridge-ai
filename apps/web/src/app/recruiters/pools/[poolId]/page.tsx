import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { PoolDetailView } from "./PoolDetailView"

/**
 * One Talent Pool (`/recruiters/pools/{id}`): name/description, archived
 * status, and the live candidate cards. Server-side auth gate identical to
 * the other recruiter pages; the API additionally isolates pools per
 * recruiter (foreign ids are indistinguishable from missing).
 */
export default async function RecruiterPoolDetailPage({
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
    redirect(`/login?next=${encodeURIComponent(`/recruiters/pools/${poolId}`)}`)
  }

  return <PoolDetailView poolId={poolId} />
}
