/**
 * StudentShell (dashboard consolidation Stage 1) — shared authenticated chrome.
 *
 * Covers: shell renders around student pages with global navigation and a
 * reachable Dashboard link; active nav resolves longest-prefix; breadcrumbs +
 * document.title follow the route; the active-project chip reflects only the
 * existing projectId URL-param convention (no new store) and never blocks the
 * shell on fetch failure; sign-out calls supabase.auth.signOut() and lands on
 * /login; recording surfaces render bare (no shell chrome recorded into
 * screen-capture evidence).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { StudentShell, activeNavHref, isBareStudentRoute, studentBreadcrumbs } from "../../components/student/StudentShell"
import { studentPersonaInitials } from "../../components/student/persona"
import { listVBRProjects, type VBRProjectResponse } from "@/lib/vbr-api"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"

const mockPush = vi.fn()
const mockRefresh = vi.fn()
let mockPathname = "/student"
let mockSearchParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: mockPush, refresh: mockRefresh, replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => mockSearchParams,
}))

vi.mock("@/lib/vbr-api", () => ({
  listVBRProjects: vi.fn(),
}))

vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: vi.fn(),
}))

const signOutMock = vi.fn()

const persona = { name: "Ada Lovelace", email: "ada@example.edu", initials: "AL" }

function makeProject(overrides: Partial<VBRProjectResponse> = {}): VBRProjectResponse {
  return {
    id: "proj-1",
    title: "Skill Evidence Tracker",
    repo_url: "https://github.com/octocat/Hello-World",
    status: "draft",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function renderShell(children = <div data-testid="page-body">page content</div>) {
  return render(<StudentShell persona={persona}>{children}</StudentShell>)
}

beforeEach(() => {
  mockPathname = "/student"
  mockSearchParams = new URLSearchParams()
  mockPush.mockReset()
  mockRefresh.mockReset()
  signOutMock.mockReset().mockResolvedValue({ error: null })
  vi.mocked(listVBRProjects).mockReset()
  vi.mocked(createSupabaseBrowserClient)
    .mockReset()
    .mockReturnValue({ auth: { signOut: signOutMock } } as unknown as ReturnType<
      typeof createSupabaseBrowserClient
    >)
})

describe("StudentShell chrome", () => {
  it("renders global navigation, brand link to the Dashboard, and the page body", () => {
    renderShell()
    expect(screen.getByTestId("student-shell")).toBeInTheDocument()
    expect(screen.getByTestId("page-body")).toBeInTheDocument()
    expect(screen.getByTestId("student-shell-brand")).toHaveAttribute("href", "/student")

    const sidebar = screen.getByTestId("student-shell-sidebar")
    for (const label of [
      "Dashboard",
      "GitHub Proof",
      "Website Proof",
      "Document Proof",
      "Project Defense",
      "Skills & Gaps",
      "Work Passport",
      "Proof Vault",
    ]) {
      expect(sidebar).toHaveTextContent(label)
    }
  })

  it("marks Dashboard active on /student and deep-nested items by longest prefix", () => {
    renderShell()
    const sidebar = screen.getByTestId("student-shell-sidebar")
    const dashboard = Array.from(sidebar.querySelectorAll("a")).find((a) => a.textContent === "Dashboard")
    expect(dashboard).toHaveAttribute("aria-current", "page")

    expect(activeNavHref("/student/vbr/passport/vault")).toBe("/student/vbr/passport/vault")
    expect(activeNavHref("/student/vbr/passport")).toBe("/student/vbr/passport")
    expect(activeNavHref("/student/vbr/passport/skills/react")).toBe("/student/vbr/passport")
    expect(activeNavHref("/student/proofs/github")).toBe("/student/proofs/github")
    expect(activeNavHref("/student/vbr/projects/p1/report")).toBe("/student")
    expect(activeNavHref("/dashboard/skill-gaps")).toBe("/dashboard/skill-gaps")
  })

  it("renders breadcrumbs and syncs document.title with the current page", () => {
    mockPathname = "/student/vbr/passport/vault"
    renderShell()
    const breadcrumbs = screen.getByTestId("student-shell-breadcrumbs")
    expect(breadcrumbs).toHaveTextContent("Dashboard")
    expect(breadcrumbs).toHaveTextContent("Work Passport")
    expect(breadcrumbs).toHaveTextContent("Proof Vault")
    expect(document.title).toBe("Proof Vault · VeriBridge AI")
  })

  it("falls back to a Dashboard-only breadcrumb on unknown student routes", () => {
    expect(studentBreadcrumbs("/student/somewhere-new")).toEqual([
      { label: "Dashboard", href: "/student" },
    ])
  })

  it("labels the Account and Settings breadcrumbs on the new canonical routes", () => {
    expect(studentBreadcrumbs("/student/account")).toEqual([
      { label: "Dashboard", href: "/student" },
      { label: "Account" },
    ])
    expect(studentBreadcrumbs("/student/settings")).toEqual([
      { label: "Dashboard", href: "/student" },
      { label: "Settings" },
    ])
  })

  it("labels the Skills & Gaps breadcrumb when the shell hosts /dashboard/skill-gaps", () => {
    expect(studentBreadcrumbs("/dashboard/skill-gaps")).toEqual([
      { label: "Dashboard", href: "/student" },
      { label: "Skills & Gaps" },
    ])
  })
})

describe("active project context", () => {
  it("shows 'All projects' and never calls the API when no project param is present", () => {
    renderShell()
    expect(screen.getByTestId("student-shell-active-project")).toHaveTextContent("All projects")
    expect(listVBRProjects).not.toHaveBeenCalled()
  })

  it("resolves the projectId param against the canonical project list", async () => {
    mockSearchParams = new URLSearchParams("projectId=proj-1")
    vi.mocked(listVBRProjects).mockResolvedValue([
      makeProject(),
      makeProject({ id: "proj-2", title: "Realtime Chat" }),
    ])
    renderShell()
    await waitFor(() =>
      expect(screen.getByTestId("student-shell-active-project")).toHaveTextContent(
        "Project: Skill Evidence Tracker"
      )
    )
  })

  it("shows the other project's title for a different projectId — no cross-project bleed", async () => {
    mockSearchParams = new URLSearchParams("projectId=proj-2")
    vi.mocked(listVBRProjects).mockResolvedValue([
      makeProject(),
      makeProject({ id: "proj-2", title: "Realtime Chat" }),
    ])
    renderShell()
    await waitFor(() =>
      expect(screen.getByTestId("student-shell-active-project")).toHaveTextContent("Project: Realtime Chat")
    )
    expect(screen.getByTestId("student-shell-active-project")).not.toHaveTextContent(
      "Skill Evidence Tracker"
    )
  })

  it("degrades to a truncated id when the project list cannot be loaded", async () => {
    mockSearchParams = new URLSearchParams("projectId=abcdefgh-1234")
    vi.mocked(listVBRProjects).mockRejectedValue(new Error("auth_session_missing"))
    renderShell()
    await waitFor(() =>
      expect(screen.getByTestId("student-shell-active-project")).toHaveTextContent("Project: abcdefgh…")
    )
  })
})

describe("profile menu and sign-out", () => {
  it("shows persona identity plus Account and Settings links", () => {
    renderShell()
    fireEvent.click(screen.getByTestId("student-shell-profile-toggle"))
    const menu = screen.getByTestId("student-shell-profile-menu")
    expect(menu).toHaveTextContent("Ada Lovelace")
    expect(menu).toHaveTextContent("ada@example.edu")
    const links = Array.from(menu.querySelectorAll("a")).map((a) => [
      a.textContent,
      a.getAttribute("href"),
    ])
    expect(links).toContainEqual(["Account", "/student/account"])
    expect(links).toContainEqual(["Settings", "/student/settings"])
    // Regression: the menu must never point back into the legacy dashboard UI.
    const hrefs = links.map(([, href]) => href)
    expect(hrefs).not.toContain("/dashboard/profile")
    expect(hrefs).not.toContain("/dashboard/settings")
  })

  it("signs out via supabase.auth.signOut() with local scope and lands on /login", async () => {
    renderShell()
    fireEvent.click(screen.getByTestId("student-shell-profile-toggle"))
    fireEvent.click(screen.getByTestId("student-shell-signout"))
    await waitFor(() => expect(signOutMock).toHaveBeenCalledTimes(1))
    expect(signOutMock).toHaveBeenCalledWith({ scope: "local" })
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/login"))
    expect(mockRefresh).toHaveBeenCalled()
  })

  it("still lands on /login when token revocation fails", async () => {
    signOutMock.mockRejectedValue(new Error("network down"))
    renderShell()
    fireEvent.click(screen.getByTestId("student-shell-profile-toggle"))
    fireEvent.click(screen.getByTestId("student-shell-signout"))
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/login"))
    expect(mockRefresh).toHaveBeenCalled()
  })
})

describe("mobile navigation", () => {
  it("toggles the drawer with navigation and a sign-out control", () => {
    renderShell()
    expect(screen.queryByTestId("student-shell-mobile-drawer")).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId("student-shell-menu-toggle"))
    const drawer = screen.getByTestId("student-shell-mobile-drawer")
    expect(drawer).toHaveTextContent("Dashboard")
    expect(drawer).toHaveTextContent("Work Passport")
    expect(screen.getByTestId("student-shell-active-project-mobile")).toHaveTextContent("All projects")
    expect(screen.getByTestId("student-shell-signout-mobile")).toBeInTheDocument()
    fireEvent.click(screen.getByTestId("student-shell-menu-toggle"))
    expect(screen.queryByTestId("student-shell-mobile-drawer")).not.toBeInTheDocument()
  })
})

describe("recording surfaces stay bare", () => {
  it.each([
    "/student/vbr/sessions/sess-123",
    "/student/proofs/project-defense/record/sess-456",
  ])("renders zero shell chrome on %s", (path) => {
    mockPathname = path
    renderShell()
    expect(screen.getByTestId("page-body")).toBeInTheDocument()
    expect(screen.queryByTestId("student-shell")).not.toBeInTheDocument()
    expect(screen.queryByTestId("student-shell-sidebar")).not.toBeInTheDocument()
    expect(screen.queryByTestId("student-shell-breadcrumbs")).not.toBeInTheDocument()
  })

  it("keeps non-recording nested routes inside the shell", () => {
    expect(isBareStudentRoute("/student/vbr/sessions/sess-123")).toBe(true)
    expect(isBareStudentRoute("/student/proofs/project-defense/record/x")).toBe(true)
    expect(isBareStudentRoute("/student/vbr")).toBe(false)
    expect(isBareStudentRoute("/student/vbr/passport")).toBe(false)
    expect(isBareStudentRoute("/student/proofs/project-defense")).toBe(false)
  })
})

describe("persona initials", () => {
  it("derives initials from name, email, or a safe fallback", () => {
    expect(studentPersonaInitials("Ada Lovelace", "ada@example.edu")).toBe("AL")
    expect(studentPersonaInitials("", "mohammed@example.com")).toBe("MO")
    expect(studentPersonaInitials("", "")).toBe("ME")
  })
})
