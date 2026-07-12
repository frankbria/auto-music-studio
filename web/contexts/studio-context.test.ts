import { describe, expect, it } from "vitest"

import {
  initialStudioState,
  studioReducer,
  type StudioState,
} from "@/contexts/studio-context"

const base = (over: Partial<StudioState> = {}): StudioState => ({
  ...initialStudioState,
  ...over,
})

describe("studioReducer tracks", () => {
  it("ADD_TRACK appends a track with a generated name and cycling color", () => {
    const s1 = studioReducer(base(), { type: "ADD_TRACK", id: "t1" })
    expect(s1.tracks).toHaveLength(1)
    expect(s1.tracks[0]).toMatchObject({ id: "t1", name: "Track 1", clips: [] })
    expect(s1.tracks[0].color).toBeTruthy()

    const s2 = studioReducer(s1, { type: "ADD_TRACK", id: "t2" })
    expect(s2.tracks).toHaveLength(2)
    expect(s2.tracks[1].name).toBe("Track 2")
    // Distinct per-track colors (plan requirement).
    expect(s2.tracks[1].color).not.toBe(s2.tracks[0].color)
  })

  it("ADD_TRACK honors an explicit name/color", () => {
    const s = studioReducer(base(), {
      type: "ADD_TRACK",
      id: "t1",
      name: "Drums",
      color: "#ff0000",
    })
    expect(s.tracks[0]).toMatchObject({ name: "Drums", color: "#ff0000" })
  })

  it("REMOVE_TRACK drops the matching track", () => {
    let s = studioReducer(base(), { type: "ADD_TRACK", id: "t1" })
    s = studioReducer(s, { type: "ADD_TRACK", id: "t2" })
    s = studioReducer(s, { type: "REMOVE_TRACK", trackId: "t1" })
    expect(s.tracks.map((t) => t.id)).toEqual(["t2"])
  })
})

describe("studioReducer clips", () => {
  function withTrack(): StudioState {
    return studioReducer(base(), {
      type: "ADD_TRACK",
      id: "t1",
      name: "Track 1",
    })
  }

  it("ADD_CLIP places a clip on the given track", () => {
    const s = studioReducer(withTrack(), {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "t1",
      clipId: "clip-a",
      startSec: 4,
      title: "My Clip",
      durationSec: 12,
    })
    expect(s.tracks[0].clips).toEqual([
      {
        id: "p1",
        clipId: "clip-a",
        startSec: 4,
        title: "My Clip",
        durationSec: 12,
      },
    ])
  })

  it("ADD_CLIP on an unknown track is a no-op", () => {
    const s = withTrack()
    const next = studioReducer(s, {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "missing",
      clipId: "clip-a",
      startSec: 0,
      title: null,
      durationSec: null,
    })
    expect(next.tracks[0].clips).toEqual([])
  })

  it("MOVE_CLIP repositions a clip within the same track", () => {
    let s = studioReducer(withTrack(), {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "t1",
      clipId: "clip-a",
      startSec: 0,
      title: "A",
      durationSec: 5,
    })
    s = studioReducer(s, {
      type: "MOVE_CLIP",
      trackId: "t1",
      placementId: "p1",
      startSec: 10,
    })
    expect(s.tracks[0].clips).toEqual([
      { id: "p1", clipId: "clip-a", startSec: 10, title: "A", durationSec: 5 },
    ])
  })

  it("MOVE_CLIP clamps to a non-negative start", () => {
    let s = studioReducer(withTrack(), {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "t1",
      clipId: "clip-a",
      startSec: 5,
      title: "A",
      durationSec: 5,
    })
    s = studioReducer(s, {
      type: "MOVE_CLIP",
      trackId: "t1",
      placementId: "p1",
      startSec: -3,
    })
    expect(s.tracks[0].clips[0].startSec).toBe(0)
  })

  it("MOVE_CLIP across tracks removes from the source and adds to the destination", () => {
    let s = studioReducer(withTrack(), {
      type: "ADD_TRACK",
      id: "t2",
      name: "Track 2",
    })
    s = studioReducer(s, {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "t1",
      clipId: "clip-a",
      startSec: 0,
      title: "A",
      durationSec: 5,
    })
    s = studioReducer(s, {
      type: "MOVE_CLIP",
      trackId: "t2",
      placementId: "p1",
      startSec: 3,
    })
    expect(s.tracks[0].clips).toEqual([])
    expect(s.tracks[1].clips).toEqual([
      { id: "p1", clipId: "clip-a", startSec: 3, title: "A", durationSec: 5 },
    ])
  })

  it("MOVE_CLIP with an unknown placement id is a no-op", () => {
    const s = withTrack()
    expect(
      studioReducer(s, {
        type: "MOVE_CLIP",
        trackId: "t1",
        placementId: "missing",
        startSec: 3,
      })
    ).toBe(s)
  })
})

describe("studioReducer transport + view state", () => {
  it("SET_PLAYHEAD updates and clamps to non-negative", () => {
    expect(
      studioReducer(base(), { type: "SET_PLAYHEAD", sec: 12.5 }).playheadSec
    ).toBe(12.5)
    expect(
      studioReducer(base(), { type: "SET_PLAYHEAD", sec: -5 }).playheadSec
    ).toBe(0)
  })

  it("SET_PLAYING toggles isPlaying", () => {
    expect(
      studioReducer(base(), { type: "SET_PLAYING", playing: true }).isPlaying
    ).toBe(true)
    expect(
      studioReducer(base({ isPlaying: true }), {
        type: "SET_PLAYING",
        playing: false,
      }).isPlaying
    ).toBe(false)
  })

  it("SET_ZOOM clamps to the supported zoom range", () => {
    expect(studioReducer(base(), { type: "SET_ZOOM", zoom: 2 }).zoom).toBe(2)
    expect(studioReducer(base(), { type: "SET_ZOOM", zoom: 100 }).zoom).toBe(4)
    expect(studioReducer(base(), { type: "SET_ZOOM", zoom: 0.01 }).zoom).toBe(
      0.25
    )
  })

  it("TOGGLE_DISPLAY_MODE flips between bars-beats and mm-ss", () => {
    const s1 = studioReducer(base(), { type: "TOGGLE_DISPLAY_MODE" })
    expect(s1.displayMode).toBe("mm-ss")
    const s2 = studioReducer(s1, { type: "TOGGLE_DISPLAY_MODE" })
    expect(s2.displayMode).toBe("bars-beats")
  })
})
