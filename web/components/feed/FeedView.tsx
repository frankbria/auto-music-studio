"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { FeedItemCard } from "@/components/feed/FeedItemCard"
import { getFeedPage } from "@/lib/feed"

// Short-form feed (US-20.4). A snap-scroll column of full-height items. Two
// IntersectionObservers: one marks the most-visible item active (auto-play/pause),
// the other watches a bottom sentinel to append the next page (infinite scroll).
// State comes from the mock seam (lib/feed); no loading/error state to render since
// getFeedPage is synchronous.

export function FeedView() {
  const firstPage = useMemo(() => getFeedPage(1), [])
  const [feed, setFeed] = useState(firstPage)
  const [activeKey, setActiveKey] = useState(firstPage.items[0]?.key ?? "")

  // Element + visibility bookkeeping for the active-item observer.
  const itemEls = useRef(new Map<string, HTMLElement>())
  const ratios = useRef(new Map<string, number>())
  const activeObserver = useRef<IntersectionObserver | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const loadMore = useCallback(() => {
    setFeed((cur) => {
      if (!cur.hasMore) return cur
      const next = getFeedPage(cur.page + 1)
      return {
        page: next.page,
        hasMore: next.hasMore,
        items: [...cur.items, ...next.items],
      }
    })
  }, [])

  // Active-item observer: track each item's visible ratio and make the most-
  // visible one active. Created once; items register via their ref callback.
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const key = (e.target as HTMLElement).dataset.key
          if (key) ratios.current.set(key, e.isIntersecting ? e.intersectionRatio : 0)
        }
        let bestKey = ""
        let bestRatio = 0
        for (const [key, ratio] of ratios.current) {
          if (ratio > bestRatio) {
            bestRatio = ratio
            bestKey = key
          }
        }
        if (bestKey) setActiveKey(bestKey)
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

  // Sentinel observer: append the next page when the loader scrolls into view.
  // Re-bound when hasMore flips so it stops observing once the feed is exhausted.
  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !feed.hasMore) return
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadMore()
      },
      { rootMargin: "300px" }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [loadMore, feed.hasMore])

  const registerItem = (key: string) => (el: HTMLElement | null) => {
    const map = itemEls.current
    const prev = map.get(key)
    if (prev) activeObserver.current?.unobserve(prev)
    if (el) {
      map.set(key, el)
      activeObserver.current?.observe(el)
    } else {
      map.delete(key)
      ratios.current.delete(key)
    }
  }

  return (
    <div
      data-testid="feed-scroll"
      aria-label="Short-form feed"
      className="h-full snap-y snap-mandatory overflow-y-scroll bg-black"
    >
      {feed.items.map((item) => (
        <div
          key={item.key}
          data-key={item.key}
          ref={registerItem(item.key)}
          className="h-full w-full snap-start snap-always"
        >
          <FeedItemCard item={item} active={item.key === activeKey} />
        </div>
      ))}

      {feed.hasMore && (
        <div
          ref={sentinelRef}
          data-testid="feed-sentinel"
          className="flex h-16 items-center justify-center text-white/60"
        >
          <HugeiconsIcon icon={Loading03Icon} size={24} className="animate-spin" />
          <span className="sr-only">Loading more</span>
        </div>
      )}
    </div>
  )
}
