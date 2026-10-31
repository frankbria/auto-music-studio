"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { FeedItemCard } from "@/components/feed/FeedItemCard"
import { Button } from "@/components/ui/button"
import { getFeedPage, type FeedItem } from "@/lib/feed"

// Short-form feed (US-20.4). A snap-scroll column of full-height items. Two
// IntersectionObservers: one marks the most-visible item active (auto-play/pause),
// the other watches a bottom sentinel to fetch the next cursor page (infinite
// scroll), until the API returns next_cursor: null.

type FeedState = {
  items: FeedItem[]
  nextCursor: string | null
  status: "loading" | "ready" | "error"
}

export function FeedView() {
  const [feed, setFeed] = useState<FeedState>({
    items: [],
    nextCursor: null,
    status: "loading",
  })
  const [activeId, setActiveId] = useState("")
  const currentId = activeId || feed.items[0]?.id

  // Cursors already requested ("" = first page): the sentinel can fire again
  // before a page lands, and StrictMode runs the mount effect twice.
  const requestedCursors = useRef(new Set<string>())
  const itemEls = useRef(new Map<string, HTMLElement>())
  const ratios = useRef(new Map<string, number>())
  const activeObserver = useRef<IntersectionObserver | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const loadPage = useCallback((cursor: string | null) => {
    const requestKey = cursor ?? ""
    if (requestedCursors.current.has(requestKey)) return
    requestedCursors.current.add(requestKey)
    getFeedPage(cursor).then(
      (page) =>
        setFeed((current) => ({
          items: [...current.items, ...page.items],
          nextCursor: page.nextCursor,
          status: "ready",
        })),
      () => {
        requestedCursors.current.delete(requestKey)
        setFeed((current) => ({ ...current, status: "error" }))
      }
    )
  }, [])

  useEffect(() => loadPage(null), [loadPage])

  // A failed first page leaves nextCursor null, so this retries the first page;
  // a failed later page left nextCursor on the cursor that failed.
  const retry = () => {
    setFeed((current) => ({ ...current, status: "loading" }))
    loadPage(feed.nextCursor)
  }

  // Active-item observer: track each item's visible ratio and make the most-
  // visible one active. Created once; items register via their ref callback.
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const id = (e.target as HTMLElement).dataset.key
          if (id)
            ratios.current.set(id, e.isIntersecting ? e.intersectionRatio : 0)
        }
        let bestId = ""
        let bestRatio = 0
        for (const [id, ratio] of ratios.current) {
          if (ratio > bestRatio) {
            bestRatio = ratio
            bestId = id
          }
        }
        if (bestId) setActiveId(bestId)
      },
      { threshold: [0.25, 0.5, 0.75] }
    )
    activeObserver.current = obs
    itemEls.current.forEach((el) => obs.observe(el))
    return () => {
      obs.disconnect()
      activeObserver.current = null
    }
  }, [])

  const hasMore = feed.status !== "error" && feed.nextCursor !== null

  // Sentinel observer: fetch the next page when the loader scrolls into view.
  // Re-bound per cursor; unbound once the feed is exhausted or a page failed.
  useEffect(() => {
    const el = sentinelRef.current
    const cursor = feed.nextCursor
    if (!el || !hasMore) return
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadPage(cursor)
      },
      { rootMargin: "300px" }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [loadPage, feed.nextCursor, hasMore])

  // Stable ref callback (reads the clip id from data-key). Kept identity-stable
  // so a re-render doesn't detach/reattach every item and churn the ratio map.
  // Items are append-only, so disconnect() on unmount is the only cleanup.
  const registerItem = useCallback((el: HTMLElement | null) => {
    if (!el) return
    const id = el.dataset.key
    if (!id) return
    itemEls.current.set(id, el)
    activeObserver.current?.observe(el)
  }, [])

  if (feed.items.length === 0) {
    return (
      <div
        data-testid="feed-scroll"
        aria-label="Short-form feed"
        className="flex h-full flex-col items-center justify-center gap-3 bg-black text-white/80"
      >
        {feed.status === "loading" && (
          <>
            <HugeiconsIcon
              icon={Loading03Icon}
              size={28}
              className="animate-spin"
            />
            <span className="sr-only">Loading feed</span>
          </>
        )}
        {feed.status === "error" && <FeedError onRetry={retry} />}
        {feed.status === "ready" && <p>No public songs yet</p>}
      </div>
    )
  }

  return (
    <div
      data-testid="feed-scroll"
      aria-label="Short-form feed"
      className="h-full snap-y snap-mandatory overflow-y-scroll bg-black"
    >
      {feed.items.map((item) => (
        <div
          key={item.id}
          data-key={item.id}
          ref={registerItem}
          className="h-full w-full snap-start snap-always"
        >
          <FeedItemCard item={item} active={item.id === currentId} />
        </div>
      ))}

      {hasMore && (
        <div
          ref={sentinelRef}
          data-testid="feed-sentinel"
          className="flex h-16 items-center justify-center text-white/60"
        >
          <HugeiconsIcon
            icon={Loading03Icon}
            size={24}
            className="animate-spin"
          />
          <span className="sr-only">Loading more</span>
        </div>
      )}
      {feed.status === "error" && (
        <div className="flex justify-center py-6 text-white/80">
          <FeedError onRetry={retry} />
        </div>
      )}
    </div>
  )
}

function FeedError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3">
      <p>Couldn&apos;t load the feed.</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}
