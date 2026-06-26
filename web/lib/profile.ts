// Profile types and client-side validation for the settings page (US-15.5).
// Rules mirror the backend (src/acemusic/api/routers/users.py and
// services/users.py) so the form catches violations before the round-trip; the
// server stays the source of truth (it re-validates and owns handle uniqueness).

/** Full profile as returned by GET /api/v1/users/me. */
export type UserProfile = {
  id: string
  email: string
  name: string
  display_name: string | null
  handle: string | null
  bio: string | null
  style_tags: string[]
  avatar_url: string | null
  subscription_tier: string
  created_at: string
  updated_at: string | null
}

/** Editable fields sent to PATCH /api/v1/users/me (avatar_url is read-only). */
export type UserProfileUpdate = {
  display_name?: string
  handle?: string | null
  bio?: string
  style_tags?: string[]
}

export const DISPLAY_NAME_MAX_LENGTH = 100
export const BIO_MAX_LENGTH = 500
export const HANDLE_MIN_LENGTH = 3
export const HANDLE_MAX_LENGTH = 30
export const STYLE_TAG_MAX_LENGTH = 30
export const STYLE_TAGS_MAX_ITEMS = 20

// Matches the backend _HANDLE_PATTERN: alphanumeric, internal hyphens allowed,
// must start and end with an alphanumeric character.
const HANDLE_PATTERN = /^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$/

/** Curated typeahead suggestions; no backend endpoint exists yet (US-15.5). */
export const STYLE_SUGGESTIONS = [
  "cello",
  "orchestral",
  "lo-fi",
  "ambient",
  "electronic",
  "acoustic",
  "jazz",
  "hip-hop",
  "classical",
  "indie",
  "pop",
  "rock",
  "folk",
  "synthwave",
  "piano",
  "drill",
  "house",
  "techno",
  "soul",
  "cinematic",
] as const

/** Return an error message, or null if valid. */
export function validateDisplayName(value: string): string | null {
  const trimmed = value.trim()
  if (trimmed.length === 0) return "Display name is required."
  if (trimmed.length > DISPLAY_NAME_MAX_LENGTH)
    return `Display name must be at most ${DISPLAY_NAME_MAX_LENGTH} characters.`
  return null
}

/** Validate handle format. Empty is allowed (handle stays unclaimed/null). */
export function validateHandle(value: string): string | null {
  if (value.length === 0) return null
  if (value.length < HANDLE_MIN_LENGTH)
    return `Handle must be ${HANDLE_MIN_LENGTH}-${HANDLE_MAX_LENGTH} characters.`
  if (value.length > HANDLE_MAX_LENGTH)
    return `Handle must be ${HANDLE_MIN_LENGTH}-${HANDLE_MAX_LENGTH} characters.`
  if (/[^A-Za-z0-9-]/.test(value))
    return "Only letters, numbers, and hyphens allowed."
  if (value.startsWith("-") || value.endsWith("-"))
    return "Cannot start or end with a hyphen."
  // Catch any residual mismatch (e.g. consecutive-hyphen edge cases the
  // backend pattern rejects) so client and server never disagree.
  if (!HANDLE_PATTERN.test(value))
    return "Only letters, numbers, and hyphens allowed."
  return null
}

export function validateBio(value: string): string | null {
  if (value.length > BIO_MAX_LENGTH)
    return `Bio must be at most ${BIO_MAX_LENGTH} characters.`
  return null
}

/**
 * Validate a tag the user is trying to add against the current list.
 * Returns an error message, or null if the (trimmed) tag is addable.
 */
export function validateNewStyleTag(
  raw: string,
  existing: string[]
): string | null {
  const tag = raw.trim()
  if (tag.length === 0) return "Tag cannot be empty."
  if (tag.length > STYLE_TAG_MAX_LENGTH)
    return `Tag must be at most ${STYLE_TAG_MAX_LENGTH} characters.`
  if (existing.some((t) => t.toLowerCase() === tag.toLowerCase()))
    return "Tag already added."
  if (existing.length >= STYLE_TAGS_MAX_ITEMS)
    return `At most ${STYLE_TAGS_MAX_ITEMS} tags allowed.`
  return null
}
