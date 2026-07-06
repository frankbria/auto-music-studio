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
