/**
 * Tier vocabulary shared by the UI (US-26.2).
 *
 * The authoritative table is the backend's `services/tiers.py` — this is what the
 * frontend needs to *explain* a lock, not to decide one. The API's 403 carries the same
 * `feature`/`message`/`upgrade_url` fields, so a lock discovered server-side and one
 * predicted client-side read the same way.
 */

export type Tier = "free" | "pro" | "enterprise"

const TIER_RANK: Record<Tier, number> = { free: 0, pro: 1, enterprise: 2 }

export const TIER_LABELS: Record<Tier, string> = {
  free: "Free",
  pro: "Pro",
  enterprise: "Enterprise",
}

/** Anything the API sends that this build does not know is free: an unknown tier must never unlock a paid feature. */
export function toTier(value: string | null | undefined): Tier {
  return value === "pro" || value === "enterprise" ? value : "free"
}

/** Enterprise has every Pro capability, so a gate asks "at least", never "exactly". */
export function hasTier(tier: Tier, required: Tier): boolean {
  return TIER_RANK[tier] >= TIER_RANK[required]
}

/** Where an upgrade prompt sends someone. Mirrors the API's `upgrade_url`. */
export const UPGRADE_URL = "/settings/billing"

/** What is locked, and what upgrading would let them do. */
export type LockedFeature = {
  name: string
  benefit: string
}

/**
 * Copy for the features the UI can lock before the server is asked.
 *
 * Keyed by the same capability strings the API's 403 uses (`detail.capability`), so a
 * 403 that arrives anyway can be rendered through the same modal.
 */
export const LOCKED_FEATURES: Record<string, LockedFeature> = {
  stems: {
    name: "Stem separation",
    benefit: "split a track into vocals, drums, bass and other",
  },
  midi: {
    name: "MIDI extraction",
    benefit: "export melody, chords, drums and bass as MIDI",
  },
  mastering: {
    name: "Mastering",
    benefit: "master your tracks to a professional loudness target",
  },
  distribution: {
    name: "Distribution",
    benefit: "publish your releases to streaming platforms",
  },
  voice_models: {
    name: "Custom voice models",
    benefit: "train a voice and sing your songs in it",
  },
  studio_editing: {
    name: "Studio editing",
    benefit: "arrange and mix in the multi-track Studio",
  },
  high_res_video: {
    name: "High-resolution video",
    benefit: "render videos above 720p, without a watermark",
  },
  video_4k: {
    name: "4K video",
    benefit: "render videos in 4K (Enterprise)",
  },
  lossless_export: {
    name: "Lossless export",
    benefit: "download WAV and FLAC as well as MP3",
  },
}

export const FREE_FEATURES = [
  "Song generation and editing",
  "MP3 export",
  "720p video with a watermark",
]

/** Pro's capabilities, without the credit allowance, which the billing page reads from the API. */
export const PRO_FEATURES = [
  "Stems, MIDI, and lossless WAV/FLAC export",
  "Mastering and distribution to streaming platforms",
  "Custom voice models trained on your own recordings",
  "Full multi-track Studio editing",
  "1080p video, without a watermark",
]

export const ENTERPRISE_FEATURES = [
  "Everything in Pro",
  "Priority job queue",
  "4K video",
]

/** What the upgrade modal lists. Deliberately short — a wall of copy sells nothing. */
export const PRO_BENEFITS = [
  "500 credits a month, instead of 50",
  ...PRO_FEATURES,
]

/**
 * The copy for a locked capability, or a generic fallback.
 *
 * Falls back rather than throwing: a capability the server knows about and this build
 * does not should still produce a usable prompt, not a crash in a dropdown.
 */
export function lockedFeature(
  capability: string | null | undefined
): LockedFeature | null {
  if (!capability) return null
  return (
    LOCKED_FEATURES[capability] ?? {
      name: "This feature",
      benefit: "unlock everything Auto Music Studio can do",
    }
  )
}
