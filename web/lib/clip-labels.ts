// Display-label maps shared by the clip card (US-16.6) and the song-detail
// header (US-17.1) so a clip's model/mode reads the same everywhere.

/** Model id → short version badge label. Unmapped models show their raw id. */
export const VERSION_LABELS: Record<string, string> = {
  "ace-step-v1": "XL",
  "ace-step-v1-turbo": "XL Turbo",
}

/** generation_mode → badge label. Plain "generate"/null show nothing. */
export const MODE_LABELS: Record<string, string> = {
  cover: "Cover",
  extend: "Extend",
  remix: "Remix",
  mashup: "Mashup",
  sample: "Sample",
  upload: "Upload",
  studio: "Studio",
  mastered: "Mastered",
  full_song: "Full Song",
}

/** Short version badge label for a model id, or null when unset. */
export function versionLabel(model: string | null): string | null {
  if (!model) return null
  return VERSION_LABELS[model] ?? model
}

/** Badge label for a generation_mode, or null when it has no badge. */
export function modeLabel(mode: string | null): string | null {
  if (!mode) return null
  return MODE_LABELS[mode] ?? null
}
