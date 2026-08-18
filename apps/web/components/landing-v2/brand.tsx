/**
 * Keystone V brand primitives — geometry is the approved production identity
 * (brand package 2026-08-13, `keystone-v-master.svg`). Exact points on a
 * 96-unit grid; do not eyeball or restyle.
 *
 * CLAIM → EVIDENCE → TRUST: two beams converge and their intersection is the
 * green keystone diamond. Proof Green is reserved for verification states.
 */

export const INK = "#14172B"
export const PROOF_GREEN = "#1FB77E"
export const PROOF_600 = "#0E8A5D"
export const BRAND_INDIGO = "#4B50D8"

/** Full-construction V (≥48px) with derived keystone. */
const V_FULL = "10,14 34,14 48,45 62,14 86,14 48,88"
const KEYSTONE_FULL = "48,45 58.3,67.9 48,88 37.7,67.9"
/** 32px optics (widened beams, keystone on). */
const V_32 = "8,12 36,12 48,40 60,12 88,12 48,90"
const KEYSTONE_32 = "48,40 60.5,67 48,90 35.5,67"

export function KeystoneMark({
  size = 28,
  tone = "dark",
  className,
}: {
  size?: number
  /** "dark" = white V for dark surfaces; "light" = Ink V for light surfaces. */
  tone?: "dark" | "light"
  className?: string
}) {
  const small = size < 40
  const v = small ? V_32 : V_FULL
  const keystone = small ? KEYSTONE_32 : KEYSTONE_FULL
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 96 96"
      aria-hidden="true"
      focusable="false"
    >
      <polygon points={v} fill={tone === "dark" ? "#FFFFFF" : INK} />
      <polygon points={keystone} fill={PROOF_GREEN} />
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

export function VeriBridgeWordmark({
  markSize = 28,
  tone = "dark",
  withAI = false,
}: {
  markSize?: number
  tone?: "dark" | "light"
  withAI?: boolean
}) {
  return (
    <span className="lv-wordmark" data-tone={tone}>
      <KeystoneMark size={markSize} tone={tone} />
      <span className="lv-wordmark-text">
        VeriBridge
        {withAI ? <span className="lv-wordmark-ai"> AI</span> : null}
      </span>
    </span>
  )
}
