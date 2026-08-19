import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { RecruitersEntryView } from "./RecruitersEntryView"

/**
 * Recruiter entry (`/recruiters`) — the canonical "Recruiters" destination
 * from the main navigation.
 *
 * Signed-in visitors go straight to their real workspace; signed-out
 * visitors get the recruiter entry/login experience. `/recruiter*` paths are
 * public in proxy.ts, so the auth check happens here server-side, exactly
 * like `/recruiters/workspace`.
 */
export default async function RecruitersPage() {
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (user) {
    redirect("/recruiters/workspace")
  }

  return <RecruitersEntryView />
}
