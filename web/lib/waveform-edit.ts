// Pure audio-editing helpers for the waveform editor (US-18.2). The truthful
// counterpart to waveform-viewport.ts: instead of viewport math, this splices
// the decoded mono samples so cut / copy / paste / delete produce a *real*
// edited ClipAudio the existing canvas renders unchanged (no operation-stack
// replay, no separate duration model — duration is always mono.length /
// sampleRate). Kept free of React so the splice math is unit-testable.
//
// Non-destructive: every function returns a NEW ClipAudio; the caller keeps the
// original prop untouched and holds the edit in component state. Persisting the
// edits (and re-encoding audio for playback) is the save story, US-18.4 — the
// `operations` log below is the handoff seam.

import type { ClipAudio } from "@/lib/audio-peaks"

/** A time range on the clip, always stored start ≤ end. */
export type Region = { startSec: number; endSec: number }

/** A recorded edit — the user's intent, for the US-18.4 save handoff + tests. */
export type EditOperation =
  | { kind: "cut"; startSec: number; endSec: number }
  | { kind: "delete"; startSec: number; endSec: number }
  | { kind: "paste"; atSec: number; durationSec: number }
  // US-18.3 processing ops. These transform sample amplitudes in place (fade /
  // gain / silence / normalize keep the length; crossfade shortens it), unlike
  // the US-18.2 splice ops above which move samples around.
  | { kind: "fade-in"; startSec: number; endSec: number }
  | { kind: "fade-out"; startSec: number; endSec: number }
  | { kind: "silence"; startSec: number; endSec: number }
  | { kind: "gain"; startSec: number; endSec: number; gainDb: number }
  | { kind: "normalize"; startSec: number; endSec: number; targetDb: number }
  | { kind: "crossfade"; positionSec: number; durationSec: number }

/** Order two times into a Region with start ≤ end. */
export function normalizeRegion(a: number, b: number): Region {
  return a <= b ? { startSec: a, endSec: b } : { startSec: b, endSec: a }
}

/** Sample index for a time, clamped to [0, length]. */
export function secToSample(
  sec: number,
  sampleRate: number,
  length: number
): number {
  const s = Math.round(Math.max(0, sec) * sampleRate)
  return Math.min(length, Math.max(0, s))
}

/** Ordered, clamped [startSample, endSample) for a region. */
function regionSamples(
  audio: ClipAudio,
  startSec: number,
  endSec: number
): { startSample: number; endSample: number } {
  const r = normalizeRegion(startSec, endSec)
  const startSample = secToSample(r.startSec, audio.sampleRate, audio.mono.length)
  const endSample = secToSample(r.endSec, audio.sampleRate, audio.mono.length)
  return { startSample, endSample: Math.max(startSample, endSample) }
}

/** Copy the samples in [startSec, endSec) as a new array (for the clipboard). */
export function sliceRegion(
  audio: ClipAudio,
  startSec: number,
  endSec: number
): Float32Array {
  const { startSample, endSample } = regionSamples(audio, startSec, endSec)
  return audio.mono.slice(startSample, endSample)
}

/** Remove [startSec, endSec) and shift the tail left (cut / delete). */
export function removeRegion(
  audio: ClipAudio,
  startSec: number,
  endSec: number
): ClipAudio {
  const { startSample, endSample } = regionSamples(audio, startSec, endSec)
  const mono = new Float32Array(audio.mono.length - (endSample - startSample))
  mono.set(audio.mono.subarray(0, startSample), 0)
  mono.set(audio.mono.subarray(endSample), startSample)
  return { ...audio, mono, duration: mono.length / audio.sampleRate }
}

/** Insert `samples` at `atSec`, shifting the tail right (paste). */
export function insertRegion(
  audio: ClipAudio,
  atSec: number,
  samples: Float32Array
): ClipAudio {
  const at = secToSample(atSec, audio.sampleRate, audio.mono.length)
  const mono = new Float32Array(audio.mono.length + samples.length)
  mono.set(audio.mono.subarray(0, at), 0)
  mono.set(samples, at)
  mono.set(audio.mono.subarray(at), at + samples.length)
  return { ...audio, mono, duration: mono.length / audio.sampleRate }
}

// --- Processing ops (US-18.3) --------------------------------------------
// These keep the sample layout (same length + duration) except crossfade, which
// overlap-mixes two windows and so shrinks the clip. All are non-destructive and
// clamp to [-1, 1] so gain/normalize can't push a real signal past full scale.

