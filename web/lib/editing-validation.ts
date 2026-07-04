/**
 * Client-side validation for the editing workflow modals (US-17.3).
 *
 * The backend accepts human time strings ("30s", "1m30s", "1.5s", "90s", "5")
 * for range/duration fields (`parse_time_string` in `src/acemusic/utils.py`) and
 * validates every bound. These helpers mirror that parser and those bounds so a
 * modal can reject bad input inline instead of round-tripping a 422. Validators
 * follow the app convention of returning the first problem string, or `null`
 * when valid (see `lib/generate.ts` `validateSounds`).
 */

// Mirrors backend _TIME_PATTERN: "<m>m<s>s" | "<s>s" | "<plain>" (plain seconds).
// The minutes group is optional but a seconds value with the "s" suffix is
// required unless the whole string is a bare number.
const TIME_PATTERN = /^(?:(\d+)m)?(\d+(?:\.\d+)?)s$|^(\d+(?:\.\d+)?)$/

/**
 * Parse a time string into milliseconds, or `null` if it is not a valid format.
 * Matches the backend's accepted formats exactly so a value that parses here is
 * one the backend will also accept.
 */
export function parseTimeString(value: string): number | null {
  const match = TIME_PATTERN.exec(value.trim())
  if (!match) return null
  const [, minutes, seconds, plain] = match
  const totalSeconds =
    plain !== undefined
      ? Number(plain)
      : Number(seconds) + Number(minutes ?? 0) * 60
  if (!Number.isFinite(totalSeconds)) return null
  return Math.round(totalSeconds * 1000)
}

/** Format a millisecond duration as a compact "1m30s" / "45s" string. */
export function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0s"
  const totalSeconds = ms / 1000
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round((totalSeconds - minutes * 60) * 100) / 100
  return minutes > 0 ? `${minutes}m${seconds}s` : `${seconds}s`
}

/**
 * Validate a single time-string field. Returns an error message when the value
 * is empty (required fields), unparseable, or — when `maxMs` is given — beyond
 * the clip's bounds. Returns `null` when valid.
 */
export function validateTimeField(
  value: string,
  label: string,
  { maxMs }: { maxMs?: number } = {}
): string | null {
  if (!value.trim()) return `${label} is required.`
  const ms = parseTimeString(value)
  if (ms === null) return `${label} must be a time like "30s" or "1m30s".`
  if (ms < 0) return `${label} can't be negative.`
  if (maxMs !== undefined && ms > maxMs) {
    return `${label} can't exceed the clip length (${formatMs(maxMs)}).`
  }
  return null
}

/**
 * Validate a `[start, end]` selection against the clip. Enforces the backend's
 * `start < end <= duration` rule (`_check_range` in iterative.py). Returns the
 * first problem, or `null` when valid.
 */
export function validateRange(
  start: string,
  end: string,
  durationMs: number | null
): string | null {
  const maxMs = durationMs ?? undefined
  const startError = validateTimeField(start, "Start", { maxMs })
  if (startError) return startError
  const endError = validateTimeField(end, "End", { maxMs })
  if (endError) return endError
  // Both parse (validateTimeField guaranteed it), so the non-null assertions hold.
  const startMs = parseTimeString(start) as number
  const endMs = parseTimeString(end) as number
  if (startMs >= endMs) return "Start must be before end."
  return null
}
