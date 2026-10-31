import { afterEach, describe, expect, it, vi } from "vitest"

import { clipInspirationHref, FEED_PAGE_SIZE, getFeedPage } from "@/lib/feed"
import { makeClip } from "@/test/clip-factory"
import { clipRequests, discoverPage } from "@/test/discover-api"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("getFeedPage", () => {
  it("requests the newest public clips, one page at a time", async () => {
    const fetchMock = vi.fn(async () => discoverPage([]))
    vi.stubGlobal("fetch", fetchMock)

    await getFeedPage()
    await getFeedPage("c2")

    expect(clipRequests(fetchMock)).toEqual([
      { sort: "newest", limit: String(FEED_PAGE_SIZE) },
      { sort: "newest", limit: String(FEED_PAGE_SIZE), cursor: "c2" },
    ])
  })

  it("gives each item its own stream URL and passes next_cursor on", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(discoverPage([makeClip({ id: "a b" })], "c2"))
    )

    const page = await getFeedPage()

    expect(page.items[0].audioUrl).toBe("/api/clips/a%20b/stream")
    expect(page.items[0].id).toBe("a b")
    expect(page.nextCursor).toBe("c2")
  })
})

describe("clipInspirationHref", () => {
  it("links to Create with the clip as inspiration", () => {
    const item = { ...makeClip({ id: "c1", title: "Neon" }), audioUrl: "" }
    const q = new URLSearchParams(clipInspirationHref(item).split("?")[1])
    expect(clipInspirationHref(item).startsWith("/create?")).toBe(true)
    expect(q.get("inspiration")).toBe("c1")
    expect(q.get("inspirationName")).toBe("Neon")
  })
})
