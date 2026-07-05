import { describe, expect, it } from "vitest"

import {
  DEFAULT_TARGET_DURATION,
  isFullSongEligible,
  MAX_SEED_DURATION,
  MIN_SECTION_SECONDS,
  planSections,
  SECTION_CONFIG,
  SONG_STRUCTURE,
} from "@/lib/song-structure"
import { makeClip } from "@/test/clip-factory"

// Parity with the backend planner (tests/test_song_structure.py). The wizard
// sizes each extend from these numbers, so they must match plan_sections().

const sum = (ns: number[]) => ns.reduce((a, b) => a + b, 0)

describe("SONG_STRUCTURE / SECTION_CONFIG", () => {
  it("is intro → outro", () => {
    expect(SONG_STRUCTURE).toEqual([
      "intro",
      "verse",
      "chorus",
      "verse",
      "chorus",
      "bridge",
      "outro",
    ])
  })

  it("has a positive weight and non-empty style hint for every section", () => {
    for (const name of new Set(SONG_STRUCTURE)) {
      const [weight, hint] = SECTION_CONFIG[name]
      expect(weight).toBeGreaterThan(0)
      expect(hint.trim()).not.toBe("")
    }
  })
})

describe("planSections", () => {
  it("returns the seven sections in canonical order", () => {
    const sections = planSections(30, DEFAULT_TARGET_DURATION)
    expect(sections.map((s) => s.name)).toEqual([...SONG_STRUCTURE])
  })

  it("section durations sum to (target - seed)", () => {
    const sections = planSections(30, 210)
    expect(sum(sections.map((s) => s.durationSeconds))).toBeCloseTo(180, 5)
  })

  it("scales durations up with the target", () => {
    const small = planSections(30, 120)
    const big = planSections(30, 300)
    expect(sum(big.map((s) => s.durationSeconds))).toBeGreaterThan(
      sum(small.map((s) => s.durationSeconds))
    )
  })

  it("keeps choruses at least as long as intros", () => {
    const sections = planSections(30, 210)
    const intro = sections.find((s) => s.name === "intro")!
    const chorus = sections.find((s) => s.name === "chorus")!
    expect(chorus.durationSeconds).toBeGreaterThanOrEqual(intro.durationSeconds)
  })

  it("applies the audible-section floor when there is headroom", () => {
    const sections = planSections(30, 210)
    for (const s of sections) {
      expect(s.durationSeconds).toBeGreaterThanOrEqual(MIN_SECTION_SECONDS)
    }
  })

  it("never overshoots the remaining budget, even at tight margins", () => {
    for (const [seed, target] of [
      [58, 60],
      [50, 55],
      [10, 11],
      [30, 33],
      [30, 60],
      [60, 100],
    ] as const) {
      const sections = planSections(seed, target)
      const total = sum(sections.map((s) => s.durationSeconds))
      expect(total).toBeLessThanOrEqual(target - seed + 0.01)
      for (const s of sections) expect(s.durationSeconds).toBeGreaterThan(0)
    }
  })

  it("returns an empty plan when target does not exceed seed", () => {
    expect(planSections(120, 60)).toEqual([])
    expect(planSections(60, 60)).toEqual([])
  })

  it("carries each section's style hint", () => {
    const sections = planSections(30, 210)
    expect(sections[0].styleHint).toBe(SECTION_CONFIG.intro[1])
    for (const s of sections) expect(s.styleHint.trim()).not.toBe("")
  })
})

describe("isFullSongEligible", () => {
  it("is true only for a known duration under the max seed", () => {
    expect(isFullSongEligible(makeClip({ duration: 30 }))).toBe(true)
    expect(isFullSongEligible(makeClip({ duration: MAX_SEED_DURATION }))).toBe(false)
    expect(isFullSongEligible(makeClip({ duration: 120 }))).toBe(false)
    expect(isFullSongEligible(makeClip({ duration: null }))).toBe(false)
  })
})
