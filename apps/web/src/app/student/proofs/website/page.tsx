"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import {
  ExtensionProofPanel,
  WEBSITE_PROOF_LIFECYCLE_FINGERPRINT,
} from "../../../../../components/skill-proof/extension-proof-panel"
import { readReturnToFromLocation } from "../../../../../components/passport/safe-return"

function WebsiteProofPageInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  // Explicit "view saved proof" mode. Only an explicit session_id in the route
  // loads a prior session — the bare base route always opens the blank
  // "Create Website Proof Session" form.
  const sessionId = searchParams.get("session_id")

  // Dev-only build fingerprint: proves in the browser console that this route
  // is served by a bundle that contains the route-mode lifecycle fix (a stale
  // dev server from another worktree logs an older fingerprint or none).
  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return
    console.info(
      "[WebsiteProofPage] build:", WEBSITE_PROOF_LIFECYCLE_FINGERPRINT,
      "| mode:", sessionId ? "existing" : "new",
      "| session_id:", sessionId ?? "(none)",
    )
  }, [sessionId])
  // When sent here from another proof-studio flow (e.g. Project Defense) with a
  // safe internal returnTo, the Back action returns there instead of the studio.
  const [returnTo] = useState<string | null>(() => readReturnToFromLocation())

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <h1
        style={{
          fontSize: 28,
          fontWeight: 700,
          color: "var(--ink)",
          letterSpacing: "-0.6px",
          marginBottom: 12,
        }}
      >
        Website / Live App Proof
      </h1>
      <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginBottom: 32, opacity: 0.85 }}>
        Capture evidence from a deployed app or live website so VeriBridge can verify real functionality,
        UI behavior, and workflow proof.
      </p>

      <ExtensionProofPanel
        initialSessionId={sessionId}
        onBack={() => router.push(returnTo ?? "/student/vbr")}
      />
    </div>
  )
}

export default function WebsiteProofPage() {
  // useSearchParams requires a Suspense boundary in the app router.
  return (
    <Suspense fallback={null}>
      <WebsiteProofPageInner />
    </Suspense>
  )
}
