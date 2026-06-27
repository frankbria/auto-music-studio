"use client"

import { useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import {
  buildClipQuery,
  type ClipListResponse,
  type ClipSearchParams,
} from "@/lib/workspace-clips"

/**
 * Fetch a page of clips from the same-origin BFF (/api/clips) with the in-memory
 * access token. Refetches whenever the serialized query (workspace/search/sort/
 * page) changes. Previous data is kept across refetches so paging/typing doesn't
 * blank the list. Use behind an auth guard (e.g. useRequireAuth).
 *
 * Pass `enabled: false` to defer the fetch (e.g. until the workspace id is known)
 * — while deferred the hook reports `loading` so the caller shows a skeleton
 * rather than a spurious unscoped fetch.
 *
 * Search debouncing is the caller's job — pass an already-debounced `search`.
 */
export function useClips(
  params: ClipSearchParams,
  {
    enabled = true,
    refreshKey = 0,
  }: { enabled?: boolean; refreshKey?: number } = {}
) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const query = buildClipQuery(params)
  const [data, setData] = useState<ClipListResponse | null>(null)
  // The query a fetch error belongs to; a later query change makes it stale so
  // the skeleton shows again on the next attempt (instead of being suppressed).
  const [errorQuery, setErrorQuery] = useState<string | null>(null)

  // `refreshKey` forces a refetch without changing the query — bumped by the
  // Create page when a generation completes so new clips appear (US-16.7).
  useEffect(() => {
    if (!enabled || authLoading || !accessToken) return
    let active = true
    fetch(`/api/clips${query ? `?${query}` : ""}`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("fetch failed")
        return (await res.json()) as ClipListResponse
      })
      .then((next) => {
        if (active) {
          setData(next)
          setErrorQuery(null)
        }
      })
      .catch(() => {
        if (active) setErrorQuery(query)
      })
    return () => {
      active = false
    }
  }, [query, enabled, accessToken, authLoading, refreshKey])

  const error = errorQuery === query
  // Deferred (not yet enabled), first load (no data), and changed-query states
  // show the skeleton; later refetches keep prior data. A failed first load
  // drops out of loading so the empty/error state can show instead of an endless
  // skeleton.
  const loading =
    authLoading || (!!accessToken && (!enabled || (data === null && !error)))

  return { data, loading, error }
}
