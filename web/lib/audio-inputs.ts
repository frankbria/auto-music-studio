/**
 * Shared types and placeholder data for the creation-page input modals (US-16.8):
 * Add Audio (remix a clip / upload a file / record from mic), Add Voice, and
 * Add Inspiration. Add Voice reads the musician's real library (US-25.4); playlists
 * have no backend yet, so that modal still reads from MOCK_PLAYLISTS below — shaped
 * to match the eventual API response so swapping in a fetch is a one-line change.
 */

/** Accepted upload formats for the Add Audio → Upload tab. */
export const ACCEPTED_AUDIO_EXTENSIONS = [
  ".wav",
  ".flac",
  ".mp3",
  ".ogg",
  ".aac",
  ".aiff",
  ".aif",
] as const

/** A reference audio the user attached, by source. `label` is what the chip shows. */
export type AudioSelection =
  | { kind: "clip"; clipId: string; label: string }
  | { kind: "upload"; file: File; label: string }
  | { kind: "record"; blob: Blob; label: string }

export type VoiceSelection = { id: string; name: string }

export type InspirationSelection = { id: string; name: string }

export type Playlist = {
  id: string
  name: string
  trackCount: number
  thumbnailUrl?: string
}

// ponytail: placeholder data — replace with a fetch once the playlists API exists.
// Shapes match the planned response so callers don't change. (Voices became real in
// US-25.4 and now come from `@/lib/voice-models`.)
export const MOCK_PLAYLISTS: Playlist[] = [
  { id: "pl-latenight", name: "Late Night Drive", trackCount: 12 },
  { id: "pl-focus", name: "Deep Focus", trackCount: 28 },
  { id: "pl-summer", name: "Summer Anthems", trackCount: 7 },
]

/** True if `name` ends in one of the accepted audio extensions (case-insensitive). */
export function isAcceptedAudioFile(name: string): boolean {
  const lower = name.toLowerCase()
  return ACCEPTED_AUDIO_EXTENSIONS.some((ext) => lower.endsWith(ext))
}
