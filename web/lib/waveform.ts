// Deterministic pseudo-waveform bar heights, seeded by a stable string (a clip
// id). Shared by the player MiniWaveform and the song-detail SongWaveform so a
// clip looks the same wherever its waveform is drawn.
//
// ponytail: this is a seeded PRNG, not real audio peaks — it looks like a
// waveform and shows played/unplayed progress without downloading and decoding
// the file. Swap for AudioContext.decodeAudioData only if true amplitude
// rendering is ever required.

export const WAVEFORM_BARS = 64

/** `count` bar heights in 0.25..0.96, deterministic for a given `seed`. */
export function barHeights(seed: string, count: number = WAVEFORM_BARS): number[] {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  const out: number[] = []
  for (let i = 0; i < count; i++) {
    h ^= h << 13
    h ^= h >>> 17
    h ^= h << 5
    out.push(0.25 + (Math.abs(h) % 1000) / 1000 / 1.4) // 0.25..0.96
  }
  return out
}
