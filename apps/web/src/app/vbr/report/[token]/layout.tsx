import type { Metadata } from "next"
import type { ReactNode } from "react"

// Static share metadata for this client-rendered public surface. Without it,
// links pasted into Slack/LinkedIn preview as the generic site title. No
// personal data here by design — the page itself is fail-closed client-side.
export const metadata: Metadata = {
  title: "Verified Build Report — VeriBridge",
  description: "An evidence-backed Verified Build Report shared by a VeriBridge candidate.",
  openGraph: { title: "Verified Build Report — VeriBridge", description: "An evidence-backed Verified Build Report shared by a VeriBridge candidate.", siteName: "VeriBridge AI" },
  twitter: { card: "summary", title: "Verified Build Report — VeriBridge", description: "An evidence-backed Verified Build Report shared by a VeriBridge candidate." },
}

export default function ShareSurfaceLayout({ children }: { children: ReactNode }) {
  return children
}
