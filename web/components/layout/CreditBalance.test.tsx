import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Sidebar } from "@/components/layout/Sidebar"

const creditsState = vi.hoisted(() => ({ current: null as unknown }))

vi.mock("@/contexts/credits-context", () => ({
  useCredits: () => ({ state: creditsState.current, refresh: vi.fn() }),
}))

vi.mock("@/contexts/notifications-context", () => ({
  useUnreadCount: () => 0,
}))

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, logout: vi.fn() }),
}))

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}))

function ready(balance: number) {
  return {
    phase: "ready",
    balance: { balance, tier: "free", upgrade_url: "/settings/billing" },
  }
}

afterEach(() => vi.clearAllMocks())

describe("Sidebar credit balance (US-26.1)", () => {
  it("shows the balance so it is visible on every page", () => {
    creditsState.current = ready(42)
    render(<Sidebar />)

    expect(screen.getByTestId("credit-balance")).toHaveTextContent("42")
  })

  it("shows half credits, since remaster costs 0.5", () => {
    creditsState.current = ready(9.5)
    render(<Sidebar />)

    expect(screen.getByTestId("credit-balance")).toHaveTextContent("9.5")
  })

  it("links somewhere the musician can do something about it", () => {
    creditsState.current = ready(0)
    render(<Sidebar />)

    expect(screen.getByTestId("credit-balance")).toHaveAttribute(
      "href",
      "/settings/billing"
    )
  })

  it("still shows a zero balance rather than hiding it", () => {
    // Zero is exactly when someone needs to see the number.
    creditsState.current = ready(0)
    render(<Sidebar />)

    expect(screen.getByTestId("credit-balance")).toHaveTextContent("0")
  })

  it("names the figure for screen readers", () => {
    creditsState.current = ready(7)
    render(<Sidebar />)

    expect(screen.getByLabelText("7 credits remaining")).toBeInTheDocument()
  })

  it.each([
    ["loading", { phase: "loading" }],
    ["signed out", { phase: "signed-out" }],
    ["errored", { phase: "error", message: "boom" }],
  ])(
    "renders nothing while %s, rather than a placeholder number",
    (_label, state) => {
      // A wrong balance is worse than no balance when it is what someone budgets against.
      creditsState.current = state
      render(<Sidebar />)

      expect(screen.queryByTestId("credit-balance")).not.toBeInTheDocument()
    }
  )
})
