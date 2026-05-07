"use client";

import type { ReactNode } from "react";
import { Fragment, useState } from "react";
import { DemoToast, useDemoToast } from "../ui/DemoToast";

// ── Helpers ────────────────────────────────────────────────────────────────

function PageHeader({
  crumb,
  title,
  lede,
  action,
}: {
  crumb: string;
  title: ReactNode;
  lede: string;
  action?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 20 }}>
      <div>
        <div
          style={{
            fontFamily: "'JetBrains Mono',monospace",
            fontSize: 11,
            letterSpacing: "0.16em",
            color: "var(--muted)",
            textTransform: "uppercase",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--purple)",
              display: "inline-block",
            }}
          />
          {crumb}
        </div>
        <h1
          style={{
            fontSize: 32,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            margin: "4px 0 4px",
            color: "var(--ink)",
          }}
        >
          {title}
        </h1>
        <p style={{ fontSize: 14, color: "var(--muted)", margin: 0, maxWidth: 680 }}>{lede}</p>
      </div>
      {action && <div style={{ display: "flex", gap: 8 }}>{action}</div>}
    </div>
  );
}

const card: React.CSSProperties = {
  background: "var(--paper)",
  border: "1px solid var(--line)",
  borderRadius: 14,
  padding: 20,
};

function Btn({ children, variant = "primary", onClick }: {
  children: ReactNode;
  variant?: "primary" | "secondary";
  onClick?: () => void;
}) {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "9px 16px",
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    border: "1px solid",
    textDecoration: "none",
  };
  const styles: React.CSSProperties =
    variant === "primary"
      ? { ...base, background: "var(--ink)", color: "#fff", borderColor: "transparent" }
      : { ...base, background: "transparent", color: "var(--ink-2)", borderColor: "var(--line)" };
  return <button type="button" onClick={onClick} style={styles}>{children}</button>;
}

function FilterChip({ children }: { children: ReactNode }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "4px 10px",
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 500,
        background: "var(--bg-2)",
        color: "var(--ink-2)",
        border: "1px solid var(--line)",
        cursor: "pointer",
      }}
    >
      {children}
    </span>
  );
}

function SwitchRow({
  label,
  sub,
  defaultOn = true,
  onToast,
}: {
  label: string;
  sub?: string;
  defaultOn?: boolean;
  onToast?: (msg: string) => void;
}) {
  const [on, setOn] = useState(defaultOn);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 12px",
        borderRadius: 8,
        background: "var(--bg-2)",
        marginBottom: 6,
        gap: 12,
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--ink-2)" }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{sub}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        onClick={() => {
          const next = !on;
          setOn(next);
          onToast?.(`${label}: ${next ? "enabled" : "disabled"}`);
        }}
        style={{
          width: 38,
          height: 22,
          borderRadius: 99,
          background: on ? "var(--emerald, #10b981)" : "var(--line, #e6e8ef)",
          border: "none",
          cursor: "pointer",
          position: "relative",
          flexShrink: 0,
          transition: "background 0.15s",
          outline: "none",
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 2,
            left: on ? undefined : 2,
            right: on ? 2 : undefined,
            width: 18,
            height: 18,
            background: "#fff",
            borderRadius: "50%",
            boxShadow: "0 1px 3px rgba(0,0,0,.2)",
            transition: "all 0.15s",
            display: "block",
          }}
        />
      </button>
    </div>
  );
}

// ── Data ──────────────────────────────────────────────────────────────────

const departments = [
  ["CS", "82%", "↑ 3pp", "92 placed / 112"],
  ["Data Science", "76%", "↑ 1pp", "68 placed / 89"],
  ["Robotics Eng.", "71%", "flat", "57 placed / 80"],
  ["Electrical & Computer", "65%", "↓ 2pp", "48 placed / 74"],
  ["Bioinformatics", "58%", "↑ 5pp", "31 placed / 53"],
];

const skills = ["Cloud/Docker", "System Design", "ML/Data", "Distributed", "Security"];

// row×col heatmap values
const heatmap = [
  [72, 54, 68, 48, 52],
  [56, 51, 82, 38, 34],
  [42, 48, 55, 36, 31],
  [38, 46, 32, 29, 44],
  [48, 36, 78, 22, 31],
];

