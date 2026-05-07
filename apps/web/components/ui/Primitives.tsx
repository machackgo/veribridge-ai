import type { ReactNode } from "react";

type Tone = "slate" | "emerald" | "indigo" | "amber" | "rose" | "violet" | "sky";

const badgeTone: Record<Tone, string> = {
  slate: "border-slate-200 bg-slate-50 text-slate-600",
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-700",
  indigo: "border-indigo-200 bg-indigo-50 text-indigo-700",
  amber: "border-amber-200 bg-amber-50 text-amber-700",
  rose: "border-rose-200 bg-rose-50 text-rose-700",
  violet: "border-violet-200 bg-violet-50 text-violet-700",
  sky: "border-sky-200 bg-sky-50 text-sky-700",
};

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`motion-lift vb-card p-5 ${className}`}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  title,
  eyebrow,
  action,
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div>
        {eyebrow ? (
          <div className="vb-eyebrow mb-1">
            {eyebrow}
          </div>
        ) : null}
        <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function Badge({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-semibold ${badgeTone[tone]}`}
    >
      {children}
    </span>
  );
}

export function ButtonLike({
  children,
  variant = "primary",
  className = "",
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "danger";
  className?: string;
}) {
  const variants = {
    primary:
      "bg-[#0a0e1a] text-white hover:bg-[#1f2a44] shadow-lg shadow-slate-900/10",
    secondary:
      "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50",
    danger:
      "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50",
  };

  return (
    <button
      className={`motion-lift inline-flex min-h-10 items-center justify-center rounded-md px-4 text-sm font-semibold transition-all duration-300 ${variants[variant]} ${className}`}
      type="button"
    >
      {children}
    </button>
  );
}

export function Metric({
  label,
  value,
  detail,
  tone = "slate",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: Tone;
}) {
  return (
    <Card>
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
        {label}
      </div>
      <div className="mt-3 text-3xl font-bold tracking-normal text-slate-950">
        {value}
      </div>
      <div className={`mt-2 text-sm font-medium ${badgeTone[tone].split(" ")[2]}`}>
        {detail}
      </div>
    </Card>
  );
}

export function ProgressBar({
  value,
  tone = "emerald",
}: {
  value: number;
  tone?: "emerald" | "indigo" | "violet" | "amber" | "rose";
}) {
  const colors = {
    emerald: "from-emerald-500 via-indigo-500 to-emerald-500",
    indigo: "from-indigo-500 via-sky-500 to-indigo-500",
    violet: "from-violet-500 via-indigo-500 to-violet-500",
    amber: "from-amber-500 via-orange-500 to-amber-500",
    rose: "from-rose-500 via-orange-500 to-rose-500",
  };

  return (
    <div className="h-2 overflow-hidden rounded-full bg-slate-100">
      <div
        className={`motion-shimmer h-2 rounded-full bg-gradient-to-r ${colors[tone]}`}
        style={{ width: `${value}%` }}
      />
    </div>
  );
}

export function Toggle({ on = true }: { on?: boolean }) {
  return (
    <span
      className={`relative inline-flex h-6 w-11 rounded-full transition-colors ${
        on ? "bg-emerald-600" : "bg-slate-300"
      }`}
    >
      <span
        className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
          on ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </span>
  );
}
