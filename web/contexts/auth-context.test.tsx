import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "@/contexts/auth-context"
import { useAuth } from "@/hooks/use-auth"

const accessToken = `h.${Buffer.from(
  JSON.stringify({ sub: "u1", email: "musician@example.com" })
).toString("base64url")}.s`

/** A token that carries an `exp` claim `secondsFromNow` in the future. */
const tokenExpiring = (secondsFromNow: number) =>
  `h.${Buffer.from(
    JSON.stringify({
      sub: "u1",
      email: "musician@example.com",
      exp: Math.floor(Date.now() / 1000) + secondsFromNow,
    })
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

  // NB: waitFor() deadlocks under fake timers (it polls on the frozen clock),
  // so these tests flush the mount refresh with act()+runOnlyPendingTimersAsync
  // and assert synchronously instead.
  it("refreshes ahead of expiry and applies the rotated token", async () => {
    vi.useFakeTimers()
    try {
      let call = 0
      const fetchMock = vi.fn(async (url: string) => {
        if (url !== "/api/auth/refresh") return unauthorized
        call += 1
        // First mount restores a token expiring in 15 min; the scheduled
        // refresh yields a fresh 15-min token before the first one dies.
        return ok({ access_token: tokenExpiring(15 * 60) })
      })
      vi.stubGlobal("fetch", fetchMock)
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>
      )
      await act(async () => {
        await vi.runOnlyPendingTimersAsync()
      })
      expect(call).toBe(1)
      expect(screen.getByTestId("state")).toHaveTextContent("in:")

      // Advance past the refresh-ahead point (~1 min before expiry).
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15 * 60 * 1000)
      })
      expect(call).toBeGreaterThanOrEqual(2)
      // Still signed in on the rotated token — no manual reload needed.
      expect(screen.getByTestId("state")).toHaveTextContent("in:")
    } finally {
      vi.useRealTimers()
    }
  })

  it("signs out when a scheduled refresh finds the session revoked", async () => {
    vi.useFakeTimers()
    try {
      let call = 0
      const fetchMock = vi.fn(async (url: string) => {
        if (url !== "/api/auth/refresh") return unauthorized
        call += 1
        // Mount succeeds; the next (scheduled) refresh is rejected — the
        // refresh token was revoked, so the session is unrecoverable.
        return call === 1 ? ok({ access_token: tokenExpiring(15 * 60) }) : unauthorized
      })
      vi.stubGlobal("fetch", fetchMock)
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>
      )
      await act(async () => {
        await vi.runOnlyPendingTimersAsync()
      })
      expect(screen.getByTestId("state")).toHaveTextContent("in:")

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15 * 60 * 1000)
      })
      // isAuthenticated flips false → useRequireAuth redirects to /login.
      expect(screen.getByTestId("state")).toHaveTextContent("out")
    } finally {
      vi.useRealTimers()
    }
  })

  it("keeps the session signed in when a refresh hits a transient 5xx", async () => {
    vi.useFakeTimers()
    try {
      let call = 0
      const serverError = { ok: false, status: 503, json: async () => ({}) }
      const fetchMock = vi.fn(async (url: string) => {
        if (url !== "/api/auth/refresh") return unauthorized
        call += 1
        // Mount restores a token; the scheduled refresh then hits a 503. A
        // transient backend error must NOT sign the user out.
        return call === 1 ? ok({ access_token: tokenExpiring(15 * 60) }) : serverError
      })
      vi.stubGlobal("fetch", fetchMock)
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>
      )
      await act(async () => {
        await vi.runOnlyPendingTimersAsync()
      })
      expect(screen.getByTestId("state")).toHaveTextContent("in:")

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15 * 60 * 1000)
      })
      // The refresh was attempted (and retried) but the still-decodable token
      // keeps the user authenticated — no bounce to /login on a blip.
      expect(call).toBeGreaterThanOrEqual(2)
      expect(screen.getByTestId("state")).toHaveTextContent("in:")
    } finally {
      vi.useRealTimers()
    }
  })

  it("coalesces concurrent refreshes into a single in-flight request", async () => {
    vi.useFakeTimers()
    try {
      let call = 0
      // Mount restores an already-expired token (decodes to a user, so the tab
      // stays "in", but the visibility listener treats it as needing a refresh).
      // Refreshes after mount hang, so two triggers overlap in flight.
      const fetchMock = vi.fn(async (url: string) => {
        if (url !== "/api/auth/refresh") return unauthorized
        call += 1
        if (call === 1) return ok({ access_token: tokenExpiring(-10) })
        return new Promise(() => {}) // never settles — stays in flight
      })
      vi.stubGlobal("fetch", fetchMock)
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>
      )
      await act(async () => {
        await vi.runOnlyPendingTimersAsync()
      })
      expect(call).toBe(1)
      expect(screen.getByTestId("state")).toHaveTextContent("in:")

      // Two visibility events fire their handlers synchronously; the
      // single-flight guard must let only ONE new refresh reach the network.
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"))
        document.dispatchEvent(new Event("visibilitychange"))
      })
      expect(call).toBe(2)
    } finally {
      vi.useRealTimers()
    }
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
