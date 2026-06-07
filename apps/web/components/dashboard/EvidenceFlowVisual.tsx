"use client";

/**
 * EvidenceFlowVisual — cinematic holographic blueprint
 *
 * Dark card, glowing cyan/purple lines, animated node entrances,
 * hub scan pulse, flowing data dashes, CSS 3D mouse-tracking tilt.
 * All motion respects prefers-reduced-motion via framer-motion useReducedMotion.
 */

import { motion, useReducedMotion, useInView } from "framer-motion";
import { useRef } from "react";

// ── Data ─────────────────────────────────────────────────────────────────────

const SOURCES = [
  { label: "GitHub Proof",            hex: "#38bdf8", borderA: 0.32 },
  { label: "Website Proof",           hex: "#818cf8", borderA: 0.32 },
  { label: "Project Defense",         hex: "#34d399", borderA: 0.32 },
  { label: "Documents / Reports",     hex: "#fbbf24", borderA: 0.28 },
  { label: "Certificates / Reports",  hex: "#c084fc", borderA: 0.32 },
] as const;

const OUTPUTS = [
  { label: "Skill Graph",             hex: "#818cf8", badge: "◈", borderA: 0.5 },
  { label: "Verified Skill Badges",   hex: "#34d399", badge: "✓", borderA: 0.5 },
  { label: "Work Passport",           hex: "#c084fc", badge: "◇", borderA: 0.5 },
] as const;

// SVG viewBox "0 0 100 100" y-centers matching CSS justifyContent: space-around
const SRC_Y = [10, 30, 50, 70, 90] as const;
const OUT_Y = [100 / 6, 50, (5 * 100) / 6] as const; // ≈ 16.67, 50, 83.33

const HX = 50, HY = 50, HR = 11; // hub center + radius in viewBox units

// Bezier paths — converge to hub left, diverge from hub right
const mkSrc = (y: number) =>
  `M 0,${y} C 24,${y} 24,${HY} ${HX - HR},${HY}`;
const mkOut = (y: number) =>
  `M ${HX + HR},${HY} C 76,${HY} 76,${y} 100,${y}`;

// ── Helpers ───────────────────────────────────────────────────────────────────

function rgb(hex: string) {
  const h = hex.replace("#", "");
  return `${parseInt(h.slice(0,2),16)},${parseInt(h.slice(2,4),16)},${parseInt(h.slice(4,6),16)}`;
}

// ── Spring preset ─────────────────────────────────────────────────────────────

const spring = { type: "spring" as const, stiffness: 310, damping: 25 };

// ── Component ─────────────────────────────────────────────────────────────────

