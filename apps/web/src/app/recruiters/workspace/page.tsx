import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { RecruiterWorkspaceView } from "./RecruiterWorkspaceView"

/**
 * Recruiter Workspace — saved candidates (`/recruiters/workspace`).
 *
 * `/recruiter*` paths are public in proxy.ts (marketing + open tools), so
 * this page enforces its own auth gate server-side: no session → the
 * standard `/login?next=…` round-trip, which returns the recruiter right
 * back here after signing in. The saved-candidate list itself is served by
 * the authenticated `/api/v1/recruiter/connections` API, which is scoped to
 * the caller's own connections — the client view never decides isolation.
 */
export default async function RecruiterWorkspacePage() {
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(`/login?next=${encodeURIComponent("/recruiters/workspace")}`)
  }

  return <RecruiterWorkspaceView />
}
