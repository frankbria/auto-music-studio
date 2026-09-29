"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import type { Page } from "@/lib/moderation"

// Server-paged admin lists (#540): the moderation queue and log, and the appeals
// queue (#543).

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong."
}

type FetchPage<T> = (cursor: string | null) => Promise<Page<T>>

// A server-paged list: `reload` fetches the first page, `more` the next one (null
// on the last page). Rows belong to the fetcher that loaded them, so a new sort or
// filter shows as loading instead of leaving the old rows up (and selectable), and
// a response a newer request has superseded is dropped, so a Load more that lands
// after a filter change can't append to the new list.
export function usePages<T>(fetchPage: FetchPage<T> | null) {
  const [loaded, setLoaded] = useState<{
    from: FetchPage<T>
    rows: T[]
    cursor: string | null
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)

  const load = useCallback(
    (after: string | null) => {
      if (!fetchPage) return Promise.resolve()
      const request = ++latest.current
      return fetchPage(after).then(
        (page) => {
          if (request !== latest.current) return
          setLoaded((prev) => ({
            from: fetchPage,
            rows: after && prev ? [...prev.rows, ...page.items] : page.items,
            cursor: page.next_cursor,
          }))
          setError(null)
        },
        (e: unknown) => {
          if (request === latest.current) setError(errorMessage(e))
        }
      )
    },
    [fetchPage]
  )

  // `reload` runs the newest `load`, not the one captured by the render that started
  // an action: a token rotation or query change mid-action mounts a new fetcher, and a
  // reload through the old one would supersede its request and strand the list loading.
  const latestLoad = useRef(load)
  useEffect(() => {
    latestLoad.current = load
    void load(null)
  }, [load])

  const current = loaded?.from === fetchPage ? loaded : null
  const cursor = current?.cursor
  return {
    rows: current?.rows ?? null,
    error,
    more: cursor ? () => void load(cursor) : null,
    reload: () => latestLoad.current(null),
  }
}

export function LoadMore({
  onClick,
  disabled,
}: {
  onClick: (() => void) | null
  disabled: boolean
}) {
  if (!onClick) return null
  return (
    <Button
      size="sm"
      variant="outline"
      className="mt-3"
      disabled={disabled}
      onClick={onClick}
    >
      Load more
    </Button>
  )
}
