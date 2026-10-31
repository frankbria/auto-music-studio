import { afterEach, describe, expect, it, vi } from "vitest"

import {
  GENRES,
  getGenreChannels,
  getNewReleases,
  NEW_RELEASES_LIMIT,
} from "@/lib/explore"
import { makeClip } from "@/test/clip-factory"
import { clipRequests, discoverPage } from "@/test/discover-api"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("explore data", () => {
  it("returns all eight genre channels", () => {
    expect(getGenreChannels()).toBe(GENRES)
    expect(GENRES).toHaveLength(8)
    expect(GENRES.map((g) => g.slug)).toContain("hip-hop")
  })

  it("new releases are the newest public clips from the discovery API", async () => {
    const clip = makeClip({ id: "fresh" })
    const fetchMock = vi.fn().mockResolvedValue(discoverPage([clip], "c2"))
    vi.stubGlobal("fetch", fetchMock)

    await expect(getNewReleases()).resolves.toEqual([clip])
    expect(clipRequests(fetchMock)).toEqual([
      { sort: "newest", limit: String(NEW_RELEASES_LIMIT) },
    ])
  })
})
