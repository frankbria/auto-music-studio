import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useReleasesPoll } from "@/hooks/use-releases-poll"
import type { ReleaseSummary } from "@/lib/releases"

// Mock the seam so we control resolution + count calls. Types are erased at
// runtime, so dropping the other exports is harmless.
vi.mock("@/lib/releases", () => ({ fetchReleases: vi.fn() }))
import { fetchReleases } from "@/lib/releases"
const mockFetch = fetchReleases as unknown as ReturnType<typeof vi.fn>

const sample: ReleaseSummary[] = [
  {
    id: "r1",
    clipId: "c1",
    title: "T",
    artist: "A",
    genre: "G",
    releaseDate: "2026-01-01",
    createdAt: "2026-01-01T00:00:00Z",
    channels: [{ channel: "soundcloud", status: "live", permalink: "https://x" }],
  },
]

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
  Object.defineProperty(document, "hidden", { value: false, configurable: true })
})

describe("useReleasesPoll", () => {
  it("loads releases on mount and clears loading", async () => {
    mockFetch.mockResolvedValue(sample)
    const { result } = renderHook(() => useReleasesPoll(1000))

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.releases).toEqual(sample))
    expect(result.current.loading).toBe(false)
    expect(result.current.lastUpdated).not.toBeNull()
  })

  it("surfaces an error when the fetch rejects", async () => {
    mockFetch.mockRejectedValue(new Error("boom"))
    const { result } = renderHook(() => useReleasesPoll(1000))
    await waitFor(() => expect(result.current.error).toMatch(/could not load/i))
    expect(result.current.loading).toBe(false)
  })

  it("re-polls on the interval while visible", async () => {
    mockFetch.mockResolvedValue(sample)
    vi.useFakeTimers()
    renderHook(() => useReleasesPoll(1000))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0) // flush the mount load
    })
    expect(mockFetch).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it("skips polling while the tab is hidden", async () => {
    mockFetch.mockResolvedValue(sample)
    vi.useFakeTimers()
    renderHook(() => useReleasesPoll(1000))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(mockFetch).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, "hidden", { value: true, configurable: true })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(mockFetch).toHaveBeenCalledTimes(1) // no extra polls while hidden
  })

  it("ignores a stale (out-of-order) resolution", async () => {
    // load #1 (mount) stays pending; load #2 (refresh) resolves with newer data
    // first; then #1 resolves late and must NOT overwrite the newer result.
    let resolveStale: (v: ReleaseSummary[]) => void = () => {}
    const stalePromise = new Promise<ReleaseSummary[]>((r) => (resolveStale = r))
    const newer: ReleaseSummary[] = [{ ...sample[0], id: "newer" }]
    mockFetch.mockReturnValueOnce(stalePromise).mockResolvedValueOnce(newer)

    const { result } = renderHook(() => useReleasesPoll(60_000))
    await act(async () => {}) // flush the mount microtask → load #1 starts, pending

    await act(async () => {
      result.current.refresh() // load #2 resolves with `newer`
    })
    await waitFor(() => expect(result.current.releases?.[0].id).toBe("newer"))

    await act(async () => {
      resolveStale([{ ...sample[0], id: "stale" }]) // late #1
    })
    expect(result.current.releases?.[0].id).toBe("newer") // not overwritten
  })

  it("refresh() forces an immediate reload", async () => {
    mockFetch.mockResolvedValue(sample)
    const { result } = renderHook(() => useReleasesPoll(60_000))
    await waitFor(() => expect(result.current.releases).toEqual(sample))
    expect(mockFetch).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.refresh()
    })
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2))
  })
})