export function EvidenceFlowVisual() {
  const prefersReduced = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement>(null);
  const inView   = useInView(wrapRef, { once: true, amount: 0.25 });

  // ── 3D mouse-tracking tilt ───────────────────────────────────────────────
  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (prefersReduced) return;
    const r = e.currentTarget.getBoundingClientRect();
    const nx = (e.clientX - r.left) / r.width  - 0.5;
    const ny = (e.clientY - r.top)  / r.height - 0.5;
    e.currentTarget.style.transform =
      `perspective(900px) rotateX(${-ny * 5}deg) rotateY(${nx * 4}deg) translateZ(0)`;
  }
  function onEnter(e: React.MouseEvent<HTMLDivElement>) {
    e.currentTarget.style.transition = "transform 0.08s ease-out";
  }
  function onLeave(e: React.MouseEvent<HTMLDivElement>) {
    e.currentTarget.style.transition = "transform 0.55s cubic-bezier(0.22,1,0.36,1)";
    e.currentTarget.style.transform  = "perspective(900px) rotateX(0deg) rotateY(0deg) translateZ(0)";
  }

  return (
    <div
      data-testid="evidence-flow-visual"
      ref={wrapRef}
      onMouseMove={onMove}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{
        margin: "16px 0",
        borderRadius: 16,
        border: "1px solid rgba(6,182,212,0.18)",
        background: "linear-gradient(155deg, #05071a 0%, #090c22 45%, #060918 100%)",
        padding: "18px 14px 12px",
        position: "relative",
        overflow: "hidden",
        transformStyle: "preserve-3d",
        willChange: "transform",
        boxShadow:
          "0 0 60px rgba(79,70,229,0.12), 0 0 28px rgba(6,182,212,0.06), 0 12px 40px rgba(0,0,0,0.45)",
      }}
    >
      {/* Blueprint grid */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          backgroundImage:
            "linear-gradient(rgba(6,182,212,0.07) 1px, transparent 1px), " +
            "linear-gradient(90deg, rgba(6,182,212,0.07) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />

      {/* Ambient glows */}
      <div aria-hidden="true" style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
        <div style={{
          position: "absolute", width: 340, height: 340,
          top: "50%", left: "50%", transform: "translate(-50%,-50%)",
          background: "radial-gradient(circle, rgba(79,70,229,0.16) 0%, transparent 65%)",
          filter: "blur(40px)",
        }} />
        <div style={{
          position: "absolute", width: 180, height: 180,
          top: "50%", left: "50%", transform: "translate(-50%,-50%)",
          background: "radial-gradient(circle, rgba(6,182,212,0.12) 0%, transparent 60%)",
          filter: "blur(20px)",
        }} />
      </div>

      {/* Eyebrow */}
      <div style={{ textAlign: "center", marginBottom: 14, position: "relative" }}>
        <span style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 9, letterSpacing: "0.24em", textTransform: "uppercase",
          color: "rgba(6,182,212,0.5)", fontWeight: 600,
        }}>
          Proof becomes verified skill trust
        </span>
      </div>

      {/* ── 3-column graph ── */}
      <div style={{
        display: "flex", alignItems: "stretch",
        height: 288, position: "relative",
      }}>
        {/* LEFT — source proof nodes */}
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={{ visible: { transition: { staggerChildren: 0.075, delayChildren: 0.05 } } }}
          style={{
            flex: "0 0 23%",
            display: "flex", flexDirection: "column",
            justifyContent: "space-around",
            zIndex: 2,
          }}
        >
          {SOURCES.map((src, i) => (
            <motion.div
              key={src.label}
              variants={prefersReduced ? {} : {
                hidden:   { opacity: 0, x: -20, scale: 0.86 },
                visible:  { opacity: 1, x: 0,   scale: 1,
                            transition: { ...spring, delay: i * 0.055 } },
              }}
              whileHover={prefersReduced ? {} : {
                scale: 1.04, x: 4, transition: { duration: 0.16 },
              }}
              style={{
                padding: "6px 9px",
                borderRadius: 8,
                background: `rgba(${rgb(src.hex)}, 0.06)`,
                border: `1px solid rgba(${rgb(src.hex)}, ${src.borderA})`,
                boxShadow: `0 0 14px rgba(${rgb(src.hex)}, 0.1)`,
                display: "flex", alignItems: "center", gap: 7,
                cursor: "default",
              }}
            >
              {/* Pulsing dot */}
              <motion.span
                animate={prefersReduced ? {} : { opacity: [0.45, 1, 0.45] }}
                transition={{ duration: 2 + i * 0.35, repeat: Infinity, ease: "easeInOut" }}
                style={{
                  width: 5, height: 5, borderRadius: "50%",
                  background: src.hex,
                  boxShadow: `0 0 8px ${src.hex}`,
                  flexShrink: 0, display: "block",
                }}
              />
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 9.5, fontWeight: 600, letterSpacing: "0.03em", lineHeight: 1.25,
                color: `rgba(${rgb(src.hex)}, 0.88)`,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {src.label}
              </span>
            </motion.div>
          ))}
        </motion.div>

        {/* CENTER — hub + SVG lines */}
        <div style={{
          flex: "0 0 54%", position: "relative", zIndex: 1,
          overflow: "hidden", /* clips ring expansion to column */
        }}>
          {/* Hub */}
          <div style={{
            position: "absolute", left: "50%", top: "50%",
            transform: "translate(-50%,-50%)", zIndex: 3,
          }}>
            {/* Expanding pulse rings */}
            {!prefersReduced && [0, 1, 2].map(i => (
              <div
                key={i}
                className="vb-hub-ring"
                style={{
                  position: "absolute", left: "50%", top: "50%",
                  width: 72, height: 72, borderRadius: "50%",
                  border: "1px solid rgba(6,182,212,0.38)",
                  animationDelay: `${i * 0.92}s`,
                  pointerEvents: "none",
                }}
              />
            ))}
            {/* Static outer ring */}
            <div style={{
              position: "absolute", left: "50%", top: "50%",
              transform: "translate(-50%,-50%)",
              width: 76, height: 76, borderRadius: "50%",
              border: "1px solid rgba(79,70,229,0.22)",
              pointerEvents: "none",
            }} />
            {/* Core circle */}
            <div style={{
              width: 64, height: 64, borderRadius: "50%",
              background: "linear-gradient(140deg, #0d0d2e 0%, #080820 100%)",
              border: "1.5px solid rgba(6,182,212,0.6)",
              boxShadow:
                "0 0 30px rgba(6,182,212,0.32), 0 0 64px rgba(79,70,229,0.18), " +
                "inset 0 0 18px rgba(6,182,212,0.06)",
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              gap: 1, position: "relative", zIndex: 4, overflow: "hidden",
            }}>
              {/* Scan line sweep */}
              {!prefersReduced && (
                <div
                  className="vb-hub-scan"
                  style={{
                    position: "absolute", left: 0, right: 0, height: 2,
                    background: "linear-gradient(90deg, transparent, rgba(6,182,212,0.85), transparent)",
                    top: 0,
                  }}
                />
              )}
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 6.5, fontWeight: 700, letterSpacing: "0.18em",
                textTransform: "uppercase", color: "rgba(6,182,212,0.52)",
                textAlign: "center", lineHeight: 1.2,
              }}>
                VB · AI
              </span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 8, fontWeight: 700, letterSpacing: "0.07em",
                color: "rgba(165,180,252,0.92)", textAlign: "center",
              }}>
                Review
              </span>
              {/* Processing dots */}
              <div style={{ display: "flex", gap: 3, marginTop: 3 }}>
                {[0, 1, 2].map(i => (
                  <div
                    key={i}
                    className="vb-hub-dot"
                    style={{
                      width: 3.5, height: 3.5, borderRadius: "50%",
                      background: "rgba(6,182,212,0.82)",
                      animationDelay: `${i * 0.24}s`,
                    }}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* SVG overlay — bezier lines only (no text, no circles except junctions) */}
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
            aria-hidden="true"
          >
            <defs>
              <filter id="vbg-sm" x="-30%" y="-30%" width="160%" height="160%">
                <feGaussianBlur stdDeviation="0.6" result="b" />
                <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
            </defs>

            {/* Faint base tracks */}
            {SRC_Y.map((y, i) => (
              <path key={`bt${i}`} d={mkSrc(y)} fill="none"
                stroke={SOURCES[i].hex} strokeWidth="0.28" strokeOpacity="0.1" />
            ))}
            {OUT_Y.map((y, i) => (
              <path key={`bo${i}`} d={mkOut(y)} fill="none"
                stroke={OUTPUTS[i].hex} strokeWidth="0.28" strokeOpacity="0.1" />
            ))}

            {/* Draw-in: source → hub */}
            {SRC_Y.map((y, i) => (
              <motion.path
                key={`sl${i}`}
                d={mkSrc(y)}
                fill="none"
                stroke={SOURCES[i].hex}
                strokeWidth="0.7"
                strokeOpacity={0.72}
                filter="url(#vbg-sm)"
                initial={{ pathLength: 0 }}
                animate={inView ? { pathLength: 1 } : { pathLength: 0 }}
                transition={prefersReduced ? { duration: 0 } : {
                  pathLength: { duration: 0.6, delay: 0.08 + i * 0.09, ease: "easeInOut" },
                }}
              />
            ))}

            {/* Draw-in: hub → output */}
            {OUT_Y.map((y, i) => (
              <motion.path
                key={`ol${i}`}
                d={mkOut(y)}
                fill="none"
                stroke={OUTPUTS[i].hex}
                strokeWidth="0.7"
                strokeOpacity={0.72}
                filter="url(#vbg-sm)"
                initial={{ pathLength: 0 }}
                animate={inView ? { pathLength: 1 } : { pathLength: 0 }}
                transition={prefersReduced ? { duration: 0 } : {
                  pathLength: { duration: 0.6, delay: 0.8 + i * 0.1, ease: "easeInOut" },
                }}
              />
            ))}

            {/* Flowing data dashes layered on top */}
            {!prefersReduced && SRC_Y.map((y, i) => (
              <path key={`sf${i}`} d={mkSrc(y)} fill="none"
                stroke={SOURCES[i].hex} strokeWidth="0.45" strokeOpacity="0.52"
                strokeDasharray="2.5 6"
                style={{ animation: `vb-flow-dash 1.6s linear infinite`, animationDelay: `${i * 0.18}s` }}
              />
            ))}
            {!prefersReduced && OUT_Y.map((y, i) => (
              <path key={`of${i}`} d={mkOut(y)} fill="none"
                stroke={OUTPUTS[i].hex} strokeWidth="0.45" strokeOpacity="0.52"
                strokeDasharray="2.5 6"
                style={{ animation: `vb-flow-dash 1.6s linear infinite`, animationDelay: `${0.4 + i * 0.18}s` }}
              />
            ))}

            {/* Junction dots at hub entry/exit */}
            <motion.circle cx={HX - HR} cy={HY} r="1.4" fill="#06b6d4"
              animate={prefersReduced ? {} : { opacity: [0.35, 1, 0.35] }}
              transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
            />
            <motion.circle cx={HX + HR} cy={HY} r="1.4" fill="#06b6d4"
              animate={prefersReduced ? {} : { opacity: [0.35, 1, 0.35] }}
              transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut", delay: 0.55 }}
            />
          </svg>
        </div>

        {/* RIGHT — output trust nodes */}
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={{ visible: { transition: { staggerChildren: 0.1, delayChildren: 1.05 } } }}
          style={{
            flex: "0 0 23%",
            display: "flex", flexDirection: "column",
            justifyContent: "space-around",
            zIndex: 2,
          }}
        >
          {OUTPUTS.map((out, i) => (
            <motion.div
              key={out.label}
              variants={prefersReduced ? {} : {
                hidden:  { opacity: 0, x: 20, scale: 0.86 },
                visible: { opacity: 1, x: 0,  scale: 1,
                           transition: { ...spring, delay: i * 0.075 } },
              }}
              whileHover={prefersReduced ? {} : {
                scale: 1.04, x: -4, transition: { duration: 0.16 },
              }}
              style={{
                padding: "7px 9px",
                borderRadius: 8,
                background: `rgba(${rgb(out.hex)}, 0.1)`,
                border: `1px solid rgba(${rgb(out.hex)}, ${out.borderA})`,
                boxShadow: `0 0 20px rgba(${rgb(out.hex)}, 0.2)`,
                display: "flex", alignItems: "center", gap: 7,
                cursor: "default",
              }}
            >
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 13, fontWeight: 700, flexShrink: 0,
                color: out.hex,
                textShadow: `0 0 10px ${out.hex}`,
              }}>
                {out.badge}
              </span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 9.5, fontWeight: 600, letterSpacing: "0.03em", lineHeight: 1.25,
                color: `rgba(${rgb(out.hex)}, 0.88)`,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {out.label}
              </span>
            </motion.div>
          ))}
        </motion.div>
      </div>

      {/* Bottom legend bar */}
      <div style={{
        display: "flex", justifyContent: "space-between",
        marginTop: 10, paddingTop: 8,
        borderTop: "1px solid rgba(6,182,212,0.06)",
        position: "relative",
      }}>
        {(["Raw Proof", "AI Review", "Verified Trust"] as const).map((label, i) => (
          <span key={label} style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 8, letterSpacing: "0.22em", textTransform: "uppercase",
            color: "rgba(6,182,212,0.28)", fontWeight: 600,
            flex: i === 1 ? "0 0 54%" : "0 0 23%",
            textAlign: i === 0 ? "left" : i === 2 ? "right" : "center",
          }}>
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
