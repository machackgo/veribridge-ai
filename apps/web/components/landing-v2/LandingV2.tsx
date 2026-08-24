"use client"

/**
 * VeriBridge landing page v2 — Keystone V brand.
 *
 * One idea, performed by the page itself: VERIBRIDGE MAKES WORK INSPECTABLE.
 * Candidate claim → project → evidence → Verified Work Passport → recruiter
 * discovery → inspected proof. Every capability shown here is live in
 * production; superseded or in-flight features (comparison, hiring briefs,
 * universities, visa intelligence) are deliberately absent.
 */

import Link from "next/link"
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion"
import { KeystoneMark, ProofDiamond, VeriBridgeWordmark } from "./brand"
import { HeroKeystone } from "./HeroKeystone"
import { CareerFairCallout, LaunchFilm } from "./LaunchFilm"
import { RecruiterDemo } from "./RecruiterDemo"
import { PassportDemo } from "./PassportDemo"

const CANDIDATE_CTA = "/login?next=/dashboard"
const RECRUITER_CTA = "/recruiters"

function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode
  delay?: number
  className?: string
}) {
  const reduced = useReducedMotion()
  return (
    <m.div
      className={className}
      initial={reduced ? false : { opacity: 0, y: 26 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.65, delay, ease: [0.2, 0.6, 0.2, 1] }}
    >
      {children}
    </m.div>
  )
}

function SectionHead({
  eyebrow,
  title,
  children,
  tone = "dark",
}: {
  eyebrow: string
  title: React.ReactNode
  children?: React.ReactNode
  tone?: "dark" | "light"
}) {
  return (
    <Reveal className="lv-sec-head" >
      <p className="lv-eyebrow" data-tone={tone}>
        <ProofDiamond state="verified" size={8} /> {eyebrow}
      </p>
      <h2 className="lv-h2">{title}</h2>
      {children ? <p className="lv-sec-sub">{children}</p> : null}
    </Reveal>
  )
}

