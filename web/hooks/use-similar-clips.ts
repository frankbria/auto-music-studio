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
 */
export function useSimilarClips(id: string | undefined, limit = 6) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [clips, setClips] = useState<Clip[]>([])
  const [error, setError] = useState(false)
  const [loaded, setLoaded] = useState(false)

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
        if (active) {
          // Reset in the async callback, not the effect body (lint:
          // react-hooks/set-state-in-effect).
          setError(false)
          setClips(next.clips ?? [])
          setLoaded(true)
        }
      })
      .catch(() => {
        if (active) {
          setError(true)
          setLoaded(true)
        }
      })
    return () => {
      active = false
    }
  }, [id, accessToken, authLoading, limit])

  const loading = authLoading || (!!accessToken && !!id && !loaded)

  return { clips, loading, error }
}
