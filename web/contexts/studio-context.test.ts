import { describe, expect, it } from "vitest"

import {
  initialStudioState,
  studioReducer,
  type StudioState,
} from "@/contexts/studio-context"
import { TRACK_TYPES, TRACK_TYPE_ORDER } from "@/lib/track-types"

const base = (over: Partial<StudioState> = {}): StudioState => ({
  ...initialStudioState,
  ...over,
})

describe("studioReducer tracks", () => {
  it("ADD_TRACK appends a track typed with the requested track type and its color", () => {
    const s1 = studioReducer(base(), {
      type: "ADD_TRACK",
      id: "t1",
      trackType: "ai",
    })
    expect(s1.tracks).toHaveLength(1)
    expect(s1.tracks[0]).toMatchObject({
      id: "t1",
      name: "Track 1",
      trackType: "ai",
      color: TRACK_TYPES.ai.color,
      clips: [],
    })

    const s2 = studioReducer(s1, {
      type: "ADD_TRACK",
      id: "t2",
      trackType: "loop",
    })
    expect(s2.tracks).toHaveLength(2)
    expect(s2.tracks[1].name).toBe("Track 2")
    expect(s2.tracks[1]).toMatchObject({
      trackType: "loop",
      color: TRACK_TYPES.loop.color,
    })
  })

  it("all four track types can be created (US-19.2 acceptance)", () => {
    let s = base()
    for (const [i, trackType] of TRACK_TYPE_ORDER.entries()) {
      s = studioReducer(s, { type: "ADD_TRACK", id: `t${i}`, trackType })
    }
    expect(s.tracks.map((t) => t.trackType)).toEqual(TRACK_TYPE_ORDER)
  })

  it("ADD_TRACK honors an explicit name/color", () => {
    const s = studioReducer(base(), {
      type: "ADD_TRACK",
      id: "t1",
      trackType: "audio",
      name: "Drums",
      color: "#ff0000",
    })
    expect(s.tracks[0]).toMatchObject({ name: "Drums", color: "#ff0000" })
  })

  it("REMOVE_TRACK drops the matching track", () => {
    let s = studioReducer(base(), { type: "ADD_TRACK", id: "t1", trackType: "ai" })
    s = studioReducer(s, { type: "ADD_TRACK", id: "t2", trackType: "ai" })
    s = studioReducer(s, { type: "REMOVE_TRACK", trackId: "t1" })
    expect(s.tracks.map((t) => t.id)).toEqual(["t2"])
  })

  it("RENAME_TRACK updates the matching track's name", () => {
    let s = studioReducer(base(), { type: "ADD_TRACK", id: "t1", trackType: "ai" })
    s = studioReducer(s, { type: "ADD_TRACK", id: "t2", trackType: "ai" })
    s = studioReducer(s, { type: "RENAME_TRACK", trackId: "t1", name: "Drums" })
    expect(s.tracks[0].name).toBe("Drums")
    expect(s.tracks[1].name).toBe("Track 2")
  })

  it("RENAME_TRACK on an unknown track is a no-op", () => {
    const s = studioReducer(base(), {
      type: "ADD_TRACK",
      id: "t1",
      trackType: "ai",
    })
    expect(
      studioReducer(s, { type: "RENAME_TRACK", trackId: "missing", name: "X" })
    ).toBe(s)
  })
})

