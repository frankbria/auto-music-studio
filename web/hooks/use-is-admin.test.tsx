import { renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useIsAdmin } from "@/hooks/use-is-admin"
import { SIGNED_IN, SignedIn, type AuthValue } from "@/test/signed-in"

function wrapperFor(value: AuthValue = SIGNED_IN) {
  return function wrapper({ children }: { children: ReactNode }) {
    return <SignedIn value={value}>{children}</SignedIn>
  }
}

function stubProfile(status: number, body: unknown) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body), { status }))
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("useIsAdmin", () => {
  it("reports an admin from the profile's is_admin flag", async () => {
    const fetchMock = stubProfile(200, { is_admin: true })
    const { result } = renderHook(() => useIsAdmin(), { wrapper: wrapperFor() })
    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.isAdmin).toBe(true)
    expect(fetchMock.mock.calls[0][0]).toBe("/api/users/me")
  })

  it("is false for a regular user", async () => {
    stubProfile(200, { is_admin: false })
    const { result } = renderHook(() => useIsAdmin(), { wrapper: wrapperFor() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.isAdmin).toBe(false)
  })

  it("fails closed when the profile request fails", async () => {
    stubProfile(500, {})
    const { result } = renderHook(() => useIsAdmin(), { wrapper: wrapperFor() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.isAdmin).toBe(false)
  })

  it("fails closed on a profile that predates the flag", async () => {
    stubProfile(200, { subscription_tier: "pro" })
    const { result } = renderHook(() => useIsAdmin(), { wrapper: wrapperFor() })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.isAdmin).toBe(false)
  })

  it("never asks when signed out", () => {
    const fetchMock = stubProfile(200, { is_admin: true })
    const { result } = renderHook(() => useIsAdmin(), {
      wrapper: wrapperFor({
        ...SIGNED_IN,
        isAuthenticated: false,
        accessToken: null,
      }),
    })
    expect(result.current).toEqual({ isAdmin: false, isLoading: false })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
