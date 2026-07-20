import { describe, expect, it } from "vitest"

import {
  GENRES,
  getCharts,
  getGenreChannels,
  getNewReleases,
  getStaffPicks,
  getTrendingClips,
} from "@/lib/explore"

describe("explore mock service", () => {
  it("returns all eight genre channels", () => {
    expect(getGenreChannels()).toBe(GENRES)
    expect(GENRES).toHaveLength(8)
    expect(GENRES.map((g) => g.slug)).toContain("hip-hop")
  })

  it("trends differently for 24h vs 7d (AC2)", () => {
    const day = getTrendingClips("24h")
    const week = getTrendingClips("7d")
    expect(day.length).toBeGreaterThan(0)
    // 24h weights likes+shares, 7d weights plays — leaders must differ.
    expect(day[0].id).not.toBe(week[0].id)
    // 24h ordered by likes+shares desc.
    const dayScore = (i: number) =>
      (day[i].like_count ?? 0) + (day[i].share_count ?? 0)
    expect(dayScore(0)).toBeGreaterThanOrEqual(dayScore(1))
    // 7d ordered by plays desc.
    expect(week[0].play_count).toBeGreaterThanOrEqual(week[1].play_count ?? 0)
  })

  it("charts are ranked highest-first by the chosen metric (AC4)", () => {
    const byPlays = getCharts("plays")
    for (let i = 1; i < byPlays.length; i++) {
      expect(byPlays[i - 1].play_count!).toBeGreaterThanOrEqual(
        byPlays[i].play_count!
      )
    }
    // A different metric can reorder the top clip.
    expect(getCharts("likes")[0].like_count).toBeGreaterThanOrEqual(
      getCharts("likes")[1].like_count ?? 0
    )
  })

  it("new releases are newest-first", () => {
    const items = getNewReleases()
    for (let i = 1; i < items.length; i++) {
      expect(Date.parse(items[i - 1].created_at)).toBeGreaterThanOrEqual(
        Date.parse(items[i].created_at)
      )
    }
  })

  it("staff picks are a non-empty curated subset of public clips", () => {
    const picks = getStaffPicks()
    expect(picks.length).toBeGreaterThan(0)
    expect(picks.every((c) => c.is_public)).toBe(true)
  })
})