describe("studioReducer clips", () => {
  function withTrack(): StudioState {
    return studioReducer(base(), {
      type: "ADD_TRACK",
      id: "t1",
      trackType: "ai",
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
        clipBpm: null,
      },
    ])
  })

  it("ADD_CLIP accepts a clip whose inferred type matches the track and stores its BPM", () => {
    let s = studioReducer(base(), {
      type: "ADD_TRACK",
      id: "loop1",
      trackType: "loop",
    })
    s = studioReducer(s, {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "loop1",
      clipId: "clip-a",
      startSec: 0,
      title: "Loop",
      durationSec: 8,
      generationMode: "sound",
      clipBpm: 90,
    })
    expect(s.tracks[0].clips).toHaveLength(1)
    expect(s.tracks[0].clips[0].clipBpm).toBe(90)
  })

  it("ADD_CLIP rejects a clip whose inferred type mismatches the track (US-19.2 strict typing)", () => {
    let s = studioReducer(base(), {
      type: "ADD_TRACK",
      id: "vocal1",
      trackType: "vocal",
    })
    const before = s
    s = studioReducer(s, {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "vocal1",
      clipId: "clip-a",
      startSec: 0,
      title: "AI song",
      durationSec: 8,
      generationMode: "song",
    })
    expect(s).toBe(before)
    expect(s.tracks[0].clips).toEqual([])
  })

  it("ADD_CLIP with no generationMode is treated as AI-generated (only ai tracks accept it)", () => {
    let s = studioReducer(base(), {
      type: "ADD_TRACK",
      id: "audio1",
      trackType: "audio",
    })
    s = studioReducer(s, {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "audio1",
      clipId: "clip-a",
      startSec: 0,
      title: null,
      durationSec: null,
    })
    expect(s.tracks[0].clips).toEqual([])
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
      {
        id: "p1",
        clipId: "clip-a",
        startSec: 10,
        title: "A",
        durationSec: 5,
        clipBpm: null,
      },
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

  it("MOVE_CLIP across same-type tracks removes from the source and adds to the destination", () => {
    let s = studioReducer(withTrack(), {
      type: "ADD_TRACK",
      id: "t2",
      trackType: "ai",
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
      {
        id: "p1",
        clipId: "clip-a",
        startSec: 3,
        title: "A",
        durationSec: 5,
        clipBpm: null,
      },
    ])
  })

  it("MOVE_CLIP to a different-type track is a no-op (US-19.2 strict typing)", () => {
    let s = studioReducer(withTrack(), {
      type: "ADD_TRACK",
      id: "vocal1",
      trackType: "vocal",
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
    const before = s
    s = studioReducer(s, {
      type: "MOVE_CLIP",
      trackId: "vocal1",
      placementId: "p1",
      startSec: 3,
    })
    expect(s).toBe(before)
    expect(s.tracks[0].clips).toHaveLength(1)
    expect(s.tracks[1].clips).toEqual([])
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

  it("MOVE_CLIP to an unknown destination track is a no-op (doesn't drop the clip)", () => {
    let s = studioReducer(withTrack(), {
      type: "ADD_CLIP",
      id: "p1",
      trackId: "t1",
      clipId: "clip-a",
      startSec: 0,
      title: "A",
      durationSec: 5,
    })
    const before = s
    s = studioReducer(s, {
      type: "MOVE_CLIP",
      trackId: "missing",
      placementId: "p1",
      startSec: 3,
    })
    expect(s).toBe(before)
    expect(s.tracks[0].clips).toEqual([
      {
        id: "p1",
        clipId: "clip-a",
        startSec: 0,
        title: "A",
        durationSec: 5,
        clipBpm: null,
      },
    ])
  })
})

describe("studioReducer project tempo (US-19.2)", () => {
  it("defaults the project tempo to 120 BPM", () => {
    expect(initialStudioState.bpm).toBe(120)
  })

  it("SET_BPM updates the tempo and clamps to the supported range", () => {
    expect(studioReducer(base(), { type: "SET_BPM", bpm: 90 }).bpm).toBe(90)
    expect(studioReducer(base(), { type: "SET_BPM", bpm: 500 }).bpm).toBe(180)
    expect(studioReducer(base(), { type: "SET_BPM", bpm: 10 }).bpm).toBe(60)
  })

  it("SET_BPM ignores a non-finite value", () => {
    expect(studioReducer(base(), { type: "SET_BPM", bpm: NaN }).bpm).toBe(120)
  })

  it("SET_BPM bumps seekEpoch so an in-flight playback reschedules at the new rates", () => {
    const s = studioReducer(base(), { type: "SET_BPM", bpm: 150 })
    expect(s.seekEpoch).toBe(1)
    // An ignored non-finite value must not force a pointless reschedule.
    expect(studioReducer(base(), { type: "SET_BPM", bpm: NaN }).seekEpoch).toBe(0)
  })

  it("SET_BPM is a full no-op when the clamped value equals the current tempo", () => {
    // Re-committing the same value (or clamping into the same value) must not
    // bump seekEpoch — that would audibly restart an in-flight playback.
    const same = studioReducer(base(), { type: "SET_BPM", bpm: 120 })
    expect(same).toBe(initialStudioState)

    const atCeiling = studioReducer(base({ bpm: 180 }), {
      type: "SET_BPM",
      bpm: 999,
    })
    expect(atCeiling.seekEpoch).toBe(0)
    expect(atCeiling.bpm).toBe(180)
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

  it("SET_PLAYHEAD does not bump seekEpoch (the rAF loop's own tick, not a user seek)", () => {
    expect(
      studioReducer(base(), { type: "SET_PLAYHEAD", sec: 5 }).seekEpoch
    ).toBe(0)
  })

  it("SEEK updates the playhead, clamps to non-negative, and bumps seekEpoch", () => {
    const s1 = studioReducer(base(), { type: "SEEK", sec: 12.5 })
    expect(s1.playheadSec).toBe(12.5)
    expect(s1.seekEpoch).toBe(1)

    const s2 = studioReducer(s1, { type: "SEEK", sec: -5 })
    expect(s2.playheadSec).toBe(0)
    expect(s2.seekEpoch).toBe(2)
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
