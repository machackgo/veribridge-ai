import Link from "next/link";

const navItems = [
  { label: "Platform", href: "#platform" },
  { label: "Students", href: "#students" },
  { label: "Recruiters", href: "#recruiters" },
  { label: "Universities", href: "#universities" },
  { label: "Roadmap", href: "#roadmap" },
];

export function Navbar() {
  return (
    <nav className="vb-glass sticky inset-x-0 top-0 z-50 border-b">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-5 py-3 sm:px-8">
        <Link href="/" className="flex items-center gap-2 text-[15px] font-semibold tracking-[-0.01em]">
          <span className="vb-logo" aria-hidden="true" />
          <span className="text-slate-950">
                VeriBridge AI
          </span>
        </Link>

        <div className="hidden flex-1 items-center justify-center gap-1 lg:flex">
          {navItems.map((item) => (
            <a
              key={item.label}
              href={item.href}
              className="rounded-lg px-3.5 py-2 text-sm font-medium text-slate-600 transition hover:bg-white hover:text-slate-950"
            >
              {item.label}
            </a>
          ))}
        </div>

        <Link
          href="/dashboard"
          className="motion-lift inline-flex min-h-10 items-center rounded-[10px] bg-[#0a0e1a] px-4 text-sm font-semibold text-white shadow-sm shadow-slate-900/10 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-slate-900/15"
        >
          Start Building Profile →
        </Link>
      </div>
    </nav>
  );
}
