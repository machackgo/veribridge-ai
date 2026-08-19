"use client"

/**
 * Interactive recruiter-search demonstration. Mirrors the real product flow
 * (natural-language query → interpretation → requirement-by-requirement
 * evidence → View Proof) using clearly-labeled presentation fixture data.
 * No scores, no percentages — matching the product's honest-signal rules.
 */

import { useEffect, useRef, useState } from "react"
import { AnimatePresence, m, useInView, useReducedMotion } from "framer-motion"
import { ProofDiamond } from "./brand"

const QUERY = "Find an entry-level AI engineer with Python, FastAPI and machine learning"

const REQUIREMENTS = [
  { skill: "Python", evidence: true },
  { skill: "FastAPI", evidence: true },
  { skill: "Machine Learning", evidence: true },
  { skill: "NLP", evidence: false },
]

const PROOF_ITEMS = [
  {
    type: "GitHub code",
    title: "sign-language-translator",
    meta: "training pipeline · model evaluation · main branch",
  },
  {
    type: "Project defense",
    title: "Recorded defense · 12 min",
    meta: "explains dataset choices and model trade-offs on camera",
  },
  {
    type: "Live site",
    title: "Deployed demo",
    meta: "captured with the Website Proof recorder",
  },
]

type Phase = "idle" | "typing" | "interpreting" | "results"

export function RecruiterDemo() {
  const reduced = useReducedMotion()
  const rootRef = useRef<HTMLDivElement>(null)
  const inView = useInView(rootRef, { once: true, amount: 0.35 })
  const [phase, setPhase] = useState<Phase>("idle")
  const [typed, setTyped] = useState("")
  const [proofOpen, setProofOpen] = useState(false)
  const [saved, setSaved] = useState(false)
  const [runId, setRunId] = useState(0)

  useEffect(() => {
    if (!inView) return
    if (reduced) {
      setTyped(QUERY)
      setPhase("results")
      return
    }
    setTyped("")
    setProofOpen(false)
    setSaved(false)
    setPhase("typing")

    let i = 0
    const timers: ReturnType<typeof setTimeout>[] = []
    const interval = setInterval(() => {
      i += 1
      setTyped(QUERY.slice(0, i))
      if (i >= QUERY.length) {
        clearInterval(interval)
        timers.push(setTimeout(() => setPhase("interpreting"), 300))
        timers.push(setTimeout(() => setPhase("results"), 1250))
      }
    }, 26)
    return () => {
      clearInterval(interval)
      timers.forEach(clearTimeout)
    }
  }, [inView, reduced, runId])

  return (
    <div ref={rootRef} className="lv-demo" data-testid="recruiter-demo">
      <div className="lv-demo-chrome">
        <span className="lv-demo-dot" />
        <span className="lv-demo-dot" />
        <span className="lv-demo-dot" />
        <span className="lv-demo-chrome-label">Recruiter Search · demonstration with fixture data</span>
        <button
          type="button"
          className="lv-demo-replay"
          onClick={() => {
            setPhase("idle")
            setRunId((n) => n + 1)
          }}
        >
          Replay
        </button>
      </div>

      {/* Search bar */}
      <div className="lv-demo-search" aria-live="polite">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
          <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <span className="lv-demo-query">
          {typed}
          {phase === "typing" && <span className="lv-caret" aria-hidden="true" />}
        </span>
        <span className="lv-demo-mic" title="Voice search is part of the real product" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="2" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </span>
      </div>

      {/* Query interpretation */}
      <AnimatePresence>
        {(phase === "interpreting" || phase === "results") && (
          <m.div
            className="lv-demo-interp"
            initial={reduced ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
          >
            <span className="lv-demo-interp-label">Understood as</span>
            <span className="lv-chip">Role · AI engineer</span>
            <span className="lv-chip">Level · entry</span>
            <span className="lv-chip">Python</span>
            <span className="lv-chip">FastAPI</span>
            <span className="lv-chip">Machine Learning</span>
          </m.div>
        )}
      </AnimatePresence>

      {/* Candidate result */}
      <AnimatePresence>
        {phase === "results" && (
          <m.div
            className="lv-demo-result"
            initial={reduced ? false : { opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.2, 0.6, 0.2, 1] }}
          >
            <div className="lv-demo-result-head">
              <span className="lv-demo-avatar" aria-hidden="true">MC</span>
              <div>
                <div className="lv-demo-name">Maya Chen</div>
                <div className="lv-demo-role">AI/ML Engineer · Verified Work Passport</div>
              </div>
              <button
                type="button"
                className="lv-demo-save"
                data-saved={saved || undefined}
                onClick={() => setSaved((s) => !s)}
              >
                {saved ? "Saved ✓" : "Save Candidate"}
              </button>
            </div>

            <ul className="lv-demo-reqs">
              {REQUIREMENTS.map((req, i) => (
                <m.li
                  key={req.skill}
                  initial={reduced ? false : { opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: reduced ? 0 : 0.15 + i * 0.12, duration: 0.35 }}
                  data-none={!req.evidence || undefined}
                >
                  <ProofDiamond state={req.evidence ? "verified" : "claimed"} size={10} />
                  <span className="lv-demo-req-skill">{req.skill}</span>
                  <span className="lv-demo-req-state">
                    {req.evidence ? "Published evidence" : "No published evidence"}
                  </span>
                  {req.skill === "Machine Learning" && (
                    <button
                      type="button"
                      className="lv-viewproof-btn"
                      aria-expanded={proofOpen}
                      onClick={() => setProofOpen((o) => !o)}
                    >
                      {proofOpen ? "Hide proof" : "View Proof"}
                    </button>
                  )}
                </m.li>
              ))}
            </ul>

            <AnimatePresence>
              {proofOpen && (
                <m.div
                  className="lv-demo-proof"
                  initial={reduced ? false : { opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={reduced ? undefined : { opacity: 0, height: 0 }}
                  transition={{ duration: 0.4, ease: [0.2, 0.6, 0.2, 1] }}
                >
                  <div className="lv-demo-proof-inner">
                    <div className="lv-demo-proof-head">
                      <ProofDiamond state="verified" size={11} />
                      <span>
                        Machine Learning · demonstrated in <b>sign-language-translator</b>
                      </span>
                    </div>
                    {PROOF_ITEMS.map((item) => (
                      <div className="lv-demo-proof-row" key={item.type}>
                        <span className="lv-demo-proof-type">{item.type}</span>
                        <span className="lv-demo-proof-title">{item.title}</span>
                        <span className="lv-demo-proof-meta">{item.meta}</span>
                      </div>
                    ))}
                    <p className="lv-demo-proof-note">
                      The recruiter doesn&apos;t have to trust the keyword — they inspect
                      where it came from.
                    </p>
                  </div>
                </m.div>
              )}
            </AnimatePresence>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}
