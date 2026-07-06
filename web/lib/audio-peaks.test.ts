import { describe, expect, it } from "vitest"

import { columnPeaks, mixToMono } from "./audio-peaks"

describe("mixToMono", () => {
  it("averages channels sample-by-sample", () => {
    const l = new Float32Array([1, 0, -1, 0.5])
    const r = new Float32Array([1, 1, 1, 0.5])
    expect(Array.from(mixToMono([l, r], 4))).toEqual([1, 0.5, 0, 0.5])
  })
  it("returns silence for no channels", () => {
    expect(Array.from(mixToMono([], 3))).toEqual([0, 0, 0])
  })
  it("passes a single channel through", () => {
    const m = new Float32Array([0.2, -0.4])
    const mono = mixToMono([m], 2)
    // Float32 storage → compare with tolerance, not exact equality.
    expect(mono[0]).toBeCloseTo(0.2)
    expect(mono[1]).toBeCloseTo(-0.4)
  })
})

describe("columnPeaks", () => {
  it("returns the max absolute amplitude per column", () => {
    // 8 samples, 2 columns → each column spans 4 samples.
    const mono = new Float32Array([0.1, -0.9, 0.2, 0.3, -0.4, 0.5, -0.2, 0.1])
    const peaks = columnPeaks(mono, 0, 8, 2)
    expect(peaks[0]).toBeCloseTo(0.9)
    expect(peaks[1]).toBeCloseTo(0.5)
  })
  it("only reads the requested sample window", () => {
    const mono = new Float32Array([1, 1, 0.25, 0.5, 1, 1])
    // Window [2,4) excludes the loud edges → peak is 0.5.
    const peaks = columnPeaks(mono, 2, 4, 1)
    expect(peaks[0]).toBe(0.5)
  })
  it("clamps peaks over 1", () => {
    const mono = new Float32Array([1.5, -2])
    expect(columnPeaks(mono, 0, 2, 1)[0]).toBe(1)
  })
  it("returns an empty array for zero columns", () => {
    expect(columnPeaks(new Float32Array([1]), 0, 1, 0).length).toBe(0)
  })
  it("survives out-of-range windows", () => {
    const mono = new Float32Array([0.3, 0.6])
    // end past the buffer clamps to the buffer length.
    expect(columnPeaks(mono, 0, 999, 1)[0]).toBeCloseTo(0.6)
    // start past the end → all-zero output, no crash.
    expect(Array.from(columnPeaks(mono, 50, 60, 2))).toEqual([0, 0])
  })
})
