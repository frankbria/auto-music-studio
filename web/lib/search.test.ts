import { describe, expect, it } from "vitest"

import {
  buildSearchQuery,
  DEFAULT_SEARCH,
  paginate,
  parseSearchParams,
  searchClips,
  type SearchParams,
} from "@/lib/search"

const params = (over: Partial<SearchParams> = {}): SearchParams => ({
  ...DEFAULT_SEARCH,
  ...over,
})

describe("searchClips", () => {
  it("matches the query across titles, tags, and lyrics (AC1)", () => {
    const byTitle = searchClips(params({ q: "neon" }))
    expect(byTitle.map((c) => c.id)).toContain("clip-neon")

    // Tag match: "trap" is a style tag on Gold Rush 88, not in its title.
    const byTag = searchClips(params({ q: "trap" }))
    expect(byTag.map((c) => c.id)).toContain("clip-gold")
    expect(byTag.every((c) => c.title?.toLowerCase().includes("trap"))).toBe(
      false
    )
  })

  it("returns nothing for a query that matches no clip", () => {
    expect(searchClips(params({ q: "zzzznomatch" }))).toEqual([])
  })

  it("narrows by BPM range (AC2)", () => {
    const all = searchClips(params())
    const ranged = searchClips(params({ bpmMin: 120, bpmMax: 140 }))
    expect(ranged.length).toBeGreaterThan(0)
    expect(ranged.length).toBeLessThan(all.length)
    expect(ranged.every((c) => c.bpm! >= 120 && c.bpm! <= 140)).toBe(true)
  })

  it("narrows by style, key, and model", () => {
    expect(
      searchClips(params({ style: "rock" })).every((c) =>
        c.style_tags.includes("rock")
      )
    ).toBe(true)
    expect(
      searchClips(params({ key: "C major" })).every((c) => c.key === "C major")
    ).toBe(true)
    const turbo = searchClips(params({ model: "ace-step-v1-turbo" }))
    expect(turbo.length).toBeGreaterThan(0)
    expect(turbo.every((c) => c.model === "ace-step-v1-turbo")).toBe(true)
  })

  it("changes ordering by sort (AC3)", () => {
    const newest = searchClips(params({ sort: "newest" }))
    for (let i = 1; i < newest.length; i++) {
      expect(Date.parse(newest[i - 1].created_at)).toBeGreaterThanOrEqual(
        Date.parse(newest[i].created_at)
      )
    }
    const popular = searchClips(params({ sort: "popular" }))
    for (let i = 1; i < popular.length; i++) {
      expect(popular[i - 1].play_count!).toBeGreaterThanOrEqual(
        popular[i].play_count!
      )
    }
    // Sorts must actually reorder relative to each other.
    expect(newest[0].id).not.toBe(popular[0].id)
  })

  it("relevance ranks a title hit above a tag-only hit", () => {
    // "electronic" is Neon Skyline's tag and Pulse Theory's tag, but neither has
    // it in the title; add a clip-agnostic check that a title match wins.
    const ranked = searchClips(params({ q: "pulse", sort: "relevance" }))
    expect(ranked[0].id).toBe("clip-pulse")
  })
})

describe("paginate", () => {
  it("splits results into pages and clamps out-of-range pages", () => {
    const all = searchClips(params())
    const p1 = paginate(all, 1)
    expect(p1.clips.length).toBeLessThanOrEqual(all.length)
    expect(p1.totalPages).toBeGreaterThanOrEqual(1)
    // A page past the end clamps to the last page rather than returning empty.
    const beyond = paginate(all, 999)
    expect(beyond.page).toBe(beyond.totalPages)
    expect(beyond.clips.length).toBeGreaterThan(0)
  })

  it("reports one empty page for no results", () => {
    const p = paginate([], 1)
    expect(p).toMatchObject({ page: 1, total: 0, totalPages: 1, clips: [] })
  })
})

describe("parseSearchParams / buildSearchQuery round-trip", () => {
  it("reads all fields from a URL query string", () => {
    const sp = new URLSearchParams(
      "q=jazz&style=jazz&bpm_min=120&bpm_max=140&key=C%20major&model=ace-step-v1-turbo&sort=newest&page=2"
    )
    expect(parseSearchParams(sp)).toEqual({
      q: "jazz",
      style: "jazz",
      bpmMin: 120,
      bpmMax: 140,
      key: "C major",
      model: "ace-step-v1-turbo",
      sort: "newest",
      page: 2,
    })
  })

  it("falls back to defaults for missing or invalid values", () => {
    const sp = new URLSearchParams("bpm_min=notanumber&sort=bogus&page=-3")
    const parsed = parseSearchParams(sp)
    expect(parsed.bpmMin).toBeNull()
    expect(parsed.sort).toBe(DEFAULT_SEARCH.sort)
    expect(parsed.page).toBe(1)
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
      sort: "popular",
      page: 3,
    })
    expect(parseSearchParams(new URLSearchParams(buildSearchQuery(state)))).toEqual(
      state
    )
  })
})
