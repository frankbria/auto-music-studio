import { afterEach, describe, expect, it, vi } from "vitest"

import {
  clearDraft,
  coverArtResolutionError,
  generateIsrc,
  generateUpc,
  loadDraft,
  MIN_COVER_ART_PX,
  prefillFromClip,
  saveDraft,
  validateMetadata,
  type ReleaseMetadata,
} from "@/lib/release-draft"
import type { Clip } from "@/lib/workspace-clips"

function makeClip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "clip-1",
    workspace_id: "ws-1",
    title: "Midnight Drive",
    format: "wav",
    duration: 180,
    bpm: 122,
    key: "A minor",
    style_tags: ["synthwave", "retro"],
    lyrics: "neon lights\nempty road",
    vocal_language: "en",
    model: "ace-step",
    seed: 42,
    inference_steps: 30,
    parent_clip_ids: [],
    generation_mode: "text",
    is_public: false,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  }
}

describe("prefillFromClip", () => {
  it("maps clip metadata onto the release form fields", () => {
    const m = prefillFromClip(makeClip())
    expect(m.title).toBe("Midnight Drive")
    expect(m.genre).toBe("synthwave") // first style tag
    expect(m.bpm).toBe(122)
    expect(m.key).toBe("A minor")
    expect(m.language).toBe("en")
    expect(m.lyrics).toBe("neon lights\nempty road")
    expect(m.explicit).toBe(false)
  })

  it("fills sensible blanks for fields the clip has no data for", () => {
    const m = prefillFromClip(makeClip({ title: null, style_tags: [], lyrics: null, bpm: null }))
    expect(m.title).toBe("")
    expect(m.artist).toBe("Unknown artist")
    expect(m.album).toBe("")
    expect(m.genre).toBe("")
    expect(m.lyrics).toBe("")
    expect(m.bpm).toBeNull()
    expect(m.releaseDate).toBe("")
    expect(m.isrc).toBe("")
    expect(m.upc).toBe("")
  })
})

describe("generateIsrc", () => {
  it("produces a well-formed ISRC (CC-XXX-YY-NNNNN)", () => {
    for (let i = 0; i < 50; i++) {
      expect(generateIsrc()).toMatch(/^[A-Z]{2}-[A-Z0-9]{3}-\d{2}-\d{5}$/)
    }
  })
})

describe("generateUpc", () => {
  it("produces 12 digits with a valid UPC-A check digit", () => {
    for (let i = 0; i < 50; i++) {
      const upc = generateUpc()
      expect(upc).toMatch(/^\d{12}$/)
      // UPC-A: 3*(odd positions) + (even positions), mod 10 == 0
      const digits = upc.split("").map(Number)
      const sum = digits.reduce((acc, d, idx) => acc + d * (idx % 2 === 0 ? 3 : 1), 0)
      expect(sum % 10).toBe(0)
    }
  })
})

describe("coverArtResolutionError", () => {
  it("passes art at or above the minimum", () => {
    expect(coverArtResolutionError(MIN_COVER_ART_PX, MIN_COVER_ART_PX)).toBeNull()
    expect(coverArtResolutionError(4000, 4000)).toBeNull()
  })

  it("rejects art below the minimum on either axis", () => {
    expect(coverArtResolutionError(2999, 3000)).toMatch(/3000/)
    expect(coverArtResolutionError(3000, 100)).toMatch(/3000/)
  })
})

describe("validateMetadata", () => {
  const base = (): ReleaseMetadata => prefillFromClip(makeClip())

  it("returns no errors for a fully-populated form", () => {
    expect(validateMetadata(base())).toEqual({})
  })

  it("flags missing required fields", () => {
    const errors = validateMetadata({ ...base(), title: "", artist: "  ", genre: "" })
    expect(errors.title).toBeTruthy()
    expect(errors.artist).toBeTruthy()
    expect(errors.genre).toBeTruthy()
  })

  it("rejects a malformed ISRC but accepts a blank one", () => {
    expect(validateMetadata({ ...base(), isrc: "not-an-isrc" }).isrc).toBeTruthy()
    expect(validateMetadata({ ...base(), isrc: "" }).isrc).toBeUndefined()
    expect(validateMetadata({ ...base(), isrc: generateIsrc() }).isrc).toBeUndefined()
  })

  it("rejects a malformed UPC but accepts a blank one", () => {
    expect(validateMetadata({ ...base(), upc: "123" }).upc).toBeTruthy()
    expect(validateMetadata({ ...base(), upc: "" }).upc).toBeUndefined()
    expect(validateMetadata({ ...base(), upc: generateUpc() }).upc).toBeUndefined()
  })
})

describe("draft persistence", () => {
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it("round-trips a draft by clip id", () => {
    const m = { ...prefillFromClip(makeClip()), album: "Night Sessions" }
    expect(loadDraft("clip-1")).toBeNull()
    saveDraft("clip-1", m)
    expect(loadDraft("clip-1")).toEqual(m)
  })

  it("keeps drafts separate per clip and clears one", () => {
    saveDraft("clip-1", { ...prefillFromClip(makeClip()), title: "One" })
    saveDraft("clip-2", { ...prefillFromClip(makeClip()), title: "Two" })
    expect(loadDraft("clip-1")?.title).toBe("One")
    expect(loadDraft("clip-2")?.title).toBe("Two")
    clearDraft("clip-1")
    expect(loadDraft("clip-1")).toBeNull()
    expect(loadDraft("clip-2")?.title).toBe("Two")
  })

  it("returns null (not a throw) on corrupt stored JSON", () => {
    localStorage.setItem("ams:release-draft:clip-1", "{not json")
    expect(loadDraft("clip-1")).toBeNull()
  })

  it("reports save success/failure instead of throwing when storage is blocked", () => {
    expect(saveDraft("clip-1", prefillFromClip(makeClip()))).toBe(true)
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError")
    })
    expect(saveDraft("clip-1", prefillFromClip(makeClip()))).toBe(false)
    spy.mockRestore()
  })
})
