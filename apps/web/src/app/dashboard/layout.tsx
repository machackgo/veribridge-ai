import type { ReactNode } from "react";
import { DashboardShell } from "../../../components/dashboard/DashboardShell";

const nav = [
  { label: "Overview", href: "/dashboard", icon: "▣" },
  { label: "Work Passport", href: "/dashboard/passport", icon: "🪪" },
  { label: "Skill Evidence", href: "/dashboard/passport/skills", icon: "🧠" },
  { label: "GitHub Proofs", href: "/dashboard/passport/github", icon: "🐙" },
  { label: "Access Requests", href: "/dashboard/passport/access", icon: "🔑" },
  { label: "Notifications", href: "/dashboard/passport/notifications", icon: "🔔" },
  { label: "Analytics", href: "/dashboard/passport/analytics", icon: "📊" },
  { label: "Export", href: "/dashboard/passport/export", icon: "📦" },
  { label: "Profile & Proof", href: "/dashboard/profile", icon: "▦" },
  { label: "Job Matches", href: "/dashboard/jobs", icon: "↗" },
  { label: "Applications", href: "/dashboard/applications", icon: "⚐" },
  { label: "Skill Gaps", href: "/dashboard/skill-gaps", icon: "◇" },
];

const accountNav = [
  { label: "Settings", href: "/dashboard/settings", icon: "⚙" },
  { label: "Privacy", href: "/dashboard/privacy", icon: "🛡" },
];

export default function StudentLayout({ children }: { children: ReactNode }) {
  return (
    <DashboardShell
      nav={nav}
      accountNav={accountNav}
      persona={{
        name: "Maya Reyes",
        detail: "maya.reyes@wpi.edu",
        initials: "MR",
      }}
      accent="emerald"
    >
      {children}
    </DashboardShell>
  );
}
