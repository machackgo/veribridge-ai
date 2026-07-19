/**
 * Self-contained Passport Card → PNG exporter (no external dependency, no
 * html2canvas, no network QR/image service).
 *
 * The card a recruiter sees is reconstructed as a deterministic inline SVG from
 * the already-safe {@link PassportCardModel}, then rasterized to a PNG entirely
 * on-device and offered as a download. We rebuild from the MODEL (not the live
 * DOM) so the export is pixel-stable across browsers and never depends on
 * `foreignObject`-to-canvas support (which Safari refuses) — and so it exports
 * ONLY the card, never the surrounding page.
 *
 * Safety: the SVG is built from the same recruiter-safe fields the card renders
 * (name, headline, program, role-area labels, proof labels, the public Passport
 * URL). The profile photo is inlined as a `data:` URI when it can be fetched so
 * the canvas is never cross-origin tainted; if the fetch fails we fall back to
 * the safe initials block rather than embedding a remote URL. No raw evidence,
 * ids, scores, or private routes are ever introduced here.
 */

import type { PassportCardModel } from "@/lib/passport-card"

const WIDTH = 480
const PAD = 22
/** Rasterization scale — 2× keeps text crisp on retina / when zoomed. */
const SCALE = 2
export const CARD_IMAGE_FILENAME = "veribridge-passport-card.png"

const PROOF_SHORT: Record<string, string> = {
  "GitHub Proof": "GitHub",
  "Document Proof": "Document",
  "Website Proof": "Website",
  "Project Defense": "Defense",
  "Video Evidence": "Video",
}

/** Escape text for safe inclusion in SVG/XML markup. */
function xml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

/** Rough advance-width estimate (system sans) for chip / wrap layout. */
function textWidth(text: string, fontSize: number): number {
  return text.length * fontSize * 0.58
}

type Chip = { text: string; dot?: string }

/** Chip surface styling (light theme variants for role vs. proof chips). */
type ChipStyle = { fill: string; stroke: string; color: string }
const ROLE_CHIP: ChipStyle = { fill: "#eef2ff", stroke: "#dfe4ff", color: "#3730a3" }
const PROOF_CHIP: ChipStyle = { fill: "#f8fafc", stroke: "#eef0f6", color: "#1f2a44" }

/**
 * Lay chips out into wrapped rows within `maxWidth`. Returns the SVG fragment and
 * the total height consumed so the caller can flow the next section below it.
 */
function layoutChips(
  chips: Chip[],
  originX: number,
  originY: number,
  maxWidth: number,
  style: ChipStyle,
): { svg: string; height: number } {
  const H = 24
  const GAP = 7
  const rowGap = 8
  const padX = 11
  let x = originX
  let y = originY
  let rows = 1
  const parts: string[] = []

  for (const chip of chips) {
    const dotW = chip.dot ? 13 : 0
    const w = Math.ceil(padX * 2 + dotW + textWidth(chip.text, 12))
    if (x + w > originX + maxWidth && x > originX) {
      x = originX
      y += H + rowGap
      rows += 1
    }
    parts.push(
      `<rect x="${x}" y="${y}" width="${w}" height="${H}" rx="12" fill="${style.fill}" stroke="${style.stroke}"/>`,
    )
    let tx = x + padX
    if (chip.dot) {
      parts.push(`<circle cx="${tx + 3}" cy="${y + H / 2}" r="3.5" fill="${chip.dot}"/>`)
      tx += dotW
    }
    parts.push(
      `<text x="${tx}" y="${y + H / 2 + 4}" font-size="12" font-weight="600" fill="${style.color}">${xml(chip.text)}</text>`,
    )
    x += w + GAP
  }
  return { svg: parts.join(""), height: rows * H + (rows - 1) * rowGap }
}

const STATUS_DOT: Record<string, string> = {
  Demonstrated: "#10b981",
  "Evidence observed": "#10b981",
  "Partially demonstrated": "#d97706",
  "Supporting evidence": "#0ea5e9",
  "Needs review": "#f43f5e",
  "Not assessed": "#94a3b8",
}

