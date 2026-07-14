import { describe, expect, it } from "vitest"

import {
  clamp,
  DEFAULT_MASTER_BUS,
  EQ_GAIN_DB_MAX,
  EQ_GAIN_DB_MIN,
  EQ_HIGH_SHELF_FREQ_MAX,
  EQ_HIGH_SHELF_FREQ_MIN,
  EQ_LOW_SHELF_FREQ_MAX,
  EQ_LOW_SHELF_FREQ_MIN,
  EQ_MID_FREQ_MAX,
  EQ_MID_FREQ_MIN,
  EQ_Q_MAX,
  EQ_Q_MIN,
  COMPRESSOR_ATTACK_SEC_MAX,
  COMPRESSOR_ATTACK_SEC_MIN,
  COMPRESSOR_RATIO_MAX,
  COMPRESSOR_RATIO_MIN,
  COMPRESSOR_RELEASE_SEC_MAX,
  COMPRESSOR_RELEASE_SEC_MIN,
  COMPRESSOR_THRESHOLD_DB_MAX,
  COMPRESSOR_THRESHOLD_DB_MIN,
  LIMITER_ATTACK_SEC,
  LIMITER_CEILING_DB_MAX,
  LIMITER_CEILING_DB_MIN,
  LIMITER_RATIO,
  MASTER_VOLUME_DB_MAX,
  MASTER_VOLUME_DB_MIN,
} from "@/lib/master-bus"

describe("master-bus defaults", () => {
  it("matches the plan's specified default values", () => {
    expect(DEFAULT_MASTER_BUS).toEqual({
      masterVolumeDb: 0,
      eq: {
        lowShelf: { freqHz: 100, gainDb: 0 },
        midPeak: { freqHz: 1000, gainDb: 0, q: 1 },
        highShelf: { freqHz: 8000, gainDb: 0 },
      },
      compressor: {
        thresholdDb: -20,
        ratio: 3,
        attackSec: 0.01,
        releaseSec: 0.1,
      },
      limiterCeilingDb: -0.3,
    })
  })

  it("reuses the track fader's volume range for master volume", () => {
    expect(MASTER_VOLUME_DB_MIN).toBe(-60)
    expect(MASTER_VOLUME_DB_MAX).toBe(6)
  })

  it("fixes the limiter ratio and attack as constants, not adjustable ranges", () => {
    expect(LIMITER_RATIO).toBe(20)
    expect(LIMITER_ATTACK_SEC).toBeCloseTo(0.001)
  })
})

describe("clamp", () => {
  it("passes values within range through unchanged", () => {
    expect(clamp(5, 0, 10)) .toBe(5)
  })
  it("clamps below the minimum", () => {
    expect(clamp(-5, 0, 10)).toBe(0)
  })
  it("clamps above the maximum", () => {
    expect(clamp(15, 0, 10)).toBe(10)
  })
})

describe("master-bus param ranges", () => {
  it("defines sane EQ gain bounds", () => {
    expect(EQ_GAIN_DB_MIN).toBeLessThan(0)
    expect(EQ_GAIN_DB_MAX).toBeGreaterThan(0)
  })

  it("defines non-overlapping-order frequency bounds per band", () => {
    expect(EQ_LOW_SHELF_FREQ_MIN).toBeLessThan(EQ_LOW_SHELF_FREQ_MAX)
    expect(EQ_MID_FREQ_MIN).toBeLessThan(EQ_MID_FREQ_MAX)
    expect(EQ_HIGH_SHELF_FREQ_MIN).toBeLessThan(EQ_HIGH_SHELF_FREQ_MAX)
    expect(EQ_Q_MIN).toBeLessThan(EQ_Q_MAX)
  })

  it("defines compressor param bounds", () => {
    expect(COMPRESSOR_THRESHOLD_DB_MIN).toBeLessThan(COMPRESSOR_THRESHOLD_DB_MAX)
    expect(COMPRESSOR_RATIO_MIN).toBeLessThan(COMPRESSOR_RATIO_MAX)
    expect(COMPRESSOR_ATTACK_SEC_MIN).toBeLessThan(COMPRESSOR_ATTACK_SEC_MAX)
    expect(COMPRESSOR_RELEASE_SEC_MIN).toBeLessThan(COMPRESSOR_RELEASE_SEC_MAX)
  })

  it("defines limiter ceiling bounds at or below 0dB", () => {
    expect(LIMITER_CEILING_DB_MIN).toBeLessThan(LIMITER_CEILING_DB_MAX)
    expect(LIMITER_CEILING_DB_MAX).toBeLessThanOrEqual(0)
  })
})
