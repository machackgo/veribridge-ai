"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/* ── Complete proof-of-skill data for all 5 skills ── */
type EvidenceItem = {
  type: string;
  title: string;
  desc: string;
  meta: string;
  link: string;
  external: boolean;
};

type SkillData = {
  count: number;
  verified: boolean;
  desc: string;
  evidence: EvidenceItem[];
};

const PROOF_DATA: Record<string, SkillData> = {
  Docker: {
    count: 4,
    verified: true,
    desc: "Container orchestration · 3 production deployments · used in distributed systems coursework and a deployed side-project.",
    evidence: [
      {
        type: "GitHub Repo",
        title: "proof-app · Maya/proof-app",
        desc: "Multi-stage Dockerfile · 14-service compose · CI deploy",
        meta: "main · 2d ago",
        link: "https://github.com/",
        external: true,
      },
      {
        type: "Deployed App",
        title: "proof-app.fly.dev",
        desc: "Live deployment serving real traffic · 99.7% uptime/30d",
        meta: "fly.io · live",
        link: "https://example.com/",
        external: true,
      },
      {
        type: "Coursework",
        title: "CS 4515 · Distributed Systems",
        desc: "Final project: containerised consensus protocol · A grade",
        meta: "WPI · A · transcript",
        link: "/dashboard/profile",
        external: false,
      },
      {
        type: "Certification",
        title: "Docker Foundations",
        desc: "Issued Nov 2025 · verified credential",
        meta: "Credential ID 8842",
        link: "/dashboard/profile",
        external: false,
      },
    ],
  },
  "React & TypeScript": {
    count: 5,
    verified: true,
    desc: "Front-end engineering · 5 evidence sources spanning two production projects, an internship, and an open-source contribution.",
    evidence: [
      {
        type: "GitHub Repo",
        title: "campus-jobs-board · 2.4k LOC",
        desc: "Production React + TS codebase · 87% test coverage",
        meta: "main · 4d ago",
        link: "https://github.com/",
        external: true,
      },
      {
        type: "Open Source PR",
        title: "shadcn-ui · PR #2014 merged",
        desc: "DataTable a11y fix · review-approved · in release v1.8",
        meta: "merged",
        link: "https://github.com/",
        external: true,
      },
      {
        type: "Internship",
        title: "Acme · Frontend Intern (Sum '25)",
        desc: "Shipped 3 features · perf review on file",
        meta: "verified",
        link: "/dashboard/profile",
        external: false,
      },
      {
        type: "Coursework",
        title: "CS 3733 · Software Engineering",
        desc: "Team project lead · React + TS stack · final grade A",
        meta: "WPI · A",
        link: "/dashboard/profile",
        external: false,
      },
    ],
  },
  "Distributed Systems": {
    count: 4,
    verified: true,
    desc: "Strong theoretical and applied foundation · final project verified by transcript and instructor sign-off.",
    evidence: [
      {
        type: "Coursework",
        title: "CS 4515 — Distributed Systems",
        desc: "Raft consensus + load balancer project · grade A",
        meta: "WPI · A",
        link: "/dashboard/profile",
        external: false,
      },
      {
        type: "GitHub Repo",
        title: "raft-go · 1.1k LOC",
        desc: "Hand-rolled Raft implementation · benchmark suite included",
        meta: "main",
        link: "https://github.com/",
        external: true,
      },
      {
        type: "Project Report",
        title: "Systems final paper · 14pp",
        desc: "Read by 2 reviewers · plagiarism-checked · instructor sign-off",
        meta: "verified",
        link: "/dashboard/profile",
        external: false,
      },
      {
        type: "Certification",
        title: "MIT 6.824 · self-paced",
        desc: "Lab 1–4 completed · auto-graded passing marks",
        meta: "transcript-on-file",
        link: "/dashboard/profile",
        external: false,
      },
    ],
  },
  "Machine Learning": {
    count: 3,
    verified: false,
    desc: "Coursework + one applied project. Two evidence items pending verification — a deployed Hugging Face Space and a Kaggle notebook.",
    evidence: [
      {
        type: "Coursework",
        title: "CS 4342 · Machine Learning",
        desc: "Final project: image classifier · grade B+",
        meta: "WPI · B+",
        link: "/dashboard/profile",
        external: false,
      },
      {
        type: "Hugging Face",
        title: "maya/sketch-classifier",
        desc: "Deployed Space · awaiting verification scan",
        meta: "pending",
        link: "https://example.com/",
        external: true,
      },
      {
        type: "Kaggle",
        title: "Notebook · top 30%",
        desc: "Tabular regression · public notebook · community upvotes",
        meta: "public · pending",
        link: "https://example.com/",
        external: true,
      },
    ],
  },
  "SQL & Postgres": {
    count: 2,
    verified: true,
    desc: "Database design · two course projects with normalised schemas and one production migration during internship.",
    evidence: [
      {
        type: "Coursework",
        title: "CS 4502 · Database Systems",
        desc: "Schema design + indexing project · grade A-",
        meta: "WPI · A-",
        link: "/dashboard/profile",
        external: false,
      },
      {
        type: "Internship Artifact",
        title: "Acme · migration script",
        desc: "Wrote prod-safe data migration · code-reviewed · deployed",
        meta: "verified",
        link: "/dashboard/profile",
        external: false,
      },
    ],
  },
};

