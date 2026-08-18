import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { BriefDetailView } from "./BriefDetailView"

/**
 * One Hiring Brief (`/recruiters/briefs/{id}`): requirements, role-scoped
 * candidate pool, live evidence comparison, brief-scoped search. Server-side
 * auth gate identical to the other recruiter pages; the API additionally
 * isolates briefs per recruiter (foreign ids are indistinguishable from
 * missing).
 */
export default async function RecruiterBriefDetailPage({
  params,
}: {
  params: Promise<{ briefId: string }>
}) {
  const { briefId } = await params
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(
      `/login?next=${encodeURIComponent(`/recruiters/briefs/${briefId}`)}`,
    )
  }

  return <BriefDetailView briefId={briefId} />
}
