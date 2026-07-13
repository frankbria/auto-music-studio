import { describe, expect, it } from "vitest"

import {
  BASE_PX_PER_SEC,
  MAX_ZOOM,
  MIN_TIMELINE_SEC,
  MIN_ZOOM,
  clampZoom,
  computePlaybackSchedule,
  secToX,
  snapSec,
  snapStepSec,
  timelineDurationSec,
  timelineTicks,
  xToSec,
  zoomToPxPerSec,
  type Placement,
  type Viewport,
} from "./timeline"

describe("clampZoom", () => {
  it("passes through an in-range zoom", () => {
    expect(clampZoom(1)).toBe(1)
  })
  it("floors at MIN_ZOOM", () => {
    expect(clampZoom(0.01)).toBe(MIN_ZOOM)
  })
  it("ceils at MAX_ZOOM", () => {
    expect(clampZoom(100)).toBe(MAX_ZOOM)
  })
})

describe("zoomToPxPerSec", () => {
  it("scales BASE_PX_PER_SEC by the clamped zoom", () => {
    expect(zoomToPxPerSec(1)).toBe(BASE_PX_PER_SEC)
    expect(zoomToPxPerSec(2)).toBe(BASE_PX_PER_SEC * 2)
  })
  it("clamps zoom before scaling", () => {
    expect(zoomToPxPerSec(0.01)).toBe(BASE_PX_PER_SEC * MIN_ZOOM)
    expect(zoomToPxPerSec(100)).toBe(BASE_PX_PER_SEC * MAX_ZOOM)
  })
})

describe("secToX / xToSec are inverses (re-exported viewport math)", () => {
  const vp: Viewport = { pxPerSec: 25, scrollSec: 4 }
  it("round-trips a time through pixels", () => {
    expect(xToSec(secToX(9.3, vp), vp)).toBeCloseTo(9.3)
  })
})

describe("timelineTicks mm:ss mode", () => {
  it("labels ticks as m:ss", () => {
    const vp: Viewport = { pxPerSec: 10, scrollSec: 0 }
    const ticks = timelineTicks(vp, 600, 60, "mm-ss")
    expect(ticks.map((t) => t.label)).toEqual([
      "0:00",
      "0:10",
      "0:20",
      "0:30",
      "0:40",
      "0:50",
      "1:00",
    ])
  })
})

describe("timelineTicks bars-beats mode", () => {
  it("labels ticks as bar.beat at 120 BPM 4/4", () => {
    // 120 BPM -> 0.5s/beat, 2s/bar. At 100px/sec a bar (2s) is 200px apart,
    // comfortably above the 80px target, so ticks land on bar boundaries.
    const vp: Viewport = { pxPerSec: 100, scrollSec: 0 }
    const ticks = timelineTicks(vp, 600, 6, "bars-beats")
    expect(ticks.map((t) => t.label)).toEqual(["1.1", "2.1", "3.1", "4.1"])
    expect(ticks.map((t) => t.sec)).toEqual([0, 2, 4, 6])
  })

  it("falls back to coarser bar steps when zoomed out", () => {
    // Very zoomed out: 1px/sec -> target ~80s -> 80s/2s-per-bar = 40 beats
    // needed, ladder should pick a multi-bar step, never sub-beat.
    const vp: Viewport = { pxPerSec: 1, scrollSec: 0 }
    const ticks = timelineTicks(vp, 600, 200, "bars-beats")
    expect(ticks.length).toBeGreaterThan(0)
    // Every tick should land on a bar boundary (2s multiples at 120 BPM 4/4).
    for (const t of ticks) expect(t.sec % 2).toBe(0)
  })
})

describe("timelineDurationSec", () => {
  it("floors at MIN_TIMELINE_SEC when there are no placements", () => {
    expect(timelineDurationSec([])).toBe(MIN_TIMELINE_SEC)
  })

  it("extends past the floor to fit the furthest clip, plus padding", () => {
    const placements: Placement[] = [
      { id: "p1", clipId: "c1", startSec: 0, title: "a", durationSec: 4 },
      {
        id: "p2",
        clipId: "c2",
        startSec: MIN_TIMELINE_SEC,
        title: "b",
        durationSec: 30,
      },
    ]
    const duration = timelineDurationSec(placements)
    expect(duration).toBeGreaterThan(MIN_TIMELINE_SEC + 30)
  })

  it("treats a null duration as zero-length for the extent calculation", () => {
    const placements: Placement[] = [
      { id: "p1", clipId: "c1", startSec: 5, title: "a", durationSec: null },
    ]
    expect(timelineDurationSec(placements)).toBe(MIN_TIMELINE_SEC)
  })
})

