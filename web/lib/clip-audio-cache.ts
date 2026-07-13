// Studio waveform-thumbnail cache (US-19.1). Decodes a clip's audio once and
// keeps both the raw AudioBuffer (the studio playback engine, US-19.1 step 7,
// schedules AudioBufferSourceNodes straight off it — no re-decode needed) and a
// small fixed-resolution peak downsample for ClipBlock's canvas thumbnail.
//
// Deliberately doesn't call lib/audio-peaks.ts's decodeClipAudio(): that helper
// closes its AudioContext and only returns the mixed-down mono track, discarding
// the AudioBuffer playback needs. This reuses its pure `mixToMono`/`columnPeaks`
// helpers but keeps its own fetch+decode so the buffer survives.

import { getAudioContextCtor } from "./audio-context"
import { columnPeaks, mixToMono } from "./audio-peaks"

export type CachedClipAudio = {
  buffer: AudioBuffer
  /** Fixed-resolution amplitude downsample for a thumbnail, in [0, 1]. */
  peaks: Float32Array
  duration: number
}

// A thumbnail is small on screen at any zoom, so a fixed low-res downsample
// (unlike the waveform editor's zoom-dependent re-bucketing) is enough detail.
const THUMBNAIL_COLUMNS = 200

const cache = new Map<string, Promise<CachedClipAudio>>()

// One shared context for every decode: browsers cap concurrent realtime
// AudioContexts (~6 in Chrome, fewer in Safari), so a context-per-decode
// would start failing once enough clips land on the timeline at once.
// decodeAudioData works fine on a suspended context, so this never needs a
// user-gesture resume. The instanceof check re-creates the context if the
// AudioContext constructor itself changes (only happens in tests, which stub
// a fresh fake class per test).
let decodeCtx: AudioContext | null = null

function getDecodeContext(): AudioContext {
  const Ctx = getAudioContextCtor()
  if (!Ctx) throw new Error("Web Audio API unavailable")
  if (!(decodeCtx instanceof Ctx)) decodeCtx = new Ctx()
  return decodeCtx
}

async function decode(
  clipId: string,
  token: string,
  signal?: AbortSignal
): Promise<CachedClipAudio> {
  const res = await fetch(`/api/clips/${encodeURIComponent(clipId)}/audio`, {
    headers: { authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`audio fetch failed: ${res.status}`)
  const bytes = await res.arrayBuffer()

  const buffer = await getDecodeContext().decodeAudioData(bytes)
  const channels: Float32Array[] = []
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    channels.push(buffer.getChannelData(c))
  }
  const mono = mixToMono(channels, buffer.length)
  const peaks = columnPeaks(mono, 0, mono.length, THUMBNAIL_COLUMNS)
  return { buffer, peaks, duration: buffer.duration }
}

/**
 * Fetch + decode + cache a clip's audio once; concurrent or repeat calls for
 * the same id share the in-flight/resolved promise. A failed decode is evicted
 * so a later call can retry instead of replaying the same rejection forever.
 */
export function getClipAudio(
  clipId: string,
  token: string,
  signal?: AbortSignal
): Promise<CachedClipAudio> {
  let entry = cache.get(clipId)
  if (!entry) {
    entry = decode(clipId, token, signal)
    cache.set(clipId, entry)
    entry.catch(() => cache.delete(clipId))
  }
  return entry
}
