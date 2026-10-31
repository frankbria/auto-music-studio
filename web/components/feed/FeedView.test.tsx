import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { FeedView } from "@/components/feed/FeedView"
import { PlayerProvider } from "@/contexts/player-context"
import { makeClip } from "@/test/clip-factory"
import { clipRequests, discoverPage } from "@/test/discover-api"

// --- IntersectionObserver mock ---------------------------------------------
// Records every observer instance so tests can fire callbacks for a given target.
type MockInstance = {
  cb: IntersectionObserverCallback
  els: Set<Element>
}
let instances: MockInstance[] = []

class MockIO {
  cb: IntersectionObserverCallback
  els = new Set<Element>()
  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb
    instances.push({ cb, els: this.els })
  }
  observe(el: Element) {
    this.els.add(el)
  }
  unobserve(el: Element) {
    this.els.delete(el)
  }
  disconnect() {
    this.els.clear()
  }
  takeRecords() {
    return []
  }
}

/** Fire an intersection for `el` at `ratio` on whichever observer watches it. */
function fireIntersect(el: Element, ratio: number) {
  const inst = instances.find((i) => i.els.has(el))
  if (!inst) throw new Error("no observer for element")
  act(() => {
    inst.cb(
      [
        {
          target: el,
          isIntersecting: ratio > 0,
          intersectionRatio: ratio,
        } as unknown as IntersectionObserverEntry,
      ],
      inst as unknown as IntersectionObserver
    )
  })
}

const clips = (prefix: string, count: number) =>
  Array.from({ length: count }, (_, i) =>
    makeClip({ id: `${prefix}${i}`, title: `${prefix} ${i}` })
  )

/** Stub fetch with one handler per cursor ("" = first page). */
function stubPages(pages: Record<string, () => Promise<Response> | Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const cursor = new URL(String(input), "http://localhost").searchParams.get(
      "cursor"
    )
    return pages[cursor ?? ""]()
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

beforeEach(() => {
  instances = []
  vi.stubGlobal("IntersectionObserver", MockIO)
  HTMLMediaElement.prototype.play = vi
    .fn()
    .mockResolvedValue(undefined) as unknown as HTMLMediaElement["play"]
  HTMLMediaElement.prototype.pause =
    vi.fn() as unknown as HTMLMediaElement["pause"]
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const renderFeed = () =>
  render(
    <PlayerProvider>
      <FeedView />
    </PlayerProvider>
  )

const wrappers = (c: HTMLElement) =>
  Array.from(c.querySelectorAll<HTMLElement>("[data-key]"))
const items = () => screen.getAllByTestId("feed-item")
const sentinel = (c: HTMLElement) =>
  c.querySelector('[data-testid="feed-sentinel"]')!

describe("FeedView", () => {
  it("shows a loader, then the newest public clips (AC1)", async () => {
    const fetchMock = stubPages({ "": () => discoverPage(clips("a", 3), "c2") })
    renderFeed()
    expect(screen.getByText("Loading feed")).toBeInTheDocument()

    expect(await screen.findAllByTestId("feed-item")).toHaveLength(3)
    expect(clipRequests(fetchMock)).toEqual([{ sort: "newest", limit: "5" }])
  })

  it("marks the first item active by default, then follows the most-visible one (AC2)", async () => {
    stubPages({ "": () => discoverPage(clips("a", 3)) })
    const { container } = renderFeed()
    await screen.findAllByTestId("feed-item")
    expect(items()[0]).toHaveAttribute("data-active", "true")

    fireIntersect(wrappers(container)[1], 0.9)
    expect(items()[1]).toHaveAttribute("data-active", "true")
    expect(items()[0]).toHaveAttribute("data-active", "false")
  })

  it("fetches the next cursor once when the sentinel is reached, and appends it (AC5)", async () => {
    let releasePage2 = () => {}
    const fetchMock = stubPages({
      "": () => discoverPage(clips("a", 2), "c2"),
      c2: () =>
        new Promise((resolve) => {
          releasePage2 = () => resolve(discoverPage(clips("b", 2), null))
        }),
    })
    const { container } = renderFeed()
    await screen.findAllByTestId("feed-item")

    fireIntersect(sentinel(container), 1)
    fireIntersect(sentinel(container), 1)
    await act(async () => releasePage2())

    expect(items()).toHaveLength(4)
    expect(clipRequests(fetchMock).map((q) => q.cursor)).toEqual([
      undefined,
      "c2",
    ])
  })

  it("stops paging when next_cursor is null", async () => {
    stubPages({ "": () => discoverPage(clips("a", 2), null) })
    renderFeed()
    await screen.findAllByTestId("feed-item")
    expect(screen.queryByTestId("feed-sentinel")).not.toBeInTheDocument()
  })

  it("shows an empty state when there are no public clips", async () => {
    stubPages({ "": () => discoverPage([]) })
    renderFeed()
    expect(await screen.findByText("No public songs yet")).toBeInTheDocument()
  })

  it("shows an error and retries the first page", async () => {
    let fail = true
    stubPages({
      "": () =>
        fail
          ? new Response("{}", { status: 502 })
          : discoverPage(clips("a", 1)),
    })
    renderFeed()
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load the feed."
    )

    fail = false
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findAllByTestId("feed-item")).toHaveLength(1)
  })

  it("keeps loaded items when a later page fails, and retries that cursor", async () => {
    let fail = true
    const fetchMock = stubPages({
      "": () => discoverPage(clips("a", 2), "c2"),
      c2: () =>
        fail
          ? new Response("{}", { status: 502 })
          : discoverPage(clips("b", 1), null),
    })
    const { container } = renderFeed()
    await screen.findAllByTestId("feed-item")

    fireIntersect(sentinel(container), 1)
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(items()).toHaveLength(2)
    expect(screen.queryByTestId("feed-sentinel")).not.toBeInTheDocument()

    fail = false
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    await screen.findByRole("region", { name: "b 0" })
    expect(items()).toHaveLength(3)
    expect(clipRequests(fetchMock).map((q) => q.cursor)).toEqual([
      undefined,
      "c2",
      "c2",
    ])
  })
})
