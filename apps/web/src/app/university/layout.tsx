import type { ReactNode } from "react";
import { DashboardShell } from "../../../components/dashboard/DashboardShell";

const nav = [
  { label: "Overview", href: "/university", icon: "▣" },
  { label: "Readiness", href: "/university/analytics", icon: "↗" },
  { label: "Skill gaps", href: "/university/skill-gaps", icon: "◇" },
  { label: "Outcomes", href: "/university/outcomes", icon: "⚐" },
  { label: "Employer trends", href: "/university/employers", icon: "⊞" },
  { label: "Cohort compare", href: "/university/privacy", icon: "▦" },
];

const reportsNav = [
  { label: "Quarterly export", href: "/university/outcomes", icon: "↓" },
  { label: "Department brief", href: "/university/analytics", icon: "⊟" },
];

const accountNav = [
  { label: "Privacy & DPA", href: "/university/privacy", icon: "🛡" },
  { label: "Settings", href: "/university/skill-gaps", icon: "⚙" },
];

export default function UniversityLayout({ children }: { children: ReactNode }) {
  return (
    <DashboardShell
      nav={nav}
      insightsNav={reportsNav}
      insightsLabel="Reports"
      accountNav={accountNav}
      persona={{
        name: "WPI Career Center",
        detail: "career-dev@wpi.edu",
        initials: "W",
        badge: "Institutional · DPA",
        avatarBg: "#9b1414",
        avatarShape: "square",
        badgeColor: "amber",
      }}
      accent="violet"
    >
      {children}
    </DashboardShell>
  );
}