/** Fetch the profile photo and return it as a same-origin `data:` URI, or null. */
async function inlinePhoto(url: string | null): Promise<string | null> {
  if (!url) return null
  try {
    const res = await fetch(url, { mode: "cors" })
    if (!res.ok) return null
    const blob = await res.blob()
    if (!blob.type.startsWith("image/")) return null
    return await new Promise<string | null>((resolve) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(typeof reader.result === "string" ? reader.result : null)
      reader.onerror = () => resolve(null)
      reader.readAsDataURL(blob)
    })
  } catch {
    return null
  }
}

/** Build the complete card SVG (as a string) from the model + inlined photo. */
function buildCardSvg(model: PassportCardModel, photoDataUri: string | null): { svg: string; height: number } {
  const initials = model.initials || "★"
  const portrait = 84
  const px = PAD
  const py = 64

  // Identity column (right of the portrait). `model.name` is only ever a REAL
  // name (placeholders are normalized to null upstream), so the fallback here is
  // honest fallback copy — and the initials block correspondingly stays "★".
  const ix = px + portrait + 16
  const name = model.name || "Verified candidate profile"
  const programLine = model.program ? `${model.program}${model.region ? ` · ${model.region}` : ""}` : null

  // Portrait: photo (clipped rounded square) or initials gradient.
  const portraitSvg = photoDataUri
    ? `<image x="${px}" y="${py}" width="${portrait}" height="${portrait}" href="${photoDataUri}" preserveAspectRatio="xMidYMid slice" clip-path="url(#pfClip)"/>` +
      `<rect x="${px}" y="${py}" width="${portrait}" height="${portrait}" rx="20" fill="none" stroke="#e6e8ef" stroke-width="1.5"/>`
    : `<rect x="${px}" y="${py}" width="${portrait}" height="${portrait}" rx="20" fill="url(#pfGrad)" stroke="#dfe4ff"/>` +
      `<text x="${px + portrait / 2}" y="${py + portrait / 2 + 11}" font-size="32" font-weight="700" fill="#ffffff" text-anchor="middle">${xml(initials)}</text>`

  // Verified badge on the portrait (published only).
  const badge = model.isPublished
    ? `<circle cx="${px + portrait - 6}" cy="${py + portrait - 6}" r="12" fill="#10b981" stroke="#ffffff" stroke-width="2"/>` +
      `<path d="M ${px + portrait - 11} ${py + portrait - 6} l 3.4 3.4 l 6 -6.6" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`
    : ""

  // Role-area chips.
  const roleChips: Chip[] = model.capabilities.map((c) => ({ text: c.label, dot: STATUS_DOT[c.status] ?? "#6366f1" }))
  // Proof coverage chips (present sources only, short labels).
  const proofChips: Chip[] = model.proofCoverage
    .filter((c) => c.present)
    .map((c) => ({ text: `✓ ${PROOF_SHORT[c.label] ?? c.label}` }))

  let y = py + portrait + 24

  const roleLabelY = y
  y += 16
  const roles = roleChips.length
    ? layoutChips(roleChips, px, y, WIDTH - px * 2, ROLE_CHIP)
    : { svg: `<text x="${px}" y="${y + 14}" font-size="12" fill="#9aa3b2">Role areas appear once skills have evidence.</text>`, height: 22 }
  y += roles.height + 20

  const proofLabelY = y
  y += 16
  const proofs = proofChips.length
    ? layoutChips(proofChips, px, y, WIDTH - px * 2, PROOF_CHIP)
    : { svg: "", height: 0 }
  y += proofs.height + 18

  // Footer: public Passport URL (or private note).
  const footer = model.publicPassportUrl
    ? xml(model.publicPassportUrl)
    : "Private preview — publish to share a public link."
  const footerY = y + 6
  const height = footerY + 22

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${height}" viewBox="0 0 ${WIDTH} ${height}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#4f46e5"/>
      <stop offset="0.55" stop-color="#6366f1"/>
      <stop offset="1" stop-color="#10b981"/>
    </linearGradient>
    <linearGradient id="pfGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6366f1"/>
      <stop offset="1" stop-color="#4338ca"/>
    </linearGradient>
    <clipPath id="pfClip"><rect x="${px}" y="${py}" width="${portrait}" height="${portrait}" rx="20"/></clipPath>
    <clipPath id="cardClip"><rect x="0" y="0" width="${WIDTH}" height="${height}" rx="18"/></clipPath>
  </defs>
  <rect x="0" y="0" width="${WIDTH}" height="${height}" rx="18" fill="#ffffff"/>
  <rect x="0" y="0" width="${WIDTH}" height="3" fill="url(#accent)" clip-path="url(#cardClip)"/>
  <rect x="0.5" y="0.5" width="${WIDTH - 1}" height="${height - 1}" rx="18" fill="none" stroke="#e6e8ef"/>
  <text x="${px}" y="${PAD + 8}" font-size="10" letter-spacing="2.2" fill="#4f46e5" font-family="'JetBrains Mono', monospace">VERIBRIDGE AI</text>
  <text x="${px}" y="${PAD + 26}" font-size="13" letter-spacing="1.6" font-weight="600" fill="#0a0e1a" font-family="'JetBrains Mono', monospace">VERIFIED WORK PASSPORT</text>
  <rect x="${WIDTH - px - 96}" y="${PAD - 4}" width="96" height="24" rx="12" fill="${model.isPublished ? "#ecfdf5" : "#f8fafc"}" stroke="${model.isPublished ? "#a7f3d0" : "#e6e8ef"}"/>
  <text x="${WIDTH - px - 48}" y="${PAD + 11}" font-size="11" font-weight="600" text-anchor="middle" fill="${model.isPublished ? "#059669" : "#6b7280"}">${model.isPublished ? "✓ Verified" : "Private"}</text>
  ${portraitSvg}
  ${badge}
  <text x="${ix}" y="${py + 20}" font-size="20" font-weight="700" fill="#0a0e1a">${xml(name.length > 22 ? name.slice(0, 21) + "…" : name)}</text>
  <text x="${ix}" y="${py + 40}" font-size="13" font-weight="500" fill="#1f2a44">${xml(model.headline.length > 34 ? model.headline.slice(0, 33) + "…" : model.headline)}</text>
  ${programLine ? `<text x="${ix}" y="${py + 60}" font-size="12" fill="#6b7280">${xml(programLine.length > 36 ? programLine.slice(0, 35) + "…" : programLine)}</text>` : ""}
  <text x="${px}" y="${roleLabelY + 10}" font-size="9.5" letter-spacing="1.4" font-weight="700" fill="#9aa3b2">ROLE AREAS</text>
  ${roles.svg}
  ${proofChips.length ? `<text x="${px}" y="${proofLabelY + 10}" font-size="9.5" letter-spacing="1.4" font-weight="700" fill="#9aa3b2">PROOF SOURCES</text>` : ""}
  ${proofs.svg}
  <text x="${px}" y="${footerY + 10}" font-size="11" fill="#6b7280" font-family="'JetBrains Mono', monospace">${footer}</text>
</svg>`

  return { svg, height }
}

function triggerDownload(blobUrl: string, filename: string) {
  const a = document.createElement("a")
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/**
 * Render the card to a PNG and trigger a download. Resolves on success; REJECTS
 * on any browser limitation (no canvas, tainted export, blocked download) so the
 * caller can show the manual "right-click / long-press to save" fallback instead
 * of silently producing a broken file.
 */
export async function downloadPassportCardImage(
  model: PassportCardModel,
  filename = CARD_IMAGE_FILENAME,
): Promise<void> {
  const photo = await inlinePhoto(model.profileImageUrl)
  const { svg, height } = buildCardSvg(model, photo)

  const svgUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  const img = new Image()
  img.crossOrigin = "anonymous"
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve()
    img.onerror = () => reject(new Error("Failed to render card image."))
    img.src = svgUrl
  })

  const canvas = document.createElement("canvas")
  canvas.width = WIDTH * SCALE
  canvas.height = height * SCALE
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("Canvas is not supported in this browser.")
  ctx.scale(SCALE, SCALE)
  ctx.drawImage(img, 0, 0)

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"))
  if (!blob) throw new Error("Could not export the card image.")

  const url = URL.createObjectURL(blob)
  try {
    triggerDownload(url, filename)
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 4000)
  }
}
