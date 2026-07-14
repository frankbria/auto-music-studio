import { describe, expect, it } from "vitest"

import {
  linearToDbfs,
  METER_FLOOR_DB,
  peakDbfs,
  PEAK_HOLD_MS,
  rmsDbfs,
  stepPeakHold,
} from "@/lib/metering"

describe("linearToDbfs", () => {
  it("maps full-scale amplitude (1.0) to 0 dBFS", () => {
    expect(linearToDbfs(1)).toBeCloseTo(0)
  })

  it("maps half amplitude to about -6 dBFS", () => {
    expect(linearToDbfs(0.5)).toBeCloseTo(-6.02, 1)
  })

  it("maps silence (0) to the meter floor, not -Infinity", () => {
    expect(linearToDbfs(0)).toBe(METER_FLOOR_DB)
  })

  it("treats negative amplitudes the same as their absolute value", () => {
    expect(linearToDbfs(-1)).toBeCloseTo(0)
  })

  it("clamps values quieter than the floor to the floor", () => {
    expect(linearToDbfs(0.0000001)).toBe(METER_FLOOR_DB)
  })
})

describe("peakDbfs", () => {
  it("returns the loudest absolute sample in the window, in dBFS", () => {
    const samples = new Float32Array([0.1, -0.9, 0.2, 0.05])
    expect(peakDbfs(samples)).toBeCloseTo(linearToDbfs(0.9))
  })

  it("returns the meter floor for an empty window", () => {
    expect(peakDbfs(new Float32Array())).toBe(METER_FLOOR_DB)
  })

  it("returns 0 dBFS for a full-scale sample", () => {
    expect(peakDbfs(new Float32Array([1, -1, 0]))).toBeCloseTo(0)
  })
})

describe("rmsDbfs", () => {
  it("computes the RMS of the window in dBFS", () => {
    // RMS of a constant 0.5 amplitude is 0.5 itself.
    const samples = new Float32Array(100).fill(0.5)
    expect(rmsDbfs(samples)).toBeCloseTo(linearToDbfs(0.5))
  })

  it("returns the meter floor for an empty window", () => {
    expect(rmsDbfs(new Float32Array())).toBe(METER_FLOOR_DB)
  })

  it("is quieter than or equal to the peak for the same window", () => {
    const samples = new Float32Array([1, 0, -1, 0])
    expect(rmsDbfs(samples)).toBeLessThanOrEqual(peakDbfs(samples))
  })
})

describe("stepPeakHold", () => {
  it("adopts a new peak immediately when there is no prior hold", () => {
    const next = stepPeakHold(null, -10, 1000)
    expect(next).toEqual({ db: -10, heldAtMs: 1000 })
  })

  it("adopts a louder incoming peak immediately, resetting the hold clock", () => {
    const prev = { db: -20, heldAtMs: 1000 }
    const next = stepPeakHold(prev, -5, 1200)
    expect(next).toEqual({ db: -5, heldAtMs: 1200 })
  })

  it("holds a quieter reading steady until the hold window elapses", () => {
    const prev = { db: -5, heldAtMs: 1000 }
    const next = stepPeakHold(prev, -20, 1000 + PEAK_HOLD_MS - 1)
    expect(next).toEqual(prev)
  })

  it("decays the held peak once the hold window has elapsed", () => {
    const prev = { db: -5, heldAtMs: 1000 }
    const now = 1000 + PEAK_HOLD_MS + 500 // 0.5s past the hold window
    const next = stepPeakHold(prev, -40, now)
    expect(next.db).toBeLessThan(-5)
    expect(next.db).toBeGreaterThan(-40)
    expect(next.heldAtMs).toBe(1000) // decay origin unchanged mid-decay
  })

  it("settles back onto the incoming peak once decay reaches it", () => {
    const prev = { db: -5, heldAtMs: 1000 }
    const now = 1000 + PEAK_HOLD_MS + 100_000 // long past full decay
    const next = stepPeakHold(prev, -40, now)
    expect(next).toEqual({ db: -40, heldAtMs: now })
  })
})
