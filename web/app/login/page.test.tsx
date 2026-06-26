import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

// This page uses useSearchParams, which the shared setup mock doesn't provide.
vi.mock("next/navigation", () => ({
  usePathname: () => "/login",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

import LoginPage from "@/app/login/page"
import { AuthContext } from "@/contexts/auth-context"

const baseAuth = {
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

function renderLogin(overrides: Partial<typeof baseAuth> = {}) {
  const value = { ...baseAuth, ...overrides }
  render(<AuthContext.Provider value={value}>
    <LoginPage />
  </AuthContext.Provider>)
  return value
}

describe("LoginPage", () => {
  it("renders both OAuth provider buttons", () => {
    renderLogin()
    expect(
      screen.getByRole("button", { name: /Continue with Google/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Continue with Discord/ })
    ).toBeInTheDocument()
  })

  it("starts the OAuth flow for the chosen provider", async () => {
    const user = userEvent.setup()
    const login = vi.fn().mockResolvedValue(undefined)
    renderLogin({ login })
    await user.click(screen.getByRole("button", { name: /Continue with Google/ }))
    expect(login).toHaveBeenCalledWith("google")
  })

  it("stashes the return path for the callback to pick up after the round-trip", async () => {
    const user = userEvent.setup()
    renderLogin({ login: vi.fn().mockResolvedValue(undefined) })
    await user.click(screen.getByRole("button", { name: /Continue with Discord/ }))
    // searchParams is empty here, so it defaults to /create.
    expect(sessionStorage.getItem("ams_return_to")).toBe("/create")
  })
})
