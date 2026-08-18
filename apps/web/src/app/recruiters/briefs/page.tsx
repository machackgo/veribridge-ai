import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { BriefsListView } from "./BriefsListView"

/**
 * Recruiter Hiring Briefs (`/recruiters/briefs`).
 *
 * `/recruiter*` paths are public in proxy.ts, so this page enforces its own
 * auth gate server-side exactly like the workspace: no session → the
 * standard `/login?next=…` round-trip. Briefs are recruiter-private
 * workflow data served by the authenticated `/api/v1/recruiter/briefs` API.
 */
export default async function RecruiterBriefsPage() {
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(`/login?next=${encodeURIComponent("/recruiters/briefs")}`)
  }

  return <BriefsListView />
}
