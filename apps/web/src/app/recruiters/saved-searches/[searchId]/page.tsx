import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { SavedSearchDetailView } from "./SavedSearchDetailView"

/**
 * One Saved Search (`/recruiters/saved-searches/{id}`): live results with
 * honest "new candidate" / "updated published evidence" annotations.
 * Server-side auth gate identical to the other recruiter pages; the API
 * additionally isolates saved searches per recruiter.
 */
export default async function RecruiterSavedSearchDetailPage({
  params,
}: {
  params: Promise<{ searchId: string }>
}) {
  const { searchId } = await params
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(
      `/login?next=${encodeURIComponent(`/recruiters/saved-searches/${searchId}`)}`,
    )
  }

  return <SavedSearchDetailView searchId={searchId} />
}
