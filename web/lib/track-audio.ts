/**
 * Per-track gain math (US-19.4). The fader runs [-60, +6] dB where the floor
 * renders as -∞ and maps to silence.
 */

export const VOLUME_DB_MIN = -60
export const VOLUME_DB_MAX = 6

export function dbToGain(volumeDb: number): number {
  if (volumeDb <= VOLUME_DB_MIN) return 0
  return Math.pow(10, volumeDb / 20)
}

/**
 * The gain a track actually plays at: silent when muted, or when other tracks
 * are soloed and this one isn't; otherwise its fader gain. Multiple solos are
 * allowed — solo is a filter, not a radio button.
 */
export function effectiveTrackGain(
  track: { volumeDb: number; muted: boolean; solo: boolean },
  anySolo: boolean
): number {
  if (track.muted) return 0
  if (anySolo && !track.solo) return 0
  return dbToGain(track.volumeDb)
}

export function formatVolumeDb(volumeDb: number): string {
  if (volumeDb <= VOLUME_DB_MIN) return "-∞ dB"
  if (volumeDb > 0) return `+${volumeDb} dB`
  return `${volumeDb} dB`
}
