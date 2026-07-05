import { describe, expect, it } from "vitest"

import {
  MAX_PX_PER_SEC,
  chooseTickInterval,
  clampPxPerSec,
  clampScrollSec,
  fitPxPerSec,
  maxScrollSec,
  secToX,
  visibleTicks,
  xToSec,
  zoomAtX,
  type Viewport,
} from "./waveform-viewport"

describe("fitPxPerSec", () => {
  it("packs the whole clip into the given width", () => {
    // 60s clip, 600px wide → 10 px/sec fills the view exactly.
    expect(fitPxPerSec(60, 600)).toBe(10)
  })
  it("guards against zero/negative inputs", () => {
    expect(fitPxPerSec(0, 600)).toBe(1)
    expect(fitPxPerSec(60, 0)).toBe(1)
  })
})

describe("clampPxPerSec", () => {
  it("floors at the fit zoom (can't zoom out past full clip)", () => {
    expect(clampPxPerSec(1, 60, 600)).toBe(10) // fit is 10
  })
  it("ceils at MAX_PX_PER_SEC", () => {
    expect(clampPxPerSec(1e9, 60, 600)).toBe(MAX_PX_PER_SEC)
  })
  it("passes through an in-range zoom", () => {
    expect(clampPxPerSec(50, 60, 600)).toBe(50)
  })
})

describe("scroll clamping", () => {
  it("maxScrollSec keeps the right edge inside the clip", () => {
    // 60s clip at 20px/sec in a 600px view → 30s visible → can scroll 30s.
    expect(maxScrollSec(60, 20, 600)).toBe(30)
  })
  it("is zero when the whole clip fits", () => {
    expect(maxScrollSec(60, 10, 600)).toBe(0)
  })
  it("clampScrollSec pins to [0, max]", () => {
    expect(clampScrollSec(-5, 60, 20, 600)).toBe(0)
    expect(clampScrollSec(1000, 60, 20, 600)).toBe(30)
    expect(clampScrollSec(10, 60, 20, 600)).toBe(10)
  })
})

describe("secToX / xToSec are inverses", () => {
  const vp: Viewport = { pxPerSec: 25, scrollSec: 4 }
  it("round-trips a time through pixels", () => {
    expect(xToSec(secToX(9.3, vp), vp)).toBeCloseTo(9.3)
  })
  it("maps the left edge to x=0", () => {
    expect(secToX(4, vp)).toBe(0)
  })
})

describe("zoomAtX", () => {
  it("keeps the audio under the anchor pixel fixed while zooming in", () => {
    const vp: Viewport = { pxPerSec: 10, scrollSec: 0 }
    const anchorX = 300 // audio at 30s under the cursor (0 + 300/10)
    const before = xToSec(anchorX, vp)
    const next = zoomAtX(vp, 40, anchorX, 60, 600)
    expect(next.pxPerSec).toBe(40)
    // Same audio time still sits under the anchor pixel after the zoom.
    expect(xToSec(anchorX, next)).toBeCloseTo(before)
  })
  it("clamps zoom-out to the fit floor", () => {
    const vp: Viewport = { pxPerSec: 40, scrollSec: 10 }
    const next = zoomAtX(vp, 1, 300, 60, 600)
    expect(next.pxPerSec).toBe(10) // fit
    expect(next.scrollSec).toBe(0) // whole clip fits → no scroll
  })
})

describe("chooseTickInterval", () => {
  it("uses coarse ticks when zoomed out, fine ticks when zoomed in", () => {
    // Zoomed way out (2px/sec): target 40s → ladder picks 60s.
    expect(chooseTickInterval(2)).toBe(60)
    // Zoomed in (200px/sec): target 0.4s → ladder picks 0.5s.
    expect(chooseTickInterval(200)).toBe(0.5)
  })
  it("monotonically shrinks as zoom grows", () => {
    const a = chooseTickInterval(5)
    const b = chooseTickInterval(50)
    const c = chooseTickInterval(500)
    expect(a).toBeGreaterThanOrEqual(b)
    expect(b).toBeGreaterThanOrEqual(c)
  })
  it("falls back to the coarsest step at absurdly low zoom", () => {
    expect(chooseTickInterval(0.0001)).toBe(600)
  })
})

describe("visibleTicks", () => {
  it("emits ticks on interval boundaries within the window", () => {
    // 60s clip, fit zoom 10px/sec in 600px → interval 10s (target 8s → 10).
    const vp: Viewport = { pxPerSec: 10, scrollSec: 0 }
    const ticks = visibleTicks(vp, 600, 60)
    expect(ticks.map((t) => t.sec)).toEqual([0, 10, 20, 30, 40, 50, 60])
    expect(ticks[0].x).toBe(0)
    expect(ticks[1].x).toBe(100) // 10s * 10px/sec
  })
  it("starts at the first boundary at or after the scroll offset", () => {
    const vp: Viewport = { pxPerSec: 20, scrollSec: 12 }
    const ticks = visibleTicks(vp, 600, 120)
    // interval at 20px/sec: target 4s → 5s. First boundary ≥12 is 15.
    expect(ticks[0].sec).toBe(15)
    expect(ticks.every((t) => t.x >= 0 && t.x <= 600)).toBe(true)
  })
})
