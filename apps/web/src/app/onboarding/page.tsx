import Link from "next/link"

const primaryLinkStyle = {
  display: "inline-flex",
  alignItems: "center",
  padding: "10px 18px",
  borderRadius: 10,
  background: "var(--indigo)",
  color: "#fff",
  fontSize: 14,
  fontWeight: 600,
  textDecoration: "none",
} as const

const secondaryLinkStyle = {
  display: "inline-flex",
  alignItems: "center",
  padding: "10px 18px",
  borderRadius: 10,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink)",
  fontSize: 14,
  fontWeight: 600,
  textDecoration: "none",
} as const

export default function OnboardingPage() {
  return (
    <div style={{ maxWidth: 560, margin: "0 auto", padding: "64px 24px" }}>
      <h1
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: "var(--ink)",
          letterSpacing: "-0.5px",
          marginBottom: 12,
        }}
      >
        VeriBridge Proof Studio has replaced Career Graph onboarding
      </h1>
      <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, opacity: 0.85, marginBottom: 28 }}>
        VeriBridge now focuses on Verified Build Reports — a verified proof-of-skill report built from
        your project, repo, and a short walkthrough.
      </p>
      <div style={{ display: "flex", gap: 12 }}>
        <Link href="/student" style={primaryLinkStyle}>
          Go to Student Dashboard
        </Link>
        <Link href="/dashboard" style={secondaryLinkStyle}>
          Go to dashboard
        </Link>
      </div>
    </div>
  )
}
