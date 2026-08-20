import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { SavedSearchesListView } from "./SavedSearchesListView"

/**
 * Recruiter Saved Searches (`/recruiters/saved-searches`).
 *
 * `/recruiter*` paths are public in proxy.ts, so this page enforces its own
 * auth gate server-side exactly like the workspace. Saved searches are
 * recruiter-private intent served by the authenticated
 * `/api/v1/recruiter/saved-searches` API.
 */
export default async function RecruiterSavedSearchesPage() {
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(`/login?next=${encodeURIComponent("/recruiters/saved-searches")}`)
  }

  return <SavedSearchesListView />
}
