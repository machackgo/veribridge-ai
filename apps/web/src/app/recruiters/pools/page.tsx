import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { PoolsListView } from "./PoolsListView"

/**
 * Recruiter Talent Pools (`/recruiters/pools`).
 *
 * `/recruiter*` paths are public in proxy.ts, so this page enforces its own
 * auth gate server-side exactly like the workspace: no session → the
 * standard `/login?next=…` round-trip. Pools are recruiter-private workflow
 * data served by the authenticated `/api/v1/recruiter/pools` API.
 */
export default async function RecruiterPoolsPage() {
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(`/login?next=${encodeURIComponent("/recruiters/pools")}`)
  }

  return <PoolsListView />
}