function cellColor(v: number): { bg: string; color: string } {
  if (v >= 70) return { bg: "var(--emerald-soft)", color: "#065f46" };
  if (v >= 50) return { bg: "#d1fae5", color: "#065f46" };
  if (v >= 40) return { bg: "var(--amber-soft)", color: "#92400e" };
  if (v >= 30) return { bg: "#fed7aa", color: "#9a3412" };
  return { bg: "var(--rose-soft)", color: "#9f1239" };
}

// ── Readiness chart ────────────────────────────────────────────────────────

const months = ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr"];
const wpiValues = [58, 62, 64, 67, 69, 71, 72, 73];

function ReadinessChart() {
  const maxVal = 80;
  return (
    <div style={{ ...card }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Cohort vs peer R1</div>
        <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>Readiness over time</div>
      </div>
      <div style={{ height: 200, display: "flex", alignItems: "flex-end", gap: 8, paddingBottom: 24, position: "relative" }}>
        {wpiValues.map((val, i) => (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3, height: "100%" }}>
            <div style={{ flex: 1, display: "flex", alignItems: "flex-end", gap: 3, width: "100%" }}>
              <div
                style={{
                  flex: 1,
                  borderRadius: "4px 4px 0 0",
                  background: "var(--purple)",
                  height: `${(val / maxVal) * 100}%`,
                  minHeight: 4,
                }}
              />
              <div
                style={{
                  flex: 1,
                  borderRadius: "4px 4px 0 0",
                  background: "#c4b5fd",
                  height: `${((val - 4) / maxVal) * 100}%`,
                  minHeight: 4,
                }}
              />
            </div>
            <div style={{ fontSize: 10, color: "var(--muted)", position: "absolute", bottom: 0 }}>{months[i]}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 12, borderRadius: 2, background: "var(--purple)", display: "inline-block" }} />
          WPI &apos;26
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 12, borderRadius: 2, background: "#c4b5fd", display: "inline-block" }} />
          Peer R1
        </span>
      </div>
    </div>
  );
}

// ── Skill gap heatmap ──────────────────────────────────────────────────────

