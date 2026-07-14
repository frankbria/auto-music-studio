/**
 * Pure metering math for the StereoMeter (US-19.5): peak/RMS in dBFS from a
 * time-domain sample window, plus a peak-hold decay step. Kept side-effect
 * free so the rAF loop that drives the meter can be tested without a real
 * AnalyserNode.
 */

/** Floor for the meter display — quieter than this reads as silence rather
 * than -Infinity, matching the [-48, 0] tick range the meter draws. */
export const METER_FLOOR_DB = -60

export function linearToDbfs(amplitude: number): number {
  const abs = Math.abs(amplitude)
  if (abs <= 0) return METER_FLOOR_DB
  return Math.max(METER_FLOOR_DB, 20 * Math.log10(abs))
}

export function peakDbfs(samples: Float32Array): number {
  let peak = 0
  for (let i = 0; i < samples.length; i++) {
    const abs = Math.abs(samples[i])
    if (abs > peak) peak = abs
  }
  return linearToDbfs(peak)
}

export function rmsDbfs(samples: Float32Array): number {
  if (samples.length === 0) return METER_FLOOR_DB
  let sumSquares = 0
  for (let i = 0; i < samples.length; i++) {
    sumSquares += samples[i] * samples[i]
  }
  return linearToDbfs(Math.sqrt(sumSquares / samples.length))
}

/** How long a peak-hold marker stays pinned before it starts decaying. */
export const PEAK_HOLD_MS = 1500
/** Decay rate once the hold window elapses. */
export const PEAK_DECAY_DB_PER_SEC = 20

export type PeakHoldState = { db: number; heldAtMs: number }

/** Advances a peak-hold marker by one meter frame. A louder incoming peak is
 * adopted immediately (and restarts the hold clock); a quieter one is held
 * steady for PEAK_HOLD_MS, then decays at a fixed rate until the incoming
 * peak catches up. */
export function stepPeakHold(
  prev: PeakHoldState | null,
  incomingDb: number,
  nowMs: number
): PeakHoldState {
  if (!prev || incomingDb >= prev.db) {
    return { db: incomingDb, heldAtMs: nowMs }
  }
  const elapsed = nowMs - prev.heldAtMs
  if (elapsed <= PEAK_HOLD_MS) return prev
  const decayed =
    prev.db - (PEAK_DECAY_DB_PER_SEC * (elapsed - PEAK_HOLD_MS)) / 1000
  if (decayed <= incomingDb) return { db: incomingDb, heldAtMs: nowMs }
  return { db: decayed, heldAtMs: prev.heldAtMs }
}
