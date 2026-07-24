import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  completeSoundCloudCallback,
  connectSoundCloud,
  disconnectSoundCloud,
  DISTRIBUTION_TARGETS,
  getSoundCloudStatus,
  prepareDistribution,
  targetById,
} from "@/lib/distribution"
import type { ReleaseMetadata } from "@/lib/release-draft"

function metadata(overrides: Partial<ReleaseMetadata> = {}): ReleaseMetadata {
  return {
    title: "Nightfall",
    artist: "AMS",
    album: "",
    genre: "House",
    description: "",
    bpm: 124,
    key: "Am",
    language: "",
    explicit: false,
    releaseDate: "",
    copyright: "",
    credits: { producer: "", songwriter: "", performer: "" },
    coverArt: { kind: "existing" },
    isrc: "US-AMS-25-00001",
    upc: "012345678905",
    lyrics: "",
    ...overrides,
  }
}

function ok(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

beforeEach(() => {
  // jsdom has no URL.createObjectURL; stub it so bundle-building is observable.
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:metadata"),
  })
})
afterEach(() => vi.unstubAllGlobals())

describe("target catalogue", () => {
  it("offers SoundCloud (auto) plus two guided targets with portal URLs", () => {
    expect(DISTRIBUTION_TARGETS.map((t) => t.id)).toEqual([
      "soundcloud",
      "landr",
      "distrokid",
    ])
    expect(targetById("soundcloud")?.kind).toBe("auto")
    expect(targetById("landr")?.portalUrl).toMatch(/landr\.com/)
    expect(targetById("distrokid")?.portalUrl).toMatch(/distrokid\.com/)
  })
})

describe("prepareDistribution", () => {
  it("passes every check and builds a bundle for complete metadata", () => {
    const pkg = prepareDistribution("landr", metadata())
    expect(pkg.allChecksPassed).toBe(true)
    expect(pkg.checklist.every((c) => c.passed)).toBe(true)
    expect(pkg.bundleUrl).toBe("blob:metadata")
    expect(pkg.instructions).toMatch(/LANDR/)
  })

  it("fails and withholds the bundle when required metadata is missing", () => {
    const pkg = prepareDistribution("distrokid", metadata({ title: "", genre: "" }))
    expect(pkg.allChecksPassed).toBe(false)
    expect(pkg.bundleUrl).toBeNull()
    expect(pkg.checklist.find((c) => c.item === "Required metadata")?.passed).toBe(false)
  })

  it("fails the cover-art check when no art is attached", () => {
    const pkg = prepareDistribution("landr", metadata({ coverArt: { kind: "none" } }))
    expect(pkg.checklist.find((c) => c.item === "Cover art")?.passed).toBe(false)
    expect(pkg.allChecksPassed).toBe(false)
  })

  it("fails the ISRC check on a malformed identifier", () => {
    const pkg = prepareDistribution("landr", metadata({ isrc: "not-an-isrc" }))
    expect(pkg.checklist.find((c) => c.item === "ISRC")?.passed).toBe(false)
  })
})

describe("SoundCloud client", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("maps a connected status response into camelCase", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        ok({
          connected: true,
          soundcloud_username: "dj-ams",
          connected_at: "2026-07-01T00:00:00Z",
          token_valid: true,
        })
      )
    )
    const res = await getSoundCloudStatus("tok")
    expect(res).toEqual({
      kind: "ok",
      status: {
        connected: true,
        username: "dj-ams",
        connectedAt: "2026-07-01T00:00:00Z",
        tokenValid: true,
      },
    })
  })

  it("classifies 401 as unauthorized", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ detail: "no" }, 401)))
    expect((await getSoundCloudStatus("tok")).kind).toBe("unauthorized")
  })

  it("returns the authorize URL from connect", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ok({ authorization_url: "https://soundcloud.com/connect?x=1" }))
    )
    const res = await connectSoundCloud("tok")
    expect(res).toEqual({
      kind: "ok",
      authorizationUrl: "https://soundcloud.com/connect?x=1",
    })
  })

  it("surfaces a 503 from connect as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ detail: "not configured" }, 503)))
    const res = await connectSoundCloud("tok")
    expect(res.kind).toBe("unavailable")
  })

  it("classifies a 400 callback as invalid state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ detail: "bad" }, 400)))
    expect((await completeSoundCloudCallback("c", "s", "tok")).kind).toBe("invalid")
  })

  it("treats a 204 disconnect as ok", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 204, json: async () => ({}) })))
    expect((await disconnectSoundCloud("tok")).kind).toBe("ok")
  })
})
