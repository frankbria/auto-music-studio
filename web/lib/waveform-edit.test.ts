import { describe, expect, it } from "vitest"

import type { ClipAudio } from "@/lib/audio-peaks"
import {
  applyCrossfade,
  applyFadeIn,
  applyFadeOut,
  applyGain,
  applyNormalize,
  applySilence,
  dbToGain,
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

// A clip with explicit fractional samples (real audio lives in [-1, 1]); 10Hz so
// 0.1s === 1 sample. For the amplitude ops, where the ramp's 0..9 values would
// all clamp to 1.
function clip(samples: number[]): ClipAudio {
  return {
    mono: Float32Array.from(samples),
    sampleRate: 10,
    duration: samples.length / 10,
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
    const region = sliceRegion(src, 0.3, 0.6) // [3,4,5]
    const cut = removeRegion(src, 0.3, 0.6) // [0,1,2,6,7,8,9]
    const pasted = insertRegion(cut, cut.duration, region) // append at new end
    expect([...pasted.mono]).toEqual([0, 1, 2, 6, 7, 8, 9, 3, 4, 5])
  })
})

// --- Processing ops (US-18.3) --------------------------------------------

const close = (out: ClipAudio, expected: number[]) => {
  expect(out.mono.length).toBe(expected.length)
  expected.forEach((v, i) => expect(out.mono[i]).toBeCloseTo(v, 5))
}

describe("dbToGain", () => {
  it("maps dB to a linear factor", () => {
    expect(dbToGain(0)).toBeCloseTo(1)
    expect(dbToGain(6.0206)).toBeCloseTo(2) // +6 dB ≈ ×2
    expect(dbToGain(-6.0206)).toBeCloseTo(0.5)
  })
})

describe("applyFadeIn", () => {
  it("ramps the region silence → full, hitting both endpoints exactly", () => {
    const out = applyFadeIn(clip([1, 1, 1, 1]), 0, 0.4)
    close(out, [0, 1 / 3, 2 / 3, 1])
    expect(out.duration).toBeCloseTo(0.4) // length preserved
  })
})

describe("applyFadeOut", () => {
  it("ramps the region full → true silence at the end", () => {
    close(applyFadeOut(clip([1, 1, 1, 1]), 0, 0.4), [1, 2 / 3, 1 / 3, 0])
  })
})

describe("applyGain", () => {
  it("scales only the selected region", () => {
    // +6 dB ≈ ×2 over samples 1..2 (0.1s..0.3s).
    close(applyGain(clip([0.1, 0.2, 0.3, 0.4]), 0.1, 0.3, 6.0206), [
      0.1, 0.4, 0.6, 0.4,
    ])
  })
  it("clamps to [-1, 1] so a boost can't exceed full scale", () => {
    close(applyGain(clip([0.8, -0.8]), 0, 0.2, 6.0206), [1, -1])
  })
})

describe("applySilence", () => {
  it("zeroes the selection but keeps the length", () => {
    const out = applySilence(clip([1, 1, 1, 1]), 0.1, 0.3)
    close(out, [1, 0, 0, 1])
    expect(out.duration).toBeCloseTo(0.4)
  })
})

describe("applyNormalize", () => {
  it("scales the region so its peak reaches the target (0 dBFS)", () => {
    // peak 0.5 → ×2 to hit 1.0.
    close(applyNormalize(clip([0.1, 0.2, 0.5, 0.25]), 0, 0.4, 0), [
      0.2, 0.4, 1, 0.5,
    ])
  })
  it("is a no-op on a silent region (no divide-by-zero)", () => {
    close(applyNormalize(clip([0, 0, 0]), 0, 0.3, 0), [0, 0, 0])
  })
})

describe("applyCrossfade", () => {
  it("overlap-mixes the two windows and shortens by the duration", () => {
    // pos 0.3s (sample 3), dur 0.2s (2 samples): pre [0.2,0.2] fades out, post
    // [0.8,0.8] fades in; result loses 2 samples.
    const out = applyCrossfade(clip([0.2, 0.2, 0.2, 0.8, 0.8, 0.8]), 0.3, 0.2)
    expect(out.mono.length).toBe(4)
    expect(out.duration).toBeCloseTo(0.4)
    expect(out.mono[0]).toBeCloseTo(0.2) // untouched head
    expect(out.mono[1]).toBeCloseTo(0.2) // start of fade (all pre)
    expect(out.mono[2]).toBeCloseTo(0.7071, 3) // equal-power midpoint blend
    expect(out.mono[3]).toBeCloseTo(0.8) // untouched tail
  })
  it("clamps the window to the clip and no-ops when it can't fit", () => {
    // position at the very start: nothing before it, so a copy.
    const src = clip([0.5, 0.5, 0.5])
    const out = applyCrossfade(src, 0, 0.2)
    close(out, [0.5, 0.5, 0.5])
  })
})
