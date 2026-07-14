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
 * Whether a track is silenced outright: muted, or out-soloed by another track.
 * Multiple solos are allowed — solo is a filter, not a radio button. Shared by
 * the audio engine and the lane's visual dimming so they can't diverge.
 */
export function isTrackSilenced(
  track: { muted: boolean; solo: boolean },
  anySolo: boolean
): boolean {
  return track.muted || (anySolo && !track.solo)
}

/**
 * The gain a track actually plays at: 0 when silenced, otherwise its fader
 * gain.
 */
export function effectiveTrackGain(
  track: { volumeDb: number; muted: boolean; solo: boolean },
  anySolo: boolean
): number {
  return isTrackSilenced(track, anySolo) ? 0 : dbToGain(track.volumeDb)
}

/** Map the UI's pan range [-100, +100] to StereoPannerNode's [-1, +1]. */
export function panToAudioValue(pan: number): number {
  return pan / 100
}

export function formatVolumeDb(volumeDb: number): string {
  if (volumeDb <= VOLUME_DB_MIN) return "-∞ dB"
  if (volumeDb > 0) return `+${volumeDb} dB`
  return `${volumeDb} dB`
}
