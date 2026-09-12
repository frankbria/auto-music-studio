import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useSubscriptionTier } from "@/hooks/use-subscription-tier"

function makeAuthValue(
  overrides: Partial<{ accessToken: string | null }> = {}
) {
  return {
    user: { id: "u1", email: "a@b.co" },
    accessToken: "tok" as string | null,
    isAuthenticated: true,
    isLoading: false,
    login: vi.fn(),
    completeLogin: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  }
}

function makeWrapper(authValue = makeAuthValue()) {
  return function wrapper({ children }: { children: ReactNode }) {
    return (
      <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
    )
  }
}

function profileRes(tier: string) {
  return new Response(JSON.stringify({ subscription_tier: tier }), {
    status: 200,
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("useSubscriptionTier", () => {
  it("fetches /api/users/me with the Bearer token and reports a pro tier", async () => {
    const fetchMock = vi.fn().mockResolvedValue(profileRes("pro"))
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => useSubscriptionTier(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.tier).toBe("pro")
    expect(result.current.isFreeTier).toBe(false)

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/users/me")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
    // Bounded fetch: a hung profile request must not lock Pro items forever.
    expect(opts.signal).toBeInstanceOf(AbortSignal)
  })

  it("reports free tier for a free profile", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(profileRes("free")))

    const { result } = renderHook(() => useSubscriptionTier(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.tier).toBe("free")
    expect(result.current.isFreeTier).toBe(true)
  })

  it("defaults to free when the profile fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")))

    const { result } = renderHook(() => useSubscriptionTier(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.isFreeTier).toBe(true)
  })

  it("shares one profile request between hooks mounted together (#402)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(profileRes("pro"))
    vi.stubGlobal("fetch", fetchMock)

    // Song detail mounts the hook twice in one commit: once for the menu badges
    // and once inside useSongActions. That used to be two identical requests.
    const { result } = renderHook(
      () => [useSubscriptionTier(), useSubscriptionTier()] as const,
      { wrapper: makeWrapper() }
    )
    await waitFor(() => expect(result.current[0].isLoading).toBe(false))
    await waitFor(() => expect(result.current[1].isLoading).toBe(false))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(result.current[0].isFreeTier).toBe(false)
    expect(result.current[1].isFreeTier).toBe(false)
  })

  it("asks again on a fresh mount, so a tier change shows without a reload", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(profileRes("free"))
      .mockResolvedValueOnce(profileRes("pro"))
    vi.stubGlobal("fetch", fetchMock)

    const first = renderHook(() => useSubscriptionTier(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(first.result.current.isLoading).toBe(false))
    expect(first.result.current.isFreeTier).toBe(true)
    first.unmount()

    // The musician upgraded in between; the next page must see it.
    const second = renderHook(() => useSubscriptionTier(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(second.result.current.isLoading).toBe(false))
    expect(second.result.current.isFreeTier).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it("defaults to free without fetching when unauthenticated", () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => useSubscriptionTier(), {
      wrapper: makeWrapper(makeAuthValue({ accessToken: null })),
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.isFreeTier).toBe(true)
  })
})
