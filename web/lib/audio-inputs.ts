/**
 * Shared types and placeholder data for the creation-page input modals (US-16.8):
 * Add Audio (remix a clip / upload a file / record from mic), Add Voice, and
 * Add Inspiration. Voice models and playlists have no backend yet, so the modals
 * read from the MOCK_* arrays below — shaped to match the eventual API responses
 * so swapping in a real fetch is a one-line change.
 */

/** Accepted upload formats for the Add Audio → Upload tab. */
export const ACCEPTED_AUDIO_EXTENSIONS = [
  ".wav",
  ".flac",
  ".mp3",
  ".ogg",
  ".aac",
  ".aiff",
] as const

/** A reference audio the user attached, by source. `label` is what the chip shows. */
export type AudioSelection =
  | { kind: "clip"; clipId: string; label: string }
  | { kind: "upload"; file: File; label: string }
  | { kind: "record"; blob: Blob; label: string }

export type VoiceSelection = { id: string; name: string }

export type InspirationSelection = { id: string; name: string }

export type VoiceModel = {
  id: string
  name: string
  description: string
  previewUrl: string
}

export type Playlist = {
  id: string
  name: string
  trackCount: number
  thumbnailUrl?: string
}

// ponytail: placeholder data — replace with a fetch once the voices/playlists
// APIs exist. Shapes match the planned responses so callers don't change.
export const MOCK_VOICES: VoiceModel[] = [
  {
    id: "voice-aria",
    name: "Aria",
    description: "Warm female pop vocal",
    previewUrl: "/audio/voices/aria.mp3",
  },
  {
    id: "voice-rex",
    name: "Rex",
    description: "Gritty male rock vocal",
    previewUrl: "/audio/voices/rex.mp3",
  },
  {
    id: "voice-lumen",
    name: "Lumen",
    description: "Airy androgynous synth vocal",
    previewUrl: "/audio/voices/lumen.mp3",
  },
]

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
