import { describe, expect, it } from "vitest"

import {
  addClip,
  buildInspirationHref,
  buildShareUrl,
  coverClips,
  createPlaylist,
  initialPlaylists,
  MOSAIC_SLOTS,
  playlistClips,
  removeClip,
  renamePlaylist,
  reorderClips,
  setCover,
  setVisibility,
  type Playlist,
} from "@/lib/playlists"

const base = (): Playlist => ({
  id: "pl-test",
  name: "Test",
  description: null,
  visibility: "private",
  clipIds: ["a", "b", "c"],
  coverDataUrl: null,
  createdAt: "2026-07-20T00:00:00Z",
})

describe("createPlaylist", () => {
  it("creates an empty private playlist and trims fields", () => {
    const pl = createPlaylist("  My Mix  ", "  vibes  ")
    expect(pl.name).toBe("My Mix")
    expect(pl.description).toBe("vibes")
    expect(pl.visibility).toBe("private")
    expect(pl.clipIds).toEqual([])
    expect(pl.coverDataUrl).toBeNull()
    expect(pl.id).toMatch(/^pl-/)
  })

  it("stores an empty description as null", () => {
    expect(createPlaylist("Solo").description).toBeNull()
  })
})

describe("renamePlaylist", () => {
  it("updates name and description without mutating the original", () => {
    const pl = base()
    const next = renamePlaylist(pl, " Renamed ", "desc")
    expect(next.name).toBe("Renamed")
    expect(next.description).toBe("desc")
    expect(pl.name).toBe("Test") // original untouched
  })
})

describe("setVisibility", () => {
  it("toggles visibility", () => {
    expect(setVisibility(base(), "public").visibility).toBe("public")
  })
})

describe("addClip / removeClip", () => {
  it("appends a new clip", () => {
    expect(addClip(base(), "d").clipIds).toEqual(["a", "b", "c", "d"])
  })

  it("ignores duplicates (each song appears once)", () => {
    const pl = base()
    expect(addClip(pl, "b")).toBe(pl) // same reference, no change
  })

  it("removes a clip", () => {
    expect(removeClip(base(), "b").clipIds).toEqual(["a", "c"])
  })
})

describe("reorderClips", () => {
  it("moves an item down", () => {
    expect(reorderClips(base(), 0, 2).clipIds).toEqual(["b", "c", "a"])
  })

  it("moves an item up", () => {
    expect(reorderClips(base(), 2, 0).clipIds).toEqual(["c", "a", "b"])
  })

  it("preserves the set — no additions or removals", () => {
    const next = reorderClips(base(), 0, 1)
    expect([...next.clipIds].sort()).toEqual(["a", "b", "c"])
  })

  it("is a no-op for out-of-range or identical indices", () => {
    const pl = base()
    expect(reorderClips(pl, 0, 0)).toBe(pl)
    expect(reorderClips(pl, -1, 2)).toBe(pl)
    expect(reorderClips(pl, 0, 9)).toBe(pl)
  })
})

describe("setCover", () => {
  it("sets and clears the custom cover", () => {
    expect(setCover(base(), "data:x").coverDataUrl).toBe("data:x")
    expect(setCover(base(), null).coverDataUrl).toBeNull()
  })
})

describe("playlistClips / coverClips", () => {
  const pool = [
    { id: "x", title: "X" },
    { id: "y", title: "Y" },
    { id: "z", title: "Z" },
  ] as never[]
  const pl: Playlist = { ...base(), clipIds: ["z", "missing", "x"] }

  it("resolves ids to clips in playlist order, dropping unknown ids", () => {
    expect(playlistClips(pl, pool).map((c) => c.id)).toEqual(["z", "x"])
  })

  it("caps cover clips at MOSAIC_SLOTS", () => {
    const many: Playlist = { ...base(), clipIds: ["x", "y", "z", "x", "y"] }
    // dedup not enforced here (ids can repeat in the test pool lookup); just assert cap
    expect(coverClips(many, pool).length).toBeLessThanOrEqual(MOSAIC_SLOTS)
  })
})

describe("initialPlaylists", () => {
  it("seeds playlists that reference real Explore clips", () => {
    const seeds = initialPlaylists()
    expect(seeds.length).toBeGreaterThan(0)
    for (const pl of seeds) {
      // every seeded id must resolve against the real discovery pool
      expect(playlistClips(pl).length).toBe(pl.clipIds.length)
    }
  })
})

describe("url builders", () => {
  it("builds a public share url", () => {
    expect(buildShareUrl("https://app.test", "pl-1")).toBe(
      "https://app.test/playlists/pl-1"
    )
  })

  it("builds an inspiration href with encoded name", () => {
    const href = buildInspirationHref({ ...base(), id: "pl-9", name: "Chill & Focus" })
    expect(href).toContain("/create?")
    const q = new URLSearchParams(href.split("?")[1])
    expect(q.get("inspiration")).toBe("pl-9")
    expect(q.get("inspirationName")).toBe("Chill & Focus")
  })
})
