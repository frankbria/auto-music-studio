import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "@/contexts/auth-context"
import { useAuth } from "@/hooks/use-auth"

const accessToken = `h.${Buffer.from(
  JSON.stringify({ sub: "u1", email: "musician@example.com" })
).toString("base64url")}.s`

function Probe() {
  const { isLoading, isAuthenticated, user, logout } = useAuth()
  if (isLoading) return <p>loading</p>
  return (
    <div>
      <p data-testid="state">
        {isAuthenticated ? `in:${user?.email}` : "out"}
      </p>
      <button onClick={() => logout()}>logout</button>
    </div>
  )
}

const ok = (body: object) => ({ ok: true, status: 200, json: async () => body })
const unauthorized = { ok: false, status: 401, json: async () => ({}) }

afterEach(() => vi.unstubAllGlobals())

describe("AuthProvider", () => {
  it("restores a session on mount via the refresh cookie", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/auth/refresh" ? ok({ access_token: accessToken }) : unauthorized
      )
    )
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent(
        "in:musician@example.com"
      )
    )
  })

  it("stays signed out when the refresh fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => unauthorized))
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent("out")
    )
  })

  it("clears the session on logout", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url === "/api/auth/refresh" ? ok({ access_token: accessToken }) : ok({})
    )
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent("in:")
    )

    await user.click(screen.getByRole("button", { name: "logout" }))

    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent("out")
    )
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", {
      method: "POST",
    })
  })
})
