import { describe, expect, it } from "vitest"

import {
  buildDawExportRequest,
  buildMixdownRequest,
  buildStudioExportBody,
} from "@/lib/studio-export"
import { initialStudioState, type StudioTrack } from "@/contexts/studio-context"
import type { Placement } from "@/lib/timeline"

function placement(over: Partial<Placement> = {}): Placement {
  return {
    id: "p1",
    clipId: "c1",
    startSec: 0,
    title: "Clip",
    durationSec: 12,
    clipBpm: null,
    ...over,
  }
}

function track(over: Partial<StudioTrack> = {}): StudioTrack {
  return {
    id: "t1",
    name: "Vocals",
    trackType: "vocal",
    color: "#fff",
    volumeDb: 0,
    pan: 0,
    muted: false,
    solo: false,
    clips: [placement()],
    ...over,
  }
}

const opts = { workspaceId: "w1", projectName: "My Song" }

describe("buildStudioExportBody", () => {
  it("carries workspace, project name, and bpm", () => {
    const state = { ...initialStudioState, bpm: 128, tracks: [track()] }
    const body = buildStudioExportBody(state, opts)
    expect(body.workspace_id).toBe("w1")
    expect(body.project_name).toBe("My Song")
    expect(body.bpm).toBe(128)
  })

  it("maps a track's audio fields and converts pan from -100..100 to -1..1", () => {
    const state = {
      ...initialStudioState,
      tracks: [
        track({ name: "Lead", trackType: "ai", volumeDb: -6, pan: 50, muted: true, solo: false }),
      ],
    }
    const [t] = buildStudioExportBody(state, opts).tracks
    expect(t).toMatchObject({
      name: "Lead",
      track_type: "ai",
      volume_db: -6,
      pan: 0.5,
      muted: true,
      solo: false,
    })
  })

  it("maps placements to clip_id/start_sec/duration_sec", () => {
    const state = {
      ...initialStudioState,
      tracks: [
        track({
          clips: [placement({ clipId: "cX", startSec: 4, durationSec: 30 })],
        }),
      ],
    }
    const [t] = buildStudioExportBody(state, opts).tracks
    expect(t.placements).toEqual([
      { clip_id: "cX", start_sec: 4, duration_sec: 30 },
    ])
  })

  it("preserves a null duration on an open-ended placement", () => {
    const state = {
      ...initialStudioState,
      tracks: [track({ clips: [placement({ durationSec: null })] })],
    }
    expect(buildStudioExportBody(state, opts).tracks[0].placements[0].duration_sec).toBeNull()
  })

  it("drops empty tracks (no placements)", () => {
    const state = {
      ...initialStudioState,
      tracks: [
        track({ id: "t1", clips: [placement()] }),
        track({ id: "t2", name: "Empty", clips: [] }),
      ],
    }
    const body = buildStudioExportBody(state, opts)
    expect(body.tracks).toHaveLength(1)
    expect(body.tracks[0].name).toBe("Vocals")
  })

  it("maps markers to name/time_sec", () => {
    const state = {
      ...initialStudioState,
      tracks: [track()],
      markers: [
        { id: "m1", sec: 8, label: "Chorus" },
        { id: "m2", sec: 16, label: "Bridge" },
      ],
    }
    expect(buildStudioExportBody(state, opts).markers).toEqual([
      { name: "Chorus", time_sec: 8 },
      { name: "Bridge", time_sec: 16 },
    ])
  })
})

describe("buildMixdownRequest", () => {
  it("adds the chosen format to the export body", () => {
    const state = { ...initialStudioState, tracks: [track()] }
    const body = buildMixdownRequest(state, { ...opts, format: "flac" })
    expect(body.format).toBe("flac")
    expect(body.workspace_id).toBe("w1")
    expect(body.tracks).toHaveLength(1)
  })
})

describe("buildDawExportRequest", () => {
  it("produces the export body without a format field", () => {
    const state = { ...initialStudioState, tracks: [track()] }
    const body = buildDawExportRequest(state, opts)
    expect(body).not.toHaveProperty("format")
    expect(body.tracks).toHaveLength(1)
  })
})
