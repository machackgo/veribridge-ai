/**
 * Landing-page brand shims — the canonical Keystone V primitives live in
 * `components/brand` (one logo system product-wide). This module re-exports
 * them and adds the landing's CSS-styled wordmark lockup.
 */

export {
  INK,
  PROOF_GREEN,
  PROOF_600,
  BRAND_INDIGO,
  KeystoneMark,
  ProofDiamond,
} from "../brand"

import { KeystoneMark } from "../brand"

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