describe("computePlaybackSchedule", () => {
  const placements: Placement[] = [
    { id: "p1", clipId: "c1", startSec: 0, title: "a", durationSec: 4 },
    { id: "p2", clipId: "c2", startSec: 4, title: "b", durationSec: 4 },
    { id: "p3", clipId: "c3", startSec: 10, title: "c", durationSec: 2 },
  ]

  it("schedules a future placement at its absolute offset from now", () => {
    const schedule = computePlaybackSchedule(placements, 0, 100)
    expect(schedule).toEqual([
      { clipId: "c1", when: 100, offset: 0, playbackRate: 1 },
      { clipId: "c2", when: 104, offset: 0, playbackRate: 1 },
      { clipId: "c3", when: 110, offset: 0, playbackRate: 1 },
    ])
  })

  it("starts an in-progress placement immediately with a nonzero offset", () => {
    // Playhead at 6s: c1 already ended (0-4), c2 (4-8) is mid-playback.
    const schedule = computePlaybackSchedule(placements, 6, 50)
    expect(schedule).toEqual([
      { clipId: "c2", when: 50, offset: 2, playbackRate: 1 },
      { clipId: "c3", when: 54, offset: 0, playbackRate: 1 },
    ])
  })

  it("excludes placements that have already finished", () => {
    const schedule = computePlaybackSchedule(placements, 12, 0)
    expect(schedule).toEqual([])
  })

  it("returns results sorted by scheduled time", () => {
    const unordered: Placement[] = [
      { id: "p2", clipId: "c2", startSec: 4, title: "b", durationSec: 4 },
      { id: "p1", clipId: "c1", startSec: 0, title: "a", durationSec: 4 },
    ]
    const schedule = computePlaybackSchedule(unordered, 0, 0)
    expect(schedule.map((s) => s.clipId)).toEqual(["c1", "c2"])
  })

  it("treats a null duration as playing through to the end — never pre-emptively excluded", () => {
    const unknownDuration: Placement[] = [
      { id: "p1", clipId: "c1", startSec: 0, title: "a", durationSec: null },
    ]
    // Even at a playhead far past any "reasonable" clip length, a null
    // duration must not be treated as already-finished.
    const schedule = computePlaybackSchedule(unknownDuration, 10_000, 0)
    expect(schedule).toEqual([
      { clipId: "c1", when: 0, offset: 10_000, playbackRate: 1 },
    ])
  })
})

describe("computePlaybackSchedule with per-placement playback rates (US-19.2)", () => {
  // A 90 BPM loop in a 120 BPM project plays at 4/3 speed: its 8s of audio
  // occupy 6s of timeline.
  const RATE = 4 / 3
  const loop: Placement = {
    id: "p1",
    clipId: "c1",
    startSec: 0,
    title: "loop",
    durationSec: 8,
  }
  const rateFor = () => RATE

  it("carries the rate onto the scheduled clip", () => {
    const schedule = computePlaybackSchedule([loop], 0, 100, rateFor)
    expect(schedule).toEqual([
      { clipId: "c1", when: 100, offset: 0, playbackRate: RATE },
    ])
  })

  it("scales the buffer offset for an in-progress sped-up clip", () => {
    // Playhead 3s into the timeline = 3 * RATE = 4s into the buffer.
    const schedule = computePlaybackSchedule([loop], 3, 50, rateFor)
    expect(schedule).toHaveLength(1)
    expect(schedule[0].when).toBe(50)
    expect(schedule[0].offset).toBeCloseTo(4)
  })

  it("uses the rate-compressed duration to decide when a clip has finished", () => {
    // 8s of audio at 4/3 speed ends at 6s on the timeline: playhead 7s → done.
    expect(computePlaybackSchedule([loop], 7, 0, rateFor)).toEqual([])
    // But at 1x it would still be playing at 7s.
    expect(computePlaybackSchedule([loop], 7, 0)).toHaveLength(1)
  })
})

describe("snap-to-grid math (US-19.3)", () => {
  // At 120 BPM a beat is 0.5s, a 4/4 bar is 2s.
  it("snapStepSec maps each resolution to its beat fraction", () => {
    expect(snapStepSec("1bar", 120)).toBeCloseTo(2)
    expect(snapStepSec("1beat", 120)).toBeCloseTo(0.5)
    expect(snapStepSec("1/2beat", 120)).toBeCloseTo(0.25)
    expect(snapStepSec("1/4beat", 120)).toBeCloseTo(0.125)
  })

  it("snapStepSec scales with tempo", () => {
    expect(snapStepSec("1beat", 60)).toBeCloseTo(1)
    expect(snapStepSec("1bar", 90)).toBeCloseTo((60 / 90) * 4)
  })

  it("snapSec rounds to the nearest grid line", () => {
    expect(snapSec(0.6, "1beat", 120)).toBeCloseTo(0.5)
    expect(snapSec(0.76, "1beat", 120)).toBeCloseTo(1)
    expect(snapSec(2.9, "1bar", 120)).toBeCloseTo(2)
    expect(snapSec(3.1, "1bar", 120)).toBeCloseTo(4)
  })

  it("snapSec is exact on a grid line and at zero", () => {
    expect(snapSec(2, "1bar", 120)).toBe(2)
    expect(snapSec(0, "1/4beat", 120)).toBe(0)
  })

  it("snapSec never returns a negative position", () => {
    expect(snapSec(-0.3, "1beat", 120)).toBe(0)
  })
})