export function LandingV2() {
  return (
    <LazyMotion features={domAnimation} strict>
      <div className="lv-page">
        {/* ── Navigation ── */}
        <header className="lv-nav">
          <div className="lv-nav-inner">
            <Link href="/" className="lv-nav-brand" aria-label="VeriBridge home">
              <VeriBridgeWordmark markSize={26} tone="dark" />
            </Link>
            <nav className="lv-nav-links" aria-label="Main">
              <a href="#candidates">For Candidates</a>
              <a href="#recruiters">For Recruiters</a>
              <a href="#how">How It Works</a>
            </nav>
            <div className="lv-nav-ctas">
              <Link className="lv-btn lv-btn-ghost" href={CANDIDATE_CTA}>
                Sign in
              </Link>
              <Link className="lv-btn lv-btn-primary" href={CANDIDATE_CTA}>
                Create Work Passport
              </Link>
            </div>
          </div>
        </header>

        <main>
          {/* ── Hero ── */}
          <section className="lv-hero">
            <div className="lv-hero-grid">
              <div className="lv-hero-copy">
                <m.p
                  className="lv-eyebrow"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5 }}
                >
                  <ProofDiamond state="verified" size={8} /> EVIDENCE-BASED HIRING
                  INFRASTRUCTURE
                </m.p>
                <m.h1
                  className="lv-h1"
                  initial={{ opacity: 0, y: 18 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, delay: 0.08 }}
                >
                  Don&apos;t just claim your skills.
                  <br />
                  <span className="lv-h1-accent">Prove them.</span>
                </m.h1>
                <m.p
                  className="lv-hero-sub"
                  initial={{ opacity: 0, y: 18 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, delay: 0.16 }}
                >
                  VeriBridge turns real projects into a{" "}
                  <b>Verified Work Passport</b> — published evidence recruiters
                  can search, inspect, and act on. Not another résumé. The work
                  behind it.
                </m.p>
                <m.div
                  className="lv-hero-ctas"
                  initial={{ opacity: 0, y: 18 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, delay: 0.24 }}
                >
                  <Link className="lv-btn lv-btn-primary lv-btn-lg" href={CANDIDATE_CTA}>
                    Create your Work Passport
                  </Link>
                  <Link className="lv-btn lv-btn-outline lv-btn-lg" href={RECRUITER_CTA}>
                    Explore recruiter search →
                  </Link>
                </m.div>
                <m.p
                  className="lv-hero-types"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.8, delay: 0.5 }}
                >
                  GITHUB CODE · LIVE SITES · DOCUMENTS · PROJECT DEFENSE · VIDEO
                  — ONE PASSPORT
                </m.p>
              </div>
              <HeroKeystone />
            </div>
          </section>

          {/* ── Official launch film ── */}
          <LaunchFilm candidateHref={CANDIDATE_CTA} recruiterHref={RECRUITER_CTA} />

          {/* ── Fall Career Fair callout ── */}
          <CareerFairCallout candidateHref={CANDIDATE_CTA} />

          {/* ── Proof-state strip ── */}
          <section className="lv-states" aria-label="Evidence states">
            <Reveal className="lv-states-inner">
              <p className="lv-states-lead">
                Claims are easy. Evidence is inspectable. Every skill on
                VeriBridge carries its true state:
              </p>
              <div className="lv-states-row">
                <span className="lv-state">
                  <ProofDiamond state="claimed" size={13} /> Claimed
                </span>
                <span className="lv-state-arrow" aria-hidden="true">→</span>
                <span className="lv-state">
                  <ProofDiamond state="attached" size={13} /> Evidence attached
                </span>
                <span className="lv-state-arrow" aria-hidden="true">→</span>
                <span className="lv-state" data-verified>
                  <ProofDiamond state="verified" size={13} /> Verified
                </span>
              </div>
            </Reveal>
          </section>

          {/* ── The problem ── */}
          <section className="lv-problem">
            <SectionHead
              eyebrow="THE PROBLEM"
              title={
                <>
                  A résumé says <em>“Machine Learning.”</em>
                  <br />
                  It can&apos;t show the work behind it.
                </>
              }
            >
              Traditional hiring asks what a candidate claims. VeriBridge shows
              what they&apos;ve actually demonstrated — the project, the code,
              the deployed site, the recorded defense.
            </SectionHead>
            <div className="lv-problem-grid">
              <Reveal className="lv-problem-card" delay={0.05}>
                <p className="lv-problem-label">A résumé keyword</p>
                <div className="lv-resume">
                  <div className="lv-resume-line">SKILLS</div>
                  <div className="lv-resume-tags">
                    <span>Python</span>
                    <span>Machine Learning</span>
                    <span>FastAPI</span>
                    <span>Computer Vision</span>
                    <span>NLP</span>
                  </div>
                  <p className="lv-resume-note">Five words. Zero ways to check any of them.</p>
                </div>
              </Reveal>
              <Reveal className="lv-problem-card" delay={0.15}>
                <p className="lv-problem-label" data-tone="green">The same skill on VeriBridge</p>
                <div className="lv-claimtrail">
                  <div className="lv-claimtrail-row">
                    <span className="lv-claimtrail-key">CLAIM</span>
                    <span>Machine Learning</span>
                  </div>
                  <div className="lv-claimtrail-row">
                    <span className="lv-claimtrail-key">PROJECT</span>
                    <span>sign-language-translator</span>
                  </div>
                  <div className="lv-claimtrail-row">
                    <span className="lv-claimtrail-key">EVIDENCE</span>
                    <span>GitHub code · live demo · recorded defense</span>
                  </div>
                  <div className="lv-claimtrail-row" data-verified>
                    <span className="lv-claimtrail-key">STATE</span>
                    <span>
                      <ProofDiamond state="verified" size={9} /> Verified · published
                      evidence
                    </span>
                  </div>
                </div>
              </Reveal>
            </div>
          </section>

          {/* ── How it works ── */}
          <section className="lv-how" id="how">
            <SectionHead
              eyebrow="FOR CANDIDATES · HOW IT WORKS"
              title={<>Four steps from project to proof.</>}
            />
            <div className="lv-steps">
              {[
                {
                  n: "01",
                  t: "Build",
                  d: "Add the projects you actually built — not a list of keywords.",
                },
                {
                  n: "02",
                  t: "Attach evidence",
                  d: "Connect GitHub code, capture a live site with the Website Proof recorder, add documents and video — and defend your project on camera.",
                },
                {
                  n: "03",
                  t: "Publish",
                  d: "You choose exactly what goes public. Everything is private by default.",
                },
                {
                  n: "04",
                  t: "Share",
                  d: "One passport link and QR code — and recruiters can find you through evidence search.",
                },
              ].map((step, i) => (
                <Reveal className="lv-step" key={step.n} delay={i * 0.08}>
                  <span className="lv-step-num">{step.n}</span>
                  <h3 className="lv-step-title">{step.t}</h3>
                  <p className="lv-step-desc">{step.d}</p>
                </Reveal>
              ))}
            </div>
          </section>

          {/* ── Work Passport demo ── */}
          <section className="lv-passport-section" id="candidates">
            <SectionHead
              eyebrow="THE WORK PASSPORT"
              title={<>One passport. Every claim connected to its proof.</>}
            >
              This is the structure recruiters see — skills, the projects that
              demonstrate them, and the published evidence behind each one.
            </SectionHead>
            <Reveal delay={0.1}>
              <PassportDemo />
            </Reveal>
          </section>

          {/* ── Recruiter experience ── */}
          <section className="lv-recruiter" id="recruiters">
            <SectionHead
              eyebrow="FOR RECRUITERS"
              title={
                <>
                  Search for what candidates have{" "}
                  <span className="lv-h2-accent">demonstrated</span> — not what
                  they typed.
                </>
              }
            >
              Ask in plain language — typed or spoken. VeriBridge interprets the
              request, verifies each requirement against published evidence, and
              lets you inspect the proof itself.
            </SectionHead>
            <Reveal delay={0.1}>
              <RecruiterDemo />
            </Reveal>
            <div className="lv-recruiter-feats">
              {[
                {
                  t: "Ask for proof directly",
                  d: "“Show me proof of machine learning” — evidence discovery answers with proof cards, not a list of résumés.",
                },
                {
                  t: "View Proof",
                  d: "Every verified requirement opens into the project and artifacts behind it — code, live site, documents, recorded defense.",
                },
                {
                  t: "Save to your workspace",
                  d: "Save candidates from search, a QR scan, or a shared passport. Your workspace keeps the date and source of every save.",
                },
              ].map((feat, i) => (
                <Reveal className="lv-feat" key={feat.t} delay={i * 0.08}>
                  <h3>{feat.t}</h3>
                  <p>{feat.d}</p>
                </Reveal>
              ))}
            </div>
            <Reveal className="lv-recruiter-motto" delay={0.1}>
              <p>
                Find the person. <span>Ask why.</span> Inspect the proof.
              </p>
            </Reveal>
          </section>

          {/* ── Honest signal ── */}
          <section className="lv-honest">
            <div className="lv-honest-inner">
              <SectionHead
                eyebrow="AN HONEST SIGNAL"
                title={<>No scores. No rankings. No&nbsp;black&nbsp;box.</>}
              />
              <div className="lv-honest-grid">
                {[
                  {
                    t: "Qualitative, always",
                    d: "Evidence is described — observed, supporting, process — never reduced to a percentage or a rank.",
                  },
                  {
                    t: "Claimed stays claimed",
                    d: "A skill without published evidence is labeled exactly that. The passport never inflates.",
                  },
                  {
                    t: "Candidates hold the keys",
                    d: "Private by default. Candidates choose precisely what becomes public, down to individual sections.",
                  },
                  {
                    t: "Proof, not promises",
                    d: "A passport is evidence of work — not a guarantee of employment, mastery, or identity. We say so, plainly.",
                  },
                ].map((item, i) => (
                  <Reveal className="lv-honest-card" key={item.t} delay={i * 0.06}>
                    <h3>{item.t}</h3>
                    <p>{item.d}</p>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* ── Two-sided CTA ── */}
          <section className="lv-cta2">
            <Reveal className="lv-cta2-card" delay={0}>
              <p className="lv-eyebrow">
                <ProofDiamond state="verified" size={8} /> FOR CANDIDATES
              </p>
              <h3>Turn your projects into evidence recruiters can inspect.</h3>
              <Link className="lv-btn lv-btn-primary" href={CANDIDATE_CTA}>
                Create Work Passport
              </Link>
            </Reveal>
            <Reveal className="lv-cta2-card" delay={0.1}>
              <p className="lv-eyebrow">
                <ProofDiamond state="verified" size={8} /> FOR RECRUITERS
              </p>
              <h3>Discover candidates through demonstrated work.</h3>
              <Link className="lv-btn lv-btn-outline" href={RECRUITER_CTA}>
                Explore Recruiter Search
              </Link>
            </Reveal>
          </section>

          {/* ── Final CTA ── */}
          <section className="lv-final">
            <Reveal className="lv-final-inner">
              <KeystoneMark size={56} tone="dark" className="lv-final-mark" />
              <h2 className="lv-final-h">
                Your work is more than a list of skills.
                <br />
                <span className="lv-h1-accent">Make it inspectable.</span>
              </h2>
              <Link className="lv-btn lv-btn-primary lv-btn-lg" href={CANDIDATE_CTA}>
                Build your Work Passport
              </Link>
            </Reveal>
          </section>
        </main>

        {/* ── Footer ── */}
        <footer className="lv-footer">
          <div className="lv-footer-inner">
            <div className="lv-footer-brand">
              <VeriBridgeWordmark markSize={24} tone="dark" withAI />
              <p>Evidence-based hiring infrastructure.</p>
            </div>
            <nav className="lv-footer-links" aria-label="Footer">
              <Link href={CANDIDATE_CTA}>For Candidates</Link>
              <Link href="/recruiters">For Recruiters</Link>
              <Link href="/extension">Website Proof Recorder</Link>
              <Link href="/privacy">Privacy</Link>
            </nav>
            <p className="lv-footer-note">© 2026 VeriBridge AI</p>
          </div>
        </footer>
      </div>
    </LazyMotion>
  )
}
