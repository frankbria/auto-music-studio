/**
 * Master bus state (US-19.5): a 3-band EQ, compressor, limiter, and post
 * fader sitting between the track sum and the destination. Mirrors the
 * per-track fader's dB-range convention (see track-audio.ts) — reused
 * directly for master volume rather than duplicated.
 */

export {
  VOLUME_DB_MAX as MASTER_VOLUME_DB_MAX,
  VOLUME_DB_MIN as MASTER_VOLUME_DB_MIN,
} from "@/lib/track-audio"

export const EQ_GAIN_DB_MIN = -15
export const EQ_GAIN_DB_MAX = 15

export const EQ_LOW_SHELF_FREQ_MIN = 20
export const EQ_LOW_SHELF_FREQ_MAX = 500

export const EQ_MID_FREQ_MIN = 200
export const EQ_MID_FREQ_MAX = 5000

export const EQ_HIGH_SHELF_FREQ_MIN = 2000
export const EQ_HIGH_SHELF_FREQ_MAX = 16000

export const EQ_Q_MIN = 0.1
export const EQ_Q_MAX = 10

export const COMPRESSOR_THRESHOLD_DB_MIN = -60
export const COMPRESSOR_THRESHOLD_DB_MAX = 0

export const COMPRESSOR_RATIO_MIN = 1
export const COMPRESSOR_RATIO_MAX = 20

export const COMPRESSOR_ATTACK_SEC_MIN = 0.001
export const COMPRESSOR_ATTACK_SEC_MAX = 1

export const COMPRESSOR_RELEASE_SEC_MIN = 0.01
export const COMPRESSOR_RELEASE_SEC_MAX = 1

export const LIMITER_CEILING_DB_MIN = -6
export const LIMITER_CEILING_DB_MAX = 0

/** Fixed, non-adjustable limiter params (a high-ratio DynamicsCompressorNode
 * standing in for a true limiter — see the plan's "no AudioWorklet" note). */
export const LIMITER_RATIO = 20
export const LIMITER_ATTACK_SEC = 0.001
// Faster than the Web Audio default (0.25s) so the ceiling lets go quickly
// instead of audibly pumping on transient-heavy material.
export const LIMITER_RELEASE_SEC = 0.05

export type MasterBusState = {
  masterVolumeDb: number
  eq: {
    lowShelf: { freqHz: number; gainDb: number }
    midPeak: { freqHz: number; gainDb: number; q: number }
    highShelf: { freqHz: number; gainDb: number }
  }
  compressor: {
    thresholdDb: number
    ratio: number
    attackSec: number
    releaseSec: number
  }
  limiterCeilingDb: number
}

export const DEFAULT_MASTER_BUS: MasterBusState = {
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
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
