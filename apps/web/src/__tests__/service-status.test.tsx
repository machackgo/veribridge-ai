import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"

async function load(status: string | undefined) {
  vi.resetModules()
  vi.stubEnv("NEXT_PUBLIC_SERVICE_STATUS", status ?? "")
  const mod = await import("@/lib/service-status")
  const banner = await import("@/components/ServiceStatusBanner")
  const shared = await import("../../components/passport/shared")
  return { ...mod, ...banner, ErrorState: shared.ErrorState }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe("service status", () => {
  it("is not paused by default: no banner, generic network message", async () => {
    const m = await load(undefined)
    expect(m.SERVICE_PAUSED).toBe(false)
    expect(m.unreachableMessage()).toBe(m.NETWORK_UNREACHABLE_MESSAGE)
    const { container } = render(<m.ServiceStatusBanner />)
    expect(container).toBeEmptyDOMElement()
  })

  it("paused: banner states what works and what does not", async () => {
    const m = await load("paused")
    expect(m.SERVICE_PAUSED).toBe(true)
    render(<m.ServiceStatusBanner />)
    const banner = screen.getByTestId("service-status-banner")
    expect(banner).toHaveTextContent(/backend is currently paused/)
    expect(banner).toHaveTextContent(/sample data/)
  })

  it("publicApiFetch turns a transport failure into the honest message", async () => {
    const m = await load("paused")
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
    await expect(m.publicApiFetch("https://api.invalid/x")).rejects.toThrow(m.SERVICE_PAUSED_MESSAGE)
  })

  it("publicApiFetch passes HTTP responses through unchanged", async () => {
    const m = await load("paused")
    const res = new Response(null, { status: 404 })
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res))
    await expect(m.publicApiFetch("https://api.invalid/x")).resolves.toBe(res)
  })

  it("ErrorState renders the paused message calmly, other errors unchanged", async () => {
    const m = await load("paused")
    const { unmount } = render(<m.ErrorState message={m.SERVICE_PAUSED_MESSAGE} onRetry={() => {}} />)
    expect(screen.getByText("Temporarily unavailable")).toBeInTheDocument()
    expect(screen.queryByText("Something went wrong")).toBeNull()
    unmount()
    render(<m.ErrorState message="Boom" onRetry={() => {}} />)
    expect(screen.getByText("Something went wrong")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
  })
})
