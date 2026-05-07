import { Sparkles } from "lucide-react";

const footerGroups = [
  {
    title: "Platform",
    links: ["For Students", "For Recruiters", "For Universities"],
  },
  {
    title: "Resources",
    links: ["Documentation", "API", "Support"],
  },
  {
    title: "Company",
    links: ["About", "Careers", "Contact"],
  },
];

export function Footer() {
  return (
    <footer className="border-t border-slate-800 bg-slate-950 px-6 py-12">
      <div className="mx-auto max-w-7xl">
        <div className="mb-8 grid gap-8 md:grid-cols-4">
          <div>
            <div className="mb-4 flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-indigo-600">
                <Sparkles className="h-5 w-5 text-white" aria-hidden="true" />
              </span>
              <span className="font-semibold text-white">CareerProof AI</span>
            </div>
            <p className="text-sm leading-6 text-slate-400">
              Proof-backed career readiness for verified students.
            </p>
          </div>

          {footerGroups.map((group) => (
            <div key={group.title}>
              <h2 className="mb-4 font-semibold text-white">{group.title}</h2>
              <ul className="space-y-2">
                {group.links.map((link) => (
                  <li key={link}>
                    <a
                      href="#platform"
                      className="text-sm text-slate-400 transition hover:text-white"
                    >
                      {link}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="flex flex-col items-center justify-between gap-4 border-t border-slate-800 pt-8 md:flex-row">
          <p className="text-sm text-slate-400">
            © 2026 CareerProof AI. All rights reserved.
          </p>
          <div className="flex gap-6">
            {["Privacy", "Terms", "Security"].map((link) => (
              <a
                key={link}
                href="#platform"
                className="text-sm text-slate-400 transition hover:text-white"
              >
                {link}
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}
