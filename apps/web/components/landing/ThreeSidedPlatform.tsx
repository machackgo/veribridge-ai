import { ArrowRight, Briefcase, Building2, GraduationCap } from "lucide-react";

const platforms = [
  {
    icon: GraduationCap,
    title: "Students",
    id: "students",
    description:
      "Build verified career profiles backed by real projects, coursework, and skills.",
    features: [
      "Resume analysis",
      "Skill verification",
      "Job matching",
      "Interview prep",
    ],
    iconClass: "bg-emerald-600",
  },
  {
    icon: Briefcase,
    title: "Recruiters",
    id: "recruiters",
    description:
      "Review verified student profiles with proof-backed skills and clearer readiness signals.",
    features: [
      "Verified candidates",
      "Skill matching",
      "Talent pipeline",
      "Readiness analytics",
    ],
    iconClass: "bg-indigo-600",
  },
  {
    icon: Building2,
    title: "Universities",
    id: "universities",
    description:
      "Track student career readiness and improve placement support with outcome data.",
    features: [
      "Student analytics",
      "Placement tracking",
      "Career services",
      "Employer network",
    ],
    iconClass: "bg-amber-600",
  },
];

export function ThreeSidedPlatform() {
  return (
    <section className="bg-white px-6 py-24" id="platform">
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <h2 className="text-4xl font-bold tracking-normal text-slate-950 md:text-5xl">
            One platform, three perspectives
          </h2>
          <p className="mt-4 text-lg leading-8 text-slate-600">
            CareerProof AI connects students, recruiters, and universities
            through verified career data.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {platforms.map((platform) => (
            <article
              key={platform.title}
              id={platform.id}
              className="rounded-lg border border-slate-200 bg-white p-6 shadow-lg shadow-slate-900/5 transition hover:-translate-y-1 hover:shadow-xl"
            >
              <div
                className={`mb-6 flex h-14 w-14 items-center justify-center rounded-lg ${platform.iconClass}`}
              >
                <platform.icon className="h-7 w-7 text-white" />
              </div>

              <h3 className="text-2xl font-bold text-slate-950">
                {platform.title}
              </h3>
              <p className="mt-3 leading-7 text-slate-600">
                {platform.description}
              </p>

              <div className="mt-6 space-y-3">
                {platform.features.map((feature) => (
                  <div key={feature} className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
                    <span className="text-sm font-medium text-slate-700">
                      {feature}
                    </span>
                  </div>
                ))}
              </div>

              <a
                href="#roadmap"
                className="mt-6 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-4 font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-100"
              >
                Learn More
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </a>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
