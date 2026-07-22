/**
 * DashboardChromeSwitch (dashboard consolidation Stage 1) — /dashboard/skill-gaps
 * gets the shared Student Shell (with the standard student content container);
 * every other /dashboard route keeps the legacy DashboardShell chrome.
 */

import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DashboardChromeSwitch } from "../../components/dashboard/DashboardChromeSwitch"

let mockPathname = "/dashboard/skill-gaps"

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock("@/lib/vbr-api", () => ({
  listVBRProjects: vi.fn().mockResolvedValue([]),
}))

vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: vi.fn().mockReturnValue({ auth: { signOut: vi.fn() } }),
}))

const props = {
  nav: [{ label: "Overview", href: "/dashboard", icon: "▣" }],
  accountNav: [{ label: "Settings", href: "/dashboard/settings", icon: "⚙" }],
  persona: { name: "Ada Lovelace", detail: "ada@example.edu", initials: "AL" },
  studentPersona: { name: "Ada Lovelace", email: "ada@example.edu", initials: "AL" },
}

function renderSwitch() {
  return render(
    <DashboardChromeSwitch {...props}>
      <div data-testid="page-body">page content</div>
    </DashboardChromeSwitch>
  )
}

beforeEach(() => {
  mockPathname = "/dashboard/skill-gaps"
})

describe("DashboardChromeSwitch", () => {
  it("hosts /dashboard/skill-gaps inside the Student Shell with exactly one chrome", () => {
    renderSwitch()
    expect(screen.getByTestId("student-shell")).toBeInTheDocument()
    expect(screen.getByTestId("page-body")).toBeInTheDocument()
    // Legacy chrome must not appear alongside the shell.
    expect(screen.queryByText("Back home")).not.toBeInTheDocument()
    expect(screen.queryByText("Workspace")).not.toBeInTheDocument()
    expect(screen.queryByText("Job Matches")).not.toBeInTheDocument()
    // Skills & Gaps is the active shell nav item.
    const sidebar = screen.getByTestId("student-shell-sidebar")
    const active = Array.from(sidebar.querySelectorAll("a[aria-current='page']"))
    expect(active.map((a) => a.textContent)).toEqual(["Skills & Gaps"])
  })

  it("wraps the skill-gaps page in the standard student content container", () => {
    renderSwitch()
    const container = screen.getByTestId("page-body").parentElement as HTMLElement
    expect(container.style.maxWidth).toBe("900px")
    expect(container.style.padding).toBe("48px 24px")
  })

  it("keeps every other /dashboard route on the legacy DashboardShell", () => {
    mockPathname = "/dashboard/profile"
    renderSwitch()
    expect(screen.queryByTestId("student-shell")).not.toBeInTheDocument()
    expect(screen.getByTestId("page-body")).toBeInTheDocument()
    expect(screen.getByText("Back home")).toBeInTheDocument()
  })
})
