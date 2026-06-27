import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useClips } from "@/hooks/use-clips"

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

function listRes(clips: unknown[] = []) {
  return new Response(
    JSON.stringify({ clips, total: clips.length, page: 1, per_page: 20, total_pages: 1 }),
    { status: 200 }
  )
}

afterEach(() => vi.restoreAllMocks())

describe("useClips", () => {
  it("fetches with the Bearer token and the serialized query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(listRes([{ id: "c1" }]))
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(
      () => useClips({ workspace_id: "w1", sort: "oldest", page: 2 }),
      { wrapper }
    )
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data?.clips).toHaveLength(1)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips?workspace_id=w1&sort=oldest&page=2")
    expect((opts.headers as Record<string, string>).authorization).toBe("Bearer tok")
  })

  it("refetches when the query params change", async () => {
    const fetchMock = vi.fn().mockResolvedValue(listRes())
    vi.stubGlobal("fetch", fetchMock)

    const { result, rerender } = renderHook((p: { search: string }) => useClips(p), {
      wrapper,
      initialProps: { search: "a" },
    })
    await waitFor(() => expect(result.current.loading).toBe(false))
    rerender({ search: "b" })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe("/api/clips?search=b")
  })

  it("flags an error when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })))
    const { result } = renderHook(() => useClips({}), { wrapper })
    await waitFor(() => expect(result.current.error).toBe(true))
  })

  it("does not fetch while disabled, then fetches when enabled", async () => {
    const fetchMock = vi.fn().mockResolvedValue(listRes())
    vi.stubGlobal("fetch", fetchMock)

    const { result, rerender } = renderHook(
      (p: { enabled: boolean }) => useClips({ workspace_id: "w1" }, { enabled: p.enabled }),
      { wrapper, initialProps: { enabled: false } }
    )
    // Deferred: no fetch yet, and the hook reports loading so the caller shows a skeleton.
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)

    rerender({ enabled: true })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
  })

  it("shows the skeleton again on the next query after an error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 500 }))
      .mockResolvedValue(listRes([{ id: "c1" }]))
    vi.stubGlobal("fetch", fetchMock)

    const { result, rerender } = renderHook((p: { search: string }) => useClips(p), {
      wrapper,
      initialProps: { search: "a" },
    })
    await waitFor(() => expect(result.current.error).toBe(true))

    // A new query supersedes the stale error: loading flips back on for the retry.
    rerender({ search: "b" })
    await waitFor(() => expect(result.current.loading).toBe(true))
    await waitFor(() => expect(result.current.data?.clips).toHaveLength(1))
  })
})
