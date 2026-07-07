"use client"

import { useMemo, type ReactNode } from "react"

import { generateQrMatrix, type QrErrorCorrectionLevel } from "@/lib/qr"

/**
 * Inline-SVG QR code for a recruiter-safe URL (public Passport / Passport Card).
 *
 * Fully self-contained: the matrix is computed on-device by {@link generateQrMatrix}
 * — no external QR API, no network request, no image host. Encodes the passed
 * `value` (always a public `{app}/card/{slug}` or `{app}/p/{slug}` URL — never a
 * private route or raw evidence). Renders nothing when there is no value yet
 * (e.g. before the passport is published).
 *
 * When `overlay` is set the code is used as the card's PROFILE area: a small
 * centered node (initials/avatar) is layered over the middle of the code. The
 * default error-correction level is raised to "H" in that mode (~30% recovery),
 * so a small central overlay never stops the code from scanning.
 */
export function QrCode({
  value,
  size = 148,
  label,
  overlay,
  ecLevel,
  "data-testid": testId = "passport-qr",
}: {
  value: string | null | undefined
  size?: number
  label?: string
  /** Centered node (initials/avatar) layered over the code's middle. */
  overlay?: ReactNode
  /** Error-correction level. Defaults to "H" with an overlay, else "M". */
  ecLevel?: QrErrorCorrectionLevel
  "data-testid"?: string
}) {
  const level: QrErrorCorrectionLevel = ecLevel ?? (overlay ? "H" : "M")
  const matrix = useMemo(() => {
    if (!value) return null
    try {
      return generateQrMatrix(value, level)
    } catch {
      // Content too long / unencodable — fail soft to the link fallback below.
      return null
    }
  }, [value, level])

  if (!value) return null

  if (!matrix) {
    // Extremely unlikely for a slug URL, but never render a broken/blank code.
    return (
      <div
        data-testid={`${testId}-fallback`}
        style={{ fontSize: 11, color: "#6b7280", maxWidth: size, textAlign: "center" }}
      >
        {label ?? "Open the link to view the passport."}
      </div>
    )
  }

  const count = matrix.length
  const quiet = 4 // Quiet-zone modules on each side (spec minimum).
  const dim = count + quiet * 2
  const cells: string[] = []
  for (let r = 0; r < count; r += 1) {
    for (let c = 0; c < count; c += 1) {
      if (matrix[r][c]) cells.push(`M${c + quiet} ${r + quiet}h1v1h-1z`)
    }
  }

  const svg = (
    <svg
      data-testid={testId}
      data-qr-value={value}
      role="img"
      aria-label={label ?? "QR code linking to the public Verified Work Passport"}
      width={size}
      height={size}
      viewBox={`0 0 ${dim} ${dim}`}
      shapeRendering="crispEdges"
      style={{ background: "#fff", borderRadius: 10, border: "1px solid #e6e8ef", padding: 6, boxSizing: "content-box" }}
    >
      <path d={cells.join("")} fill="#0a0e1a" />
    </svg>
  )

  // Profile mode: layer the initials/avatar over the code's centre. The overlay
  // is kept small (≈30% of the code) so level-"H" recovery keeps it scannable.
  if (overlay) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
        <div style={{ position: "relative", width: size, height: size }}>
          {svg}
          <div
            data-testid={`${testId}-overlay`}
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "#fff",
              borderRadius: 10,
              padding: 3,
              boxShadow: "0 1px 3px rgba(10,14,26,0.18)",
            }}
          >
            {overlay}
          </div>
        </div>
        {label && <span style={{ fontSize: 10, color: "#6b7280", textAlign: "center", maxWidth: size + 32 }}>{label}</span>}
      </div>
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      {svg}
      {label && <span style={{ fontSize: 11, color: "#6b7280", textAlign: "center", maxWidth: size + 24 }}>{label}</span>}
    </div>
  )
}
