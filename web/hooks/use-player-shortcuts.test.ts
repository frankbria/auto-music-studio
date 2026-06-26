import { describe, expect, it } from "vitest"

import { playerShortcutAction } from "@/hooks/use-player-shortcuts"
import { initialPlayerState, type PlayerState } from "@/contexts/player-context"
import type { Track } from "@/lib/clips"

const track: Track = { id: "a", title: "A", artist: "x", audioUrl: "/a.wav" }
const state = (over: Partial<PlayerState> = {}): PlayerState => ({
  ...initialPlayerState,
  current: track,
  ...over,
})

describe("playerShortcutAction", () => {
  it("returns null when no track is loaded", () => {
    expect(playerShortcutAction(" ", initialPlayerState, null)).toBeNull()
  })

  it("ignores keys while typing in an input", () => {
    const input = document.createElement("input")
    expect(playerShortcutAction(" ", state(), input)).toBeNull()
  })

  it("space toggles play/pause", () => {
    expect(playerShortcutAction(" ", state(), null)).toEqual({ type: "toggle" })
  })

  it("arrows seek by 5s, clamped at 0", () => {
    expect(
      playerShortcutAction("ArrowRight", state({ currentTime: 10 }), null)
    ).toEqual({
      type: "seek/request",
      time: 15,
    })
    expect(
      playerShortcutAction("ArrowLeft", state({ currentTime: 2 }), null)
    ).toEqual({
      type: "seek/request",
      time: 0,
    })
  })

  it("up/down adjust volume by 10%", () => {
    expect(
      playerShortcutAction("ArrowUp", state({ volume: 0.5 }), null)
    ).toEqual({
      type: "volume/set",
      volume: 0.6,
    })
    expect(
      playerShortcutAction("ArrowDown", state({ volume: 0.5 }), null)
    ).toEqual({
      type: "volume/set",
      volume: 0.4,
    })
  })

  it("m toggles mute", () => {
    expect(playerShortcutAction("m", state(), null)).toEqual({
      type: "mute/toggle",
    })
  })
})
