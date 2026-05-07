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
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-white/80 px-4 py-2">
            <Shield className="h-4 w-4 text-emerald-700" aria-hidden="true" />
            <span className="text-sm font-medium text-slate-700">
              Verified .edu students only
            </span>
          </div>

          <h1 className="max-w-4xl text-5xl font-bold leading-[1.05] tracking-normal text-slate-950 sm:text-6xl">
            Proof-backed career readiness for verified students
          </h1>

          <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
            CareerProof AI helps students turn resumes, projects, coursework,
            and applications into verified career profiles recruiters and
            universities can trust.
          </p>

          <div className="mt-8 flex flex-col gap-4 sm:flex-row">
            <Link
              href="/dashboard"
              className="inline-flex min-h-12 items-center justify-center gap-2 rounded-md bg-emerald-600 px-6 font-semibold text-white shadow-xl shadow-emerald-600/20 transition hover:bg-emerald-700"
            >
              Start Building Profile
              <ArrowRight className="h-5 w-5" aria-hidden="true" />
            </Link>
            <a
              href="#platform"
              className="inline-flex min-h-12 items-center justify-center rounded-md border border-slate-300 bg-white px-6 font-semibold text-slate-700 shadow-sm transition hover:border-slate-400 hover:text-slate-950"
            >
              View Platform
            </a>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white/85 p-6 shadow-2xl shadow-slate-900/10 backdrop-blur">
          <div className="mb-6 flex items-center justify-between">
            <h2 className="font-semibold text-slate-950">Career Dashboard</h2>
            <span className="rounded-md bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
              Active
            </span>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-4">
              <TrendingUp
                className="mb-2 h-8 w-8 text-emerald-700"
                aria-hidden="true"
              />
              <div className="text-3xl font-bold text-slate-950">92</div>
              <div className="text-xs font-medium text-slate-600">
                Career Readiness
              </div>
            </div>

            <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-4">
              <Award
                className="mb-2 h-8 w-8 text-indigo-700"
                aria-hidden="true"
              />
              <div className="text-3xl font-bold text-slate-950">15</div>
              <div className="text-xs font-medium text-slate-600">
                Verified Skills
              </div>
            </div>
          </div>

          <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700">
                Job Match Score
              </span>
              <span className="text-sm font-bold text-emerald-700">88%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-100">
              <div className="h-2 w-[88%] rounded-full bg-gradient-to-r from-emerald-500 to-indigo-500" />
            </div>
          </div>

          <div className="mt-5 space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Proof-of-skill cards
            </div>
            {verifiedSkills.map((skill) => (
              <div
                key={skill}
                className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3"
              >
                <CheckCircle2
                  className="h-4 w-4 shrink-0 text-emerald-600"
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
