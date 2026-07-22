import { describe, expect, it } from "vitest"

import {
  getProfileByHandle,
  profileClips,
  publicPlaylists,
} from "@/lib/profiles"

describe("profiles mock service", () => {
  it("looks up a profile by bare or @-prefixed handle, any case", () => {
    const a = getProfileByHandle("nova")
    const b = getProfileByHandle("@Nova")
    expect(a).not.toBeNull()
    expect(a).toBe(b)
    expect(a?.display_name).toBe("Nova Bloom")
    expect(a?.handle).toBe("nova")
  })

  it("returns null for an unknown handle (route → notFound)", () => {
    expect(getProfileByHandle("nobody")).toBeNull()
    expect(getProfileByHandle("@ghost")).toBeNull()
  })

  it("resolves published clips against the Explore pool in declared order", () => {
    const nova = getProfileByHandle("nova")!
    const clips = profileClips(nova)
    expect(clips.map((c) => c.id)).toEqual(nova.clip_ids)
    // Every id resolved to a real Clip (no gaps from stale ids).
    expect(clips).toHaveLength(nova.clip_ids.length)
    expect(clips.every((c) => c.title)).toBe(true)
  })

  it("shows only public playlists (AC5)", () => {
    const lists = publicPlaylists()
    expect(lists.length).toBeGreaterThan(0)
    expect(lists.every((pl) => pl.visibility === "public")).toBe(true)
  })
})
