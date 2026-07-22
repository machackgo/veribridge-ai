"use client"

import { Suspense, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ExtensionProofPanel } from "../../../../../components/skill-proof/extension-proof-panel"
import { readReturnToFromLocation } from "../../../../../components/passport/safe-return"

function WebsiteProofPageInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const requestedSessionId = searchParams.get("session")
  const historyMode = searchParams.get("history") === "1"
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
        {requestedSessionId ? "Website Proof result" : historyMode ? "Website Proof history" : "Create Website Proof"}
      </h1>
      <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginBottom: 32, opacity: 0.85 }}>
        {requestedSessionId
          ? "Review this specific Website Proof session, including its retained replay, analysis, privacy result, and verification."
          : historyMode
            ? "Review your Website Proof history without replacing the fresh proof entry state."
            : "Record a fresh walkthrough of a deployed website or local application."}
      </p>

      <ExtensionProofPanel
        onBack={() => router.push(returnTo ?? "/student")}
        requestedSessionId={requestedSessionId}
        historyMode={historyMode}
      />
    </div>
  )
}

export default function WebsiteProofPage() {
  return (
    <Suspense>
      <WebsiteProofPageInner />
    </Suspense>
  )
}
