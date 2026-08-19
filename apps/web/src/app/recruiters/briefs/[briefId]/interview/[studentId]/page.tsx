import { redirect } from "next/navigation"

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { InterviewWorkspaceView } from "./InterviewWorkspaceView"

/**
 * Interview workspace for one (brief, candidate) pair
 * (`/recruiters/briefs/{id}/interview/{studentId}`): live verification
 * checklist, evidence-grounded questions, recruiter-private notes and the
 * decision strip. Server-side auth gate identical to the brief page; the
 * API additionally isolates briefs per recruiter (foreign ids are
 * indistinguishable from missing).
 */
export default async function RecruiterInterviewWorkspacePage({
  params,
}: {
  params: Promise<{ briefId: string; studentId: string }>
}) {
  const { briefId, studentId } = await params
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect(
      `/login?next=${encodeURIComponent(
        `/recruiters/briefs/${briefId}/interview/${studentId}`,
      )}`,
    )
  }

  return <InterviewWorkspaceView briefId={briefId} studentUserId={studentId} />
}
