import type { ReactNode } from "react"
import { StudentShell } from "../../../components/student/StudentShell"
import { studentPersonaInitials } from "../../../components/student/persona"
import { createSupabaseServerClient } from "../../lib/supabase/server"

/**
 * Shared authenticated Student Shell (dashboard consolidation Stage 1).
 * Route gating stays in proxy.ts — this layout only resolves the persona for
 * display; an unauthenticated request never reaches it.
 */
export default async function StudentLayout({ children }: { children: ReactNode }) {
  // Resolve the persona from the authenticated session — never a hardcoded identity.
  let email = ""
  let name = ""
  try {
    const supabase = await createSupabaseServerClient()
    const {
      data: { user },
    } = await supabase.auth.getUser()
    email = user?.email ?? ""
    const metadata = (user?.user_metadata ?? {}) as Record<string, unknown>
    name =
      (typeof metadata.full_name === "string" && metadata.full_name) ||
      (typeof metadata.name === "string" && metadata.name) ||
      ""
  } catch {
    // Fall through to safe generic labels if the session cannot be read.
  }

  return (
    <StudentShell
      persona={{
        name: name || email || "My Workspace",
        email,
        initials: studentPersonaInitials(name, email),
      }}
    >
      {children}
    </StudentShell>
  )
}
