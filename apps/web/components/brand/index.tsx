/**
 * Canonical VeriBridge brand system — the approved Keystone V identity
 * (production package 2026-08-13, `keystone-v-master.svg`). This is the ONE
 * source for the VeriBridge mark across the web product; do not create
 * local logo variants, lettermarks, or emoji stand-ins.
 *
 * Geometry is exact, on a 96-unit grid, with per-size optics from the brand
 * guidelines: below 24px the keystone is dropped (silhouette carries alone),
 * 24–39px uses the widened 32px-optics build, 40px+ the full construction.
 */

export const INK = "#14172B"
export const PROOF_GREEN = "#1FB77E"
export const PROOF_600 = "#0E8A5D"
export const BRAND_INDIGO = "#4B50D8"

const V_FULL = "10,14 34,14 48,45 62,14 86,14 48,88"
const KEYSTONE_FULL = "48,45 58.3,67.9 48,88 37.7,67.9"
const V_32 = "8,12 36,12 48,40 60,12 88,12 48,90"
const KEYSTONE_32 = "48,40 60.5,67 48,90 35.5,67"
const V_16 = "6,10 40,10 48,30 56,10 90,10 48,90"

export function KeystoneMark({
  size = 28,
  tone = "light",
  className,
  style,
}: {
  size?: number
  /** "light" = Ink V for light surfaces; "dark" = white V for dark surfaces. */
  tone?: "light" | "dark"
  className?: string
  style?: React.CSSProperties
}) {
  const fill = tone === "dark" ? "#FFFFFF" : INK
  const tiny = size < 24
  const small = !tiny && size < 40
  const v = tiny ? V_16 : small ? V_32 : V_FULL
  const keystone = tiny ? null : small ? KEYSTONE_32 : KEYSTONE_FULL
  return (
    <svg
      className={className}
      style={style}
      width={size}
      height={size}
      viewBox="0 0 96 96"
      aria-hidden="true"
      focusable="false"
    >
      <polygon points={v} fill={fill} />
      {keystone ? <polygon points={keystone} fill={PROOF_GREEN} /> : null}
    </svg>
  )
}

/** Keystone proof-state diamond — the product's evidence state language. */
export function ProofDiamond({
  state,
  size = 12,
  className,
}: {
  state: "claimed" | "attached" | "verified"
  size?: number
  className?: string
}) {
  const h = size * (34 / 24)
  return (
    <svg
      className={className}
      width={size}
      height={h}
      viewBox="0 0 24 34"
      aria-hidden="true"
      focusable="false"
    >
      {state === "claimed" && (
        <polygon
          points="12,1.5 22.7,17 12,32.5 1.3,17"
          fill="none"
          stroke="#8A91A6"
          strokeWidth="2.4"
        />
      )}
      {state === "attached" && (
        <>
          <polygon
            points="12,1.5 22.7,17 12,32.5 1.3,17"
            fill="none"
            stroke="#5C6377"
            strokeWidth="2.4"
          />
          <polygon points="12,34 0,17 12,0" fill="#5C6377" opacity="0.85" />
        </>
      )}
      {state === "verified" && (
        <polygon points="12,0 24,17 12,34 0,17" fill={PROOF_GREEN} />
      )}
    </svg>
  )
}

const WORDMARK_FONT =
  '"Schibsted Grotesk", "Inter", ui-sans-serif, system-ui, sans-serif'

/**
 * Standard app-shell lockup: mark + "VeriBridge" wordmark, with optional
 * "AI" suffix and an optional product-context label (e.g. "Student").
 * Self-contained inline styles — safe on any surface, no stylesheet needed.
 */
export function VeriBridgeBrand({
  markSize = 24,
  tone = "light",
  withAI = false,
  label,
  fontSize = 15,
}: {
  markSize?: number
  tone?: "light" | "dark"
  withAI?: boolean
  /** Contextual product-mode label rendered after the wordmark. */
  label?: string
  fontSize?: number
}) {
  const ink = tone === "dark" ? "#FFFFFF" : INK
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <KeystoneMark size={markSize} tone={tone} />
      <span
        style={{
          fontFamily: WORDMARK_FONT,
          fontWeight: 600,
          letterSpacing: "-0.025em",
          fontSize,
          color: ink,
          lineHeight: 1,
        }}
      >
        VeriBridge
        {withAI ? (
          <span style={{ fontWeight: 500, color: "#8A91A6" }}> AI</span>
        ) : null}
      </span>
      {label ? (
        <span
          style={{
            fontFamily:
              '"JetBrains Mono", "SFMono-Regular", Consolas, monospace',
            fontSize: Math.round(fontSize * 0.67),
            fontWeight: 600,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "#8A91A6",
            lineHeight: 1,
          }}
        >
          {label}
        </span>
      ) : null}
    </span>
  )
}
