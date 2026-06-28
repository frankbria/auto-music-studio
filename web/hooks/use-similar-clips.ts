"use client"

import { useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import type { Clip } from "@/lib/workspace-clips"

type SimilarClipsResponse = {
  clips: Clip[]
}

/**
 * Fetch clips similar to `id` from the same-origin BFF
 * (/api/clips/{id}/similar) for the song-detail "Related songs" panel
 * (US-17.1). Empty/error both resolve to an empty list — related songs are a
 * nice-to-have, so the panel degrades quietly rather than blocking the page.
 *
 * The result is tagged with the id it belongs to so that, when the page stays
 * mounted across /song/:id navigations, the previous song's suggestions aren't
 * shown under the new clip while its fetch is in flight.
 */
export function useSimilarClips(id: string | undefined, limit = 6) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [result, setResult] = useState<{ id: string; clips: Clip[] } | null>(
    null
  )
  const [errorId, setErrorId] = useState<string | null>(null)

  useEffect(() => {
    if (authLoading || !accessToken || !id) return
    let active = true
    fetch(`/api/clips/${encodeURIComponent(id)}/similar?limit=${limit}`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("fetch failed")
        return (await res.json()) as SimilarClipsResponse
      })
      .then((next) => {
        if (active) setResult({ id, clips: next.clips ?? [] })
      })
      .catch(() => {
        if (active) {
          setErrorId(id)
          setResult({ id, clips: [] })
        }
      })
    return () => {
      active = false
    }
  }, [id, accessToken, authLoading, limit])

  const matches = result !== null && result.id === id
  const clips = matches ? result.clips : []
  const error = errorId === id
  const loading = authLoading || (!!accessToken && !!id && !matches)

  return { clips, loading, error }
}
