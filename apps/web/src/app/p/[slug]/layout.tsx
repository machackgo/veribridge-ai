import type { Metadata } from "next"
import type { ReactNode } from "react"

// Static share metadata for this client-rendered public surface. Without it,
// links pasted into Slack/LinkedIn preview as the generic site title. No
// personal data here by design — the page itself is fail-closed client-side.
export const metadata: Metadata = {
  title: "Verified Work Passport — VeriBridge AI",
  description: "A verified, evidence-backed Work Passport shared by a VeriBridge AI candidate.",
  openGraph: { title: "Verified Work Passport — VeriBridge AI", description: "A verified, evidence-backed Work Passport shared by a VeriBridge AI candidate.", siteName: "VeriBridge AI" },
  twitter: { card: "summary", title: "Verified Work Passport — VeriBridge AI", description: "A verified, evidence-backed Work Passport shared by a VeriBridge AI candidate." },
}

export default function ShareSurfaceLayout({ children }: { children: ReactNode }) {
  return children
}
