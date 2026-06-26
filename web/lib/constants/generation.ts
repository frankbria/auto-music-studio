/**
 * Generation parameter bounds for the Advanced creation form (US-16.2).
 *
 * These mirror the backend's `GenerationRequest` constraints
 * (`src/acemusic/constants.py`); the backend uses `extra="forbid"` and validates
 * every range, so the form validates against the same numbers to surface errors
 * before submission rather than as a round-trip 422.
 */

export const BPM_MIN = 60
export const BPM_MAX = 180
export const DURATION_MIN = 30
export const DURATION_MAX = 240
export const WEIRDNESS_MIN = 0
export const WEIRDNESS_MAX = 100
export const STYLE_INFLUENCE_MIN = 0
export const STYLE_INFLUENCE_MAX = 100

export const PROMPT_MAX_LENGTH = 2000
export const STYLE_MAX_LENGTH = 1000
export const LYRICS_MAX_LENGTH = 5000
export const KEY_MAX_LENGTH = 50

/** Mirrors backend VALID_TIME_SIGNATURES (order is the display order). */
export const VALID_TIME_SIGNATURES = ["4/4", "3/4", "6/8", "5/4", "7/8"] as const

/** Slider/control defaults (match the backend field defaults). */
export const WEIRDNESS_DEFAULT = 50
export const STYLE_INFLUENCE_DEFAULT = 50

/** Duration preset shortcuts (seconds), all within [DURATION_MIN, DURATION_MAX]. */
export const DURATION_PRESETS = [30, 60, 120, 240] as const

/**
 * Key options for the selector. "" is the "Any" choice (omitted from the
 * payload). The rest are common major/minor keys kept well under KEY_MAX_LENGTH.
 */
export const KEY_OPTIONS = [
  "C major",
  "A minor",
  "G major",
  "E minor",
  "D major",
  "B minor",
  "F major",
  "D minor",
] as const

/** Common vocal languages; "" is the "Auto" / unset choice (omitted from payload). */
export const VOCAL_LANGUAGES = [
  "English",
  "Spanish",
  "French",
  "German",
  "Italian",
  "Portuguese",
  "Japanese",
  "Korean",
  "Chinese",
] as const
