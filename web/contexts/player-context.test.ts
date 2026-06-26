import { describe, expect, it } from "vitest"

import {
  initialPlayerState,
  playerReducer,
  type PlayerState,
} from "@/contexts/player-context"
import type { Track } from "@/lib/clips"

const track = (id: string): Track => ({
  id,
  title: `Track ${id}`,
  artist: "Artist",
  audioUrl: `/demo/${id}.wav`,
})

const base = (over: Partial<PlayerState> = {}): PlayerState => ({
  ...initialPlayerState,
  ...over,
})

describe("playerReducer transport", () => {
  it("play/track sets current, plays, and pushes outgoing to history", () => {
    const s1 = playerReducer(base(), { type: "play/track", track: track("a") })
    expect(s1.current?.id).toBe("a")
    expect(s1.isPlaying).toBe(true)
    const s2 = playerReducer(s1, { type: "play/track", track: track("b") })
    expect(s2.current?.id).toBe("b")
    expect(s2.history.map((t) => t.id)).toEqual(["a"])
  })

  it("toggle is a no-op without a current track", () => {
    expect(playerReducer(base(), { type: "toggle" }).isPlaying).toBe(false)
  })

  it("toggle flips play state when a track is loaded", () => {
    const s = base({ current: track("a"), isPlaying: false })
    expect(playerReducer(s, { type: "toggle" }).isPlaying).toBe(true)
  })

  it("play/queue starts at the given index and queues the rest", () => {
    const s = playerReducer(base(), {
      type: "play/queue",
      tracks: [track("a"), track("b"), track("c")],
      startIndex: 1,
    })
    expect(s.current?.id).toBe("b")
    expect(s.queue.map((t) => t.id)).toEqual(["a", "c"])
  })
})

describe("playerReducer next/previous", () => {
  it("next advances to the head of the queue", () => {
    const s = base({ current: track("a"), queue: [track("b"), track("c")] })
    const n = playerReducer(s, { type: "next" })
    expect(n.current?.id).toBe("b")
    expect(n.queue.map((t) => t.id)).toEqual(["c"])
    expect(n.history.map((t) => t.id)).toEqual(["a"])
  })

  it("next with an empty queue and repeat=off stops playback", () => {
    const s = base({ current: track("a"), queue: [], duration: 30 })
    const n = playerReducer(s, { type: "next" })
    expect(n.isPlaying).toBe(false)
    expect(n.current?.id).toBe("a")
  })

  it("next with repeat=all rebuilds the queue from history", () => {
    const s = base({
      current: track("c"),
      history: [track("a"), track("b")],
      queue: [],
      repeatMode: "all",
    })
    const n = playerReducer(s, { type: "next" })
    expect(n.current?.id).toBe("a")
    expect(n.queue.map((t) => t.id)).toEqual(["b", "c"])
    expect(n.history).toEqual([])
  })

  it("previous restarts the track when past 3s", () => {
    const s = base({
      current: track("b"),
      currentTime: 10,
      history: [track("a")],
    })
    const p = playerReducer(s, { type: "previous" })
    expect(p.current?.id).toBe("b")
    expect(p.seekRequest).toBe(0)
  })

  it("previous steps back when near the start", () => {
    const s = base({
      current: track("b"),
      currentTime: 1,
      history: [track("a")],
      queue: [],
    })
    const p = playerReducer(s, { type: "previous" })
    expect(p.current?.id).toBe("a")
    expect(p.queue.map((t) => t.id)).toEqual(["b"])
  })
})

describe("playerReducer ended", () => {
  it("repeat=one replays the current track", () => {
    const s = base({ current: track("a"), repeatMode: "one" })
    const e = playerReducer(s, { type: "ended" })
    expect(e.current?.id).toBe("a")
    expect(e.seekRequest).toBe(0)
    expect(e.isPlaying).toBe(true)
  })

  it("repeat=off advances then stops at the end of the queue", () => {
    const s = base({ current: track("a"), queue: [], duration: 12 })
    const e = playerReducer(s, { type: "ended" })
    expect(e.isPlaying).toBe(false)
    expect(e.currentTime).toBe(12)
  })
})

describe("playerReducer volume + mute", () => {
  it("mute stores volume, then restores on unmute", () => {
    const s = base({ volume: 0.6 })
    const muted = playerReducer(s, { type: "mute/toggle" })
    expect(muted.isMuted).toBe(true)
    expect(muted.previousVolume).toBe(0.6)
    const unmuted = playerReducer(muted, { type: "mute/toggle" })
    expect(unmuted.isMuted).toBe(false)
    expect(unmuted.volume).toBe(0.6)
  })

  it("setting volume clamps and unmutes", () => {
    const s = base({ isMuted: true, volume: 0 })
    const v = playerReducer(s, { type: "volume/set", volume: 1.4 })
    expect(v.volume).toBe(1)
    expect(v.isMuted).toBe(false)
  })
})

describe("playerReducer queue management", () => {
  it("adds to the end and to the front", () => {
    let s = base({ queue: [track("a")] })
    s = playerReducer(s, { type: "queue/add", track: track("b") })
    expect(s.queue.map((t) => t.id)).toEqual(["a", "b"])
    s = playerReducer(s, { type: "queue/addNext", track: track("c") })
    expect(s.queue.map((t) => t.id)).toEqual(["c", "a", "b"])
  })

  it("removes and reorders queue items", () => {
    let s = base({ queue: [track("a"), track("b"), track("c")] })
    s = playerReducer(s, { type: "queue/reorder", from: 0, to: 2 })
    expect(s.queue.map((t) => t.id)).toEqual(["b", "c", "a"])
    s = playerReducer(s, { type: "queue/remove", index: 1 })
    expect(s.queue.map((t) => t.id)).toEqual(["b", "a"])
  })

  it("ignores out-of-range reorder", () => {
    const s = base({ queue: [track("a"), track("b")] })
    expect(playerReducer(s, { type: "queue/reorder", from: 0, to: 9 })).toBe(s)
  })
})

describe("playerReducer modes + likes", () => {
  it("cycles repeat off -> all -> one -> off", () => {
    let s = base()
    s = playerReducer(s, { type: "repeat/cycle" })
    expect(s.repeatMode).toBe("all")
    s = playerReducer(s, { type: "repeat/cycle" })
    expect(s.repeatMode).toBe("one")
    s = playerReducer(s, { type: "repeat/cycle" })
    expect(s.repeatMode).toBe("off")
  })

  it("toggles like state for a track id", () => {
    let s = base()
    s = playerReducer(s, { type: "like/toggle", id: "x" })
    expect(s.likedIds).toContain("x")
    s = playerReducer(s, { type: "like/toggle", id: "x" })
    expect(s.likedIds).not.toContain("x")
  })
})
