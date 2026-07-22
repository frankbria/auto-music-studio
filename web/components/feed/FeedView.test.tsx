import { act, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { FeedView } from "@/components/feed/FeedView"
import { PlayerProvider } from "@/contexts/player-context"
import { FEED_PAGE_SIZE } from "@/lib/feed"

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

beforeEach(() => {
  instances = []
  vi.stubGlobal("IntersectionObserver", MockIO)
  HTMLMediaElement.prototype.play = vi
    .fn()
    .mockResolvedValue(undefined) as unknown as HTMLMediaElement["play"]
  HTMLMediaElement.prototype.pause = vi.fn() as unknown as HTMLMediaElement["pause"]
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

describe("FeedView", () => {
  it("renders a first page of items in a scroll layout (AC1)", () => {
    renderFeed()
    expect(screen.getByTestId("feed-scroll")).toBeInTheDocument()
    expect(items()).toHaveLength(FEED_PAGE_SIZE)
  })

  it("marks the first item active by default, then follows the most-visible one (AC2)", () => {
    const { container } = renderFeed()
    expect(items()[0]).toHaveAttribute("data-active", "true")

    // Second item scrolls into view.
    fireIntersect(wrappers(container)[1], 0.9)
    expect(items()[1]).toHaveAttribute("data-active", "true")
    expect(items()[0]).toHaveAttribute("data-active", "false")
  })

  it("loads more items when the sentinel is reached (AC5)", () => {
    const { container } = renderFeed()
    expect(items()).toHaveLength(FEED_PAGE_SIZE)
    const sentinel = container.querySelector('[data-testid="feed-sentinel"]')!
    fireIntersect(sentinel, 1)
    expect(items()).toHaveLength(FEED_PAGE_SIZE * 2)
  })
})
