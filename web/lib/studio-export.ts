// Pure builders that turn the studio's in-memory arrangement (StudioState) into
// the request bodies the backend mixdown / DAW-export jobs expect (US-19.6). The
// studio keeps no server-side arrangement, so each export ships the full picture:
// every non-empty track with its clip placements, per-track volume/pan/mute/solo,
// the project tempo, and the section markers. Kept side-effect-free so the hook
// and its tests can build payloads without touching the network.

import type { StudioState, StudioTrack } from "@/contexts/studio-context"
import { panToAudioValue } from "@/lib/track-audio"

/** Output containers the mixdown job can render to (US-19.6). */
export type StudioFormat = "wav" | "flac" | "mp3"

/** The studio has no project-name field yet; a stable default names the mixdown
 * clip and the DAW bundle's ZIP wherever an export is triggered. */
export const DEFAULT_STUDIO_PROJECT_NAME = "Studio Mix"

export type StudioPlacementPayload = {
  clip_id: string
  start_sec: number
  duration_sec: number | null
}

export type StudioTrackPayload = {
  name: string
  track_type: string
  /** Fader level in dB — server applies it to the bounce. */
  volume_db: number
  /** Stereo position in StereoPannerNode units [-1, +1] (converted from UI's [-100, +100]). */
  pan: number
  muted: boolean
  solo: boolean
  placements: StudioPlacementPayload[]
}

export type StudioMarkerPayload = { name: string; time_sec: number }

export type StudioExportBody = {
  workspace_id: string
  project_name: string
  bpm: number | null
  markers: StudioMarkerPayload[]
  tracks: StudioTrackPayload[]
}

export type MixdownRequestBody = StudioExportBody & { format: StudioFormat }

type BuildOpts = { workspaceId: string; projectName: string }

function buildTrackPayload(track: StudioTrack): StudioTrackPayload {
  return {
    name: track.name,
    track_type: track.trackType,
    volume_db: track.volumeDb,
    pan: panToAudioValue(track.pan),
    muted: track.muted,
    solo: track.solo,
    placements: track.clips.map((p) => ({
      clip_id: p.clipId,
      start_sec: p.startSec,
      duration_sec: p.durationSec,
    })),
  }
}

/** The arrangement payload shared by mixdown and DAW export. Empty tracks (no
 * placements) are dropped so the server never bounces silent stems. */
export function buildStudioExportBody(
  state: StudioState,
  { workspaceId, projectName }: BuildOpts
): StudioExportBody {
  return {
    workspace_id: workspaceId,
    project_name: projectName,
    bpm: state.bpm,
    markers: state.markers.map((m) => ({ name: m.label, time_sec: m.sec })),
    tracks: state.tracks
      .filter((t) => t.clips.length > 0)
      .map(buildTrackPayload),
  }
}

/** Mixdown request: the arrangement plus the chosen output format. */
export function buildMixdownRequest(
  state: StudioState,
  opts: BuildOpts & { format: StudioFormat }
): MixdownRequestBody {
  return { ...buildStudioExportBody(state, opts), format: opts.format }
}

/** DAW export request: the arrangement with no format (stems are always WAV). */
export function buildDawExportRequest(
  state: StudioState,
  opts: BuildOpts
): StudioExportBody {
  return buildStudioExportBody(state, opts)
}
