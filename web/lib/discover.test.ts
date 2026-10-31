import { afterEach, describe, expect, it, vi } from "vitest"

import { fetchFacets, fetchPublicClips } from "@/lib/discover"
import { makeClip } from "@/test/clip-factory"
import { clipRequests, discoverPage } from "@/test/discover-api"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("fetchPublicClips", () => {
  it("sends set fields to the BFF and maps next_cursor", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(discoverPage([makeClip()], "c2", 7))
    vi.stubGlobal("fetch", fetchMock)

    const page = await fetchPublicClips({
      q: "lofi",
      bpm_min: 90,
      bpm_max: null,
      key: "",
      sort: "newest",
      cursor: "c1",
    })

    expect(fetchMock.mock.calls[0][0]).toMatch(/^\/api\/discover\/clips\?/)
    expect(clipRequests(fetchMock)).toEqual([
      { q: "lofi", bpm_min: "90", sort: "newest", cursor: "c1" },
    ])
    expect(page).toEqual({ clips: [makeClip()], nextCursor: "c2", total: 7 })
  })

  it("calls the bare path when no field is set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(discoverPage([]))
    vi.stubGlobal("fetch", fetchMock)

    await fetchPublicClips({})

    expect(fetchMock.mock.calls[0][0]).toBe("/api/discover/clips")
  })

  it("throws on a non-OK response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 429 }))
    )

    await expect(fetchPublicClips({})).rejects.toThrow("429")
  })
})

describe("fetchFacets", () => {
  it("reads the facets endpoint", async () => {
    const facets = { keys: ["A minor"], models: ["m1"] }
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(facets), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await expect(fetchFacets()).resolves.toEqual(facets)
    expect(fetchMock.mock.calls[0][0]).toBe("/api/discover/facets")
  })
})
