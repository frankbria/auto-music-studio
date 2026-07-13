// Real audio peak extraction for the waveform editor (US-18.1). This is the
// truthful counterpart to the seeded bar-chart in lib/waveform.ts: instead of
// hashing the clip id, it decodes the clip's actual audio bytes and reads
// amplitude peaks straight from the samples. The decode needs the browser
// AudioContext; the bucketing math is pure so it stays unit-testable.
//
// ponytail: the decoded mono track is held in memory at full resolution
// (~44.1k floats/sec → ~32 MB for a 3-min song). Fine for an editor opened one
// clip at a time; downsample to a capped peak buffer if multi-clip memory ever
// bites.

import { getAudioContextCtor } from "./audio-context"

export type ClipAudio = {
  /** Mono mixdown of the decoded audio, one sample per element in ~[-1, 1]. */
  mono: Float32Array
  sampleRate: number
  /** Duration in seconds. */
  duration: number
}

/** Average every channel into a single mono track of `length` samples. */
export function mixToMono(
  channels: Float32Array[],
  length: number
): Float32Array {
  const mono = new Float32Array(length)
  if (channels.length === 0) return mono
  for (const ch of channels) {
    const n = Math.min(length, ch.length)
    for (let i = 0; i < n; i++) mono[i] += ch[i]
  }
  for (let i = 0; i < length; i++) mono[i] /= channels.length
  return mono
}

/**
 * Peak amplitude (max |sample|) per output column across the sample window
 * [startSample, endSample). Reads raw samples, so it is exact at any zoom and
 * only touches the visible slice. Returns `columns` values in [0, 1].
 */
export function columnPeaks(
  mono: Float32Array,
  startSample: number,
  endSample: number,
  columns: number
): Float32Array {
  const out = new Float32Array(Math.max(0, columns))
  if (columns <= 0) return out
  const start = Math.max(0, Math.min(Math.floor(startSample), mono.length))
  const end = Math.max(start, Math.min(Math.ceil(endSample), mono.length))
  const span = end - start
  if (span <= 0) return out
  const per = span / columns
  for (let c = 0; c < columns; c++) {
    const s = start + Math.floor(c * per)
    const e = Math.min(end, start + Math.floor((c + 1) * per))
    let peak = 0
    for (let i = s; i < e; i++) {
      const a = Math.abs(mono[i])
      if (a > peak) peak = a
    }
    out[c] = peak > 1 ? 1 : peak
  }
  return out
}

/**
 * Fetch the clip's audio through the authed same-origin proxy
 * (/api/clips/{id}/audio, which forwards the Bearer token) and decode it to
 * peak data. Throws on fetch failure or an undecodable body so the caller can
 * show an error state.
 */
export async function decodeClipAudio(
  clipId: string,
  token: string,
  signal?: AbortSignal
): Promise<ClipAudio> {
  const res = await fetch(`/api/clips/${encodeURIComponent(clipId)}/audio`, {
    headers: { authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`audio fetch failed: ${res.status}`)
  const bytes = await res.arrayBuffer()

  const Ctx = getAudioContextCtor()
  if (!Ctx) throw new Error("Web Audio API unavailable")
  const ctx = new Ctx()
  try {
    const buffer = await ctx.decodeAudioData(bytes)
    const channels: Float32Array[] = []
    for (let c = 0; c < buffer.numberOfChannels; c++) {
      channels.push(buffer.getChannelData(c))
    }
    return {
      mono: mixToMono(channels, buffer.length),
      sampleRate: buffer.sampleRate,
      duration: buffer.duration,
    }
  } finally {
    void ctx.close()
  }
}
