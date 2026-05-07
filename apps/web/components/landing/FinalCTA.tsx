import Link from "next/link";
import { ArrowRight, Shield, Sparkles, Zap } from "lucide-react";

const valueProps = [
  {
    icon: Shield,
    title: "Verified .edu Only",
    description: "Designed around verified student access.",
  },
  {
    icon: Zap,
    title: "AI-Powered",
    description: "Prepared for smart matching and analysis.",
  },
  {
    icon: Sparkles,
    title: "Proof-Backed",
    description: "Every skill can connect back to evidence.",
  },
];

export function FinalCTA() {
  return (
    <section className="relative overflow-hidden bg-slate-950 px-6 py-24">
      <div className="mx-auto max-w-4xl text-center">
        <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-4 py-2">
          <Sparkles className="h-4 w-4 text-emerald-300" aria-hidden="true" />
          <span className="text-sm font-medium text-white">
            Join verified students building stronger profiles
          </span>
        </div>

        <h2 className="text-4xl font-bold tracking-normal text-white md:text-5xl">
          Build your verified career profile today
        </h2>

        <p className="mx-auto mt-6 max-w-2xl text-xl leading-8 text-slate-300">
          Turn your resume, projects, and skills into a proof-backed profile
          recruiters and universities can trust.
        </p>

        <div className="mt-10 flex flex-col justify-center gap-4 sm:flex-row">
          <Link
            href="/dashboard"
            className="inline-flex min-h-12 items-center justify-center gap-3 rounded-md bg-emerald-600 px-7 font-semibold text-white shadow-xl shadow-emerald-600/25 transition hover:bg-emerald-700"
          >
            Start Building Profile
            <ArrowRight className="h-5 w-5" aria-hidden="true" />
          </Link>
          <a
            href="#platform"
            className="inline-flex min-h-12 items-center justify-center rounded-md border border-white/20 bg-white/10 px-7 font-semibold text-white transition hover:bg-white/15"
          >
            Schedule Demo
          </a>
        </div>

        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {valueProps.map((item) => (
            <article
              key={item.title}
              className="rounded-lg border border-white/10 bg-white/[0.06] p-6"
            >
              <item.icon className="mx-auto mb-3 h-8 w-8 text-emerald-300" />
              <h3 className="font-semibold text-white">{item.title}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                {item.description}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
