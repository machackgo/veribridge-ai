import { SERVICE_PAUSED } from "@/lib/service-status"

/**
 * Site-wide notice shown only while NEXT_PUBLIC_SERVICE_STATUS=paused.
 * States plainly what works and what does not; renders nothing otherwise.
 */
export function ServiceStatusBanner() {
  if (!SERVICE_PAUSED) return null
  return (
    <div
      role="status"
      data-testid="service-status-banner"
      style={{
        background: "#fffbeb",
        borderBottom: "1px solid #f59e0b",
        color: "#78350f",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: 13,
        lineHeight: 1.5,
        padding: "8px 16px",
        textAlign: "center",
      }}
    >
      <strong>Portfolio preview:</strong> VeriBridge&apos;s hosted backend is currently paused. Public pages and the
      product demonstration (sample data) work; sign-in workspaces and shared reports are temporarily unavailable.{" "}
      <a
        href="https://github.com/machackgo/veribridge-ai"
        style={{ color: "#78350f", fontWeight: 600, textDecoration: "underline" }}
      >
        View the source on GitHub
      </a>
    </div>
  )
}
