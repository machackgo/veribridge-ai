import type { ReactNode } from "react";
import { DashboardChromeSwitch } from "../../../components/dashboard/DashboardChromeSwitch";
import { studentPersonaInitials } from "../../../components/student/persona";
import { createSupabaseServerClient } from "../../lib/supabase/server";

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

/** Derive display initials from a name (preferred) or email, never blank. */
export function dashboardPersonaInitials(name: string, email: string): string {
  const source = (name || email || "").trim();
  if (!source) return "ME";
  const words = source.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export default async function StudentLayout({ children }: { children: ReactNode }) {
  // Resolve the persona from the authenticated session — never a hardcoded identity.
  let email = "";
  let name = "";
  try {
    const supabase = await createSupabaseServerClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    email = user?.email ?? "";
    const metadata = (user?.user_metadata ?? {}) as Record<string, unknown>;
    name =
      (typeof metadata.full_name === "string" && metadata.full_name) ||
      (typeof metadata.name === "string" && metadata.name) ||
      "";
  } catch {
    // Fall through to safe generic labels if the session cannot be read.
  }

  const displayName = name || email || "My Workspace";

  return (
    <DashboardChromeSwitch
      nav={nav}
      accountNav={accountNav}
      persona={{
        name: displayName,
        detail: email,
        initials: dashboardPersonaInitials(name, email),
      }}
      studentPersona={{
        name: displayName,
        email,
        initials: studentPersonaInitials(name, email),
      }}
    >
      {children}
    </DashboardChromeSwitch>
  );
}