/** Linear gain factor for a dB value (0 dB → 1, +6 dB → ~2, −∞ dB → 0). */
export function dbToGain(db: number): number {
  return 10 ** (db / 20)
}

const clampSample = (v: number) => (v > 1 ? 1 : v < -1 ? -1 : v)

/** Multiply [startSec, endSec) by a per-sample factor, clamped to [-1, 1]. */
function mapRegion(
  audio: ClipAudio,
  startSec: number,
  endSec: number,
  factorAt: (offset: number, span: number) => number
): ClipAudio {
  const { startSample, endSample } = regionSamples(audio, startSec, endSec)
  const span = endSample - startSample
  const mono = audio.mono.slice()
  for (let i = startSample; i < endSample; i++) {
    mono[i] = clampSample(mono[i] * factorAt(i - startSample, span))
  }
  return { ...audio, mono }
}

// Fades divide by (span - 1) so the ramp hits its endpoints exactly: fade-in
// reaches full scale on the region's last sample, fade-out reaches true silence
// there. A 1-sample region can't be ramped, so it's left unchanged.

/** Ramp the selection from silence to full volume (linear fade-in). */
export function applyFadeIn(
  audio: ClipAudio,
  startSec: number,
  endSec: number
): ClipAudio {
  return mapRegion(audio, startSec, endSec, (o, span) =>
    span > 1 ? o / (span - 1) : 1
  )
}

/** Ramp the selection from full volume to silence (linear fade-out). */
export function applyFadeOut(
  audio: ClipAudio,
  startSec: number,
  endSec: number
): ClipAudio {
  return mapRegion(audio, startSec, endSec, (o, span) =>
    span > 1 ? 1 - o / (span - 1) : 1
  )
}

/** Raise/lower the selection's volume by `gainDb` decibels. */
export function applyGain(
  audio: ClipAudio,
  startSec: number,
  endSec: number,
  gainDb: number
): ClipAudio {
  const g = dbToGain(gainDb)
  return mapRegion(audio, startSec, endSec, () => g)
}

/** Replace the selection with silence (zero samples), keeping the length. */
export function applySilence(
  audio: ClipAudio,
  startSec: number,
  endSec: number
): ClipAudio {
  return mapRegion(audio, startSec, endSec, () => 0)
}

/** Peak amplitude in [startSample, endSample). */
function regionPeak(mono: Float32Array, start: number, end: number): number {
  let peak = 0
  for (let i = start; i < end; i++) {
    const a = Math.abs(mono[i])
    if (a > peak) peak = a
  }
  return peak
}

/** Scale the selection so its loudest sample hits `targetDb` dBFS (peak
 *  normalize). No-op when the region is already silent. */
export function applyNormalize(
  audio: ClipAudio,
  startSec: number,
  endSec: number,
  targetDb = 0
): ClipAudio {
  const { startSample, endSample } = regionSamples(audio, startSec, endSec)
  const peak = regionPeak(audio.mono, startSample, endSample)
  if (peak === 0) return { ...audio, mono: audio.mono.slice() }
  const factor = dbToGain(targetDb) / peak
  return mapRegion(audio, startSec, endSec, () => factor)
}

/** Equal-power crossfade at `positionSec`: overlap-mix the `durationSec` before
 *  the position (fading out) with the `durationSec` after (fading in) so a hard
 *  cut becomes a smooth transition. Shortens the clip by `durationSec`. The
 *  window is clamped to what fits; a zero/degenerate window is a no-op copy. */
export function applyCrossfade(
  audio: ClipAudio,
  positionSec: number,
  durationSec: number
): ClipAudio {
  const { mono: src, sampleRate } = audio
  const pos = secToSample(positionSec, sampleRate, src.length)
  const want = Math.max(0, Math.round(durationSec * sampleRate))
  const d = Math.min(want, pos, src.length - pos) // fit both windows
  if (d <= 0) return { ...audio, mono: src.slice() }

  const mono = new Float32Array(src.length - d)
  mono.set(src.subarray(0, pos - d), 0)
  for (let k = 0; k < d; k++) {
    const t = (k / d) * (Math.PI / 2) // 0 → π/2
    const out = Math.cos(t) // 1 → 0 over the pre-window tail
    const inn = Math.sin(t) // 0 → 1 over the post-window head
    mono[pos - d + k] = clampSample(src[pos - d + k] * out + src[pos + k] * inn)
  }
  mono.set(src.subarray(pos + d), pos)
  return { ...audio, mono, duration: mono.length / sampleRate }
}
