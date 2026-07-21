import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { dashboardPersonaInitials } from "../app/dashboard/layout";

const here = dirname(fileURLToPath(import.meta.url));
const layoutSource = readFileSync(
  resolve(here, "../app/dashboard/layout.tsx"),
  "utf8"
);

describe("student dashboard persona", () => {
  it("derives two-letter initials from a full name", () => {
    expect(dashboardPersonaInitials("Mohammed Mubashir", "x@y.com")).toBe("MM");
  });

  it("falls back to the email when no name is present", () => {
    expect(dashboardPersonaInitials("", "rahil@example.com")).toBe("RA");
  });

  it("never returns blank initials", () => {
    expect(dashboardPersonaInitials("", "")).toBe("ME");
  });

  // Regression: the sidebar persona must come from the session, never a hardcoded
  // identity. A real logged-in student previously saw "Maya Reyes / maya.reyes@wpi.edu".
  it("does not hardcode a demo identity in the student dashboard layout", () => {
    expect(layoutSource).not.toMatch(/Maya Reyes/i);
    expect(layoutSource).not.toMatch(/maya\.reyes@wpi\.edu/i);
  });

  it("resolves the persona from the authenticated Supabase user", () => {
    expect(layoutSource).toContain("auth.getUser()");
    expect(layoutSource).toContain("user?.email");
  });
});
