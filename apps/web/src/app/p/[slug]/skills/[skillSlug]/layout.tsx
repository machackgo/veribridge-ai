import type { Metadata } from "next"
import type { ReactNode } from "react"

// Static share metadata for this client-rendered public surface. Without it,
// links pasted into Slack/LinkedIn preview as the generic site title. No
// personal data here by design — the page itself is fail-closed client-side.
export const metadata: Metadata = {
  title: "Verified Skill Report — VeriBridge",
  description: "An evidence-backed skill report from a VeriBridge Work Passport.",
  openGraph: { title: "Verified Skill Report — VeriBridge", description: "An evidence-backed skill report from a VeriBridge Work Passport.", siteName: "VeriBridge AI" },
  twitter: { card: "summary", title: "Verified Skill Report — VeriBridge", description: "An evidence-backed skill report from a VeriBridge Work Passport." },
}

export default function ShareSurfaceLayout({ children }: { children: ReactNode }) {
  return children
}
