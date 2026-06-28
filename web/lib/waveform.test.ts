import { describe, expect, it } from "vitest"

import { WAVEFORM_BARS, barHeights } from "@/lib/waveform"

describe("barHeights", () => {
  it("returns WAVEFORM_BARS heights by default", () => {
    expect(barHeights("c1")).toHaveLength(WAVEFORM_BARS)
  })

  it("is deterministic for a given seed", () => {
    expect(barHeights("c1")).toEqual(barHeights("c1"))
  })

  it("varies by seed", () => {
    expect(barHeights("c1")).not.toEqual(barHeights("c2"))
  })

  it("keeps every height within the ~0.25..0.96 band", () => {
    for (const h of barHeights("some-clip-id")) {
      expect(h).toBeGreaterThanOrEqual(0.25)
      expect(h).toBeLessThanOrEqual(0.965)
    }
  })
})
