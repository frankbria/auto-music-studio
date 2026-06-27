import { describe, expect, it } from "vitest"

import {
  activeFilterCount,
  applyClientFilters,
  buildClipQuery,
  EMPTY_FILTERS,
  type Clip,
} from "@/lib/workspace-clips"

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "c1",
    workspace_id: "w1",
    title: "Song",
    format: "wav",
    duration: 60,
    bpm: 120,
    key: "C",
    style_tags: [],
    lyrics: null,
    vocal_language: null,
    model: null,
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: "generate",
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

describe("buildClipQuery", () => {
  it("includes only the params that are set", () => {
    expect(buildClipQuery({ workspace_id: "w1", page: 2 })).toBe(
      "workspace_id=w1&page=2"
    )
  })

  it("trims search and omits it when blank", () => {
    expect(buildClipQuery({ search: "  lofi  " })).toBe("search=lofi")
    expect(buildClipQuery({ search: "   " })).toBe("")
  })

  it("serializes sort and per_page", () => {
    expect(buildClipQuery({ sort: "oldest", per_page: 20 })).toBe(
      "sort=oldest&per_page=20"
    )
  })
})

describe("activeFilterCount", () => {
  it("counts enabled toggles", () => {
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0)
    expect(activeFilterCount({ liked: true, public: false, uploads: true })).toBe(2)
  })
})

describe("applyClientFilters", () => {
  const clips = [
    clip({ id: "a", is_public: true, generation_mode: "generate" }),
    clip({ id: "b", is_public: false, generation_mode: "upload" }),
    clip({ id: "c", is_public: true, generation_mode: "upload" }),
  ]

  it("returns all clips when no filter is active", () => {
    expect(applyClientFilters(clips, EMPTY_FILTERS, [])).toHaveLength(3)
  })

  it("narrows to liked clips using the likedIds set", () => {
    const out = applyClientFilters(clips, { ...EMPTY_FILTERS, liked: true }, ["c"])
    expect(out.map((c) => c.id)).toEqual(["c"])
  })

  it("narrows to public clips", () => {
    const out = applyClientFilters(clips, { ...EMPTY_FILTERS, public: true }, [])
    expect(out.map((c) => c.id)).toEqual(["a", "c"])
  })

  it("narrows to uploads via generation_mode", () => {
    const out = applyClientFilters(clips, { ...EMPTY_FILTERS, uploads: true }, [])
    expect(out.map((c) => c.id)).toEqual(["b", "c"])
  })

  it("AND-combines active toggles", () => {
    const out = applyClientFilters(
      clips,
      { liked: true, public: true, uploads: true },
      ["c"]
    )
    expect(out.map((c) => c.id)).toEqual(["c"])
  })
})
