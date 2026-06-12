"use client"

import { useRouter } from "next/navigation"
import { ExtensionProofPanel } from "../../../../../components/skill-proof/extension-proof-panel"

export default function WebsiteProofPage() {
  const router = useRouter()

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

      <ExtensionProofPanel onBack={() => router.push("/student/vbr")} />
    </div>
  )
}