function SkillGapHeatmap() {
  return (
    <div style={card}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Cells suppressed when n &lt; 25</div>
        <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>Department-level skill gaps</div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "140px repeat(5, 1fr)",
            gap: 4,
            minWidth: 520,
          }}
        >
          {/* Header row */}
          <div />
          {skills.map((s) => (
            <div key={s} style={{ fontSize: 10, fontWeight: 700, color: "var(--muted)", textAlign: "center", padding: "4px 2px" }}>{s}</div>
          ))}
          {/* Data rows */}
          {departments.map(([dept], row) => (
            <Fragment key={dept}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-2)", display: "flex", alignItems: "center", paddingRight: 8 }}>{dept}</div>
              {heatmap[row].map((val, col) => {
                const { bg, color } = cellColor(val);
                return (
                  <div
                    key={col}
                    style={{
                      background: bg,
                      color,
                      borderRadius: 6,
                      padding: "6px 4px",
                      textAlign: "center",
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {val}%
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
        {/* Gradient bar */}
        <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 10, color: "var(--muted)" }}>Low</span>
          <div
            style={{
              flex: 1,
              height: 6,
              borderRadius: 3,
              background: "linear-gradient(to right, var(--rose-soft), var(--amber-soft), var(--emerald-soft))",
            }}
          />
          <span style={{ fontSize: 10, color: "var(--muted)" }}>High</span>
        </div>
      </div>
    </div>
  );
}

// ── Department outcomes ────────────────────────────────────────────────────

const trendColors: Record<string, { bg: string; color: string }> = {
  "↑ 3pp": { bg: "var(--emerald-soft)", color: "#065f46" },
  "↑ 1pp": { bg: "var(--emerald-soft)", color: "#065f46" },
  "↑ 5pp": { bg: "var(--emerald-soft)", color: "#065f46" },
  flat: { bg: "var(--bg-2)", color: "var(--muted)" },
  "↓ 2pp": { bg: "var(--rose-soft)", color: "#9f1239" },
};

function DeptOutcomesTable() {
  return (
    <div style={card}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Placement rate · Class of 2026</div>
        <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>Department outcomes</div>
      </div>
      {departments.map(([dept, rate, trend, detail], i) => {
        const { bg, color } = trendColors[trend] ?? { bg: "var(--bg-2)", color: "var(--muted)" };
        return (
          <div
            key={dept}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 0",
              borderBottom: i < departments.length - 1 ? "1px solid var(--line)" : "none",
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: 13, color: "var(--ink)", marginBottom: 2 }}>{dept}</div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>{detail}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, fontSize: 16, color: "var(--purple)" }}>{rate}</span>
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 7px",
                  borderRadius: 4,
                  background: bg,
                  color,
                  fontWeight: 700,
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                {trend}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Employer engagement ────────────────────────────────────────────────────

const employers = [
  { name: "Stripe", initials: "St", bg: "#000", views: 186, invites: 24, hires: 8, growth: "+34%" },
  { name: "Linear", initials: "Li", bg: "#5e6ad2", views: 142, invites: 18, hires: 5, growth: "+22%" },
  { name: "Vercel", initials: "Ve", bg: "#171717", views: 128, invites: 15, hires: 4, growth: "+18%" },
  { name: "Anthropic", initials: "An", bg: "#c84b31", views: 96, invites: 11, hires: 3, growth: "+12%" },
];

function EmployerTable() {
  return (
    <div style={card}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Profile views and invitations · last 90 days</div>
        <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>Employer engagement</div>
      </div>
      {employers.map((emp, i) => (
        <div
          key={emp.name}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "10px 0",
            borderBottom: i < employers.length - 1 ? "1px solid var(--line)" : "none",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 7,
              background: emp.bg,
              display: "grid",
              placeItems: "center",
              color: "#fff",
              fontWeight: 700,
              fontSize: 11,
              flexShrink: 0,
            }}
          >
            {emp.initials}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: "var(--ink)", marginBottom: 1 }}>{emp.name}</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>
              {emp.views} views · {emp.invites} invites · {emp.hires} hires
            </div>
          </div>
          <span
            style={{
              fontSize: 11,
              padding: "3px 8px",
              borderRadius: 5,
              background: "var(--emerald-soft)",
              color: "#065f46",
              fontWeight: 700,
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            {emp.growth}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Main views ─────────────────────────────────────────────────────────────

export function UniversityOverview() {
  const { show, msg } = useDemoToast();

  const metrics = [
    { label: "Cohort size", value: "1,284", detail: "Class of 2026" },
    { label: "Avg. readiness", value: "73.4", detail: "+4.1 vs last year" },
    { label: "Verified profiles", value: "847", detail: "66% of cohort" },
    { label: "Placed by graduation", value: "71%", detail: "↑ 3pp year-on-year" },
    { label: "Employer engagement", value: "142", detail: "firms active · last 90d" },
  ];

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="University console"
        title="Class of 2026 · Cohort overview"
        lede="Aggregate cohort analytics, department skill gaps, and employer engagement — with k-anonymity and FERPA-aware privacy controls."
        action={<Btn variant="secondary" onClick={() => show("Report export — PDF generation coming soon.")}>↓ Export PDF report</Btn>}
      />

      {/* Filter row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {["Cohort: 2026", "All departments", "All terms", "Compare: Peer R1"].map((f) => (
            <FilterChip key={f}>{f}</FilterChip>
          ))}
        </div>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "#065f46",
            fontFamily: "'JetBrains Mono',monospace",
            background: "var(--emerald-soft)",
            padding: "4px 10px",
            borderRadius: 6,
          }}
        >
          🛡 k-anon ≥ 25 · FERPA-aware
        </span>
      </div>

      {/* k-anon banner */}
      <div
        style={{
          background: "linear-gradient(135deg, var(--emerald-soft), var(--teal-soft, #e6f4f2))",
          border: "1px solid #a7f3d0",
          borderRadius: 12,
          padding: "14px 18px",
          display: "grid",
          gridTemplateColumns: "auto 1fr auto",
          alignItems: "center",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: "#d1fae5",
            display: "grid",
            placeItems: "center",
            fontSize: 18,
            flexShrink: 0,
          }}
        >
          k≥25
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: "#065f46" }}>k-anonymity threshold active</div>
          <div style={{ fontSize: 12, color: "#047857" }}>All cells with fewer than 25 students are suppressed. No individual student records are exposed.</div>
        </div>
        <span
          style={{
            fontSize: 12,
            fontWeight: 700,
            padding: "5px 12px",
            borderRadius: 6,
            background: "var(--emerald)",
            color: "#fff",
            whiteSpace: "nowrap",
          }}
        >
          Compliant ✓
        </span>
      </div>

      {/* 5-column metric strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 12, marginBottom: 20 }}>
        {metrics.map((m) => (
          <div key={m.label} style={{ ...card, padding: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 6 }}>{m.label}</div>
            <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 22, fontWeight: 700, color: "var(--purple)", lineHeight: 1 }}>{m.value}</div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{m.detail}</div>
          </div>
        ))}
      </div>

      {/* 2-col grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <ReadinessChart />
          <SkillGapHeatmap />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <DeptOutcomesTable />
          <EmployerTable />
        </div>
      </div>
    </div>
  );
}

export function UniversityAnalytics() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="University console · Readiness"
        title="Readiness analytics"
        lede="Cohort readiness over time compared to peer R1 institutions."
        action={<Btn variant="secondary" onClick={() => show("Export coming soon.")}>↓ Export</Btn>}
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <ReadinessChart />
        <div style={card}>
          <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Readiness breakdown</div>
          {[
            { label: "Profile completeness", value: 82, color: "var(--purple)" },
            { label: "Verified skills", value: 66, color: "var(--indigo)" },
            { label: "Proof artifacts", value: 58, color: "var(--emerald)" },
            { label: "Interview readiness", value: 47, color: "var(--amber)" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                <span style={{ color: "var(--ink-2)", fontWeight: 500 }}>{label}</span>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, color }}>{value}%</span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: "var(--bg-2)", overflow: "hidden" }}>
                <div style={{ width: `${value}%`, height: "100%", borderRadius: 3, background: color }} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ marginTop: 20 }}>
        <DeptOutcomesTable />
      </div>
    </div>
  );
}

export function UniversitySkillGaps() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="University console · Skill Gaps"
        title="Skill gap heatmap"
        lede="Department-level skill coverage across the cohort. Cells with n &lt; 25 are suppressed."
        action={<Btn variant="secondary" onClick={() => show("Export coming soon.")}>↓ Export</Btn>}
      />
      <div style={{ marginBottom: 20 }}>
        <SkillGapHeatmap />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {skills.map((skill) => (
          <div key={skill} style={card}>
            <div style={{ fontWeight: 700, fontSize: 15, color: "var(--ink)", marginBottom: 12 }}>{skill}</div>
            {departments.map(([dept], row) => {
              const val = heatmap[row][skills.indexOf(skill)];
              const { bg, color } = cellColor(val);
              return (
                <div
                  key={dept}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "7px 0",
                    borderBottom: "1px solid var(--line)",
                    fontSize: 12,
                  }}
                >
                  <span style={{ color: "var(--ink-2)", fontWeight: 500 }}>{dept}</span>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: bg, color }}>{val}%</span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export function UniversityOutcomes() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="University console · Outcomes"
        title="Student outcome reports"
        lede="Placement rates, destinations, and trend data by department — aggregate only."
        action={
          <>
            <Btn variant="secondary" onClick={() => show("Export coming soon.")}>↓ Quarterly export</Btn>
            <Btn variant="secondary" onClick={() => show("Export coming soon.")}>↓ Department brief</Btn>
          </>
        }
      />
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Placement rate · Class of 2026</div>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>Student outcome reports</div>
          </div>
          <span
            style={{
              fontSize: 11,
              padding: "3px 9px",
              borderRadius: 5,
              background: "var(--emerald-soft)",
              color: "#065f46",
              fontWeight: 600,
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            aggregate only
          </span>
        </div>
        {departments.map(([dept, rate, trend, detail], i) => {
          const numRate = parseInt(rate);
          const { bg, color } = trendColors[trend] ?? { bg: "var(--bg-2)", color: "var(--muted)" };
          return (
            <div key={dept} style={{ padding: "14px 0", borderBottom: i < departments.length - 1 ? "1px solid var(--line)" : "none" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)", marginBottom: 2 }}>{dept}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>{detail}</div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, fontSize: 22, color: "var(--purple)" }}>{rate}</span>
                  <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: bg, color, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace" }}>{trend}</span>
                </div>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: "var(--bg-2)", overflow: "hidden" }}>
                <div style={{ width: `${numRate}%`, height: "100%", borderRadius: 3, background: "var(--purple)" }} />
              </div>
            </div>
          );
        })}
      </div>
      <EmployerTable />
    </div>
  );
}

export function UniversityEmployers() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="University console · Employer Trends"
        title="Employer engagement"
        lede="Companies actively engaging with WPI talent — views, invites, and hiring outcomes."
        action={<Btn variant="secondary" onClick={() => show("Export coming soon.")}>↓ Export</Btn>}
      />
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 20 }}>
        <div>
          <EmployerTable />
          <div style={{ ...card, marginTop: 20 }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Employer actions</div>
            {["Invite Stripe to WPI proof fair", "Send Docker gap cohort report", "Create employer-ready backend cohort list", "Schedule recruiter feedback session"].map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => show("Action queued — backend integration coming soon.")}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "10px 12px",
                  borderRadius: 8,
                  background: "var(--bg-2)",
                  border: "1px solid var(--line)",
                  marginBottom: 6,
                  fontSize: 13,
                  color: "var(--ink-2)",
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        <div style={card}>
          <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Engagement breakdown</div>
          {employers.map((emp) => (
            <div key={emp.name} style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 6 }}>
                <span style={{ fontWeight: 600, color: "var(--ink-2)" }}>{emp.name}</span>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, color: "var(--emerald)" }}>{emp.growth}</span>
              </div>
              {[
                { label: "Views", value: emp.views, max: 200 },
                { label: "Invites", value: emp.invites, max: 30 },
                { label: "Hires", value: emp.hires, max: 10 },
              ].map(({ label, value, max }) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 10, color: "var(--muted)", width: 42 }}>{label}</span>
                  <div style={{ flex: 1, height: 4, borderRadius: 2, background: "var(--bg-2)", overflow: "hidden" }}>
                    <div style={{ width: `${(value / max) * 100}%`, height: "100%", borderRadius: 2, background: "var(--purple)" }} />
                  </div>
                  <span style={{ fontSize: 10, fontFamily: "'JetBrains Mono',monospace", fontWeight: 600, color: "var(--ink-2)", width: 24, textAlign: "right" }}>{value}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function UniversityPrivacy() {
  const { show, msg } = useDemoToast();

  const controls = [
    { label: "Suppress groups with k < 25", sub: "Cells below threshold are hidden from all views", on: true },
    { label: "Block department × visa cross-tabs", sub: "Prevents identification via intersection", on: true },
    { label: "Aggregate-only dashboards", sub: "No individual student rows ever exposed", on: true },
    { label: "No individual student exposure without permission", sub: "Requires explicit per-student opt-in", on: true },
    { label: "FERPA-aware export filters", sub: "Reports strip identifying fields before download", on: true },
    { label: "Audit log for all data access", sub: "Every query logged with timestamp and role", on: true },
  ];

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="University console · Privacy & DPA"
        title="Privacy & DPA"
        lede="FERPA-aware privacy controls, k-anonymity thresholds, and data processing agreement status."
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div>
          <div style={{ ...card, marginBottom: 20 }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Privacy controls</div>
            {controls.map((item) => (
              <SwitchRow
                key={item.label}
                label={item.label}
                sub={item.sub}
                defaultOn={item.on}
                onToast={show}
              />
            ))}
          </div>
        </div>
        <div>
          <div style={{ ...card, marginBottom: 20 }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 8 }}>Institutional messaging</div>
            <p style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.7 }}>
              University users see readiness analytics, department skill gaps, cohort trends, and outcome reports only in aggregate. Individual student exposure requires explicit student permission.
            </p>
            <div
              style={{
                marginTop: 14,
                padding: "12px 14px",
                borderRadius: 10,
                background: "var(--emerald-soft)",
                border: "1px solid #a7f3d0",
                fontSize: 12,
                fontWeight: 700,
                color: "#065f46",
              }}
            >
              k-anonymity threshold active · no suppressed cells shown
            </div>
          </div>
          <div style={card}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>DPA status</div>
            {[
              { label: "Data Processing Agreement", status: "Signed", ok: true },
              { label: "FERPA compliance review", status: "Passed", ok: true },
              { label: "Security audit", status: "Passed · 2025-Q3", ok: true },
              { label: "Student consent framework", status: "Active", ok: true },
            ].map(({ label, status, ok }) => (
              <div
                key={label}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "9px 0",
                  borderBottom: "1px solid var(--line)",
                  fontSize: 13,
                }}
              >
                <span style={{ color: "var(--ink-2)", fontWeight: 500 }}>{label}</span>
                <span
                  style={{
                    fontSize: 11,
                    padding: "2px 8px",
                    borderRadius: 4,
                    background: ok ? "var(--emerald-soft)" : "var(--rose-soft)",
                    color: ok ? "#065f46" : "#9f1239",
                    fontWeight: 700,
                  }}
                >
                  {status}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
