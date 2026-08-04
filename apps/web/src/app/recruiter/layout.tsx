import type { ReactNode } from "react";
import { DashboardShell } from "../../../components/dashboard/DashboardShell";
import { SampleDataNotice } from "../../../components/dashboard/SampleDataNotice";

const nav = [
  { label: "Search", href: "/recruiter", icon: "▣", count: "240" },
  { label: "Work Passports", href: "/recruiter/passport", icon: "🪪" },
  { label: "Saved Candidates", href: "/recruiter/saved-passports", icon: "📌" },
  { label: "Compare Candidates", href: "/recruiter/compare", icon: "⚖️" },
  { label: "Saved Lists", href: "/recruiter/candidates", icon: "★", count: "8" },
  { label: "Pipeline", href: "/recruiter/search", icon: "⚐", count: "42" },
  { label: "Messages", href: "/recruiter/invites", icon: "✉", count: "12" },
  { label: "Job Posts", href: "/recruiter/company", icon: "▦", count: "5" },
];

const insightsNav = [
  { label: "Funnel", href: "/recruiter/search", icon: "↗" },
  { label: "Trust score", href: "/recruiter/settings", icon: "◇" },
];

const accountNav = [
  { label: "Team & billing", href: "/recruiter/settings", icon: "⚙" },
];

export default function RecruiterLayout({ children }: { children: ReactNode }) {
  return (
    <DashboardShell
      nav={nav}
      insightsNav={insightsNav}
      accountNav={accountNav}
      sidebarWidth={260}
      persona={{
        name: "Stripe Early Talent",
        detail: "recruiter@stripe.com",
        initials: "St",
        badge: "✓ Verified",
        avatarBg: "#000000",
        avatarShape: "square",
      }}
      accent="indigo"
    >
      {/* Prototype role preview: every persona, count, and metric in this
          shell is fabricated sample content (linked from the landing page as a
          preview). The banner must stay until this portal is wired to real
          data. */}
      <SampleDataNotice controlsInert />
      {children}
    </DashboardShell>
  );
}
