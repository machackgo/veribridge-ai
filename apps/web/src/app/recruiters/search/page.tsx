import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { RecruiterSearchView } from "./RecruiterSearchView"

/**
 * Recruiter Search & Discovery (`/recruiters/search`).
 *
 * `/recruiter*` paths are public in proxy.ts, so this page enforces its own
 * auth gate server-side exactly like the workspace: no session → the
 * standard `/login?next=…` round-trip. The search itself is served by the
 * authenticated `/api/v1/recruiter/search` API, which only ever returns
 * candidates derived from their published public Work Passports.
 */
export default async function RecruiterSearchPage() {
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(`/login?next=${encodeURIComponent("/recruiters/search")}`)
  }

  return <RecruiterSearchView />
}
