"use client"

/**
 * Hero visual — the Keystone story performed, not explained.
 *
 * A candidate claim and a recruiter requirement converge as two beams; their
 * intersection is the green keystone (verification). The keystone rests on a
 * Verified Work Passport carrying the actual evidence types the product
 * supports. All content is presentation fixture data.
 */

import { useRef } from "react"
import {
  m,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
} from "framer-motion"
import { PROOF_GREEN } from "./brand"

const EVIDENCE_CHIPS = [
  { label: "GitHub code", x: 88 },
  { label: "Live site", x: 194 },
  { label: "Documents", x: 283 },
  { label: "Defense", x: 376 },
  { label: "Video", x: 456 },
]

const draw = (delay: number) => ({
  hidden: { pathLength: 0, opacity: 0 },
  show: {
    pathLength: 1,
    opacity: 1,
    transition: {
      pathLength: { delay, duration: 0.7, ease: [0.3, 0, 0.2, 1] as const },
      opacity: { delay, duration: 0.2 },
    },
  },
})

const appear = (delay: number) => ({
  hidden: { opacity: 0, y: 14 },
  show: {
    opacity: 1,
    y: 0,
    transition: { delay, duration: 0.55, ease: [0.2, 0.6, 0.2, 1] as const },
  },
})

export function HeroKeystone() {
  const reduced = useReducedMotion()
  const wrapRef = useRef<HTMLDivElement>(null)
  const px = useMotionValue(0)
  const py = useMotionValue(0)
  const rx = useSpring(useTransform(py, [-0.5, 0.5], [2.4, -2.4]), {
    stiffness: 120,
    damping: 18,
  })
  const ry = useSpring(useTransform(px, [-0.5, 0.5], [-2.8, 2.8]), {
    stiffness: 120,
    damping: 18,
  })

  function onPointerMove(e: React.PointerEvent) {
    if (reduced || e.pointerType !== "mouse" || !wrapRef.current) return
    const r = wrapRef.current.getBoundingClientRect()
    px.set((e.clientX - r.left) / r.width - 0.5)
    py.set((e.clientY - r.top) / r.height - 0.5)
  }

  function onPointerLeave() {
    px.set(0)
    py.set(0)
  }

  return (
    <div
      ref={wrapRef}
      className="lv-hero-visual"
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      role="img"
      aria-label="Diagram: a candidate claim and a recruiter requirement converge into a verified keystone, backed by a Work Passport with published evidence — GitHub code, a live site, documents, a recorded project defense, and video."
    >
      <m.svg
        viewBox="0 0 560 604"
        className="lv-hero-svg"
        style={reduced ? undefined : { rotateX: rx, rotateY: ry }}
        initial={reduced ? "show" : "hidden"}
        animate="show"
      >
        <defs>
          <linearGradient id="lvBeamL" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#8A91A6" />
            <stop offset="1" stopColor={PROOF_GREEN} />
          </linearGradient>
          <linearGradient id="lvBeamR" x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#8A91A6" />
            <stop offset="1" stopColor={PROOF_GREEN} />
          </linearGradient>
          <radialGradient id="lvKeystoneGlow" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor={PROOF_GREEN} stopOpacity="0.35" />
            <stop offset="1" stopColor={PROOF_GREEN} stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* ── Claim + requirement cards ── */}
        <m.g variants={appear(0.1)}>
          <rect className="lv-svg-card" x="24" y="18" width="240" height="74" rx="14" />
          <text className="lv-svg-eyebrow" x="44" y="45">
            CANDIDATE CLAIM
          </text>
          <text className="lv-svg-title" x="44" y="72">
            Machine Learning
          </text>
        </m.g>
        <m.g variants={appear(0.25)}>
          <rect className="lv-svg-card" x="296" y="18" width="240" height="74" rx="14" />
          <text className="lv-svg-eyebrow" x="316" y="45">
            RECRUITER REQUIREMENT
          </text>
          <text className="lv-svg-mono-q" x="316" y="72">
            “machine learning”
          </text>
        </m.g>

        {/* ── Converging beams ── */}
        <m.path
          d="M 144 92 L 271 234"
          stroke="url(#lvBeamL)"
          strokeWidth="2"
          fill="none"
          variants={draw(0.55)}
        />
        <m.path
          d="M 416 92 L 289 234"
          stroke="url(#lvBeamR)"
          strokeWidth="2"
          fill="none"
          variants={draw(0.55)}
        />

        {/* ── The keystone ── */}
        <m.g variants={appear(1.15)}>
          <circle cx="280" cy="272" r="74" fill="url(#lvKeystoneGlow)" />
          <m.polygon
            points="280,238 304,272 280,306 256,272"
            fill={PROOF_GREEN}
            animate={
              reduced
                ? undefined
                : { opacity: [1, 0.82, 1], scale: [1, 1.035, 1] }
            }
            transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut" }}
            style={{ transformOrigin: "280px 272px" }}
          />
          <text className="lv-svg-verified" x="280" y="336" textAnchor="middle">
            VERIFIED · PUBLISHED EVIDENCE
          </text>
        </m.g>

        {/* ── Connector into the passport ── */}
        <m.path
          d="M 280 344 L 280 392"
          stroke={PROOF_GREEN}
          strokeWidth="2"
          strokeDasharray="3 6"
          fill="none"
          variants={draw(1.5)}
        />

        {/* ── Verified Work Passport ── */}
        <m.g variants={appear(1.75)}>
          <rect className="lv-svg-passport" x="40" y="392" width="480" height="188" rx="18" />
          <text className="lv-svg-eyebrow" x="66" y="424">
            VERIFIED WORK PASSPORT
          </text>
          <text className="lv-svg-title" x="66" y="452">
            Maya Chen
          </text>
          <text className="lv-svg-sub" x="66" y="472">
            AI/ML Engineer · 3 projects · 4 skills with published evidence
          </text>
          <line x1="66" y1="490" x2="494" y2="490" className="lv-svg-line" />
          {EVIDENCE_CHIPS.map((chip, i) => (
            <m.g key={chip.label} variants={appear(1.95 + i * 0.08)}>
              <polygon
                points={`${chip.x},516 ${chip.x + 5},523 ${chip.x},530 ${chip.x - 5},523`}
                fill={PROOF_GREEN}
              />
              <text className="lv-svg-chip" x={chip.x + 11} y="527">
                {chip.label}
              </text>
            </m.g>
          ))}
          <text className="lv-svg-viewproof" x="66" y="562">
            View proof →
          </text>
        </m.g>
      </m.svg>
    </div>
  )
}
