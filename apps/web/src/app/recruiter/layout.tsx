import type { ReactNode } from "react";
import { DashboardShell } from "../../../components/dashboard/DashboardShell";

const nav = [
  { label: "Search", href: "/recruiter", icon: "▣", count: "240" },
  { label: "Work Passports", href: "/recruiter/passport", icon: "🪪" },
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
      {children}
    </DashboardShell>
  );
}
