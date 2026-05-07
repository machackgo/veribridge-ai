import Link from "next/link";
import {
  CheckSquare,
  Sparkles,
  Target,
  TrendingDown,
  Upload,
} from "lucide-react";

const dashboardCards = [
  {
    icon: Upload,
    title: "Resume Upload",
    description: "Upload and organize resume versions before review.",
    className: "bg-sky-600",
  },
  {
    icon: Target,
    title: "Job Match",
    description: "Track target roles and future fit recommendations.",
    className: "bg-emerald-600",
  },
  {
    icon: TrendingDown,
    title: "Skill Gap",
    description: "Identify missing skills for internships and entry roles.",
    className: "bg-amber-600",
  },
  {
    icon: CheckSquare,
    title: "Application Tracker",
    description: "Monitor applications, statuses, and next actions.",
    className: "bg-indigo-600",
  },
];

export default function DashboardPage() {
  return (
    <main className="min-h-screen bg-slate-50 px-6 py-8 text-slate-950 sm:px-8">
      <section className="mx-auto w-full max-w-7xl">
        <nav className="mb-12 flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm sm:px-6">
          <Link href="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-indigo-600">
              <Sparkles className="h-5 w-5 text-white" aria-hidden="true" />
            </span>
            <span className="font-semibold text-slate-950">
              CareerProof AI
            </span>
          </Link>
          <Link
            href="/"
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-500 hover:text-slate-950"
          >
            Home
          </Link>
        </nav>

        <div className="mb-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-700">
            Dashboard
          </p>
          <h1 className="text-4xl font-bold tracking-normal text-slate-950">
            Welcome to your CareerProof workspace
          </h1>
          <p className="mt-4 max-w-2xl text-lg leading-8 text-slate-600">
            This placeholder dashboard will become the student command center
            for profile building, readiness checks, and application tracking.
          </p>
        </div>

        <section className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {dashboardCards.map((card) => (
            <article
              key={card.title}
              className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
            >
              <div
                className={`mb-5 flex h-12 w-12 items-center justify-center rounded-lg ${card.className}`}
              >
                <card.icon className="h-6 w-6 text-white" aria-hidden="true" />
              </div>
              <h2 className="text-lg font-semibold text-slate-950">
                {card.title}
              </h2>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                {card.description}
              </p>
            </article>
          ))}
        </section>
      </section>
    </main>
  );
}
