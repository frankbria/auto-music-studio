// Song-structure planning for the Get Full Song flow (US-17.4).
//
// A TypeScript port of the backend planner (src/acemusic/song_structure.py,
// plan_sections) so the wizard can preview the section breakdown and size each
// extend without an extra API round-trip. The structure and per-section weights
// are static, spec-defined data (spec §21); keep the values here in lockstep
// with SECTION_CONFIG on the backend. Pure functions only.

import type { Clip } from "@/lib/workspace-clips"
import { DURATION_MAX } from "@/lib/constants/generation"

/** The canonical seven-section song shape (intro → outro). */
export const SONG_STRUCTURE = [
  "intro",
  "verse",
  "chorus",
  "verse",
  "chorus",
  "bridge",
  "outro",
] as const

export type SectionName = (typeof SONG_STRUCTURE)[number]

/**
 * Per-section `[relativeWeight, styleHint]`, normalized across the whole
 * structure — each occurrence (both verses, both choruses) contributes its
 * weight independently. Mirrors the backend SECTION_CONFIG exactly.
 */
export const SECTION_CONFIG: Record<SectionName, readonly [number, string]> = {
  intro: [1.0, "intro, atmospheric build, sparse arrangement"],
  verse: [2.0, "verse, melodic, narrative groove"],
  chorus: [2.0, "chorus, hook, energetic, full arrangement"],
  bridge: [1.5, "bridge, transition, contrast and tension"],
  outro: [1.0, "outro, fade and resolve"],
}

/** Round each section up to this many seconds when the budget allows (audible chunk). */
export const MIN_SECTION_SECONDS = 4

/** Longest seed a full-song build accepts; also the clip-card eligibility cutoff. */
export const MAX_SEED_DURATION = 60
/** Target-duration slider bounds (seconds). Max tracks the backend generation cap. */
export const TARGET_DURATION_MIN = 120
export const TARGET_DURATION_MAX = DURATION_MAX // 240
/** Default target when the wizard opens. */
export const DEFAULT_TARGET_DURATION = 210

/** A planned section: what to generate, how long, with what style emphasis. */
export type Section = {
  name: SectionName
  durationSeconds: number
  styleHint: string
}

/**
 * Distribute `(targetDuration - seedDuration)` across the canonical structure,
 * each section getting a slice proportional to its configured weight.
 *
 * When there is headroom every section is rounded up to MIN_SECTION_SECONDS so
 * it produces an audible chunk; when the remainder is too small to honor that
 * floor across all sections the floor is dropped and durations stay purely
 * proportional — so the planned total never overshoots `targetDuration`. Every
 * section still gets a positive duration. Mirrors the backend `plan_sections`.
 *
 * Returns `[]` for a non-positive or too-short target rather than throwing —
 * the caller clamps the slider to a valid range, and an empty plan reads as
 * "nothing to do" in the UI.
 */
export function planSections(
  seedDuration: number,
  targetDuration: number
): Section[] {
  const remaining = targetDuration - seedDuration
  if (remaining <= 0) return []

  const weights = SONG_STRUCTURE.map((name) => SECTION_CONFIG[name][0])
  const totalWeight = weights.reduce((a, b) => a + b, 0)
  const raw = weights.map((w) => remaining * (w / totalWeight))

  // Apply the audible-section floor only if doing so still fits the budget;
  // otherwise fall back to the raw proportional split (never overshoots).
  const floored = raw.map((d) => Math.max(d, MIN_SECTION_SECONDS))
  const flooredTotal = floored.reduce((a, b) => a + b, 0)
  const durations = flooredTotal <= remaining ? floored : raw

  return SONG_STRUCTURE.map((name, i) => ({
    name,
    durationSeconds: durations[i],
    styleHint: SECTION_CONFIG[name][1],
  }))
}

/**
 * The whole-second duration actually requested when extending for a section.
 * Floored (not rounded) so summed sections never push the cumulative clip past
 * the backend's generation cap; every section still gets at least one second.
 * Shared by the generation step (what to send) and the completion summary (what
 * was assembled).
 */
export function sectionExtendSeconds(section: Section): number {
  return Math.max(1, Math.floor(section.durationSeconds))
}

/**
 * A clip is eligible for the Full Song flow when it has a known duration under
 * MAX_SEED_DURATION — the flow grows a short seed into a full song, so it only
 * makes sense for short clips.
 */
export function isFullSongEligible(clip: Pick<Clip, "duration">): boolean {
  return clip.duration != null && clip.duration < MAX_SEED_DURATION
}
