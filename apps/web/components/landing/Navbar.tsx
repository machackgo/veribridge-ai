import Link from "next/link";
import { Sparkles } from "lucide-react";

const navItems = [
  { label: "Platform", href: "#platform" },
  { label: "Students", href: "#students" },
  { label: "Recruiters", href: "#recruiters" },
  { label: "Universities", href: "#universities" },
  { label: "Roadmap", href: "#roadmap" },
];

export function Navbar() {
  return (
    <nav className="fixed inset-x-0 top-0 z-50 px-4 py-4 sm:px-6">
      <div className="mx-auto max-w-7xl">
        <div className="rounded-lg border border-slate-200/80 bg-white/90 px-4 py-3 shadow-lg shadow-slate-900/5 backdrop-blur-xl sm:px-6">
          <div className="flex items-center justify-between gap-5">
            <Link href="/" className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-indigo-600">
                <Sparkles className="h-5 w-5 text-white" aria-hidden="true" />
              </span>
              <span className="font-semibold text-slate-950">
                CareerProof AI
              </span>
            </Link>

            <div className="hidden items-center gap-7 lg:flex">
              {navItems.map((item) => (
                <a
                  key={item.label}
                  href={item.href}
                  className="text-sm font-medium text-slate-600 transition hover:text-slate-950"
                >
                  {item.label}
                </a>
              ))}
            </div>

            <Link
              href="/dashboard"
              className="inline-flex min-h-10 items-center rounded-md bg-emerald-600 px-4 text-sm font-semibold text-white shadow-lg shadow-emerald-600/20 transition hover:bg-emerald-700"
            >
              Start Building Profile
            </Link>
          </div>
        </div>
      </div>
    </nav>
  );
}
