import {
  Award,
  BookOpen,
  CheckCircle2,
  FileText,
  GitBranch,
  Link as LinkIcon,
} from "lucide-react";

const skillCards = [
  { skill: "Full-Stack Development", sources: ["GitHub", "Projects"] },
  { skill: "Machine Learning", sources: ["Coursework", "Certifications"] },
  { skill: "Cloud Architecture", sources: ["Portfolio", "GitHub"] },
];

const proofSources = [
  { icon: GitBranch, label: "GitHub Projects", className: "bg-emerald-600" },
  { icon: FileText, label: "Coursework", className: "bg-indigo-600" },
  { icon: Award, label: "Certifications", className: "bg-amber-600" },
  { icon: BookOpen, label: "Portfolio", className: "bg-sky-600" },
];

export function ProofOfSkill() {
  return (
    <section className="bg-gradient-to-br from-slate-50 via-white to-slate-100 px-6 py-24">
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <h2 className="text-4xl font-bold tracking-normal text-slate-950 md:text-5xl">
            Skills backed by proof, not just claims
          </h2>
          <p className="mt-4 text-lg leading-8 text-slate-600">
            Every skill is connected to evidence from projects, coursework, and
            achievements.
          </p>
        </div>

        <div className="grid items-center gap-12 lg:grid-cols-2">
          <div className="space-y-5">
            {skillCards.map((card, index) => (
              <article
                key={card.skill}
                className={`motion-lift motion-fade-up rounded-lg border border-slate-200 bg-white p-6 shadow-lg shadow-slate-900/5 hover:border-emerald-200 hover:shadow-xl ${
                  index === 1
                    ? "motion-delay-100"
                    : index === 2
                      ? "motion-delay-200"
                      : ""
                }`}
              >
                <div className="mb-4 flex items-start justify-between gap-4">
                  <div>
                    <div className="mb-3 flex flex-wrap items-center gap-3">
                      <h3 className="font-semibold text-slate-950">
                        {card.skill}
                      </h3>
                      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                        <CheckCircle2
                          className="motion-pulse-soft h-3 w-3"
                          aria-hidden="true"
                        />
                        Verified
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {card.sources.map((source) => (
                        <span
                          key={source}
                          className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600"
                        >
                          {source}
                        </span>
                      ))}
                    </div>
                  </div>
                  <LinkIcon
                    className="motion-icon-tilt h-5 w-5 shrink-0 text-slate-400"
                    aria-hidden="true"
                  />
                </div>

                <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className="motion-shimmer h-1.5 rounded-full bg-gradient-to-r from-emerald-500 via-indigo-500 to-emerald-500" />
                </div>
              </article>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-4">
            {proofSources.map((source, index) => (
              <article
                key={source.label}
                className={`motion-lift motion-fade-up rounded-lg border border-slate-200 bg-white p-6 shadow-lg shadow-slate-900/5 hover:shadow-xl ${
                  index === 1
                    ? "motion-delay-100"
                    : index === 2
                      ? "motion-delay-200"
                      : index === 3
                        ? "motion-delay-300"
                        : ""
                }`}
              >
                <div
                  className={`motion-icon-tilt mb-4 flex h-12 w-12 items-center justify-center rounded-lg ${source.className}`}
                >
                  <source.icon className="h-6 w-6 text-white" />
                </div>
                <h3 className="font-semibold text-slate-950">
                  {source.label}
                </h3>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
