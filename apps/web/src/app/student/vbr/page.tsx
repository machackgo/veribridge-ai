import { redirect } from "next/navigation"

/**
 * Legacy Proof Studio home (dashboard consolidation Stage 2).
 *
 * /student is now the canonical student home; the old /student/vbr index
 * forwards to its Proofs section so stale bookmarks and old links keep
 * working. ONLY this index redirects — every /student/vbr/** sub-route
 * (recorder sessions, passport, vault, project reports) is untouched, and the
 * recorder routes in particular must keep rendering bare.
 */
export default function LegacyProofStudioPage() {
  redirect("/student?section=proofs")
}