const proofCards: Array<[string, string, string]> = [
  ["Dk", "Docker", "4 evidence · verified"],
  ["Re", "React & TypeScript", "5 evidence · verified"],
  ["DS", "Distributed Systems", "4 evidence · verified"],
  ["ML", "Machine Learning", "3 evidence · pending"],
  ["SQ", "SQL & Postgres", "2 evidence · verified"],
];

const flow: Array<[string, string, string, string, string]> = [
  ["01 · Ingest", "Resume + GitHub + Coursework", "PDF parsing · transcript extraction · repo analysis", "▣", "#4f46e5"],
  ["02 · AI", "AI Analysis", "Skill extraction · embeddings · evidence binding", "◇", "#8b5cf6"],
  ["03 · Match", "Match Score", "Job fit · ranked, explained, visa-aware", "✓", "#10b981"],
  ["04 · Tailor", "Tailored Resume", "Bullets · cover letter · grounded in evidence", "↗", "#4f46e5"],
  ["05 · Gap", "Skill Gap", "Missing skills · ranked by impact", "⚐", "#d97706"],
  ["06 · Project", "Project Suggestion", "Targeted builds that close real gaps", "▦", "#8b5cf6"],
  ["07 · Prep", "Mock Interview", "Role-specific drills · grounded feedback", "★", "#10b981"],
];

