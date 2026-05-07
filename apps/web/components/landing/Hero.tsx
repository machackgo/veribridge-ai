import Link from "next/link";
import {
  ArrowRight,
  Award,
  CheckCircle2,
  Shield,
  TrendingUp,
} from "lucide-react";

const verifiedSkills = [
  "React Development",
  "Machine Learning",
  "Data Structures",
];

export function Hero() {
  return (
    <section className="relative flex min-h-screen items-center overflow-hidden bg-gradient-to-br from-slate-50 via-indigo-50/50 to-emerald-50/40 px-6 pb-20 pt-32">
      <div className="mx-auto grid max-w-7xl items-center gap-12 lg:grid-cols-[1.04fr_0.96fr]">
        <div>
          <div className="motion-fade-up mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-white/80 px-4 py-2">
            <Shield className="h-4 w-4 text-emerald-700" aria-hidden="true" />
            <span className="text-sm font-medium text-slate-700">
              Verified .edu students only
            </span>
          </div>

          <h1 className="motion-fade-up motion-delay-100 max-w-4xl text-5xl font-bold leading-[1.05] tracking-normal text-slate-950 sm:text-6xl">
            Proof-backed career readiness for verified students
          </h1>

          <p className="motion-fade-up motion-delay-200 mt-6 max-w-2xl text-lg leading-8 text-slate-600">
            CareerProof AI helps students turn resumes, projects, coursework,
            and applications into verified career profiles recruiters and
            universities can trust.
          </p>

          <div className="motion-fade-up motion-delay-300 mt-8 flex flex-col gap-4 sm:flex-row">
            <Link
              href="/dashboard"
              className="motion-lift inline-flex min-h-12 items-center justify-center gap-2 rounded-md bg-emerald-600 px-6 font-semibold text-white shadow-xl shadow-emerald-600/20 transition-all duration-300 hover:bg-emerald-700 hover:shadow-2xl hover:shadow-emerald-600/30"
            >
              Start Building Profile
              <ArrowRight
                className="h-5 w-5 transition-transform duration-300 group-hover:translate-x-1"
                aria-hidden="true"
              />
            </Link>
            <a
              href="#platform"
              className="motion-lift inline-flex min-h-12 items-center justify-center rounded-md border border-slate-300 bg-white px-6 font-semibold text-slate-700 shadow-sm transition-all duration-300 hover:border-slate-400 hover:text-slate-950 hover:shadow-lg"
            >
              View Platform
            </a>
          </div>
        </div>

        <div className="motion-float-slow motion-glow transform-gpu rounded-lg border border-slate-200 bg-white/85 p-6 shadow-2xl shadow-slate-900/10 backdrop-blur">
          <div className="mb-6 flex items-center justify-between">
            <h2 className="font-semibold text-slate-950">Career Dashboard</h2>
            <span className="motion-pulse-soft rounded-md bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
              Active
            </span>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="motion-lift rounded-lg border border-emerald-100 bg-emerald-50 p-4 hover:shadow-lg hover:shadow-emerald-600/10">
              <TrendingUp
                className="motion-icon-tilt mb-2 h-8 w-8 text-emerald-700"
                aria-hidden="true"
              />
              <div className="text-3xl font-bold text-slate-950">92</div>
              <div className="text-xs font-medium text-slate-600">
                Career Readiness
              </div>
            </div>

            <div className="motion-lift rounded-lg border border-indigo-100 bg-indigo-50 p-4 hover:shadow-lg hover:shadow-indigo-600/10">
              <Award
                className="motion-icon-tilt mb-2 h-8 w-8 text-indigo-700"
                aria-hidden="true"
              />
              <div className="text-3xl font-bold text-slate-950">15</div>
              <div className="text-xs font-medium text-slate-600">
                Verified Skills
              </div>
            </div>
          </div>

          <div className="motion-lift mt-5 rounded-lg border border-slate-200 bg-white p-4 hover:border-emerald-200 hover:shadow-lg">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700">
                Job Match Score
              </span>
              <span className="text-sm font-bold text-emerald-700">88%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="motion-shimmer h-2 w-[88%] rounded-full bg-gradient-to-r from-emerald-500 via-indigo-500 to-emerald-500" />
            </div>
          </div>

          <div className="mt-5 space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Proof-of-skill cards
            </div>
            {verifiedSkills.map((skill) => (
              <div
                key={skill}
                className="motion-lift flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 hover:border-emerald-200 hover:shadow-md"
              >
                <CheckCircle2
                  className="motion-icon-tilt h-4 w-4 shrink-0 text-emerald-600"
                  aria-hidden="true"
                />
                <span className="flex-1 text-sm text-slate-700">{skill}</span>
                <span className="text-xs font-medium text-slate-500">
                  Verified
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
