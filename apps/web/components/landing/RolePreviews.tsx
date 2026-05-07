import Link from "next/link";
import { Building2, GraduationCap, SearchCheck } from "lucide-react";

const previews = [
  {
    id: "students",
    icon: GraduationCap,
    title: "Student dashboard preview",
    href: "/dashboard",
    metrics: ["Score 82", "24 verified skills", "94% top job match"],
    detail:
      "A student command center for proof, job readiness, skill gaps, applications, visa fit, and privacy controls.",
  },
  {
    id: "recruiters",
    icon: SearchCheck,
    title: "Recruiter preview",
    href: "/recruiter",
    metrics: ["240 matches", "Proof artifacts", "Student-controlled visa chips"],
    detail:
      "A proof-backed search console for finding candidates by verified evidence, not inflated profile keywords.",
  },
  {
    id: "universities",
    icon: Building2,
    title: "University preview",
    href: "/university",
    metrics: ["k-anon ≥ 25", "Cohort trends", "Employer engagement"],
    detail:
      "Aggregate readiness analytics and skill gap reporting without exposing individual student records.",
  },
];

export function RolePreviews() {
  return (
    <section className="bg-gradient-to-br from-slate-50 via-white to-indigo-50/50 px-6 py-24">
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <div className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-700">
            Clickable product previews
          </div>
          <h2 className="text-4xl font-bold tracking-normal text-slate-950 md:text-5xl">
            Built for students, recruiters, and universities.
          </h2>
          <p className="mt-4 text-lg leading-8 text-slate-600">
            Each side gets a dedicated workspace with different permissions,
            incentives, and privacy boundaries.
          </p>
        </div>

        <div className="grid gap-5 lg:grid-cols-3">
          {previews.map((preview) => (
            <article
              key={preview.title}
              id={preview.id}
              className="motion-lift rounded-lg border border-slate-200 bg-white p-6 shadow-lg shadow-slate-900/5 hover:border-emerald-200 hover:shadow-xl"
            >
              <preview.icon className="motion-icon-tilt mb-5 h-9 w-9 text-emerald-700" />
              <h3 className="text-xl font-bold text-slate-950">
                {preview.title}
              </h3>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                {preview.detail}
              </p>
              <div className="mt-5 grid gap-2">
                {preview.metrics.map((metric) => (
                  <div
                    key={metric}
                    className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700"
                  >
                    {metric}
                  </div>
                ))}
              </div>
              <Link
                href={preview.href}
                className="mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-md bg-slate-950 px-4 font-semibold text-white transition-all duration-300 hover:bg-emerald-700"
              >
                Open preview →
              </Link>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
