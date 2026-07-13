import { describe, expect, it } from "vitest"

import {
  BPM_MAX,
  BPM_MIN,
  TRACK_TYPES,
  TRACK_TYPE_ORDER,
  inferTrackType,
  placementPlaybackRate,
  type TrackType,
} from "./track-types"

describe("TRACK_TYPES config", () => {
  it("defines all four track types, each with a label, description, color, and icon", () => {
    expect(TRACK_TYPE_ORDER).toEqual(["ai", "audio", "loop", "vocal"])
    for (const type of TRACK_TYPE_ORDER) {
      const cfg = TRACK_TYPES[type]
      expect(cfg.label).toBeTruthy()
      expect(cfg.description).toBeTruthy()
      expect(cfg.color).toMatch(/^#[0-9a-f]{6}$/i)
      expect(cfg.icon).toBeTruthy()
    }
  })

  it("gives each type a distinct color (visual distinction requirement)", () => {
    const colors = TRACK_TYPE_ORDER.map((t) => TRACK_TYPES[t].color)
    expect(new Set(colors).size).toBe(colors.length)
  })
})

describe("inferTrackType", () => {
  it.each([
    ["upload", "audio"],
    ["stems", "vocal"],
    ["sound", "loop"],
    ["song", "ai"],
    ["generate", "ai"],
    ["compose", "ai"],
    ["cover", "ai"],
    ["extend", "ai"],
    ["remix", "ai"],
    ["mashup", "ai"],
    ["sample", "ai"],
    ["full_song", "ai"],
    ["mastering", "ai"],
  ] as [string, TrackType][])("maps generation_mode %j → %j", (mode, expected) => {
    expect(inferTrackType(mode)).toBe(expected)
  })

  it("defaults null/undefined/unknown modes to ai", () => {
    expect(inferTrackType(null)).toBe("ai")
    expect(inferTrackType(undefined)).toBe("ai")
    expect(inferTrackType("some-future-mode")).toBe("ai")
  })
})

describe("placementPlaybackRate", () => {
  it("scales a loop-track clip's rate to the project tempo", () => {
    // 90 BPM loop in a 120 BPM project plays at 4/3 speed.
    expect(placementPlaybackRate(90, "loop", 120)).toBeCloseTo(4 / 3)
    expect(placementPlaybackRate(120, "loop", 120)).toBe(1)
  })

  it("returns 1 on non-loop tracks regardless of BPM", () => {
    expect(placementPlaybackRate(90, "ai", 120)).toBe(1)
    expect(placementPlaybackRate(90, "audio", 120)).toBe(1)
    expect(placementPlaybackRate(90, "vocal", 120)).toBe(1)
  })

  it("returns 1 when the clip has no usable BPM", () => {
    expect(placementPlaybackRate(null, "loop", 120)).toBe(1)
    expect(placementPlaybackRate(undefined, "loop", 120)).toBe(1)
    expect(placementPlaybackRate(0, "loop", 120)).toBe(1)
    expect(placementPlaybackRate(-4, "loop", 120)).toBe(1)
  })

  it("exports the project tempo bounds mirroring the backend", () => {
    expect(BPM_MIN).toBe(60)
    expect(BPM_MAX).toBe(180)
  })
})
