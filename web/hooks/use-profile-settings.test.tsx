import { renderHook, waitFor, act } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useProfileSettings } from "@/hooks/use-profile-settings"

const authValue = {
  user: { id: "u1", email: "a@b.co" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

function wrapper({ children }: { children: ReactNode }) {
  return <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
}

const PROFILE = {
  id: "u1",
  email: "a@b.co",
  name: "Ada",
  display_name: "Ada",
  handle: "ada",
  bio: "",
  style_tags: [],
  avatar_url: null,
  subscription_tier: "free",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
}

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => vi.restoreAllMocks())

describe("useProfileSettings", () => {
  it("fetches the profile on mount with the Bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(PROFILE))
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => useProfileSettings(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.profile?.handle).toBe("ada")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/users/me")
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer tok")
  })

  it("save() returns the updated profile on success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(PROFILE)) // mount fetch
      .mockResolvedValueOnce(jsonRes({ ...PROFILE, display_name: "Ada L" })) // PATCH
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => useProfileSettings(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    let res!: Awaited<ReturnType<typeof result.current.save>>
    await act(async () => {
      res = await result.current.save({ display_name: "Ada L" })
    })
    expect(res.ok).toBe(true)
    if (res.ok) expect(res.profile.display_name).toBe("Ada L")
  })

  it("maps a 409 to a handle field error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(PROFILE))
      .mockResolvedValueOnce(jsonRes({ detail: "taken" }, 409))
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => useProfileSettings(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    let res!: Awaited<ReturnType<typeof result.current.save>>
    await act(async () => {
      res = await result.current.save({ handle: "taken" })
    })
    expect(res.ok).toBe(false)
    if (!res.ok) expect(res.fieldErrors.handle).toMatch(/already taken/)
  })

  it("maps a 422 to field errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(PROFILE))
      .mockResolvedValueOnce(
        jsonRes(
          { detail: [{ loc: ["body", "bio"], msg: "too long" }] },
          422
        )
      )
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => useProfileSettings(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    let res!: Awaited<ReturnType<typeof result.current.save>>
    await act(async () => {
      res = await result.current.save({ bio: "x" })
    })
    expect(res.ok).toBe(false)
    if (!res.ok) expect(res.fieldErrors.bio).toBe("too long")
  })

  it("maps a nested style_tags item error to the style_tags field", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes(PROFILE))
      .mockResolvedValueOnce(
        jsonRes(
          { detail: [{ loc: ["body", "style_tags", 0], msg: "too long" }] },
          422
        )
      )
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => useProfileSettings(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    let res!: Awaited<ReturnType<typeof result.current.save>>
    await act(async () => {
      res = await result.current.save({ style_tags: ["x".repeat(40)] })
    })
    expect(res.ok).toBe(false)
    if (!res.ok) expect(res.fieldErrors.style_tags).toBe("too long")
  })
})
