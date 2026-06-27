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
 * Search debouncing is the caller's job — pass an already-debounced `search`.
 */
export function useClips(params: ClipSearchParams) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const query = buildClipQuery(params)
  const [data, setData] = useState<ClipListResponse | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (authLoading || !accessToken) return
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
          setError(false)
        }
      })
      .catch(() => {
        if (active) setError(true)
      })
    return () => {
      active = false
    }
  }, [query, accessToken, authLoading])

  // First load (no data yet) shows the skeleton; later refetches keep prior data.
  const loading = authLoading || (!!accessToken && data === null && !error)

  return { data, loading, error }
}
