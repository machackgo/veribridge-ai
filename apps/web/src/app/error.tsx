"use client"

// Route-level error boundary: any uncaught render/effect error previously
// dead-ended on Next's default error page with no way back. This keeps the
// student in the app with an honest message and a real retry.

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div
      role="alert"
      style={{
        minHeight: "60vh",
        display: "grid",
        placeContent: "center",
        gap: 12,
        textAlign: "center",
        padding: 24,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <div style={{ fontSize: 40 }}>⚠️</div>
      <h1 style={{ fontSize: 20, fontWeight: 800, margin: 0, color: "#111827" }}>
        Something went wrong on this page
      </h1>
      <p style={{ fontSize: 14, color: "#4b5563", margin: 0, maxWidth: 420 }}>
        Your data is safe — this is a display error, not a data loss.
        {error.digest ? ` Reference: ${error.digest}` : ""}
      </p>
      <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 8 }}>
        <button
          type="button"
          onClick={reset}
          style={{
            background: "#4f46e5",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "10px 18px",
            fontSize: 14,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Try again
        </button>
        <a
          href="/student"
          style={{
            border: "1px solid #d1d5db",
            borderRadius: 8,
            padding: "10px 18px",
            fontSize: 14,
            fontWeight: 600,
            color: "#374151",
            textDecoration: "none",
          }}
        >
          Back to dashboard
        </a>
      </div>
    </div>
  )
}
