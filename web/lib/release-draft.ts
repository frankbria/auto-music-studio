// Release metadata + draft seam (US-21.4).
//
// Like mastering history ([[us-21-3-mastering-status-tracking]]) and the Stage-20
// pages, there is no backend release endpoint yet. This module is the local,
// typed layer the distribution form is built on: it prefills from a clip,
// generates/validates identifiers, checks cover-art resolution, and persists a
// draft to localStorage. The persistence shape mirrors an eventual
// `PATCH /releases/{id}` — when that lands, swap the localStorage calls for a
// fetch and the form stays unchanged.

import type { Clip } from "@/lib/workspace-clips"

/** Distributor minimum for cover art on the major stores (Spotify/Apple). */
export const MIN_COVER_ART_PX = 3000

/** Credits captured for the release (spec 42.3). */
export type ReleaseCredits = {
  producer: string
  songwriter: string
  performer: string
}

/** How the cover art was chosen. The uploaded File itself is not persisted to a
 *  draft (localStorage can't hold it) — only the descriptor, so a resumed draft
 *  shows "was uploaded: name" and the user re-picks if they want to change it. */
export type CoverArtChoice =
  | { kind: "none" }
  | { kind: "existing" }
  | { kind: "uploaded"; name: string }

/** The editable release form model. `bpm` stays null when the song has none. */
export type ReleaseMetadata = {
  title: string
  artist: string
  album: string
  genre: string
  description: string
  bpm: number | null
  key: string
  language: string
  explicit: boolean
  releaseDate: string
  copyright: string
  credits: ReleaseCredits
  coverArt: CoverArtChoice
  isrc: string
  upc: string
  lyrics: string
}

/** Pre-populate the form from a song's existing metadata (AC1). Fields the Clip
 *  model doesn't carry (artist, album, release date, credits, ISRC/UPC) start
 *  blank for the user to fill; artist mirrors the player's placeholder. */
export function prefillFromClip(clip: Clip): ReleaseMetadata {
  return {
    title: clip.title ?? "",
    artist: "Unknown artist",
    album: "",
    genre: clip.style_tags?.[0] ?? "",
    description: "",
    bpm: clip.bpm,
    key: clip.key ?? "",
    language: clip.vocal_language ?? "",
    explicit: false,
    releaseDate: "",
    copyright: "",
    credits: { producer: "", songwriter: "", performer: "" },
    coverArt: { kind: "none" },
    isrc: "",
    upc: "",
    lyrics: clip.lyrics ?? "",
  }
}

/** Random n-digit string (as characters, leading zeros kept). */
function digits(n: number): string {
  let out = ""
  for (let i = 0; i < n; i++) out += Math.floor(Math.random() * 10)
  return out
}

/** Generate a syntactically-valid placeholder ISRC (AC4): CC-Registrant-YY-Designation.
 *  Real allocation needs a registrant code from a label; this stands in until a
 *  distributor assigns one. */
export function generateIsrc(): string {
  const yy = String(new Date().getFullYear() % 100).padStart(2, "0")
  return `US-AMS-${yy}-${digits(5)}`
}

/** UPC-A check digit for the first 11 digits (weights 3,1,3,1,… from the left). */
function upcCheckDigit(first11: string): number {
  const sum = first11
    .split("")
    .reduce((acc, ch, idx) => acc + Number(ch) * (idx % 2 === 0 ? 3 : 1), 0)
  return (10 - (sum % 10)) % 10
}

/** Generate a valid 12-digit UPC-A (AC4): 11 random digits + computed check digit. */
export function generateUpc(): string {
  const first11 = digits(11)
  return first11 + upcCheckDigit(first11)
}

/** True when a 12-digit string carries a correct UPC-A check digit. */
function isValidUpc(upc: string): boolean {
  return /^\d{12}$/.test(upc) && upcCheckDigit(upc.slice(0, 11)) === Number(upc[11])
}

/** ISRC shape check (not registry-verified): CC-XXX-YY-NNNNN. */
function isValidIsrc(isrc: string): boolean {
  return /^[A-Z]{2}-[A-Z0-9]{3}-\d{2}-\d{5}$/.test(isrc)
}

/** Error message if cover art is below the store minimum, else null (AC3). */
export function coverArtResolutionError(width: number, height: number): string | null {
  if (width < MIN_COVER_ART_PX || height < MIN_COVER_ART_PX) {
    return `Cover art must be at least ${MIN_COVER_ART_PX}×${MIN_COVER_ART_PX}px (got ${width}×${height}).`
  }
  return null
}

/** Field-keyed validation errors (AC5). Empty object ⇒ valid. Required: title,
 *  artist, genre. ISRC/UPC are optional but must be well-formed when present. */
export function validateMetadata(m: ReleaseMetadata): Partial<Record<keyof ReleaseMetadata, string>> {
  const errors: Partial<Record<keyof ReleaseMetadata, string>> = {}
  if (!m.title.trim()) errors.title = "Title is required."
  if (!m.artist.trim()) errors.artist = "Artist is required."
  if (!m.genre.trim()) errors.genre = "Genre is required."
  if (m.isrc.trim() && !isValidIsrc(m.isrc.trim())) errors.isrc = "Enter a valid ISRC (e.g. US-AMS-25-00001)."
  if (m.upc.trim() && !isValidUpc(m.upc.trim())) errors.upc = "Enter a valid 12-digit UPC."
  return errors
}

const DRAFT_PREFIX = "ams:release-draft:"

/** Load a saved draft for a clip, or null if none / corrupt / unavailable (AC6).
 *  The try/catch also makes this safe during SSR, where `localStorage` is undefined
 *  (returns null). Callers should merge the result over a fresh prefill so a draft
 *  written by an older version — missing newer fields — can't crash on read. */
export function loadDraft(clipId: string): Partial<ReleaseMetadata> | null {
  try {
    const raw = localStorage.getItem(DRAFT_PREFIX + clipId)
    return raw ? (JSON.parse(raw) as Partial<ReleaseMetadata>) : null
  } catch {
    return null
  }
}

/** Persist a draft for a clip so it can be resumed later (AC6). Returns false when
 *  storage is full/blocked (private mode, quota) so the caller can surface it
 *  instead of throwing an uncaught error and silently losing the user's work. */
export function saveDraft(clipId: string, metadata: ReleaseMetadata): boolean {
  try {
    localStorage.setItem(DRAFT_PREFIX + clipId, JSON.stringify(metadata))
    return true
  } catch {
    return false
  }
}

/** Remove a clip's saved draft. Best-effort — never throws. */
export function clearDraft(clipId: string): void {
  try {
    localStorage.removeItem(DRAFT_PREFIX + clipId)
  } catch {
    // storage unavailable — nothing to remove
  }
}
