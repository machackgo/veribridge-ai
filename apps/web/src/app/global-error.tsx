"use client"

// Root-layout error boundary (rare: errors thrown by the root layout itself).
// Must render its own <html>/<body> per Next.js contract.

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="en">
      <body
        style={{
          minHeight: "100vh",
          display: "grid",
          placeContent: "center",
          gap: 12,
          textAlign: "center",
          padding: 24,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        }}
      >
        <div style={{ fontSize: 40 }}>⚠️</div>
        <h1 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>VeriBridge hit an unexpected error</h1>
        <p style={{ fontSize: 14, color: "#4b5563", margin: 0 }}>
          Your data is safe.{error.digest ? ` Reference: ${error.digest}` : ""}
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            justifySelf: "center",
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
          Reload
        </button>
      </body>
    </html>
  )
}
