/**
 * Bounds and option lists for the editing/iterative workflow modals (US-17.3).
 *
 * These mirror the backend request models in
 * `src/acemusic/api/routers/editing.py` and `.../iterative.py` (both use
 * `extra="forbid"` and validate every range), so the modals validate against the
 * same numbers and surface errors inline instead of as a round-trip 422.
 */

/** `SpeedRequest.multiplier` range (editing.py SPEED_MULTIPLIER_MIN/MAX). */
export const SPEED_MULTIPLIER_MIN = 0.5
export const SPEED_MULTIPLIER_MAX = 2.0

/** `SampleRequest.num_clips` range (iterative.py _MAX_SAMPLE_CLIPS). */
export const SAMPLE_NUM_CLIPS_MIN = 1
export const SAMPLE_NUM_CLIPS_MAX = 4

/** `MashupRequest.clip_ids` length bounds (iterative.py _MAX_MASHUP_CLIPS). */
export const MASHUP_CLIPS_MIN = 2
export const MASHUP_CLIPS_MAX = 8

/** `SampleRequest.role` — the musical role of an extracted sample. */
export const SAMPLE_ROLES = [
  { value: "loop-bed", label: "Loop bed" },
  { value: "intro-outro", label: "Intro / outro" },
  { value: "rhythmic-element", label: "Rhythmic element" },
  { value: "melodic-hook", label: "Melodic hook" },
] as const

export type SampleRole = (typeof SAMPLE_ROLES)[number]["value"]

/** `MashupRequest.blend_mode` — how a mashup combines its sources. */
export const BLEND_MODES = [
  { value: "layered", label: "Layered" },
  { value: "sequential", label: "Sequential" },
  { value: "ai-guided", label: "AI-guided" },
] as const

export type BlendMode = (typeof BLEND_MODES)[number]["value"]
