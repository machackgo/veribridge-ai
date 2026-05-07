import { Award, CheckSquare, Target, TrendingDown, Upload } from "lucide-react";

const dashboardCards = [
  {
    icon: Upload,
    title: "Resume Upload",
    description: "AI-ready resume analysis",
    stat: "98%",
    statLabel: "Completeness",
    className: "bg-sky-600",
  },
  {
    icon: Target,
    title: "Job Match",
    description: "Top opportunities for you",
    stat: "12",
    statLabel: "Matches",
    className: "bg-emerald-600",
  },
  {
    icon: TrendingDown,
    title: "Skill Gap",
    description: "Areas to improve",
    stat: "3",
    statLabel: "Skills",
    className: "bg-amber-600",
  },
  {
    icon: CheckSquare,
    title: "Application Tracker",
    description: "Track your progress",
    stat: "8",
    statLabel: "Active",
    className: "bg-indigo-600",
  },
  {
    icon: Award,
    title: "CareerProof Score",
    description: "Your career readiness",
    stat: "92",
    statLabel: "Score",
    className: "bg-violet-600",
  },
];

const scoreItems = [
  ["Projects", "86%"],
  ["Skills", "92%"],
  ["Experience", "74%"],
  ["Education", "90%"],
  ["Certifications", "78%"],
];

export function DashboardPreview() {
  return (
    <section className="bg-gradient-to-br from-slate-50 via-indigo-50/50 to-emerald-50/40 px-6 py-24">
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <h2 className="text-4xl font-bold tracking-normal text-slate-950 md:text-5xl">
            Your complete career command center
          </h2>
          <p className="mt-4 text-lg leading-8 text-slate-600">
            Track every aspect of your career journey in one focused dashboard.
          </p>
        </div>

        <div className="grid gap-5 md:grid-cols-3">
          {dashboardCards.map((card, index) => (
            <article
              key={card.title}
              className={`motion-lift motion-fade-up rounded-lg border border-slate-200 bg-white p-6 shadow-lg shadow-slate-900/5 hover:border-emerald-200 hover:shadow-xl ${
                index === 4 ? "md:col-span-3" : ""
              } ${
                index === 1
                  ? "motion-delay-100"
                  : index === 2
                    ? "motion-delay-200"
                    : index === 3
                      ? "motion-delay-300"
                      : index === 4
                        ? "motion-delay-400"
                        : ""
              }`}
            >
              <div className="mb-4 flex items-start justify-between gap-4">
                <div
                  className={`motion-icon-tilt flex h-14 w-14 items-center justify-center rounded-lg ${card.className}`}
                >
                  <card.icon className="h-7 w-7 text-white" />
                </div>
                <div className="text-right">
                  <div className="text-3xl font-bold text-slate-950">
                    {card.stat}
                  </div>
                  <div className="text-xs font-medium text-slate-500">
                    {card.statLabel}
                  </div>
                </div>
              </div>

              <h3 className="font-semibold text-slate-950">{card.title}</h3>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                {card.description}
              </p>

              {index === 4 && (
                <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                  {scoreItems.map(([item, width]) => (
                    <div key={item}>
                      <div className="mb-2 h-2 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="motion-shimmer h-2 rounded-full bg-gradient-to-r from-violet-500 via-indigo-500 to-violet-500"
                          style={{ width }}
                        />
                      </div>
                      <span className="text-xs font-medium text-slate-600">
                        {item}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
