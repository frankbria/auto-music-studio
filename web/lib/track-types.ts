// Track types for the Studio multi-track editor (US-19.2, spec §24.2). Each
// track accepts only clips whose category matches: the category is inferred
// from the clip's persisted generation_mode (the API stores the generation
// request's mode — "song"/"sound" — or the operation that produced the clip:
// "upload", "stems", "cover", "extend", …). Everything that isn't an upload,
// a stem extraction, or a sound/loop generation is an AI-generated clip, so
// unknown/null modes default to "ai" rather than being unplaceable.

import {
  AiMagicIcon,
  Mic01Icon,
  RepeatIcon,
  Upload01Icon,
} from "@hugeicons/core-free-icons"

export type TrackType = "ai" | "audio" | "loop" | "vocal"

export const TRACK_TYPE_ORDER: readonly TrackType[] = [
  "ai",
  "audio",
  "loop",
  "vocal",
]

export type TrackTypeConfig = {
  label: string
  description: string
  /** Lane strip / clip block accent color. */
  color: string
  /** @hugeicons/core-free-icons icon for HugeiconsIcon. */
  icon: typeof AiMagicIcon
}

export const TRACK_TYPES: Record<TrackType, TrackTypeConfig> = {
  ai: {
    label: "AI-Generated",
    description: "Generated songs, covers, extensions, and remixes",
    color: "#6d28d9",
    icon: AiMagicIcon,
  },
  audio: {
    label: "Audio",
    description: "Uploaded audio files",
    color: "#0ea5e9",
    icon: Upload01Icon,
  },
  loop: {
    label: "Sound/Loop",
    description: "Sounds and loops, tempo-matched to the project",
    color: "#22c55e",
    icon: RepeatIcon,
  },
  vocal: {
    label: "Vocal",
    description: "Extracted vocal stems",
    color: "#f97316",
    icon: Mic01Icon,
  },
}

/** Project tempo bounds, mirroring the backend's BPM_MIN/BPM_MAX (constants.py). */
export const BPM_MIN = 60
export const BPM_MAX = 180

/** The track type a clip belongs on, inferred from its generation_mode. */
export function inferTrackType(
  generationMode: string | null | undefined
): TrackType {
  switch (generationMode) {
    case "upload":
      return "audio"
    case "stems":
      return "vocal"
    case "sound":
      return "loop"
    default:
      return "ai"
  }
}

/**
 * Playback rate for a placement: loop-track clips stretch to the project
 * tempo (rate = projectBpm / clipBpm); everything else — including loops with
 * no usable BPM metadata — plays at 1x.
 */
export function placementPlaybackRate(
  clipBpm: number | null | undefined,
  trackType: TrackType,
  projectBpm: number
): number {
  if (trackType !== "loop") return 1
  if (!clipBpm || clipBpm <= 0) return 1
  return projectBpm / clipBpm
}
