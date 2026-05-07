import {
  BookOpen,
  Brain,
  CheckCircle2,
  FileText,
  GitBranch,
  Target,
  TrendingUp,
} from "lucide-react";

const workflowSteps = [
  { icon: FileText, label: "Resume Upload" },
  { icon: GitBranch, label: "GitHub Analysis" },
  { icon: BookOpen, label: "Coursework Review" },
  { icon: Brain, label: "AI Analysis" },
  { icon: Target, label: "Match Score" },
  { icon: TrendingUp, label: "Skill Gap Analysis" },
  { icon: CheckCircle2, label: "Interview Prep" },
];

export function AIWorkflow() {
  return (
    <section className="bg-white px-6 py-24">
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <h2 className="text-4xl font-bold tracking-normal text-slate-950 md:text-5xl">
            AI-powered career intelligence
          </h2>
          <p className="mt-4 text-lg leading-8 text-slate-600">
            The future workflow will analyze a complete student profile to
            match opportunities and identify growth areas.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-7">
          {workflowSteps.map((step, index) => (
            <article
              key={step.label}
              className="relative rounded-lg border border-slate-200 bg-slate-50 p-5 text-center"
            >
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-lg border border-slate-200 bg-white shadow-sm">
                <step.icon className="h-7 w-7 text-slate-700" />
              </div>
              <h3 className="text-sm font-semibold text-slate-950">
                {step.label}
              </h3>
              <div className="mx-auto mt-3 h-1 w-8 rounded-full bg-gradient-to-r from-emerald-500 to-indigo-500" />
              <span className="absolute right-3 top-3 text-xs font-semibold text-slate-400">
                {String(index + 1).padStart(2, "0")}
              </span>
            </article>
          ))}
        </div>

        <div
          className="mt-12 grid gap-5 rounded-lg border border-emerald-200 bg-gradient-to-br from-emerald-50 to-indigo-50 p-8 md:grid-cols-3"
          id="roadmap"
        >
          {[
            ["10K+", "Skills Analyzed"],
            ["95%", "Match Accuracy"],
            ["2.5x", "Faster Hiring"],
          ].map(([stat, label]) => (
            <div key={label} className="text-center">
              <div className="text-4xl font-bold text-slate-950">{stat}</div>
              <div className="mt-2 font-medium text-slate-600">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
