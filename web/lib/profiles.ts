// Public profile data seam (US-20.5).
//
// The public profile page (/@handle) has no backend: there is no public
// "user by handle" endpoint, no published-clips-by-user endpoint, and no Follow
// system. Like Explore (US-20.1), Search (US-20.2), Playlists (US-20.3), and the
// Feed (US-20.4), the page runs on this local, typed mock layer whose shapes
// mirror the eventual public profile API. Published songs are drawn from the same
// discovery pool as Explore; public playlists from the playlists seam. When the
// social API lands, swap each getter's body for a fetch and callers won't change.
//
// ponytail: session-scoped mock, no persistence and no network delay — the reads
// are synchronous local data. Add both when a getter becomes a real fetch.

import { getAllClips } from "@/lib/explore"
import { initialPlaylists, type Playlist } from "@/lib/playlists"
import type { Clip } from "@/lib/workspace-clips"

/** A public creator profile. Mirrors the eventual GET /users/by-handle/{handle}. */
export type PublicProfile = {
  /** Bare handle, no leading "@" (e.g. "nova"). The URL adds the "@". */
  handle: string
  display_name: string
  bio: string
  style_tags: string[]
  /** No authed artwork proxy yet, so this is always null → initials/glyph avatar. */
  avatar_url: string | null
  follower_count: number
  following_count: number
  joined_at: string
  /** Ids of the creator's published clips, resolved against the Explore pool. */
  clip_ids: string[]
}

// A handful of mock creators, each owning a slice of the Explore discovery pool
// (ids from lib/explore) as their published songs. Keyed by bare, lowercase handle.
const MOCK_PROFILES: Record<string, PublicProfile> = {
  nova: {
    handle: "nova",
    display_name: "Nova Bloom",
    bio: "Synthwave and neon-lit electronic. Chasing the empty highway at 2am.",
    style_tags: ["synthwave", "electronic", "ambient"],
    avatar_url: null,
    follower_count: 12800,
    following_count: 142,
    joined_at: "2026-01-14T00:00:00Z",
    clip_ids: ["clip-neon", "clip-pulse", "clip-paper"],
  },
  ember: {
    handle: "ember",
    display_name: "Ember Vale",
    bio: "Loud guitars, dusty roads. Indie rock with the windows down.",
    style_tags: ["rock", "indie", "folk"],
    avatar_url: null,
    follower_count: 8400,
    following_count: 88,
    joined_at: "2026-02-02T00:00:00Z",
    clip_ids: ["clip-emberr", "clip-crown", "clip-dust"],
  },
  sol: {
    handle: "sol",
    display_name: "Sol Marlowe",
    bio: "Late-night brass, velvet soul, and the odd cathedral of strings.",
    style_tags: ["jazz", "soul", "rnb", "classical"],
    avatar_url: null,
    follower_count: 5100,
    following_count: 231,
    joined_at: "2026-03-20T00:00:00Z",
    clip_ids: ["clip-brass", "clip-mono", "clip-glass", "clip-velvet"],
  },
}

/** Normalize a URL handle to the mock key: drop one leading "@", lowercase. */
function normalizeHandle(handle: string): string {
  return handle.replace(/^@/, "").toLowerCase()
}

/**
 * Look up a public profile by handle. Accepts "@nova" or "nova" (any case).
 * Returns null when no such creator exists → the route renders notFound().
 */
export function getProfileByHandle(handle: string): PublicProfile | null {
  return MOCK_PROFILES[normalizeHandle(handle)] ?? null
}

/** Resolve a profile's published clips against the Explore pool, order preserved. */
export function profileClips(profile: PublicProfile): Clip[] {
  const byId = new Map(getAllClips().map((c) => [c.id, c]))
  return profile.clip_ids
    .map((id) => byId.get(id))
    .filter((c): c is Clip => c != null)
}

/**
 * Public playlists to show on a profile. Playlists aren't owned per-user in the
 * mock (US-20.3), so every profile surfaces the shared public set — enough to
 * satisfy the "shows public playlists" criterion without scope-creeping into a
 * per-user playlist API. Add a handle param + swap for GET /users/{handle}/
 * playlists when a per-user playlist backend lands.
 */
export function publicPlaylists(): Playlist[] {
  return initialPlaylists().filter((pl) => pl.visibility === "public")
}
