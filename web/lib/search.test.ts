import { afterEach, describe, expect, it, vi } from "vitest"

import {
  buildSearchQuery,
  DEFAULT_SEARCH,
  parseSearchParams,
  searchClips,
  type SearchParams,
} from "@/lib/search"
import { clipRequests, discoverPage } from "@/test/discover-api"

const params = (over: Partial<SearchParams> = {}): SearchParams => ({
  ...DEFAULT_SEARCH,
  ...over,
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("searchClips", () => {
  it("maps search state onto the discovery API query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(discoverPage([]))
    vi.stubGlobal("fetch", fetchMock)

    await searchClips(
      params({
        q: "  neon  ",
        style: "rock",
        bpmMin: 90,
        bpmMax: 120,
        key: "A minor",
        model: "m1",
        sort: "newest",
      }),
      "c2"
    )

    expect(clipRequests(fetchMock)).toEqual([
      {
        q: "neon",
        style: "rock",
        bpm_min: "90",
        bpm_max: "120",
        key: "A minor",
        model: "m1",
        sort: "newest",
        cursor: "c2",
      },
    ])
  })

  it("leaves unset filters out and caps the query at the API's 200 chars", async () => {
    const fetchMock = vi.fn().mockResolvedValue(discoverPage([]))
    vi.stubGlobal("fetch", fetchMock)

    await searchClips(params({ q: "x".repeat(250) }))

    expect(clipRequests(fetchMock)).toEqual([
      { q: "x".repeat(200), sort: "relevance" },
    ])
  })
})

describe("parseSearchParams / buildSearchQuery round-trip", () => {
  it("reads all fields from a URL query string", () => {
    const sp = new URLSearchParams(
      "q=jazz&style=jazz&bpm_min=120&bpm_max=140&key=C%20major&model=ace-step-v1-turbo&sort=newest"
    )
    expect(parseSearchParams(sp)).toEqual({
      q: "jazz",
      style: "jazz",
      bpmMin: 120,
      bpmMax: 140,
      key: "C major",
      model: "ace-step-v1-turbo",
      sort: "newest",
    })
  })

  it("falls back to defaults for missing or invalid values", () => {
    const parsed = parseSearchParams(
      new URLSearchParams("bpm_min=notanumber&sort=bogus")
    )
    expect(parsed.bpmMin).toBeNull()
    expect(parsed.sort).toBe(DEFAULT_SEARCH.sort)
  })

  it("treats an old sort=popular link as the default sort", () => {
    expect(parseSearchParams(new URLSearchParams("sort=popular")).sort).toBe(
      "relevance"
    )
  })

  it("omits default/empty values from the built query for clean URLs", () => {
    expect(buildSearchQuery(DEFAULT_SEARCH)).toBe("")
    expect(buildSearchQuery(params({ q: "jazz", sort: "newest" }))).toBe(
      "q=jazz&sort=newest"
    )
  })

  it("round-trips a populated state through the URL", () => {
    const state = params({
      q: "beats",
      style: "hip-hop",
      bpmMin: 90,
      bpmMax: 120,
      key: "A minor",
      sort: "newest",
    })
    expect(
      parseSearchParams(new URLSearchParams(buildSearchQuery(state)))
    ).toEqual(state)
  })
})
