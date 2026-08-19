"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { KeystoneMark } from "../brand";

export type NavItem = {
  label: string;
  href: string;
  icon: string;
  count?: string;
};

export function DashboardShell({
  children,
  nav,
  accountNav,
  insightsNav,
  insightsLabel = "Insights",
  persona,
  eyebrow,
  title,
  description,
  accent = "emerald",
  sidebarWidth = 240,
}: {
  children: ReactNode;
  nav: NavItem[];
  accountNav?: NavItem[];
  insightsNav?: NavItem[];
  insightsLabel?: string;
  persona: {
    name: string;
    detail: string;
    initials: string;
    badge?: string;
    avatarBg?: string;
    avatarShape?: "circle" | "square";
    badgeColor?: "emerald" | "amber" | "indigo";
  };
  eyebrow?: string;
  title?: string;
  description?: string;
  accent?: "emerald" | "indigo" | "violet";
  sidebarWidth?: number;
}) {
  const pathname = usePathname();

  const isActive = (item: NavItem) =>
    pathname === item.href ||
    (item.href !== "/dashboard" &&
      item.href !== "/recruiter" &&
      item.href !== "/university" &&
      pathname.startsWith(item.href));

  const avatarGrad =
    accent === "emerald"
      ? "linear-gradient(135deg,#4f46e5,#8b5cf6)"
      : accent === "indigo"
      ? "linear-gradient(135deg,#4f46e5,#0ea5e9)"
      : "linear-gradient(135deg,#8b5cf6,#4f46e5)";

  const avatarBackground = persona.avatarBg ?? avatarGrad;
  const avatarBorderRadius = persona.avatarShape === "square" ? 8 : "50%";

  const badgeColorMap: Record<string, { bg: string; color: string }> = {
    emerald: { bg: "#d1fae5", color: "#065f46" },
    amber: { bg: "#fef3c7", color: "#92400e" },
    indigo: { bg: "#e0e7ff", color: "#3730a3" },
  };
  const badgeStyle = badgeColorMap[persona.badgeColor ?? "emerald"];

  function SideNavLink({ item }: { item: NavItem }) {
    const active = isActive(item);
    return (
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        className={!active ? "dash-nav-hover" : ""}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 10px",
          borderRadius: 7,
          fontSize: 13,
          /* Always explicit colors — never rely on inheritance */
          color: active ? "#ffffff" : "var(--ink-2)",
          background: active ? "var(--ink)" : "transparent",
          fontWeight: active ? 600 : 400,
          marginBottom: 1,
          textDecoration: "none",
          transition: "background 0.12s",
        }}
      >
        <span style={{ width: 14, flexShrink: 0, color: active ? "#ffffff" : "var(--muted)" }}>{item.icon}</span>
        <span style={{ flex: 1, color: active ? "#ffffff" : "inherit" }}>{item.label}</span>
        {item.count && (
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              padding: "2px 6px",
              borderRadius: 4,
              background: active ? "rgba(255,255,255,.18)" : "var(--bg-2)",
              color: active ? "rgba(255,255,255,.9)" : "var(--muted)",
              fontWeight: 600,
              letterSpacing: "0.04em",
            }}
          >
            {item.count}
          </span>
        )}
      </Link>
    );
  }

  const sectionLabelStyle = {
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 10,
    letterSpacing: "0.16em",
    color: "var(--muted)",
    textTransform: "uppercase" as const,
    margin: "14px 0 8px",
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", color: "var(--ink)", fontFamily: "'Inter', system-ui, sans-serif" }}>
      {/* ── Navbar ── */}
      <nav
        style={{
          position: "sticky",
          top: 0,
          zIndex: 60,
          backdropFilter: "saturate(180%) blur(16px)",
          background: "rgba(250,251,253,.85)",
          borderBottom: "1px solid var(--line)",
        }}
      >
        <div
          style={{
            maxWidth: 1480,
            margin: "0 auto",
            padding: "14px 28px",
            display: "flex",
            alignItems: "center",
            gap: 24,
          }}
        >
          {/* Brand */}
          <Link
            href="/"
            style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 600, fontSize: 15, color: "var(--ink)", textDecoration: "none" }}
          >
            <KeystoneMark size={24} tone="light" />
            <span>
              VeriBridge
              <span style={{ color: "var(--muted)", fontWeight: 500, marginLeft: 2 }}>AI</span>
            </span>
          </Link>
          {/* Centered nav links */}
          <div style={{ display: "flex", gap: 4, flex: 1, justifyContent: "center" }}>
            {[
              { label: "Platform", href: "/#platform" },
              { label: "Students", href: "/dashboard" },
              { label: "Recruiters", href: "/recruiter" },
              { label: "Universities", href: "/university" },
            ].map((link) => (
              <Link
                key={link.href}
                href={link.href}
                style={{
                  fontSize: 14,
                  color: "var(--ink-2)",
                  padding: "8px 14px",
                  borderRadius: 8,
                  fontWeight: 500,
                  textDecoration: "none",
                }}
              >
                {link.label}
              </Link>
            ))}
          </div>
          {/* CTA */}
          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "9px 14px",
              borderRadius: 9,
              fontSize: 13,
              fontWeight: 600,
              background: "var(--ink)",
              color: "#fff",
              border: "1px solid transparent",
              textDecoration: "none",
            }}
          >
            Back home
          </Link>
        </div>
      </nav>

      {/* ── Page layout ── */}
      <div
        style={{
          maxWidth: 1480,
          margin: "0 auto",
          padding: "32px 28px 80px",
          display: "grid",
          gridTemplateColumns: `${sidebarWidth}px 1fr`,
          gap: 28,
        }}
      >
        {/* ── Sidebar ── */}
        <aside
          style={{
            position: "sticky",
            top: 80,
            alignSelf: "start",
            background: "var(--paper)",
            border: "1px solid var(--line)",
            borderRadius: 14,
            padding: 18,
          }}
        >
          {/* Who */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
              paddingBottom: 14,
              borderBottom: "1px solid var(--line)",
              marginBottom: 14,
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: avatarBorderRadius,
                background: avatarBackground,
                color: "#fff",
                display: "grid",
                placeItems: "center",
                fontWeight: 600,
                fontSize: 13,
                flexShrink: 0,
              }}
            >
              {persona.initials}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{persona.name}</div>
              <div
                style={{
                  fontSize: 11,
                  color: "var(--muted)",
                  fontFamily: "'JetBrains Mono', monospace",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {persona.detail}
              </div>
              {persona.badge && (
                <div
                  style={{
                    display: "inline-block",
                    marginTop: 4,
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "2px 7px",
                    borderRadius: 5,
                    background: badgeStyle.bg,
                    color: badgeStyle.color,
                    fontFamily: "'JetBrains Mono', monospace",
                    letterSpacing: "0.04em",
                  }}
                >
                  {persona.badge}
                </div>
              )}
            </div>
          </div>

          {/* Workspace label + main nav */}
          <div style={sectionLabelStyle}>Workspace</div>
          <nav>
            {nav.map((item) => (
              <SideNavLink key={item.href} item={item} />
            ))}
          </nav>

          {/* Insights/Reports section */}
          {insightsNav && insightsNav.length > 0 && (
            <>
              <div style={sectionLabelStyle}>{insightsLabel}</div>
              <nav>
                {insightsNav.map((item) => (
                  <SideNavLink key={item.href} item={item} />
                ))}
              </nav>
            </>
          )}

          {/* Account label + account nav */}
          {accountNav && accountNav.length > 0 && (
            <>
              <div style={sectionLabelStyle}>Account</div>
              <nav>
                {accountNav.map((item) => (
                  <SideNavLink key={item.href} item={item} />
                ))}
              </nav>
            </>
          )}
        </aside>

        {/* ── Main content ── */}
        <main style={{ minWidth: 0 }} className="vb-reveal">
          {/* Optional page header (for recruiter/university layouts) */}
          {eyebrow && title && (
            <div style={{ marginBottom: 24 }}>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  letterSpacing: "0.16em",
                  color: "var(--muted)",
                  textTransform: "uppercase",
                }}
              >
                {eyebrow}
              </div>
              <h1
                style={{
                  fontSize: 32,
                  fontWeight: 600,
                  letterSpacing: "-0.02em",
                  margin: "0 0 4px",
                  color: "var(--ink)",
                }}
              >
                {title}
              </h1>
              {description && (
                <p style={{ fontSize: 14, color: "var(--muted)", margin: "6px 0 0", lineHeight: 1.5 }}>
                  {description}
                </p>
              )}
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