export function ClaudeLanding() {
  const [activeSkill, setActiveSkill] = useState<string>("Docker");
  const skillData = PROOF_DATA[activeSkill];

  /* Scroll-reveal: add .vb-in-view when element enters viewport */
  useEffect(() => {
    const targets = document.querySelectorAll<HTMLElement>(
      ".cp-triad, .cp-flow-rail, .cp-cta-card, .cp-visa-inner, .cp-proof-stage"
    );
    if (!targets.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("vb-in-view");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.10, rootMargin: "0px 0px -40px 0px" }
    );
    targets.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return (
    <main className="cp-page">
      <svg width="0" height="0" className="cp-defs" aria-hidden="true">
        <defs>
          <linearGradient id="ringGrad" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#a5b4fc" />
            <stop offset=".5" stopColor="#c4b5fd" />
            <stop offset="1" stopColor="#86efac" />
          </linearGradient>
        </defs>
      </svg>

      {/* ── Navbar ── */}
      <nav className="cp-nav" role="navigation" aria-label="Main navigation">
        <div className="cp-nav-inner">
          <Link className="cp-brand" href="/" aria-label="VeriBridge AI home">
            <span className="cp-logo" />
            VeriBridge<span>AI</span>
          </Link>
          <div className="cp-nav-links">
            <a href="#platform">Platform</a>
            <Link href="/dashboard">Students</Link>
            <Link href="/recruiter">Recruiters</Link>
            <Link href="/university">Universities</Link>
            <a href="#roadmap">Roadmap</a>
          </div>
          <div className="cp-nav-cta">
            <Link className="cp-btn cp-btn-ghost" href="/login?next=/dashboard">
              Sign in
            </Link>
            <Link className="cp-btn cp-btn-primary" href="/login?next=/dashboard">
              Start Building Profile <span className="cp-btn-arrow">→</span>
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="cp-hero">
        <div className="cp-wrap cp-hero-grid">
          <div className="cp-hero-copy">
            <div className="cp-hero-stamp cp-reveal">
              <span className="cp-pulse" />
              Verified <span className="cp-mono cp-edu">.edu</span> · Now in private beta with WPI
            </div>
            <h1 className="cp-hero-h">
              Verified student talent backed by evidence for{" "}
              <em>verified students</em>.
            </h1>
            <p className="cp-hero-sub">
              VeriBridge AI helps verified students turn projects, coursework,
              resumes, and applications into evidence-backed career profiles
              recruiters and universities can trust.
            </p>
            <div className="cp-hero-ctas">
              <Link className="cp-btn cp-btn-primary" href="/login?next=/dashboard">
                Start Building Profile <span className="cp-btn-arrow">→</span>
              </Link>
              <a className="cp-btn cp-btn-glass" href="#platform">
                View Platform
              </a>
            </div>
            <div className="cp-hero-trust">
              <span><b>FERPA-aware</b> by design</span>
              <span className="cp-sep" />
              <span><b>Three-sided</b> trust graph</span>
              <span className="cp-sep" />
              <span><b>Built at WPI</b></span>
            </div>
          </div>

          <div className="cp-stage">
            <svg className="cp-stage-svg" viewBox="0 0 600 620" preserveAspectRatio="none" aria-hidden="true">
              <path d="M 120 100 Q 250 60 400 180" />
              <path d="M 480 220 Q 380 280 280 240" />
              <path d="M 460 480 Q 320 420 200 380" />
              <path d="M 100 480 Q 200 440 300 400" />
            </svg>
            <div className="cp-stage-rot">
              <div className="cp-dash">
                <div className="cp-dash-top">
                  <span /><span /><span />
                  <span className="cp-url">veribridge.ai/me</span>
                </div>
                <div className="cp-dash-body">
                  <div className="cp-score-card">
                    <div className="cp-ring">
                      <svg viewBox="0 0 70 70">
                        <circle className="cp-ring-bg" cx="35" cy="35" r="30" fill="none" strokeWidth="6" />
                        <circle className="cp-ring-fg" cx="35" cy="35" r="30" fill="none" strokeWidth="6" />
                      </svg>
                      <div>82</div>
                    </div>
                    <div>
                      <div className="cp-score-label">Career Readiness</div>
                      <div className="cp-score-num">82 / 100 · Strong</div>
                    </div>
                    <div className="cp-score-bar">
                      <div>Trend</div>
                      <strong>↑ 14 / 30d</strong>
                    </div>
                  </div>
                  <div className="cp-mini cp-mini-indigo">
                    <div>Verified Skills</div>
                    <strong>24</strong>
                    <span>18 with public proof</span>
                  </div>
                  <div className="cp-mini cp-mini-green">
                    <div>Top Job Match</div>
                    <strong>94%</strong>
                    <span>Backend Eng · NYC</span>
                  </div>
                </div>
              </div>

              <FloatingCard className="cp-f-skill" tag="Skill · Proof-Backed" title="Docker" icon="Dk" verified>
                <p>3 evidence sources · last verified 2d ago</p>
                <EvidenceRow icon="▣" title="github.com/maya/proof-app" meta="2.1k LOC" />
                <EvidenceRow icon="↗" title="Deployed app" meta="live" />
              </FloatingCard>

              <FloatingCard className="cp-f-evidence" tag="Evidence Trail" title="CS 4515 — Distributed Systems">
                <p>Final project · A · transcript-verified</p>
                <EvidenceRow icon="⚐" title="Project report" meta="14 pp" />
                <EvidenceRow icon="▦" title="Test coverage" meta="87%" />
              </FloatingCard>

              <div className="cp-float cp-f-match">
                <div className="cp-float-head">
                  <span>Top Match · Today</span>
                  <span className="cp-verified cp-indigo-verified">94%</span>
                </div>
                <h4>Backend Engineer, Intern</h4>
                <p>Visa-compatible · 6 of 7 required skills proven</p>
              </div>

              <div className="cp-float cp-f-gap">
                <div className="cp-float-head">
                  <span>Gap · Build Next</span>
                </div>
                <h4>Kubernetes</h4>
                <p>Required by 68% of your saved jobs</p>
                <div className="cp-gap-bar"><div /></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Three-sided platform ── */}
      <section className="cp-three-sided" id="platform">
        <div className="cp-wrap">
          <SectionHead
            eyebrow="The platform"
            title={<>One verified profile, <em>three sides</em>, one source of truth.</>}
          >
            Each side gets a distinct surface, business model, and trust anchor
            — but they share the same proof-of-skill data plane underneath.
          </SectionHead>
          <div className="cp-triad">
            <SideCard
              type="a"
              badge="Side A · B2C · Free"
              title="Students"
              who={<>Verified <span className="cp-mono cp-dark">.edu</span> learners building real career profiles.</>}
              href="/dashboard"
              trust="Trust anchor"
              trustValue=".edu domain · institutional record"
              features={[
                "AI-built evidence-backed career profile",
                "Tailored applications & cover letters",
                "Readiness score with a real trend line",
                "Skill-gap recommendations & project ideas",
                "Mock interview prep",
              ]}
            >
              Turn coursework, projects, and applications into a portable
              profile recruiters can trust — and get an honest readout of
              what&apos;s missing.
            </SideCard>
            <SideCard
              type="b"
              badge="Side B · B2B · Subscription"
              title="Recruiters"
              who="Talent teams hiring early-career engineers and analysts."
              href="/recruiter"
              trust="Trust anchor"
              trustValue="Verified company & recruiter identity"
              features={[
                "Faceted search across verified students",
                "Visa-compatibility filter built in",
                "Evidence-backed profile views",
                "Anti-ghosting trust score",
                "Pipeline tracker & team workspace",
              ]}
            >
              Search for proven skills, not bullet points. Every candidate
              profile carries the receipts — and your shortlist comes
              pre-filtered for visa, role-fit, and verification.
            </SideCard>
            <SideCard
              type="c"
              badge="Side C · Institutional"
              title="Universities"
              who="Career centers and provosts who need real outcome data."
              href="/university"
              trust="Trust anchor"
              trustValue="Institution · DPA · FERPA-aware"
              features={[
                "Cohort-level readiness analytics",
                "Department skill-gap heatmaps",
                "Employer engagement trends",
                "k-anonymous aggregates · audit log",
                "Exportable board-ready reports",
              ]}
            >
              Aggregate readiness, department-level skill gaps, and recruiter
              engagement — without ever touching individual student records or
              breaking FERPA.
            </SideCard>
          </div>
        </div>
      </section>

      {/* ── Visa Intelligence Section ── */}
      <section className="cp-visa-section" id="visa">
        <div className="cp-wrap">
          <div className="cp-visa-inner">
            <div className="cp-visa-copy">
              <span className="cp-eyebrow"><span />Built for international students</span>
              <h2 className="cp-visa-h">
                Visa-aware matching,{" "}
                <em>not an afterthought</em>.
              </h2>
              <p className="cp-visa-sub">
                VeriBridge AI is designed from day one for F-1, CPT/OPT, and STEM OPT students.
                Visa intelligence is part of every job match — not a tooltip buried in settings.
              </p>
              <ul className="cp-visa-feats">
                <li>CPT/OPT-aware job matching for every role</li>
                <li>STEM OPT-friendly employer filtering</li>
                <li>H-1B sponsorship signal detection per company</li>
                <li>No sponsorship / U.S. citizens only warning</li>
                <li>Security clearance requirement warning</li>
                <li>Company visa friendliness score built into match</li>
                <li>Student-controlled visibility — private by default</li>
              </ul>
              <p className="cp-visa-disclaimer">
                VeriBridge AI provides career-readiness and job compatibility insights, not legal or immigration advice.
              </p>
              <div className="cp-visa-ctas">
                <Link className="cp-btn cp-btn-primary" href="/dashboard/visa-fit">
                  Check Visa Fit →
                </Link>
                <Link className="cp-btn cp-btn-ghost" href="/dashboard/jobs">
                  View compatible jobs
                </Link>
                <Link className="cp-btn cp-btn-ghost" href="/dashboard/privacy">
                  Learn privacy controls
                </Link>
              </div>
            </div>
            <div className="cp-visa-cards">
              {/* Visa status card */}
              <div className="cp-visa-status-card">
                <div className="cp-visa-status-head">
                  <span className="cp-mono" style={{ fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "rgba(255,255,255,.6)" }}>
                    Visa Fit · F-1 Status
                  </span>
                  <span className="cp-visa-badge">F-1 Active</span>
                </div>
                <div className="cp-visa-grid-4">
                  {([ ["Status", "F-1 Active"], ["CPT", "Spring 2026"], ["OPT", "June 2026"], ["STEM OPT", "Eligible"] ] as [string, string][]).map(([l, v]) => (
                    <div key={l} className="cp-visa-cell">
                      <div className="cp-visa-cell-label">{l}</div>
                      <div className="cp-visa-cell-val">{v}</div>
                    </div>
                  ))}
                </div>
              </div>
              {/* Job visa match rows */}
              <div className="cp-visa-jobs">
                {[
                  { co: "St", bg: "#0a0e1a", role: "Backend Engineer, Intern", company: "Stripe · NYC", match: 94, visa: 92, ok: true },
                  { co: "Lr", bg: "#0d9488", role: "Software Engineer Intern", company: "Linear · Remote", match: 91, visa: 89, ok: true },
                  { co: "An", bg: "#f59e0b", role: "SRE Intern", company: "Anthropic · SF", match: 83, visa: 46, ok: false },
                ].map((j) => (
                  <Link key={j.role} href="/dashboard/jobs" className="cp-visa-job-row" style={{ textDecoration: "none" }}>
                    <div className="cp-visa-job-co" style={{ background: j.bg }}>{j.co}</div>
                    <div className="cp-visa-job-info">
                      <div className="cp-visa-job-role">{j.role}</div>
                      <div className="cp-visa-job-company">{j.company}</div>
                    </div>
                    <div className="cp-visa-job-scores">
                      <div className="cp-visa-score-item">
                        <div className="cp-visa-score-label">Match</div>
                        <div className="cp-visa-score-val" style={{ color: "#10b981" }}>{j.match}%</div>
                      </div>
                      <div className="cp-visa-score-item">
                        <div className="cp-visa-score-label">Visa</div>
                        <div className="cp-visa-score-val" style={{ color: j.ok ? "#10b981" : "#d97706" }}>{j.visa}%</div>
                      </div>
                    </div>
                    {!j.ok && <div className="cp-visa-warn">⚠ sponsor req.</div>}
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Interactive Proof-of-Skill ── */}
      <section className="cp-proof" id="proof">
        <div className="cp-wrap">
          <SectionHead
            eyebrow="The differentiator · Proof-of-Skill"
            title={<>Every skill carries <em>receipts</em>.</>}
          >
            Click a skill below and see the GitHub repos, deployed apps,
            coursework, and certifications behind it — not self-reported tags.
          </SectionHead>
          <div className="cp-proof-stage">
            {/* Skill selector tabs — now interactive */}
            <div className="cp-proof-skills" role="tablist" aria-label="Skill evidence tabs">
              {proofCards.map(([icon, name, meta]) => {
                const isActive = activeSkill === name;
                const isPending = meta.includes("pending");
                return (
                  <button
                    key={name}
                    role="tab"
                    aria-selected={isActive}
                    aria-controls={`proof-panel-${name}`}
                    className="cp-skill-tab"
                    data-active={isActive ? "true" : undefined}
                    data-pending={isPending ? "true" : undefined}
                    type="button"
                    onClick={() => setActiveSkill(name)}
                  >
                    <span style={{
                      background: isActive ? "rgba(255,255,255,.12)" : isPending ? "#fef3e6" : undefined,
                      color: isActive ? "#fff" : isPending ? "#d97706" : undefined,
                    }}>
                      {icon}
                    </span>
                    <span>
                      <strong>{name}</strong>
                      <small>{meta}</small>
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Evidence detail panel — updates when skill changes */}
            <div
              id={`proof-panel-${activeSkill}`}
              role="tabpanel"
              className="cp-proof-detail"
              aria-label={`Evidence for ${activeSkill}`}
              key={activeSkill}
            >
              <div className="cp-pd-head">
                <div>
                  <div>Skill · {skillData.count} evidence source{skillData.count !== 1 ? "s" : ""}</div>
                  <h3>{activeSkill}</h3>
                  <p>{skillData.desc}</p>
                </div>
                <span
                  data-testid="skill-status-badge"
                  style={{
                    background: skillData.verified ? undefined : "#fef3e6",
                    color: skillData.verified ? undefined : "#d97706",
                  }}
                >
                  {skillData.verified ? "Verified" : "Pending"}
                </span>
              </div>
              <div className="cp-ev-graph">
                {skillData.evidence.map((ev) => {
                  const content = (
                    <>
                      <div>{ev.type}</div>
                      <h4>{ev.title}</h4>
                      <p>{ev.desc}</p>
                      <footer>
                        <span>{ev.meta}</span>
                        <i style={{ background: skillData.verified ? undefined : "#d97706" }} />
                      </footer>
                      <span className="cp-ev-arrow">↗</span>
                    </>
                  );
                  return ev.external ? (
                    <a
                      key={ev.title}
                      className="cp-ev-card"
                      href={ev.link}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`View evidence: ${ev.title}`}
                    >
                      {content}
                    </a>
                  ) : (
                    <Link
                      key={ev.title}
                      className="cp-ev-card"
                      href={ev.link}
                      aria-label={`View evidence: ${ev.title}`}
                    >
                      {content}
                    </Link>
                  );
                })}
              </div>
              <div className="cp-pd-foot">
                <span>What recruiters see</span>
                <p>
                  A clickable proof trail. Every claim leads to{" "}
                  <b>real artifacts</b> — not self-reported tags.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── AI Workflow ── */}
      <section className="cp-workflow" id="workflow">
        <div className="cp-wrap">
          <SectionHead
            eyebrow="How it works · AI workflow"
            title={<>Resume in. <em>Proof-backed profile</em> out.</>}
          >
            A single canonical pipeline. Every model is versioned, evaluated
            against goldens, and feeds outcomes back into the recommender.
          </SectionHead>
          <div className="cp-flow-rail">
            {flow.map(([num, name, detail, icon, color], index) => (
              <div className={`cp-flow-step cp-s${index + 1}`} key={num}>
                <div>{num}</div>
                <span className="cp-flow-ico" style={{ color }}>{icon}</span>
                <strong>{name}</strong>
                <p>{detail}</p>
              </div>
            ))}
          </div>
          <div className="cp-flow-loop">
            <span>Outcome learning loop</span>
            <p>
              Edits, applications, interviews and rejections become training
              signal that re-ranks recommendations and recalibrates readiness.
            </p>
          </div>
        </div>
      </section>

      {/* ── Final CTA ── */}
      <section className="cp-cta" id="cta">
        <div className="cp-wrap">
          <div className="cp-cta-card">
            <span className="cp-eyebrow">
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#86efac", display: "inline-block", marginRight: 8 }} />
              Build your VeriBridge profile
            </span>
            <h2>Stop describing your work. <em>Prove it.</em></h2>
            <p>Free for verified <span className="cp-mono">.edu</span> students. No credit card. Profile in under 10 minutes.</p>
            <div>
              <Link className="cp-btn cp-btn-primary" href="/login?next=/dashboard">
                Start Building Profile <span className="cp-btn-arrow">→</span>
              </Link>
              <a className="cp-btn cp-btn-ghost" href="#roadmap">View Roadmap</a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="cp-footer" id="roadmap">
        <div className="cp-wrap cp-footer-inner">
          <Link className="cp-brand" href="/">
            <span className="cp-logo" />
            VeriBridge<span>AI</span>
          </Link>
          <div>
            <a href="#platform">Platform</a>
            <Link href="/dashboard">Students</Link>
            <Link href="/recruiter">Recruiters</Link>
            <Link href="/university">Universities</Link>
            <a href="#workflow">Roadmap</a>
            <Link href="/dashboard/privacy">Privacy</Link>
          </div>
          <p className="cp-mono">© 2026 VeriBridge AI · Built at WPI</p>
        </div>
      </footer>
    </main>
  );
}

/* ── Sub-components ── */

function SectionHead({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="cp-sec-head">
      <span className="cp-eyebrow"><span />{eyebrow}</span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}

function SideCard({
  type,
  badge,
  title,
  who,
  features,
  trust,
  trustValue,
  href,
  children,
}: {
  type: "a" | "b" | "c";
  badge: string;
  title: string;
  who: React.ReactNode;
  features: string[];
  trust: string;
  trustValue: string;
  href: string;
  children: React.ReactNode;
}) {
  return (
    <article className={`cp-side cp-side-${type}`}>
      <span className="cp-side-badge">{badge}</span>
      <h3>{title}</h3>
      <p className="cp-side-who">{who}</p>
      <p className="cp-side-vp">{children}</p>
      <ul>
        {features.map((feature) => <li key={feature}>{feature}</li>)}
      </ul>
      <div className="cp-anchor">{trust}<b>{trustValue}</b></div>
      <Link className="cp-preview" href={href}>
        Preview the {title.toLowerCase()} dashboard →
      </Link>
    </article>
  );
}

function FloatingCard({
  className,
  tag,
  title,
  icon,
  verified,
  children,
}: {
  className: string;
  tag: string;
  title: string;
  icon?: string;
  verified?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`cp-float ${className}`}>
      <div className="cp-float-head">
        <span>{tag}</span>
        {verified ? <span className="cp-verified">Verified</span> : null}
      </div>
      <h4>
        {icon ? <span className="cp-skill-icon">{icon}</span> : null}
        {title}
      </h4>
      {children}
    </div>
  );
}

function EvidenceRow({ icon, title, meta }: { icon: string; title: string; meta: string }) {
  return (
    <div className="cp-ev-row">
      <span>{icon}</span>
      <b>{title}</b>
      <em>{meta}</em>
    </div>
  );
}
