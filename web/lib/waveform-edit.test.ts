import { describe, expect, it } from "vitest"

import type { ClipAudio } from "@/lib/audio-peaks"
import {
  insertRegion,
  normalizeRegion,
  removeRegion,
  secToSample,
  sliceRegion,
} from "@/lib/waveform-edit"

// 10 samples @ 10Hz = 1s clip; each sample's value is its index so splices are
// easy to read (mono[3] === 3). Everything is in seconds; 0.1s === 1 sample.
function ramp(): ClipAudio {
  return {
    mono: Float32Array.from({ length: 10 }, (_, i) => i),
    sampleRate: 10,
    duration: 1,
  }
}

describe("normalizeRegion", () => {
  it("orders the two times", () => {
    expect(normalizeRegion(0.8, 0.2)).toEqual({ startSec: 0.2, endSec: 0.8 })
    expect(normalizeRegion(0.2, 0.8)).toEqual({ startSec: 0.2, endSec: 0.8 })
  })
})

describe("secToSample", () => {
  it("rounds to the nearest sample and clamps to [0, length]", () => {
    expect(secToSample(0.3, 10, 10)).toBe(3)
    expect(secToSample(-1, 10, 10)).toBe(0)
    expect(secToSample(5, 10, 10)).toBe(10) // past the end → clamped
  })
})

describe("sliceRegion", () => {
  it("copies the samples in the range, order-independent", () => {
    expect([...sliceRegion(ramp(), 0.3, 0.6)]).toEqual([3, 4, 5])
    expect([...sliceRegion(ramp(), 0.6, 0.3)]).toEqual([3, 4, 5]) // reversed
  })
  it("does not mutate the source", () => {
    const a = ramp()
    sliceRegion(a, 0.3, 0.6)
    expect([...a.mono]).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
  })
})

describe("removeRegion", () => {
  it("removes the range, shifts the tail left, and shrinks the duration", () => {
    const out = removeRegion(ramp(), 0.3, 0.6)
    expect([...out.mono]).toEqual([0, 1, 2, 6, 7, 8, 9])
    expect(out.duration).toBeCloseTo(0.7)
  })
  it("removing an empty range is a no-op copy", () => {
    const out = removeRegion(ramp(), 0.4, 0.4)
    expect([...out.mono]).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
  })
})

describe("insertRegion", () => {
  it("splices samples in at the position and grows the duration", () => {
    const out = insertRegion(ramp(), 0.3, Float32Array.from([100, 101]))
    expect([...out.mono]).toEqual([0, 1, 2, 100, 101, 3, 4, 5, 6, 7, 8, 9])
    expect(out.duration).toBeCloseTo(1.2)
  })
  it("appends when pasting at the end", () => {
    const out = insertRegion(ramp(), 1, Float32Array.from([100]))
    expect([...out.mono]).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
  })
})

describe("cut → paste round-trip", () => {
  it("copy then remove then insert relocates the region intact", () => {
    const src = ramp()
    const clip = sliceRegion(src, 0.3, 0.6) // [3,4,5]
    const cut = removeRegion(src, 0.3, 0.6) // [0,1,2,6,7,8,9]
    const pasted = insertRegion(cut, cut.duration, clip) // append at new end
    expect([...pasted.mono]).toEqual([0, 1, 2, 6, 7, 8, 9, 3, 4, 5])
  })
})
