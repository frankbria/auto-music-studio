// Mock clip pool, read only by the profile and playlist mock seams.

import type { Clip } from "@/lib/workspace-clips"

/** Build a mock public clip; only the fields profiles and playlists show are meaningful. */
function mockClip(
  id: string,
  title: string,
  style_tags: string[],
  created_at: string,
  engagement: { plays: number; likes: number; shares: number },
  extra: Partial<Clip> = {}
): Clip {
  return {
    id,
    workspace_id: null,
    title,
    format: "wav",
    duration: 90 + (engagement.plays % 120),
    bpm: 100 + (engagement.likes % 60),
    key: null,
    style_tags,
    lyrics: null,
    vocal_language: null,
    model: "ace-step-v1",
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: "generate",
    is_public: true,
    created_at,
    is_owner: false,
    play_count: engagement.plays,
    like_count: engagement.likes,
    share_count: engagement.shares,
    ...extra,
  }
}

const TURBO = "ace-step-v1-turbo"
const POOL: Clip[] = [
  mockClip(
    "clip-neon",
    "Neon Skyline",
    ["synthwave", "electronic"],
    "2026-07-19T09:00:00Z",
    { plays: 8200, likes: 640, shares: 210 },
    { key: "A minor", model: TURBO }
  ),
  mockClip(
    "clip-velvet",
    "Velvet Static",
    ["lofi", "chill"],
    "2026-07-19T06:30:00Z",
    { plays: 5400, likes: 980, shares: 90 },
    { key: "C major" }
  ),
  mockClip(
    "clip-emberr",
    "Ember Roads",
    ["rock", "indie"],
    "2026-07-18T22:10:00Z",
    { plays: 12100, likes: 720, shares: 340 },
    { key: "E minor", model: TURBO }
  ),
  mockClip(
    "clip-glass",
    "Glass Cathedral",
    ["classical", "ambient"],
    "2026-07-18T14:00:00Z",
    { plays: 3100, likes: 410, shares: 620 },
    { key: "D major" }
  ),
  mockClip(
    "clip-gold",
    "Gold Rush 88",
    ["hip-hop", "trap"],
    "2026-07-17T20:45:00Z",
    { plays: 15800, likes: 1240, shares: 470 },
    { key: "G minor", model: TURBO }
  ),
  mockClip(
    "clip-tide",
    "Tidal Bloom",
    ["pop", "dance"],
    "2026-07-17T11:20:00Z",
    { plays: 9700, likes: 1580, shares: 260 },
    { key: "C major" }
  ),
  mockClip(
    "clip-brass",
    "Midnight Brass",
    ["jazz", "soul"],
    "2026-07-16T19:05:00Z",
    { plays: 2600, likes: 300, shares: 55 },
    { key: "F major" }
  ),
  mockClip(
    "clip-dust",
    "Dust & Denim",
    ["country", "folk"],
    "2026-07-15T08:15:00Z",
    { plays: 4300, likes: 520, shares: 130 },
    { key: "G major" }
  ),
  mockClip(
    "clip-mono",
    "Monochrome Heart",
    ["rnb", "soul"],
    "2026-07-14T17:40:00Z",
    { plays: 7100, likes: 890, shares: 175 },
    { key: "A minor", model: TURBO }
  ),
  mockClip(
    "clip-pulse",
    "Pulse Theory",
    ["electronic", "techno"],
    "2026-07-13T05:00:00Z",
    { plays: 11200, likes: 610, shares: 400 },
    { key: "D minor" }
  ),
  mockClip(
    "clip-paper",
    "Paper Lanterns",
    ["lofi", "ambient"],
    "2026-07-12T12:30:00Z",
    { plays: 1900, likes: 260, shares: 40 },
    { key: "C major" }
  ),
  mockClip(
    "clip-crown",
    "Crownfall",
    ["rock", "metal"],
    "2026-07-11T21:55:00Z",
    { plays: 6800, likes: 700, shares: 220 },
    { key: "E minor", model: TURBO }
  ),
]

export function getAllClips(): Clip[] {
  return [...POOL]
}
