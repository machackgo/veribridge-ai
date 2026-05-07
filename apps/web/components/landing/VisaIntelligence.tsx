import { AlertTriangle, BadgeCheck, Globe2, ShieldCheck } from "lucide-react";

const signals = [
  {
    icon: BadgeCheck,
    title: "CPT / OPT / STEM OPT readiness",
    detail: "Students can understand where a role fits their work authorization timeline.",
  },
  {
    icon: Globe2,
    title: "Company visa friendliness",
    detail: "Static signals highlight employers with stronger international-student compatibility.",
  },
  {
    icon: AlertTriangle,
    title: "Risk language detection",
    detail: "No sponsorship, U.S. citizens only, and security clearance warnings are surfaced early.",
  },
  {
    icon: ShieldCheck,
    title: "Student-controlled visibility",
    detail: "Recruiters only see work authorization chips when the student opts in.",
  },
];

export function VisaIntelligence() {
  return (
    <section className="bg-white px-6 py-24" id="visa">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <div>
            <div className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-indigo-700">
              International students · Visa intelligence
            </div>
            <h2 className="text-4xl font-bold tracking-normal text-slate-950 md:text-5xl">
              Compatibility insight before students waste a week applying.
            </h2>
            <p className="mt-5 text-lg leading-8 text-slate-600">
              VeriBridge helps international students compare job fit with
              work authorization signals, sponsorship friendliness, and
              sensitive visibility controls.
            </p>
            <p className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
              VeriBridge provides career-readiness and job compatibility
              insights, not legal or immigration advice.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {signals.map((signal) => (
              <article
                key={signal.title}
                className="motion-lift rounded-lg border border-slate-200 bg-slate-50 p-5 hover:border-indigo-200 hover:bg-white hover:shadow-xl"
              >
                <signal.icon className="motion-icon-tilt mb-4 h-8 w-8 text-indigo-700" />
                <h3 className="font-semibold text-slate-950">
                  {signal.title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {signal.detail}
                </p>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
