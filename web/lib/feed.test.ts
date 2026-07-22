import { describe, expect, it } from "vitest"

import {
  artistForClip,
  clipInspirationHref,
  FEED_AUDIO_URL,
  FEED_MAX_PAGES,
  FEED_PAGE_SIZE,
  getFeedPage,
} from "@/lib/feed"

describe("artistForClip", () => {
  it("is deterministic for a given id", () => {
    expect(artistForClip("clip-neon")).toBe(artistForClip("clip-neon"))
  })

  it("always returns a non-empty name", () => {
    for (const id of ["clip-neon", "clip-gold", "x", ""]) {
      expect(artistForClip(id).length).toBeGreaterThan(0)
    }
  })
})

describe("getFeedPage", () => {
  it("returns a full page of items with real clip ids and shared audio", () => {
    const { items } = getFeedPage(1)
    expect(items).toHaveLength(FEED_PAGE_SIZE)
    for (const item of items) {
      expect(item.id).toMatch(/^clip-/) // real clip id preserved for actions
      expect(item.audioUrl).toBe(FEED_AUDIO_URL)
      expect(item.artist).toBeTruthy()
    }
  })

  it("gives every item a unique render key across pages", () => {
    const keys = new Set<string>()
    for (let p = 1; p <= FEED_MAX_PAGES; p++) {
      for (const item of getFeedPage(p).items) keys.add(item.key)
    }
    expect(keys.size).toBe(FEED_PAGE_SIZE * FEED_MAX_PAGES)
  })

  it("reports hasMore until the last page (infinite scroll terminates)", () => {
    expect(getFeedPage(1).hasMore).toBe(true)
    expect(getFeedPage(FEED_MAX_PAGES).hasMore).toBe(false)
  })

  it("clamps out-of-range pages", () => {
    expect(getFeedPage(0).page).toBe(1)
    expect(getFeedPage(999).page).toBe(FEED_MAX_PAGES)
  })

  it("cycles the pool so later pages still have items", () => {
    expect(getFeedPage(FEED_MAX_PAGES).items).toHaveLength(FEED_PAGE_SIZE)
  })
})

describe("clipInspirationHref", () => {
  it("links to Create with the clip as inspiration", () => {
    const item = getFeedPage(1).items[0]
    const href = clipInspirationHref(item)
    const q = new URLSearchParams(href.split("?")[1])
    expect(href.startsWith("/create?")).toBe(true)
    expect(q.get("inspiration")).toBe(item.id)
    expect(q.get("inspirationName")).toBe(item.title ?? "Untitled clip")
  })
})
